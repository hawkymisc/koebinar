"""ElevenLabs-compatible HTTP client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from koebinar.config import Settings, get_settings
from koebinar.pipeline.audio_format import (
    ELEVENLABS_OUTPUT_FORMATS,
    AudioFormat,
    AudioFormatError,
    detect_audio_format,
)


class ElevenLabsError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        provider_code: str | None = None,
        provider_message: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_code = provider_code
        self.provider_message = provider_message
        self.request_id = request_id


@dataclass(frozen=True)
class SynthesizedAudio:
    """One provider response with a validated on-disk artifact contract."""

    data: bytes
    audio_format: AudioFormat
    requested_output_format: str
    declared_content_type: str

    @property
    def codec(self) -> str:
        return self.audio_format.codec

    @property
    def content_type(self) -> str:
        return self.audio_format.content_type

    @property
    def extension(self) -> str:
        return self.audio_format.extension

    @property
    def duration_sec(self) -> float:
        return self.audio_format.duration_sec


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

    def _safe_provider_text(self, value: Any, *, limit: int = 500) -> str | None:
        if not isinstance(value, str):
            return None
        text = " ".join(value.split())
        if not text:
            return None
        if self.api_key:
            text = text.replace(self.api_key, "[redacted]")
        return text[:limit]

    def _response_error(self, operation: str, resp: httpx.Response) -> ElevenLabsError:
        provider_code: str | None = None
        provider_message: str | None = None
        request_id: str | None = None
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail")
            # ElevenLabs has used both status/message and type/code/message
            # response shapes. Only structured fields are surfaced; arbitrary
            # response text stays out of user-visible errors.
            if isinstance(detail, dict):
                provider_code = self._safe_provider_text(
                    detail.get("code") or detail.get("status") or detail.get("type"),
                    limit=100,
                )
                provider_message = self._safe_provider_text(detail.get("message"))
                request_id = self._safe_provider_text(detail.get("request_id"), limit=100)

        message = f"{operation} error: HTTP {resp.status_code}"
        if provider_code:
            message += f" [{provider_code}]"
        if provider_message:
            message += f" {provider_message}"
        return ElevenLabsError(
            message,
            status_code=resp.status_code,
            provider_code=provider_code,
            provider_message=provider_message,
            request_id=request_id,
        )

    def get_subscription(self) -> dict[str, Any]:
        url = f"{self.base_url}/user/subscription"
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"subscription request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise self._response_error("subscription", resp)
        return resp.json()

    def list_voices(self) -> dict[str, Any]:
        url = f"{self.base_url}/voices"
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ElevenLabsError(f"voices request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise self._response_error("voices", resp)
        return resp.json()

    def _post_tts(
        self,
        voice_id: str,
        text: str,
        *,
        model_id: Optional[str],
        voice_settings: Optional[dict[str, Any]],
        output_format: Optional[str],
        retries: int,
    ) -> httpx.Response:
        url = f"{self.base_url}/text-to-speech/{voice_id}"
        payload: dict[str, Any] = {
            "text": text,
            "model_id": model_id or self.settings.tts_model,
        }
        if voice_settings:
            payload["voice_settings"] = voice_settings
        params = {"output_format": output_format} if output_format else None

        last_err: Exception | None = None
        attempts = max(1, retries + 1)
        for attempt in range(attempts):
            try:
                resp = self._client.post(url, headers=self._headers(), json=payload, params=params)
            except httpx.HTTPError as exc:
                last_err = ElevenLabsError(f"TTS request failed: {exc}")
                if attempt >= attempts - 1:
                    raise last_err from exc
                continue
            if resp.status_code >= 400:
                error = self._response_error("TTS", resp)
                # Provider 4xx responses (including voice_not_found) are
                # request-contract failures. Retrying them spends latency and
                # quota without changing the outcome; only 429 is transient.
                retryable = resp.status_code == 429 or resp.status_code >= 500
                if not retryable or attempt >= attempts - 1:
                    raise error
                last_err = error
                continue
            return resp
        assert last_err is not None
        raise last_err

    def text_to_speech(
        self,
        voice_id: str,
        text: str,
        *,
        model_id: Optional[str] = None,
        voice_settings: Optional[dict[str, Any]] = None,
        output_format: Optional[str] = None,
        retries: int = 2,
    ) -> bytes:
        """Return raw response bytes for backwards-compatible callers."""
        response = self._post_tts(
            voice_id,
            text,
            model_id=model_id,
            voice_settings=voice_settings,
            output_format=output_format,
            retries=retries,
        )
        return response.content

    def synthesize(
        self,
        voice_id: str,
        text: str,
        *,
        model_id: Optional[str] = None,
        voice_settings: Optional[dict[str, Any]] = None,
        output_format: Optional[str] = None,
        retries: int = 2,
    ) -> SynthesizedAudio:
        """Synthesize and reject payloads that cannot become playable artifacts."""
        requested = output_format or self.settings.tts_output_format
        if requested not in ELEVENLABS_OUTPUT_FORMATS:
            raise ElevenLabsError(f"unsupported ElevenLabs output_format: {requested}")
        response = self._post_tts(
            voice_id,
            text,
            model_id=model_id,
            voice_settings=voice_settings,
            output_format=requested,
            retries=retries,
        )
        declared = response.headers.get("content-type", "")
        try:
            audio_format = detect_audio_format(response.content, declared_content_type=declared)
        except AudioFormatError as exc:
            raise ElevenLabsError(f"TTS audio rejected: {exc}") from exc
        return SynthesizedAudio(
            data=response.content,
            audio_format=audio_format,
            requested_output_format=requested,
            declared_content_type=declared,
        )
