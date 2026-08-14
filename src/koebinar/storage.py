"""Durable SQLite metadata store + filesystem artifact (object) store.

Process-safe: API and worker share the same db_path. Artifacts live under
artifacts_dir and survive process restarts independently of the API process.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from koebinar.config import Settings, get_settings
from koebinar.crypto import generate_id
from koebinar.models import (
    Answer,
    Chunk,
    GenerationLog,
    IntegrationStatus,
    IntentSignal,
    KnowledgeDocument,
    Provider,
    Question,
    Webinar,
)

T = TypeVar("T")


class IntegrationRecord:
    """Internal record holding encrypted key (never returned via API as plaintext)."""

    def __init__(
        self,
        id: str,
        provider: Provider,
        encrypted_api_key: str,
        key_mask: str,
        status: IntegrationStatus,
        tenant_id: str = "default",
        validated_at: Any = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.id = id
        self.tenant_id = tenant_id
        self.provider = provider
        self.encrypted_api_key = encrypted_api_key
        self.key_mask = key_mask
        self.status = status
        self.validated_at = validated_at
        self.meta = meta or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "provider": self.provider.value if isinstance(self.provider, Provider) else self.provider,
            "encrypted_api_key": self.encrypted_api_key,
            "key_mask": self.key_mask,
            "status": self.status.value if isinstance(self.status, IntegrationStatus) else self.status,
            "validated_at": self.validated_at.isoformat() if hasattr(self.validated_at, "isoformat") else self.validated_at,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntegrationRecord":
        from datetime import datetime

        va = data.get("validated_at")
        if isinstance(va, str):
            try:
                va = datetime.fromisoformat(va)
            except ValueError:
                pass
        return cls(
            id=data["id"],
            tenant_id=data.get("tenant_id") or "default",
            provider=Provider(data["provider"]),
            encrypted_api_key=data.get("encrypted_api_key") or "",
            key_mask=data.get("key_mask") or "",
            status=IntegrationStatus(data.get("status") or "active"),
            validated_at=va,
            meta=data.get("meta") or {},
        )


def _dumps(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(mode="json"), ensure_ascii=False, default=str)
    if isinstance(obj, IntegrationRecord):
        return json.dumps(obj.to_dict(), ensure_ascii=False, default=str)
    return json.dumps(obj, ensure_ascii=False, default=str)


def _loads_model(cls: type[T], raw: str) -> T:
    data = json.loads(raw)
    return cls.model_validate(data)  # type: ignore[attr-defined]


class _KvMap(MutableMapping[str, Any]):
    """SQLite-backed string-key map with JSON payloads."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        lock: threading.RLock,
        kind: str,
        decoder: Callable[[str], Any],
        encoder: Callable[[Any], str] | None = None,
    ) -> None:
        self._conn = conn
        self._lock = lock
        self._kind = kind
        self._decoder = decoder
        self._encoder = encoder or _dumps

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM kv WHERE kind=? AND key=?",
                (self._kind, str(key)),
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return self._decoder(row[0])

    def __setitem__(self, key: str, value: Any) -> None:
        payload = self._encoder(value)
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(kind, key, payload) VALUES(?,?,?) "
                "ON CONFLICT(kind, key) DO UPDATE SET payload=excluded.payload",
                (self._kind, str(key), payload),
            )
            self._conn.commit()

    def __delitem__(self, key: str) -> None:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM kv WHERE kind=? AND key=?",
                (self._kind, str(key)),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key FROM kv WHERE kind=?",
                (self._kind,),
            ).fetchall()
        return iter(r[0] for r in rows)

    def __len__(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM kv WHERE kind=?",
                (self._kind,),
            ).fetchone()
        return int(row[0]) if row else 0

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE kind=?", (self._kind,))
            self._conn.commit()

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        try:
            return self[key]
        except KeyError:
            return default

    def values(self):  # type: ignore[override]
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM kv WHERE kind=?",
                (self._kind,),
            ).fetchall()
        return [self._decoder(r[0]) for r in rows]

    def items(self):  # type: ignore[override]
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, payload FROM kv WHERE kind=?",
                (self._kind,),
            ).fetchall()
        return [(k, self._decoder(p)) for k, p in rows]

    def keys(self):  # type: ignore[override]
        return list(self)


class Store:
    """Thread- and multi-process-safe application store (SQLite + FS artifacts)."""

    def __init__(self, settings: Optional[Settings] = None, *, memory: bool = False) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self._lock = threading.RLock()
        self._memory = memory
        if memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            db = Path(self.settings.db_path)
            db.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db), check_same_thread=False, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._init_schema()

        self.documents: MutableMapping[str, KnowledgeDocument] = _KvMap(
            self._conn, self._lock, "document", lambda r: _loads_model(KnowledgeDocument, r)
        )
        self.chunks: MutableMapping[str, list[Chunk]] = _KvMap(
            self._conn,
            self._lock,
            "chunks",
            lambda r: [Chunk.model_validate(c) for c in json.loads(r)],
            encoder=lambda v: json.dumps([c.model_dump(mode="json") for c in v], ensure_ascii=False),
        )
        self.webinars: MutableMapping[str, Webinar] = _KvMap(
            self._conn, self._lock, "webinar", lambda r: _loads_model(Webinar, r)
        )
        self.integrations: MutableMapping[Provider, IntegrationRecord] = _KvMap(
            self._conn,
            self._lock,
            "integration",
            lambda r: IntegrationRecord.from_dict(json.loads(r)),
            encoder=lambda v: json.dumps(v.to_dict() if isinstance(v, IntegrationRecord) else v, default=str),
        )
        # Provider keys: normalize str/Provider
        self._wrap_provider_map()

        self.questions: MutableMapping[str, Question] = _KvMap(
            self._conn, self._lock, "question", lambda r: _loads_model(Question, r)
        )
        self.answers: MutableMapping[str, Answer] = _KvMap(
            self._conn, self._lock, "answer", lambda r: _loads_model(Answer, r)
        )
        self.intent_signals: list[IntentSignal] = self._load_list("intent_signals", IntentSignal)
        self.generation_logs: list[GenerationLog] = self._load_list("generation_logs", GenerationLog)
        self.voice_refs: MutableMapping[str, dict[str, Any]] = _KvMap(
            self._conn,
            self._lock,
            "voice_ref",
            lambda r: json.loads(r),
            encoder=lambda v: json.dumps(v, ensure_ascii=False, default=str),
        )
        self.tts_cache: MutableMapping[str, dict[str, Any]] = _KvMap(
            self._conn,
            self._lock,
            "tts_cache",
            lambda r: json.loads(r),
            encoder=lambda v: json.dumps(v, ensure_ascii=False, default=str),
        )

    def _wrap_provider_map(self) -> None:
        """Allow store.integrations[Provider.X] while keys stored as provider value strings."""
        inner = self.integrations
        store = self

        class ProviderMap(MutableMapping):
            def __getitem__(self, key):
                k = key.value if isinstance(key, Provider) else str(key)
                return inner[k]

            def __setitem__(self, key, value):
                k = key.value if isinstance(key, Provider) else str(key)
                inner[k] = value

            def __delitem__(self, key):
                k = key.value if isinstance(key, Provider) else str(key)
                del inner[k]

            def __iter__(self):
                for k in inner:
                    try:
                        yield Provider(k)
                    except ValueError:
                        yield k

            def __len__(self):
                return len(inner)

            def get(self, key, default=None):
                try:
                    return self[key]
                except KeyError:
                    return default

            def values(self):
                return inner.values()

            def items(self):
                return [(Provider(k) if k in {p.value for p in Provider} else k, v) for k, v in inner.items()]

            def clear(self):
                inner.clear()

            def keys(self):
                return list(self)

        self.integrations = ProviderMap()  # type: ignore[assignment]

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS kv (
                  kind TEXT NOT NULL,
                  key TEXT NOT NULL,
                  payload TEXT NOT NULL,
                  PRIMARY KEY (kind, key)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY,
                  webinar_id TEXT NOT NULL,
                  tenant_id TEXT NOT NULL DEFAULT 'default',
                  step TEXT NOT NULL,
                  status TEXT NOT NULL,
                  error TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
                """
            )
            columns = {
                row[1] for row in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "tenant_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE jobs ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
                )
            self._conn.commit()

    def _load_list(self, kind: str, cls: type) -> list:
        """List-like that auto-persists on append via subclass."""
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM kv WHERE kind=? AND key=?",
                (kind, "_list"),
            ).fetchone()
        items: list = []
        if row:
            items = [cls.model_validate(x) for x in json.loads(row[0])]
        return _PersistentList(self, kind, cls, items)

    def _save_list(self, kind: str, items: list) -> None:
        payload = json.dumps(
            [i.model_dump(mode="json") if hasattr(i, "model_dump") else i for i in items],
            ensure_ascii=False,
            default=str,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(kind, key, payload) VALUES(?,?,?) "
                "ON CONFLICT(kind, key) DO UPDATE SET payload=excluded.payload",
                (kind, "_list", payload),
            )
            self._conn.commit()

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv")
            self._conn.execute("DELETE FROM jobs")
            self._conn.commit()
        # re-bind list wrappers
        self.intent_signals = self._load_list("intent_signals", IntentSignal)
        self.generation_logs = self._load_list("generation_logs", GenerationLog)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- artifacts on disk (object store) ---

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

    def add_generation_log(
        self,
        purpose: str,
        model_id: str,
        prompt_version: str,
        cost_hint: str | None = None,
        tenant_id: str = "default",
    ) -> GenerationLog:
        log = GenerationLog(
            id=generate_id("log_"),
            tenant_id=tenant_id,
            request_id=generate_id("req_"),
            purpose=purpose,
            model_id=model_id,
            prompt_version=prompt_version,
            cost_hint=cost_hint,
        )
        self.generation_logs.append(log)
        return log


class _PersistentList(list):
    def __init__(self, store: Store, kind: str, cls: type, items: list) -> None:
        super().__init__(items)
        self._store = store
        self._kind = kind
        self._cls = cls

    def append(self, item: Any) -> None:  # type: ignore[override]
        super().append(item)
        self._store._save_list(self._kind, list(self))

    def clear(self) -> None:  # type: ignore[override]
        super().clear()
        self._store._save_list(self._kind, [])


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
    store = Store(memory=True)
    set_store(store)
    return store


def open_store(settings: Settings) -> Store:
    """Open a durable store for the given settings (API / worker)."""
    return Store(settings=settings, memory=False)
