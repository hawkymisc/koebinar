"""TTS adapter: pronunciation apply, sentence split, synthesize, cache."""

from __future__ import annotations

import hashlib
import wave
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from koebinar.config import Settings, get_settings
from koebinar.crypto import generate_id
from koebinar.integrations.elevenlabs import ElevenLabsClient, ElevenLabsError
from koebinar.integrations.service import IntegrationError, IntegrationsService
from koebinar.models import Provider
from koebinar.pipeline.audio_format import AudioFormat, AudioFormatError, load_audio_format, silence_wav
from koebinar.pipeline.pronunciation import (
    apply_pronunciation,
    estimate_tts_credits,
    load_pronunciation_dict,
    split_for_tts,
)
from koebinar.storage import Store, get_store


def cache_key(text: str, voice_id: str, model_id: str, settings_hash: str = "") -> str:
    raw = f"{text}|{voice_id}|{model_id}|{settings_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def estimate_duration_sec(text: str, lang: str = "ja") -> float:
    """Heuristic duration when audio binary has no reliable header."""
    chars = max(1, len(text or ""))
    # ~4 chars/sec JA, ~13 chars/sec EN reading speed approximation
    cps = 13.0 if lang == "en" else 4.0
    return max(0.5, chars / cps)


def wav_duration_sec(data: bytes) -> float | None:
    try:
        with wave.open(BytesIO(data), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            return frames / float(rate)
    except Exception:
        return None


def synthesize_silence_wav(duration_sec: float, sample_rate: int = 22050) -> bytes:
    """Generate a valid WAV fixture; provider failures are never replaced by it."""
    return silence_wav(duration_sec, sample_rate=sample_rate)


class TTSAdapter:
    def __init__(
        self,
        store: Optional[Store] = None,
        settings: Optional[Settings] = None,
        integrations: Optional[IntegrationsService] = None,
        http_client=None,
    ) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        self.integrations = integrations or IntegrationsService(
            store=self.store, settings=self.settings, http_client=http_client
        )
        self.http_client = http_client
        self._dict = load_pronunciation_dict(self.settings.pronunciation_dict_path)

    def prepare_tts_script(self, script: dict[str, Any], lang: str) -> dict[str, Any]:
        slides_out: list[dict[str, Any]] = []
        total_credits = 0
        for i, slide in enumerate(script.get("slides") or []):
            narration = slide.get("narration") or slide.get("text") or ""
            corrected = apply_pronunciation(narration, self._dict)
            sentences = split_for_tts(corrected, lang=lang)
            credits = sum(estimate_tts_credits(s) for s in sentences)
            total_credits += credits
            slides_out.append(
                {
                    "slide_index": i,
                    "title": slide.get("title", f"Slide {i + 1}"),
                    "original": narration,
                    "corrected": corrected,
                    "sentences": sentences,
                    "document_ids": slide.get("document_ids") or slide.get("references") or [],
                    "credits": credits,
                }
            )
        return {
            "lang": lang,
            "slides": slides_out,
            "total_credits": total_credits,
            "prompt_version": self.settings.prompt_version,
        }

    def synthesize_script(
        self,
        webinar_id: str,
        tts_script: dict[str, Any],
        voice_id: str,
        lang: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return (durations list, meta). Fail closed if no key or no consent."""
        # Re-check at the external side-effect boundary: consent may have been
        # revoked while an asynchronous job was waiting in the queue.
        self.integrations.assert_voice_usable(voice_id)
        api_key = self.integrations.resolve_api_key(Provider.ELEVENLABS, require=True)
        client = ElevenLabsClient(
            api_key,
            base_url=self.settings.elevenlabs_base_url,
            settings=self.settings,
            client=self.http_client,
        )
        durations: list[dict[str, Any]] = []
        model_id = self.settings.tts_model
        output_format = self.settings.tts_output_format
        try:
            for slide in tts_script.get("slides") or []:
                sidx = int(slide.get("slide_index", 0))
                for j, sentence in enumerate(slide.get("sentences") or []):
                    key = cache_key(sentence, voice_id, model_id, settings_hash=output_format)
                    if self.integrations.tenant_id != "default":
                        key = f"{self.integrations.tenant_id}:{key}"
                    entry = self._reuse_cached(key)
                    if entry is None:
                        entry = self._synthesize_one(
                            client,
                            webinar_id=webinar_id,
                            voice_id=voice_id,
                            sentence=sentence,
                            model_id=model_id,
                            output_format=output_format,
                            slide_index=sidx,
                            sentence_index=j,
                        )
                        self.store.tts_cache[key] = entry
                        cache_hit = False
                    else:
                        cache_hit = True
                    durations.append(
                        {
                            "slide_index": sidx,
                            "sentence_index": j,
                            "text": sentence,
                            "cache_hit": cache_hit,
                            **entry,
                        }
                    )
            self.store.add_generation_log(
                purpose="tts",
                model_id=model_id,
                prompt_version=self.settings.prompt_version,
                cost_hint=str(tts_script.get("total_credits", 0)),
                tenant_id=self.integrations.tenant_id,
            )
            return durations, {
                "model_id": model_id,
                "voice_id": voice_id,
                "output_format": output_format,
            }
        finally:
            if self.http_client is None:
                client.close()

    def _artifact_entry(self, audio_uri: str, fmt: AudioFormat) -> dict[str, Any]:
        root = Path(self.store.settings.artifacts_dir).resolve()
        path = Path(audio_uri)
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise AudioFormatError(f"audio artifact is outside artifact root: {path}") from exc
        return {
            "audio_uri": str(path),
            "audio_rel_path": relative,
            "duration_sec": fmt.duration_sec,
            "codec": fmt.codec,
            "content_type": fmt.content_type,
            "extension": fmt.extension,
            "sample_rate": fmt.sample_rate,
            "channels": fmt.channels,
        }

    def _reuse_cached(self, key: str) -> Optional[dict[str, Any]]:
        """Reuse cache only after re-reading and decoding the artifact."""
        cached = self.store.tts_cache.get(key)
        if not cached or not cached.get("audio_uri"):
            return None
        try:
            fmt = load_audio_format(cached["audio_uri"])
            return self._artifact_entry(cached["audio_uri"], fmt)
        except (AudioFormatError, TypeError, ValueError):
            return None

    def _synthesize_one(
        self,
        client: ElevenLabsClient,
        *,
        webinar_id: str,
        voice_id: str,
        sentence: str,
        model_id: str,
        output_format: str,
        slide_index: int,
        sentence_index: int,
    ) -> dict[str, Any]:
        try:
            audio = client.synthesize(
                voice_id,
                sentence,
                model_id=model_id,
                output_format=output_format,
            )
        except ElevenLabsError as exc:
            if exc.status_code in (401, 403):
                self.integrations.mark_invalid(Provider.ELEVENLABS)
            raise
        fmt = audio.audio_format
        filename = f"audio/s{slide_index}_{sentence_index}_{generate_id()}{fmt.extension}"
        audio_uri = self.store.write_bytes_atomic(webinar_id, filename, audio.data)
        return self._artifact_entry(audio_uri, fmt)
