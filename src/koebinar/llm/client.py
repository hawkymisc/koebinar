"""OrcaRouter OpenAI-compatible LLM client."""

from __future__ import annotations

import json
import math
import re
import time
from typing import Any, Optional

import httpx

from koebinar.config import Settings, get_settings


class LLMError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        provider_code: str | None = None,
        provider_message: str | None = None,
        provider_type: str | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code
        self.provider_message = provider_message
        self.provider_type = provider_type
        # Compatibility names used by retry and capability decisions.
        self.error_code = error_code or provider_code
        self.error_type = provider_type


class OrcaRouterClient:
    """Thin OpenAI-compatible client used for all LLM calls."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        settings: Optional[Settings] = None,
        client: Optional[httpx.Client] = None,
        timeout: float | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.api_key = api_key
        self.base_url = (base_url or self.settings.orcarouter_base_url).rstrip("/")
        read_timeout = timeout if timeout is not None else self.settings.orcarouter_read_timeout_sec
        self._timeout = httpx.Timeout(
            connect=self.settings.orcarouter_connect_timeout_sec,
            read=read_timeout,
            write=self.settings.orcarouter_write_timeout_sec,
            pool=self.settings.orcarouter_pool_timeout_sec,
        )
        self._models_timeout = httpx.Timeout(
            connect=self.settings.orcarouter_connect_timeout_sec,
            read=self.settings.orcarouter_models_read_timeout_sec,
            write=self.settings.orcarouter_write_timeout_sec,
            pool=self.settings.orcarouter_pool_timeout_sec,
        )
        self._client = client or httpx.Client(timeout=self._timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _safe_provider_text(self, value: Any, *, limit: int = 500) -> str | None:
        if not isinstance(value, str):
            return None
        text = " ".join(value.split())
        if not text:
            return None
        if self.api_key:
            text = text.replace(self.api_key, "[redacted]")
        return text[:limit]

    def _response_error(self, operation: str, response: httpx.Response) -> LLMError:
        provider_code: str | None = None
        provider_message: str | None = None
        provider_type: str | None = None
        error_code: str | None = None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("error") or payload.get("detail")
            if isinstance(detail, dict):
                raw_code = detail.get("code") or detail.get("type")
                if isinstance(raw_code, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", raw_code):
                    error_code = raw_code
                provider_type = self._safe_provider_text(detail.get("type"), limit=100)
                provider_code = self._safe_provider_text(
                    raw_code, limit=100
                )
                provider_message = self._safe_provider_text(detail.get("message"))

        message = f"OrcaRouter {operation} error: HTTP {response.status_code}"
        if provider_code:
            message += f" [{provider_code}]"
        if provider_message:
            message += f" {provider_message}"
        return LLMError(
            message,
            status_code=response.status_code,
            provider_code=provider_code,
            provider_message=provider_message,
            provider_type=provider_type,
            error_code=error_code,
        )

    def list_models(self) -> dict[str, Any]:
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url, headers=self._headers(), timeout=self._models_timeout)
        except httpx.HTTPError as exc:
            raise LLMError(f"OrcaRouter models request failed: {exc}") from exc
        if response.status_code >= 400:
            raise self._response_error("models", response)
        return response.json()

    def chat_completions(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        response_format: Optional[dict[str, Any]] = None,
        retries: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        retry_count = self.settings.orcarouter_max_retries if retries is None else retries
        attempts = max(1, retry_count + 1)
        for attempt in range(attempts):
            try:
                response = self._client.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                error = LLMError(f"OrcaRouter chat request failed: {exc}")
                if attempt + 1 < attempts:
                    time.sleep(self._backoff_delay(attempt))
                    continue
                raise error from exc
            if response.status_code >= 400:
                error = self._response_error("chat", response)
                delay = self._retry_delay(response, error, attempt)
                if attempt + 1 < attempts and delay is not None:
                    time.sleep(delay)
                    continue
                raise error
            return response.json()
        raise AssertionError("unreachable OrcaRouter retry state")

    def _backoff_delay(self, attempt: int) -> float:
        return min(
            self.settings.orcarouter_retry_backoff_sec * (2**attempt),
            self.settings.orcarouter_retry_max_delay_sec,
        )

    def _retry_delay(
        self,
        response: httpx.Response,
        error: LLMError,
        attempt: int,
    ) -> float | None:
        if response.status_code == 503 and error.error_code in {
            "model_not_found",
            "byok:key_unavailable",
        }:
            return None
        if response.status_code == 429:
            return self._retry_after_delay(response)
        if response.status_code in {408, 409, 500, 502, 503, 504}:
            retry_after = self._retry_after_delay(response)
            return retry_after if retry_after is not None else self._backoff_delay(attempt)
        return None

    def _retry_after_delay(self, response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            delay = float(raw)
        except ValueError:
            return None
        if (
            not math.isfinite(delay)
            or delay < 0
            or delay > self.settings.orcarouter_retry_max_delay_sec
        ):
            return None
        return delay

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        try:
            data = self.chat_completions(
                messages,
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except LLMError as exc:
            # Anthropic upstreams do not implement response_format. Retry only
            # this capability mismatch with the JSON-instructed prompt.
            if exc.status_code != 400 or exc.error_code != "api_not_implemented":
                raise
            data = self.chat_completions(
                messages,
                model=model,
                temperature=temperature,
                response_format=None,
            )
        content = parse_chat_content(data)
        if isinstance(content, dict):
            return content
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMError("malformed JSON chat completion response") from exc
        if not isinstance(parsed, dict):
            raise LLMError("malformed JSON chat completion response")
        return parsed


def parse_chat_content(response: dict[str, Any]) -> Any:
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("malformed chat completion response") from exc
