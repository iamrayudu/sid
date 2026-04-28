import time
import asyncio
import logging
import os
from pathlib import Path
from typing import Type, TypeVar, List, Dict, Any, Optional, Tuple

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

def _load_config() -> tuple[dict, dict]:
    try:
        with open(_MODELS_YAML, "r") as f:
            content = f.read()
            content = os.path.expandvars(content)
            data = yaml.safe_load(content)

        providers = data.get("providers", {})
        models = data.get("models", {})

        detailed_models = {}
        for k, v in models.items():
            if isinstance(v, dict):
                detailed_models[k] = v
            else:
                detailed_models[k] = {"model": v, "provider": "local"}

        return providers, detailed_models
    except Exception as e:
        logger.warning("Could not load config/models.yaml, using defaults: %s", e)
        return {}, {}


_DEFAULT_MODELS = {
    "stage1": {"model": "qwen2.5:3b", "provider": "local"},
    "stage2": {"model": "qwen2.5:14b", "provider": "local"},
    "agent_chat": {"model": "qwen2.5:14b", "provider": "local"},
    "morning": {"model": "qwen2.5:14b", "provider": "local"},
    "evening": {"model": "qwen2.5:14b", "provider": "local"},
    "checkin": {"model": "qwen2.5:3b", "provider": "local"},
    "weekly": {"model": "qwen2.5:14b", "provider": "local"},
    "critique": {"model": "qwen2.5:14b", "provider": "local"},
    "document": {"model": "qwen2.5:14b", "provider": "local"},
    "milestone": {"model": "qwen2.5:14b", "provider": "local"},
}


class GatewayError(Exception):
    pass


class LLMGateway:
    def __init__(self):
        self.settings = get_settings()
        
        raw_providers, loaded_models = _load_config()
        self._model_map: dict = {**_DEFAULT_MODELS, **loaded_models}

        # Store full provider configs so _structured_call can check capabilities
        self._provider_configs: dict[str, dict] = {}
        self._clients: dict[str, AsyncOpenAI] = {}

        if "local" not in raw_providers:
            raw_providers["local"] = {
                "client": "openai_sdk",
                "base_url": f"{self.settings.ollama_base_url}/v1",
                "api_key": "ollama",
                "native_json_schema": True,
            }

        for name, p_conf in raw_providers.items():
            # Skip providers explicitly disabled
            if not p_conf.get("enabled", True):
                logger.debug("Provider '%s' is disabled (enabled: false) — skipping", name)
                continue

            client_type = p_conf.get("client", "openai_sdk")
            if client_type == "openai_sdk":
                api_key = p_conf.get("api_key", "default")
                extra_headers = p_conf.get("extra_headers", {})
                try:
                    self._clients[name] = AsyncOpenAI(
                        base_url=p_conf.get("base_url"),
                        api_key=api_key,
                        timeout=120.0,
                        default_headers=extra_headers if extra_headers else None,
                    )
                    self._provider_configs[name] = p_conf
                except Exception as e:
                    logger.error("Failed to initialise provider '%s': %s", name, e)
            else:
                logger.warning(
                    "Provider '%s' uses unsupported client type '%s' — skipping. "
                    "Only 'openai_sdk' is supported (covers Ollama, OpenAI, Anthropic v1).",
                    name, client_type,
                )

        self._embedder: Optional[SentenceTransformer] = None

    @property
    def embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            logger.info("Loading sentence-transformers all-MiniLM-L6-v2 (first use)...")
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._embedder

    def config_for(self, purpose: str) -> Tuple[str, str, AsyncOpenAI]:
        """Return (model_name, provider_name, client_instance) for a configured purpose."""
        config = self._model_map.get(purpose)
        if not config:
            logger.warning("No config for purpose '%s', falling back to stage2", purpose)
            config = self._model_map.get("stage2", _DEFAULT_MODELS["stage2"])

        model = config["model"]
        provider = config["provider"]
        client = self._clients.get(provider)

        if not client:
            # Fall back to local if the intended provider isn't available
            local_client = self._clients.get("local")
            if local_client:
                logger.warning(
                    "Provider '%s' not available for purpose '%s' — falling back to local.",
                    provider, purpose,
                )
                return self._model_map["stage2"]["model"], "local", local_client
            raise GatewayError(
                f"Provider '{provider}' not available for purpose '{purpose}' and no local fallback."
            )

        return model, provider, client

    def _supports_json_schema(self, provider: str) -> bool:
        """True if the provider natively supports response_format.json_schema."""
        p_conf = self._provider_configs.get(provider, {})
        return p_conf.get("native_json_schema", True)
        
    def model_for(self, purpose: str) -> str:
        """Legacy helper for returning only the active model name string."""
        model, _, _ = self.config_for(purpose)
        return model

    async def health_check(self) -> bool:
        """Checks the default local provider health."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.settings.ollama_base_url}/api/tags")
                resp.raise_for_status()
            logger.info("Ollama health check passed.")
            return True
        except Exception as e:
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
        model, _, client = self.config_for(purpose)
        return await self._structured_call(client, model, purpose, prompt, schema)

    async def chat_for(self, purpose: str, messages: List[Dict[str, str]]) -> str:
        model, _, client = self.config_for(purpose)
        return await self._chat_call(client, model, purpose, messages)

    # ── Legacy helpers kept for pipeline compatibility ─────────────────────────

    async def fast(self, prompt: str, schema: Type[T]) -> T:
        model, _, client = self.config_for("stage1")
        return await self._structured_call(client, model, "stage1", prompt, schema)

    async def deep(self, prompt: str, schema: Type[T]) -> T:
        model, _, client = self.config_for("stage2")
        return await self._structured_call(client, model, "stage2", prompt, schema)

    async def chat(self, messages: List[Dict[str, str]], purpose: str = "agent_chat") -> str:
        model, _, client = self.config_for(purpose)
        return await self._chat_call(client, model, purpose, messages)

    # ── Core implementations ───────────────────────────────────────────────────

    async def _chat_call(self, client: AsyncOpenAI, model: str, purpose: str, messages: List[Dict[str, str]]) -> str:
        start_time = time.perf_counter()
        success = True
        prompt_tokens = 0
        completion_tokens = 0

        try:
            response = await client.chat.completions.create(
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
            raise GatewayError(f"Gateway chat call failed [{model}/{purpose}]: {e}")
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

    async def _structured_call(self, client: AsyncOpenAI, model: str, purpose: str, prompt: str, schema: Type[T]) -> T:
        start_time = time.perf_counter()
        success = True
        prompt_tokens = 0
        completion_tokens = 0

        # Determine which provider owns this client and check its capabilities
        provider = next((n for n, c in self._clients.items() if c is client), "local")
        use_json_schema = self._supports_json_schema(provider)

        schema_json = schema.model_json_schema()

        def _build_request(content: str) -> dict:
            req: dict = {"model": model, "messages": [{"role": "user", "content": content}]}
            if use_json_schema:
                req["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": schema_json},
                }
            else:
                # Prompt-based JSON extraction for providers without native schema support
                req["messages"][0]["content"] = (
                    f"Respond ONLY with a valid JSON object matching this schema:\n"
                    f"{schema_json}\n\n{content}"
                )
            return req

        try:
            response = await client.chat.completions.create(**_build_request(prompt))
            raw_content = response.choices[0].message.content

            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens

            try:
                return schema.model_validate_json(raw_content)
            except Exception:
                retry_prompt = f"Respond ONLY with valid JSON matching this schema.\n\n{prompt}"
                response2 = await client.chat.completions.create(**_build_request(retry_prompt))
                return schema.model_validate_json(response2.choices[0].message.content)

        except Exception as e:
            success = False
            raise GatewayError(f"Gateway structured call failed [{model}/{purpose}]: {e}")
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
