"""Client for a Gemma model served through the Google Generative Language REST API.

The model name and API key come from settings (``GEMMA_MODEL`` / ``GEMMA_API_KEY`` in ``.env``); both are empty by
default and the assistant then runs rule-based only. The key is sent only in the ``x-goog-api-key`` header, never in
a URL, an error message or a log line.

Hosted Gemma models do not all support system instructions or native function calling, so this client only sends
plain user/model turns; the tool protocol is plain JSON text, validated by the caller (see ``llm_assistant``).
"""
from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


class LlmUnavailable(RuntimeError):
    """The model could not produce a usable reply. ``code`` is stable and safe to show; the message never holds the key."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GemmaClient:
    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE, timeout_s: float = 45.0,
                 retries: int = 1, http: httpx.Client | None = None, sleep=time.sleep) -> None:
        self._key, self._model = api_key.strip(), model.strip()
        self._base = (base_url or DEFAULT_BASE).rstrip("/")
        self._retries, self._sleep = retries, sleep
        self._http = http or httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10.0))

    @property
    def configured(self) -> bool:
        return bool(self._key and self._model)

    @property
    def model(self) -> str:
        return self._model

    def generate(self, turns: list[tuple[str, str]], max_output_tokens: int = 1024, temperature: float = 0.2) -> str:
        """``turns`` is a list of (role, text) with role ``user`` or ``model``. Returns the model's text."""
        if not self.configured:
            raise LlmUnavailable("not_configured", "no Gemma model name or API key is set")
        body: dict[str, Any] = {
            "contents": [{"role": role, "parts": [{"text": text}]} for role, text in turns],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens},
        }
        url = f"{self._base}/models/{self._model}:generateContent"
        last: LlmUnavailable | None = None
        for attempt in range(self._retries + 1):
            try:
                r = self._http.post(url, json=body, headers={"x-goog-api-key": self._key})
            except httpx.TimeoutException:
                last = LlmUnavailable("timeout", "the language model did not answer in time")
            except httpx.TransportError:
                last = LlmUnavailable("unreachable", "the language model service could not be reached")
            else:
                if r.status_code == 200:
                    return self._text(r)
                if r.status_code in (401, 403):
                    raise LlmUnavailable("api_key_rejected", "the language model service rejected the API key")
                if r.status_code == 404:
                    raise LlmUnavailable("model_not_found", "the configured Gemma model name was not found")
                if r.status_code == 400:
                    raise LlmUnavailable("bad_request", "the language model service rejected the request")
                last = LlmUnavailable("rate_limited" if r.status_code == 429 else "server_error",
                                      f"the language model service answered {r.status_code}")
            if attempt < self._retries:
                self._sleep(1.0)
        raise last or LlmUnavailable("unreachable", "the language model service could not be reached")

    @staticmethod
    def _text(r: httpx.Response) -> str:
        try:
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        except (ValueError, KeyError, IndexError, TypeError):
            raise LlmUnavailable("empty_reply", "the language model returned no usable text") from None
        if not text:
            raise LlmUnavailable("empty_reply", "the language model returned no usable text")
        return text
