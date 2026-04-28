"""LLM Gateway — single chokepoint for all model calls in SID.

Multi-provider, purpose-based routing. Reads config/models.yaml for:
  - providers (ollama / openai / anthropic)
  - default model per purpose
  - per-purpose route overrides
  - cloud fallback when Ollama is stuck

Public surface (all callers go through these — Rule #1):
  gateway.generate(purpose, prompt, schema)   → structured Pydantic output
  gateway.chat_for(purpose, messages)         → free-text chat
  gateway.model_for(purpose)                  → model name string
  gateway.config_for(purpose)                 → (model, provider, client)
  gateway.embed(text) / embed_batch(texts)    → local sentence-transformers
  gateway.health_status()                     → snapshot dict
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

import httpx
import yaml
from openai import AsyncOpenAI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from config.settings import get_settings
from services.llm_gateway.metrics import MetricsTracker

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MODELS_YAML = Path(__file__).parent.parent.parent / "config" / "models.yaml"

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


def _load_yaml() -> dict:
    try:
        with open(_MODELS_YAML, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Could not load config/models.yaml: %s", e)
        return {}


# Match a JSON object inside a code fence or free text — used by Anthropic path.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> str:
    """Pull a JSON object out of free text. Used when provider doesn't natively
    support response_format=json_schema (e.g. Anthropic OpenAI-compatible)."""
    if not raw:
        return raw
    m = _JSON_FENCE_RE.search(raw)
    if m:
        return m.group(1)
    m = _JSON_OBJ_RE.search(raw)
    if m:
        return m.group(0)
    return raw.strip()


class LLMGateway:
    def __init__(self):
        self.settings = get_settings()
        cfg = _load_yaml()

        # Models per purpose: bare strings only (provider chosen separately).
        models_section = cfg.get("models") or {}
        self._model_map: dict = {**_DEFAULT_MODELS, **models_section}

        # Provider configs from yaml.
        self._providers: Dict[str, dict] = cfg.get("providers") or {}
        self._default_provider: str = cfg.get("default_provider", "ollama")

        # Per-purpose explicit overrides: { purpose: { provider, model } }
        self._routes: Dict[str, dict] = cfg.get("routes") or {}

        # Optional fallback for stuck-Ollama scenarios.
        self._fallback_cfg: dict = cfg.get("fallback") or {}

        # Cost table (per 1k tokens).
        self._cost_per_1k: dict = cfg.get("cost_per_1k_tokens") or {}

        # Build per-provider AsyncOpenAI clients.
        self._clients: Dict[str, AsyncOpenAI] = {}
        self._init_clients()

        # Backward compat: gateway.client points at the default provider.
        self.client = self._clients.get(self._default_provider) or self._fallback_default_client()

        # Embedder (lazy-loaded).
        self._embedder: Optional[SentenceTransformer] = None

        # Health tracking — applies to default_provider (Ollama).
        self._last_health_ok_at: Optional[float] = None
        self._last_health_fail_at: Optional[float] = None
        self._last_health_error: Optional[str] = None
        self._health_monitor_task: Optional[asyncio.Task] = None
        self._monitor_running: bool = False

    # ── Provider client construction ───────────────────────────────────────────

    def _fallback_default_client(self) -> AsyncOpenAI:
        """If models.yaml has no providers block, fall back to a plain Ollama client
        constructed from settings.ollama_base_url so existing setups keep working."""
        return AsyncOpenAI(
            base_url=f"{self.settings.ollama_base_url}/v1",
            api_key="ollama",
            timeout=120.0,
        )

    def _init_clients(self) -> None:
        if not self._providers:
            # Legacy yaml without providers block.
            self._clients["ollama"] = self._fallback_default_client()
            return

        for name, cfg in self._providers.items():
            if not cfg.get("enabled", False):
                continue

            api_key = cfg.get("api_key")
            if not api_key:
                env = cfg.get("api_key_env")
                if env:
                    api_key = os.environ.get(env)
                if not api_key:
                    logger.warning(
                        "Provider %s is enabled but no api_key/api_key_env value resolved — skipping.",
                        name,
                    )
                    continue

            extra_headers = cfg.get("extra_headers") or {}
            try:
                self._clients[name] = AsyncOpenAI(
                    base_url=cfg.get("base_url"),
                    api_key=api_key,
                    timeout=120.0,
                    default_headers=extra_headers or None,
                )
                logger.info("LLM provider initialized: %s (%s)", name, cfg.get("base_url"))
            except Exception as e:
                logger.error("Failed to init provider %s: %s", name, e)

        # Always make sure default_provider has *something* even if disabled in yaml,
        # so legacy paths that bypass config_for() still function.
        if self._default_provider not in self._clients:
            logger.warning(
                "Default provider %s not initialized — using best-effort Ollama default.",
                self._default_provider,
            )
            self._clients[self._default_provider] = self._fallback_default_client()

    # ── Routing ────────────────────────────────────────────────────────────────

    def model_for(self, purpose: str) -> str:
        """Return the model name for a purpose (route override, else default)."""
        route = self._routes.get(purpose)
        if route and route.get("model"):
            return route["model"]
        model = self._model_map.get(purpose)
        if not model:
            logger.warning("No model configured for purpose '%s', falling back to stage2", purpose)
            model = self._model_map.get("stage2", "qwen2.5:14b")
        return model

    def provider_for(self, purpose: str) -> str:
        """Return the provider name for a purpose (route override, else default)."""
        route = self._routes.get(purpose)
        if route and route.get("provider"):
            return route["provider"]
        return self._default_provider

    def config_for(self, purpose: str) -> Tuple[str, str, AsyncOpenAI]:
        """Return (model_name, provider_name, client) for a purpose.

        This is the canonical accessor: anywhere we make a chat-completions call,
        get the client this way so route overrides and provider switching work.
        """
        model = self.model_for(purpose)
        provider = self.provider_for(purpose)
        client = self._clients.get(provider)
        if client is None:
            # Provider configured-but-not-initialized (disabled, missing key).
            # Fall back to default provider so the call doesn't blow up.
            logger.warning(
                "Provider %s for purpose %s not initialized — using default %s.",
                provider, purpose, self._default_provider,
            )
            provider = self._default_provider
            client = self._clients.get(provider) or self._fallback_default_client()
        return model, provider, client

    # ── Fallback ───────────────────────────────────────────────────────────────

    def _fallback_target(self, purpose: str) -> Optional[Tuple[str, str, AsyncOpenAI]]:
        """If fallback is enabled and the default (Ollama) provider is stuck,
        return (model, provider, client) for the fallback target. Else None.

        Only kicks in for purposes routed to the default provider — explicit
        cloud routes already use cloud, so fallback isn't needed there.
        """
        if not self._fallback_cfg.get("enabled"):
            return None

        # If this purpose isn't on the default provider, no fallback applies.
        if self.provider_for(purpose) != self._default_provider:
            return None

        if not self.health_status().get("stuck"):
            return None

        provider = self._fallback_cfg.get("provider")
        model = self._fallback_cfg.get("model")
        if not provider or not model:
            return None
        client = self._clients.get(provider)
        if client is None:
            logger.warning(
                "Fallback provider %s configured but not initialized — skipping fallback.",
                provider,
            )
            return None
        return model, provider, client

    # ── Health (Ollama default-provider only) ──────────────────────────────────

    def health_status(self) -> dict:
        now = time.time()
        ok_at = self._last_health_ok_at
        fail_at = self._last_health_fail_at
        stuck_secs = self.settings.ollama_stuck_threshold_secs

        is_healthy = ok_at is not None and (fail_at is None or ok_at > fail_at)

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

    # ── Embeddings (local) ─────────────────────────────────────────────────────

    @property
    def embedder(self) -> SentenceTransformer:
        if self._embedder is None:
            logger.info("Loading sentence-transformers all-MiniLM-L6-v2 (first use)...")
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        return self._embedder

    def embed(self, text: str) -> List[float]:
        return self.embedder.encode(text).tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return self.embedder.encode(texts).tolist()

    # ── Metrics ────────────────────────────────────────────────────────────────

    def _cost_for(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        rate = self._cost_per_1k.get(model, self._cost_per_1k.get("default", 0.0))
        return ((prompt_tokens + completion_tokens) / 1000.0) * float(rate)

    async def _record_call(
        self,
        model: str,
        purpose: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        success: bool,
    ) -> None:
        record = MetricsTracker.create_record(
            model=model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=success,
            cost_per_1k=0.0,
        )
        # Override the cost with our cost table.
        record.estimated_cost_usd = self._cost_for(model, prompt_tokens, completion_tokens)

        async def do_write():
            try:
                from services.memory import get_store
                store = get_store()
                if store:
                    await store.write_llm_call(record)
            except Exception as exc:
                logger.debug("Metrics write failed (non-fatal): %s", exc)

        asyncio.create_task(do_write())

    # ── Public purpose-based entry points ──────────────────────────────────────

    async def generate(self, purpose: str, prompt: str, schema: Type[T]) -> T:
        """Structured call. Tries primary; if Ollama is stuck, falls back to cloud."""
        model, provider, client = self.config_for(purpose)
        try:
            return await self._structured_call(model, provider, purpose, prompt, schema, client)
        except GatewayError:
            target = self._fallback_target(purpose)
            if target is None:
                raise
            fb_model, fb_provider, fb_client = target
            logger.warning(
                "Primary call failed for %s, falling back to %s/%s",
                purpose, fb_provider, fb_model,
            )
            return await self._structured_call(fb_model, fb_provider, purpose, prompt, schema, fb_client)

    async def chat_for(self, purpose: str, messages: List[Dict[str, str]]) -> str:
        """Free-text chat. Tries primary; falls back to cloud if Ollama is stuck."""
        model, provider, client = self.config_for(purpose)
        try:
            return await self._chat_call(model, provider, purpose, messages, client)
        except GatewayError:
            target = self._fallback_target(purpose)
            if target is None:
                raise
            fb_model, fb_provider, fb_client = target
            logger.warning(
                "Primary chat failed for %s, falling back to %s/%s",
                purpose, fb_provider, fb_model,
            )
            return await self._chat_call(fb_model, fb_provider, purpose, messages, fb_client)

    # ── Legacy helpers ─────────────────────────────────────────────────────────

    async def fast(self, prompt: str, schema: Type[T]) -> T:
        return await self.generate("stage1", prompt, schema)

    async def deep(self, prompt: str, schema: Type[T]) -> T:
        return await self.generate("stage2", prompt, schema)

    async def chat(self, messages: List[Dict[str, str]], purpose: str = "agent_chat") -> str:
        return await self.chat_for(purpose, messages)

    # ── Core LLM calls ─────────────────────────────────────────────────────────

    async def _chat_call(
        self,
        model: str,
        provider: str,
        purpose: str,
        messages: List[Dict[str, str]],
        client: AsyncOpenAI,
    ) -> str:
        start = time.perf_counter()
        success = True
        prompt_tokens = 0
        completion_tokens = 0

        try:
            response = await client.chat.completions.create(model=model, messages=messages)
            content = response.choices[0].message.content or ""
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
            return content
        except Exception as e:
            success = False
            raise GatewayError(f"Chat call failed [{provider}/{model}/{purpose}]: {e}")
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            await self._record_call(model, purpose, prompt_tokens, completion_tokens, latency_ms, success)

    async def _structured_call(
        self,
        model: str,
        provider: str,
        purpose: str,
        prompt: str,
        schema: Type[T],
        client: AsyncOpenAI,
    ) -> T:
        """Structured Pydantic output. Uses native response_format when the
        provider supports json_schema; falls back to prompt-based JSON extraction
        for providers like Anthropic that don't (native_json_schema: false)."""
        provider_cfg = self._providers.get(provider, {})
        native = provider_cfg.get("native_json_schema", True)

        start = time.perf_counter()
        success = True
        prompt_tokens = 0
        completion_tokens = 0

        try:
            if native:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
                    },
                )
                raw = resp.choices[0].message.content or ""
                if resp.usage:
                    prompt_tokens = resp.usage.prompt_tokens
                    completion_tokens = resp.usage.completion_tokens
                try:
                    return schema.model_validate_json(raw)
                except Exception:
                    # Retry once with explicit instruction.
                    retry_prompt = f"Respond ONLY with valid JSON matching this schema.\n\n{prompt}"
                    resp2 = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": retry_prompt}],
                        response_format={
                            "type": "json_schema",
                            "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
                        },
                    )
                    if resp2.usage:
                        prompt_tokens += resp2.usage.prompt_tokens
                        completion_tokens += resp2.usage.completion_tokens
                    return schema.model_validate_json(resp2.choices[0].message.content or "")

            # Prompt-based JSON path (Anthropic etc.).
            schema_desc = json.dumps(schema.model_json_schema(), indent=2)
            messages = [
                {
                    "role": "user",
                    "content": (
                        "Respond with ONLY a JSON object matching this schema. "
                        "No markdown, no explanation, no surrounding text.\n\n"
                        f"Schema:\n{schema_desc}\n\nTask:\n{prompt}"
                    ),
                }
            ]
            resp = await client.chat.completions.create(model=model, messages=messages)
            raw = resp.choices[0].message.content or ""
            if resp.usage:
                prompt_tokens = resp.usage.prompt_tokens
                completion_tokens = resp.usage.completion_tokens
            extracted = _extract_json(raw)
            try:
                return schema.model_validate_json(extracted)
            except Exception as e:
                raise GatewayError(
                    f"Failed to parse JSON from {provider}/{model}: {e} — raw[:200]={raw[:200]!r}"
                )

        except Exception as e:
            success = False
            if isinstance(e, GatewayError):
                raise
            raise GatewayError(f"Structured call failed [{provider}/{model}/{purpose}]: {e}")
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            await self._record_call(model, purpose, prompt_tokens, completion_tokens, latency_ms, success)


_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
