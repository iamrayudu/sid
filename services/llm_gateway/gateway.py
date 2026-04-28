import time
import asyncio
import logging
from typing import Type, TypeVar, List, Dict, Any, Optional

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from config.settings import get_settings
from shared.schemas.models import LLMCallRecord
from services.llm_gateway.metrics import MetricsTracker

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GatewayError(Exception):
    pass


class LLMGateway:
    def __init__(self):
        self.settings = get_settings()
        self.fast_model = self.settings.fast_model
        self.deep_model = self.settings.deep_model

        self.client = AsyncOpenAI(
            base_url=f"{self.settings.ollama_base_url}/v1",
            api_key="ollama",
            timeout=120.0
        )

        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")

    async def health_check(self) -> bool:
        """Verify Ollama is reachable. Returns True if healthy, logs warning and returns False otherwise."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                resp.raise_for_status()
            logger.info("Ollama health check passed.")
            return True
        except Exception as e:
            logger.warning("Ollama health check failed (Ollama may not be running): %s", e)
            return False

    async def _record_call(
        self,
        model: str,
        purpose: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        success: bool
    ):
        record = MetricsTracker.create_record(
            model=model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=success,
            cost_per_1k=0.0
        )

        async def do_write():
            from services.memory import get_store
            store = get_store()
            if store:
                await store.write_llm_call(record)

        asyncio.create_task(do_write())

    async def fast(self, prompt: str, schema: Type[T]) -> T:
        return await self._structured_call(self.fast_model, "stage1", prompt, schema)

    async def deep(self, prompt: str, schema: Type[T]) -> T:
        return await self._structured_call(self.deep_model, "stage2", prompt, schema)

    async def chat(self, messages: List[Dict[str, str]], purpose: str = "agent_chat") -> str:
        start_time = time.perf_counter()
        success = True
        prompt_tokens = 0
        completion_tokens = 0

        try:
            response = await self.client.chat.completions.create(
                model=self.deep_model,
                messages=messages
            )
            raw_content = response.choices[0].message.content
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
            return raw_content
        except Exception as e:
            success = False
            raise GatewayError(f"Ollama chat call failed: {e}")
        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_call(
                model=self.deep_model,
                purpose=purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=success
            )

    async def _structured_call(self, model: str, purpose: str, prompt: str, schema: Type[T]) -> T:
        start_time = time.perf_counter()
        success = True
        prompt_tokens = 0
        completion_tokens = 0

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": schema.model_json_schema()
                    }
                }
            )

            raw_content = response.choices[0].message.content

            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens

            try:
                return schema.model_validate_json(raw_content)
            except Exception:
                # Retry once with explicit JSON instruction
                retry_prompt = f"Respond ONLY with valid JSON matching this schema.\n\n{prompt}"
                response2 = await self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": retry_prompt}],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema.__name__,
                            "schema": schema.model_json_schema()
                        }
                    }
                )
                return schema.model_validate_json(response2.choices[0].message.content)

        except Exception as e:
            success = False
            raise GatewayError(f"Ollama structured call failed: {e}")
        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_call(
                model=model,
                purpose=purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=success
            )

    def embed(self, text: str) -> List[float]:
        vector = self.embedder.encode(text)
        return vector.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        vectors = self.embedder.encode(texts)
        return vectors.tolist()
