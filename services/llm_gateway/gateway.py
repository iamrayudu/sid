import time
import asyncio
import logging
from pathlib import Path
from typing import Type, TypeVar, List, Dict, Any, Optional

import httpx
import yaml
from openai import AsyncOpenAI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from config.settings import get_settings
from shared.schemas.models import LLMCallRecord
from services.llm_gateway.metrics import MetricsTracker

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MODELS_YAML = Path(__file__).parent.parent.parent / "config" / "models.yaml"


def _load_model_map() -> dict:
    try:
        with open(_MODELS_YAML, "r") as f:
            data = yaml.safe_load(f)
        return data.get("models", {})
    except Exception as e:
        logger.warning("Could not load config/models.yaml, using defaults: %s", e)
        return {}


_DEFAULT_MODELS = {
    "stage1": "qwen2.5:3b",
    "stage2": "qwen2.5:14b",
    "agent_chat": "qwen2.5:14b",
    "morning": "qwen2.5:14b",
    "evening": "qwen2.5:14b",
    "checkin": "qwen2.5:3b",
    "weekly": "qwen2.5:14b",
    "critique": "qwen2.5:14b",
    "document": "qwen2.5:14b",
    "milestone": "qwen2.5:14b",
}


class GatewayError(Exception):
    pass


class LLMGateway:
    def __init__(self):
        self.settings = get_settings()
        self._model_map: dict = {**_DEFAULT_MODELS, **_load_model_map()}

        self.client = AsyncOpenAI(
            base_url=f"{self.settings.ollama_base_url}/v1",
            api_key="ollama",
            timeout=120.0
        )

        self._embedder: Optional[SentenceTransformer] = None

        # Health tracking — updated by health_check() / monitor task
        self._last_health_ok_at: Optional[float] = None
        self._last_health_fail_at: Optional[float] = None
        self._last_health_error: Optional[str] = None
        self._health_monitor_task: Optional[asyncio.Task] = None
        self._monitor_running: bool = False

    # ── Health snapshot ────────────────────────────────────────────────────────

    def health_status(self) -> dict:
        """Return a snapshot of Ollama availability."""
        now = time.time()
        ok_at = self._last_health_ok_at
        fail_at = self._last_health_fail_at
        stuck_secs = self.settings.ollama_stuck_threshold_secs

        # Healthy if last successful ping is more recent than last failure.
        is_healthy = ok_at is not None and (fail_at is None or ok_at > fail_at)

        # Stuck if we haven't seen success in a long while AND we have failures.
        unhealthy_for = None
        if not is_healthy and fail_at is not None:
            unhealthy_for = int(now - (ok_at if ok_at else fail_at))
        is_stuck = (not is_healthy) and (unhealthy_for is not None and unhealthy_for >= stuck_secs)

        return {
            "healthy": is_healthy,
            "stuck": is_stuck,
            "last_ok_seconds_ago": int(now - ok_at) if ok_at else None,
            "last_fail_seconds_ago": int(now - fail_at) if fail_at else None,
            "last_error": self._last_health_error,
            "base_url": self.settings.ollama_base_url,
        }

    async def _monitor_loop(self) -> None:
        interval = self.settings.ollama_healthcheck_interval_secs
        logger.info("Ollama health monitor started (interval %ds).", interval)
        while self._monitor_running:
            try:
                await self.health_check()
            except Exception as e:
                logger.debug("Health monitor swallowed error: %s", e)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
        logger.info("Ollama health monitor stopped.")

    def start_health_monitor(self) -> None:
        if self._health_monitor_task and not self._health_monitor_task.done():
            return
        self._monitor_running = True
        self._health_monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop_health_monitor(self) -> None:
        self._monitor_running = False
        if self._health_monitor_task and not self._health_monitor_task.done():
            try:
                await asyncio.wait_for(self._health_monitor_task, timeout=3.0)
            except asyncio.TimeoutError:
                self._health_monitor_task.cancel()
        self._health_monitor_task = None

    @property
    def embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            logger.info("Loading sentence-transformers all-MiniLM-L6-v2 (first use)...")
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._embedder

    def model_for(self, purpose: str) -> str:
        """Return the configured model name for a given purpose."""
        model = self._model_map.get(purpose)
        if not model:
            logger.warning("No model configured for purpose '%s', falling back to stage2", purpose)
            model = self._model_map.get("stage2", "qwen2.5:14b")
        return model

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                resp.raise_for_status()
            self._last_health_ok_at = time.time()
            self._last_health_error = None
            return True
        except Exception as e:
            self._last_health_fail_at = time.time()
            self._last_health_error = str(e)[:200]
            logger.warning("Ollama health check failed: %s", e)
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
            try:
                from services.memory import get_store
                store = get_store()
                if store:
                    await store.write_llm_call(record)
            except Exception as exc:
                logger.debug("Metrics write failed (non-fatal): %s", exc)

        asyncio.create_task(do_write())

    # ── Purpose-based entry point (preferred for all agent/routine calls) ──────

    async def generate(self, purpose: str, prompt: str, schema: Type[T]) -> T:
        """Structured call routed by purpose (resolves model from models.yaml)."""
        model = self.model_for(purpose)
        return await self._structured_call(model, purpose, prompt, schema)

    async def chat_for(self, purpose: str, messages: List[Dict[str, str]]) -> str:
        """Free-text chat routed by purpose."""
        model = self.model_for(purpose)
        return await self._chat_call(model, purpose, messages)

    # ── Legacy helpers kept for pipeline compatibility ─────────────────────────

    async def fast(self, prompt: str, schema: Type[T]) -> T:
        return await self._structured_call(self.model_for("stage1"), "stage1", prompt, schema)

    async def deep(self, prompt: str, schema: Type[T]) -> T:
        return await self._structured_call(self.model_for("stage2"), "stage2", prompt, schema)

    async def chat(self, messages: List[Dict[str, str]], purpose: str = "agent_chat") -> str:
        return await self._chat_call(self.model_for(purpose), purpose, messages)

    # ── Core implementations ───────────────────────────────────────────────────

    async def _chat_call(self, model: str, purpose: str, messages: List[Dict[str, str]]) -> str:
        start_time = time.perf_counter()
        success = True
        prompt_tokens = 0
        completion_tokens = 0

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages
            )
            raw_content = response.choices[0].message.content
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
            return raw_content
        except Exception as e:
            success = False
            raise GatewayError(f"Ollama chat call failed [{model}/{purpose}]: {e}")
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
            raise GatewayError(f"Ollama structured call failed [{model}/{purpose}]: {e}")
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


_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
