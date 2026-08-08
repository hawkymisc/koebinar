"""SQLite-backed job queue for async pipeline execution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from koebinar.crypto import generate_id
from koebinar.models import PipelineStep
from koebinar.storage import Store


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    id: str
    webinar_id: str
    step: str
    status: JobStatus = JobStatus.PENDING
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    attempts: int = 0


class JobQueue:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._conn = store._conn
        self._lock = store._lock

    def enqueue(self, webinar_id: str, step: PipelineStep | str) -> Job:
        step_s = step.value if isinstance(step, PipelineStep) else str(step)
        now = _utcnow().isoformat()
        job = Job(
            id=generate_id("job_"),
            webinar_id=webinar_id,
            step=step_s,
            status=JobStatus.PENDING,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs(id, webinar_id, step, status, error, created_at, updated_at, attempts) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (job.id, job.webinar_id, job.step, job.status.value, None, now, now, 0),
            )
            self._conn.commit()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, webinar_id, step, status, error, created_at, updated_at, attempts "
                "FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_job(row)

    def list_for_webinar(self, webinar_id: str) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, webinar_id, step, status, error, created_at, updated_at, attempts "
                "FROM jobs WHERE webinar_id=? ORDER BY created_at",
                (webinar_id,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def claim_next(self) -> Optional[Job]:
        """Atomically claim the oldest pending job."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM jobs WHERE status=? ORDER BY created_at LIMIT 1",
                (JobStatus.PENDING.value,),
            ).fetchone()
            if not row:
                return None
            job_id = row[0]
            now = _utcnow().isoformat()
            cur = self._conn.execute(
                "UPDATE jobs SET status=?, updated_at=?, attempts=attempts+1 "
                "WHERE id=? AND status=?",
                (JobStatus.RUNNING.value, now, job_id, JobStatus.PENDING.value),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
            row2 = self._conn.execute(
                "SELECT id, webinar_id, step, status, error, created_at, updated_at, attempts "
                "FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        return self._row_to_job(row2) if row2 else None

    def complete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status=?, updated_at=?, error=NULL WHERE id=?",
                (JobStatus.COMPLETED.value, _utcnow().isoformat(), job_id),
            )
            self._conn.commit()

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status=?, updated_at=?, error=? WHERE id=?",
                (JobStatus.FAILED.value, _utcnow().isoformat(), error[:2000], job_id),
            )
            self._conn.commit()

    def pending_count(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status=?",
                (JobStatus.PENDING.value,),
            ).fetchone()
        return int(row[0]) if row else 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def _row_to_job(self, row: tuple) -> Job:
        return Job(
            id=row[0],
            webinar_id=row[1],
            step=row[2],
            status=JobStatus(row[3]),
            error=row[4],
            created_at=datetime.fromisoformat(row[5]) if isinstance(row[5], str) else row[5],
            updated_at=datetime.fromisoformat(row[6]) if isinstance(row[6], str) else row[6],
            attempts=int(row[7] or 0),
        )
