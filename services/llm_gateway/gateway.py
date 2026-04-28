import time
import asyncio
from typing import Type, TypeVar, List, Dict, Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from config.settings import get_settings
from shared.schemas.models import LLMCallRecord
from services.llm_gateway.metrics import MetricsTracker

T = TypeVar("T", bound=BaseModel)

class GatewayError(Exception):
    pass

class LLMGateway:
    def __init__(self):
        self.settings = get_settings()
        self.fast_model = self.settings.fast_model
        self.deep_model = self.settings.deep_model
        
        # We rely on Ollama providing the OpenAI-compatible /v1 endpoints
        self.client = AsyncOpenAI(
            base_url=f"{self.settings.ollama_base_url}/v1",
            api_key="ollama", # dummy key for standard compliancy
            timeout=120.0
        )
        
        # Load local embedding model immediately (approx 380MB, runs locally) 
        # Using default PyTorch backend. ONNX can be added later if CPU load is too high.
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        
    async def _record_call(
        self,
        model: str,
        purpose: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        success: bool
    ):
        """Asynchronously writes the metric to SQLite without blocking the main event flow."""
        record = MetricsTracker.create_record(
            model=model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=success,
            cost_per_1k=0.0 # Standard local Ollama cost is 0
        )
        
        # Lazy import resolves circular dependency between Gateway and MemoryStore
        async def do_write():
            from services.memory import get_store
            store = get_store()
            if store:
                await store.write_llm_call(record)
                
        asyncio.create_task(do_write())
        
    async def fast(self, prompt: str, schema: Type[T]) -> T:
        """Stage 1: Fast reasoning (Classification, extraction, cleanup)."""
        return await self._structured_call(self.fast_model, "stage1", prompt, schema)
        
    async def deep(self, prompt: str, schema: Type[T]) -> T:
        """Stage 2: Deep reasoning (Complex relationships, intent, long extraction)."""
        return await self._structured_call(self.deep_model, "stage2", prompt, schema)
        
    async def chat(self, messages: List[Dict[str, str]], purpose: str = "agent_chat") -> str:
        """Unstructured conversational agent call."""
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
            # Format using Ollama's native JSON Schema structured output
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
                
            # Parse the model's raw string output directly purely into Pydantic
            # Retries can be implemented here if JSON parsing fails natively.
            return schema.model_validate_json(raw_content)
            
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
        """Provides local embeddings for semantic search."""
        vector = self.embedder.encode(text)
        return vector.tolist()
        
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Provides batch embeddings locally."""
        vectors = self.embedder.encode(texts)
        return vectors.tolist()
