"""OrcaRouter OpenAI-compatible LLM client."""

from __future__ import annotations

import json
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
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code
        self.provider_message = provider_message


class OrcaRouterClient:
    """Thin OpenAI-compatible client used for all LLM calls."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        settings: Optional[Settings] = None,
        client: Optional[httpx.Client] = None,
        timeout: float = 60.0,
    ) -> None:
        self.settings = settings or get_settings()
        self.api_key = api_key
        self.base_url = (base_url or self.settings.orcarouter_base_url).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
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

    def _response_error(self, operation: str, resp: httpx.Response) -> LLMError:
        provider_code: str | None = None
        provider_message: str | None = None
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("error") or payload.get("detail")
            if isinstance(detail, dict):
                provider_code = self._safe_provider_text(
                    detail.get("code") or detail.get("type"), limit=100
                )
                provider_message = self._safe_provider_text(detail.get("message"))

        message = f"OrcaRouter {operation} error: HTTP {resp.status_code}"
        if provider_code:
            message += f" [{provider_code}]"
        if provider_message:
            message += f" {provider_message}"
        return LLMError(
            message,
            status_code=resp.status_code,
            provider_code=provider_code,
            provider_message=provider_message,
        )

    def list_models(self) -> dict[str, Any]:
        url = f"{self.base_url}/models"
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise LLMError(f"OrcaRouter models request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise self._response_error("models", resp)
        return resp.json()

    def chat_completions(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        response_format: Optional[dict[str, Any]] = None,
        retries: int = 1,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        last_err: Exception | None = None
        attempts = max(1, retries + 1)
        for _ in range(attempts):
            try:
                resp = self._client.post(url, headers=self._headers(), json=payload)
            except httpx.HTTPError as exc:
                last_err = LLMError(f"OrcaRouter chat request failed: {exc}")
                continue
            if resp.status_code >= 400:
                last_err = self._response_error("chat", resp)
                if resp.status_code in (401, 403):
                    raise last_err
                continue
            return resp.json()
        assert last_err is not None
        raise last_err

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        data = self.chat_completions(
            messages,
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            return content
        return json.loads(content)


def parse_chat_content(response: dict[str, Any]) -> str:
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("malformed chat completion response") from exc
