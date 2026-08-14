"""Pipeline worker process — claims jobs and runs orchestrator steps."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from typing import Optional

import httpx

from koebinar.config import Settings, get_settings, reset_settings_cache
from koebinar.jobs import JobQueue, JobStatus
from koebinar.pipeline.orchestrator import PipelineError, PipelineOrchestrator
from koebinar.storage import Store, open_store, set_store

logger = logging.getLogger("koebinar.worker")

_STOP = False


def _handle_signal(signum, frame) -> None:  # noqa: ANN001
    global _STOP
    _STOP = True
    logger.info("shutdown signal received (%s)", signum)


def process_one(
    store: Store,
    settings: Settings,
    *,
    http_client: Optional[httpx.Client] = None,
) -> bool:
    """Claim and process at most one job. Returns True if a job was handled."""
    queue = JobQueue(store)
    job = queue.claim_next()
    if job is None:
        return False
    logger.info("claimed job %s webinar=%s step=%s", job.id, job.webinar_id, job.step)
    orch = PipelineOrchestrator(
        store=store,
        settings=settings,
        http_client=http_client,
        tenant_id=job.tenant_id,
    )
    try:
        orch.run_from(job.webinar_id, job.step)
        queue.complete(job.id)
        logger.info("completed job %s", job.id)
    except Exception as exc:
        logger.exception("job %s failed: %s", job.id, exc)
        queue.fail(job.id, str(exc))
        # webinar status already set by orchestrator on failure
    return True


def run_worker(
    settings: Optional[Settings] = None,
    *,
    max_jobs: Optional[int] = None,
    http_client: Optional[httpx.Client] = None,
) -> int:
    """Run the worker loop. Returns number of jobs processed."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = open_store(settings)
    set_store(store)
    processed = 0
    logger.info(
        "worker started db=%s artifacts=%s poll=%.2fs",
        settings.db_path,
        settings.artifacts_dir,
        settings.worker_poll_interval_sec,
    )
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=60.0)
    try:
        while not _STOP:
            did = process_one(store, settings, http_client=client)
            if did:
                processed += 1
                if max_jobs is not None and processed >= max_jobs:
                    break
                continue
            if settings.worker_idle_exit or (max_jobs is not None and processed >= (max_jobs or 0) and processed > 0):
                if settings.worker_idle_exit:
                    break
            if max_jobs == 0:
                break
            time.sleep(settings.worker_poll_interval_sec)
            if settings.worker_idle_exit and JobQueue(store).pending_count() == 0:
                # drain: if nothing pending and nothing just done, exit
                break
    finally:
        if owns_client:
            client.close()
        store.close()
    logger.info("worker stopped processed=%d", processed)
    return processed


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Koebinar pipeline worker")
    parser.add_argument("--max-jobs", type=int, default=None, help="Stop after N jobs (tests)")
    parser.add_argument("--once", action="store_true", help="Process at most one job then exit")
    parser.add_argument("--idle-exit", action="store_true", help="Exit when queue is empty")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    reset_settings_cache()
    settings = get_settings()
    if args.idle_exit:
        settings.worker_idle_exit = True
    max_jobs = 1 if args.once else args.max_jobs
    run_worker(settings, max_jobs=max_jobs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
