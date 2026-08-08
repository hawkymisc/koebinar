"""In-memory repository + filesystem artifact store."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from koebinar.config import Settings, get_settings
from koebinar.crypto import generate_id
from koebinar.models import (
    Answer,
    Chunk,
    GenerationLog,
    IntegrationStatus,
    IntentSignal,
    KnowledgeDocument,
    PipelineArtifact,
    Provider,
    Question,
    Webinar,
)


class IntegrationRecord:
    """Internal record holding encrypted key (never returned via API as plaintext)."""

    def __init__(
        self,
        id: str,
        provider: Provider,
        encrypted_api_key: str,
        key_mask: str,
        status: IntegrationStatus,
        validated_at: Any = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.id = id
        self.provider = provider
        self.encrypted_api_key = encrypted_api_key
        self.key_mask = key_mask
        self.status = status
        self.validated_at = validated_at
        self.meta = meta or {}


class Store:
    """Thread-safe application store for MVP (process-local)."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self._lock = threading.RLock()
        self.documents: dict[str, KnowledgeDocument] = {}
        self.chunks: dict[str, list[Chunk]] = {}
        self.webinars: dict[str, Webinar] = {}
        self.integrations: dict[Provider, IntegrationRecord] = {}
        self.questions: dict[str, Question] = {}
        self.answers: dict[str, Answer] = {}
        self.intent_signals: list[IntentSignal] = []
        self.generation_logs: list[GenerationLog] = []
        self.voice_refs: dict[str, dict[str, Any]] = {}
        self.tts_cache: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        with self._lock:
            self.documents.clear()
            self.chunks.clear()
            self.webinars.clear()
            self.integrations.clear()
            self.questions.clear()
            self.answers.clear()
            self.intent_signals.clear()
            self.generation_logs.clear()
            self.voice_refs.clear()
            self.tts_cache.clear()

    # --- artifacts on disk ---

    def artifact_path(self, webinar_id: str, name: str) -> Path:
        base = self.settings.artifacts_dir / webinar_id
        base.mkdir(parents=True, exist_ok=True)
        return base / name

    def write_json(self, webinar_id: str, name: str, data: Any) -> str:
        path = self.artifact_path(webinar_id, name)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(path)

    def write_bytes(self, webinar_id: str, name: str, data: bytes) -> str:
        path = self.artifact_path(webinar_id, name)
        path.write_bytes(data)
        return str(path)

    def read_json(self, uri: str) -> Any:
        return json.loads(Path(uri).read_text(encoding="utf-8"))

    def add_generation_log(self, purpose: str, model_id: str, prompt_version: str, cost_hint: str | None = None) -> GenerationLog:
        log = GenerationLog(
            id=generate_id("log_"),
            request_id=generate_id("req_"),
            purpose=purpose,
            model_id=model_id,
            prompt_version=prompt_version,
            cost_hint=cost_hint,
        )
        with self._lock:
            self.generation_logs.append(log)
        return log


# Global store used by default app; tests can inject alternatives.
_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def set_store(store: Store) -> None:
    global _store
    _store = store


def reset_store() -> Store:
    store = Store()
    set_store(store)
    return store
