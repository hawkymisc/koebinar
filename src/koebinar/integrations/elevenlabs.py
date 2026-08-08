"""ElevenLabs-compatible HTTP client."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from koebinar.config import Settings, get_settings


class ElevenLabsError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ElevenLabsClient:
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
        self.base_url = (base_url or self.settings.elevenlabs_base_url).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self.api_key, "Content-Type": "application/json"}

    def get_subscription(self) -> dict[str, Any]:
        url = f"{self.base_url}/user/subscription"
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"subscription request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise ElevenLabsError("invalid or unauthorized ElevenLabs API key", status_code=resp.status_code)
        if resp.status_code >= 400:
            raise ElevenLabsError(
                f"subscription error: {resp.status_code} {resp.text}",
                status_code=resp.status_code,
            )
        return resp.json()

    def list_voices(self) -> dict[str, Any]:
        url = f"{self.base_url}/voices"
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"voices request failed: {exc}") from exc
        if resp.status_code in (401, 403):
            raise ElevenLabsError("invalid or unauthorized ElevenLabs API key", status_code=resp.status_code)
        if resp.status_code >= 400:
            raise ElevenLabsError(f"voices error: {resp.status_code} {resp.text}", status_code=resp.status_code)
        return resp.json()

    def text_to_speech(
        self,
        voice_id: str,
        text: str,
        *,
        model_id: Optional[str] = None,
        voice_settings: Optional[dict[str, Any]] = None,
        retries: int = 2,
    ) -> bytes:
        url = f"{self.base_url}/text-to-speech/{voice_id}"
        payload: dict[str, Any] = {
            "text": text,
            "model_id": model_id or self.settings.tts_model,
        }
        if voice_settings:
            payload["voice_settings"] = voice_settings

        last_err: Exception | None = None
        attempts = max(1, retries + 1)
        for attempt in range(attempts):
            try:
                resp = self._client.post(url, headers=self._headers(), json=payload)
            except httpx.HTTPError as exc:
                last_err = ElevenLabsError(f"TTS request failed: {exc}")
                continue
            if resp.status_code in (401, 403):
                raise ElevenLabsError("invalid or unauthorized ElevenLabs API key", status_code=resp.status_code)
            if resp.status_code == 429 and attempt < attempts - 1:
                continue
            if resp.status_code >= 400:
                last_err = ElevenLabsError(
                    f"TTS error: {resp.status_code} {resp.text}",
                    status_code=resp.status_code,
                )
                continue
            return resp.content
        assert last_err is not None
        raise last_err
