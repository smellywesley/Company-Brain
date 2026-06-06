"""
LLM Adapter for Company Brain.

Provides a unified **async** interface over multiple LLM providers
(Gemini, OpenAI, Anthropic) using raw HTTP (httpx.AsyncClient) — no
vendor SDKs required.  Supports function / tool calling, retry with
exponential back‑off, and cost estimation.

This is the async rewrite of the original synchronous adapter.
All provider methods are now coroutines so they do not block the
FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Response dataclass ──────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """Standardised response returned by every provider implementation."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)  # input_tokens, output_tokens
    raw_response: dict[str, Any] = field(default_factory=dict)


# ── Cost table (approximate, USD per 1 K tokens) ───────────────────────────

_COST_PER_1K: dict[str, dict[str, float]] = {
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
}


# ── Adapter ─────────────────────────────────────────────────────────────────

class LLMAdapter:
    """Unified async LLM interface.  Instantiate with provider name and API key.

    All ``generate*`` methods are coroutines that use ``httpx.AsyncClient``
    so they yield control back to the event loop during network I/O.
    """

    SUPPORTED_PROVIDERS = ("gemini", "openai", "anthropic")

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'. Choose from {self.SUPPORTED_PROVIDERS}")
        self.provider = provider
        self.api_key = api_key
        self.model = model or self._default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        # Async client — shared for the lifetime of this adapter instance.
        self._client = httpx.AsyncClient(timeout=120.0)

        # Initialize Langfuse LLM Telemetry
        self._langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        self._langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        self._langfuse_host = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
        self._langfuse = None

        if self._langfuse_public_key and self._langfuse_secret_key:
            try:
                from langfuse import Langfuse
                self._langfuse = Langfuse(
                    public_key=self._langfuse_public_key,
                    secret_key=self._langfuse_secret_key,
                    host=self._langfuse_host
                )
                logger.info("Langfuse telemetry initialized for model %s", self.model)
            except ImportError:
                logger.warning("langfuse package not installed. Telemetry will be disabled.")

    def _default_model(self) -> str:
        return {
            "gemini": "gemini-1.5-pro",
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-20250514",
        }[self.provider]

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    # ── Public API ──────────────────────────────────────────────────────

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        retries: int = 3,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send a prompt and return a standardised ``LLMResponse``.

        Retries with exponential back-off on transient HTTP errors.
        """
        # Start Langfuse Trace
        generation_span = None
        if self._langfuse:
            try:
                tenant_id = metadata.get("tenant_id") if metadata else "system"
                user_id = metadata.get("user_id") if metadata else "system"
                trace_name = metadata.get("trace_name", "agent-generation") if metadata else "agent-generation"

                trace = self._langfuse.trace(
                    name=trace_name,
                    user_id=str(user_id) if user_id else None,
                    metadata={"tenant_id": str(tenant_id)} if tenant_id else {}
                )
                generation_span = trace.generation(
                    name=self.provider,
                    model=self.model,
                    input={"system_prompt": system_prompt, "user_prompt": user_prompt, "tools": tools},
                    model_parameters={"temperature": self.temperature, "max_tokens": self.max_tokens}
                )
            except Exception as e:
                logger.warning("Failed to start Langfuse trace: %s", e)

        dispatch = {
            "gemini": self._generate_gemini,
            "openai": self._generate_openai,
            "anthropic": self._generate_anthropic,
        }
        last_err: Exception | None = None
        res: LLMResponse | None = None
        for attempt in range(1, retries + 1):
            try:
                res = await dispatch[self.provider](system_prompt, user_prompt, tools)
                break
            except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectError) as exc:
                last_err = exc
                wait = 2 ** attempt
                logger.warning(
                    "LLM request failed (attempt %d/%d): %s – retrying in %ds",
                    attempt, retries, exc, wait,
                )
                await asyncio.sleep(wait)

        if res is None:
            if generation_span:
                try:
                    generation_span.end(status_message=f"Failed after {retries} retries: {last_err}")
                except Exception:
                    pass
            raise RuntimeError(f"LLM request failed after {retries} retries") from last_err

        # End Langfuse trace
        if generation_span:
            try:
                generation_span.end(
                    output=res.content if not res.tool_calls else {"content": res.content, "tool_calls": res.tool_calls},
                    usage={"input": res.usage.get("input_tokens", 0), "output": res.usage.get("output_tokens", 0)}
                )
            except Exception as e:
                logger.warning("Failed to end Langfuse trace: %s", e)

        # Enqueue cost metrics
        tenant_id = metadata.get("tenant_id") if metadata else None
        if tenant_id:
            try:
                cost = self.estimate_cost(res.usage)
                from celery import Celery
                celery_app = Celery("company_brain", broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))
                celery_app.send_task(
                    "tasks.accumulate_llm_cost",
                    args=[str(tenant_id), cost, res.usage.get("input_tokens", 0), res.usage.get("output_tokens", 0)],
                    queue="default"
                )
            except Exception as e:
                logger.warning("Failed to enqueue cost accumulation: %s", e)

        return res

    def estimate_cost(self, usage: dict[str, int]) -> float:
        """Return estimated USD cost based on token usage."""
        rates = _COST_PER_1K.get(self.model, {"input": 0.0, "output": 0.0})
        input_cost = (usage.get("input_tokens", 0) / 1000) * rates["input"]
        output_cost = (usage.get("output_tokens", 0) / 1000) * rates["output"]
        return round(input_cost + output_cost, 6)

    # ── Provider implementations (all async) ────────────────────────────

    async def _generate_gemini(
        self, system_prompt: str, user_prompt: str, tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]

        resp = await self._client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

        candidate = data.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if "text" in p)
        tool_calls = [
            {"name": p["functionCall"]["name"], "arguments": p["functionCall"].get("args", {})}
            for p in parts
            if "functionCall" in p
        ]
        usage_meta = data.get("usageMetadata", {})
        usage = {
            "input_tokens": usage_meta.get("promptTokenCount", 0),
            "output_tokens": usage_meta.get("candidatesTokenCount", 0),
        }
        return LLMResponse(content=text, tool_calls=tool_calls, usage=usage, raw_response=data)

    async def _generate_openai(
        self, system_prompt: str, user_prompt: str, tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        url = "https://api.openai.com/v1/chat/completions"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]

        resp = await self._client.post(
            url, json=body, headers={"Authorization": f"Bearer {self.api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        text = msg.get("content", "") or ""
        tool_calls = []
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            tool_calls.append({
                "name": fn.get("name", ""),
                "arguments": json.loads(fn.get("arguments", "{}")),
            })
        usage_raw = data.get("usage", {})
        usage = {
            "input_tokens": usage_raw.get("prompt_tokens", 0),
            "output_tokens": usage_raw.get("completion_tokens", 0),
        }
        return LLMResponse(content=text, tool_calls=tool_calls, usage=usage, raw_response=data)

    async def _generate_anthropic(
        self, system_prompt: str, user_prompt: str, tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        url = "https://api.anthropic.com/v1/messages"
        body: dict[str, Any] = {
            "model": self.model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = [
                {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {}),
                }
                for t in tools
            ]

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = await self._client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                })

        usage_raw = data.get("usage", {})
        usage = {
            "input_tokens": usage_raw.get("input_tokens", 0),
            "output_tokens": usage_raw.get("output_tokens", 0),
        }
        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            usage=usage,
            raw_response=data,
        )
