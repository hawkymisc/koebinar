"""Isolated API process for browser E2E with local provider doubles."""

from __future__ import annotations

import argparse
import atexit
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from koebinar.config import Settings
from koebinar.main import create_app
from koebinar.storage import open_store
from tests.mocks.providers import install_mocks

RUN_DIRECTORY = tempfile.TemporaryDirectory(prefix="koebinar-browser-e2e-")
atexit.register(RUN_DIRECTORY.cleanup)


def build_app():
    run_dir = Path(RUN_DIRECTORY.name)
    settings = Settings(
        data_dir=run_dir / "data",
        artifacts_dir=run_dir / "artifacts",
        db_path=run_dir / "data" / "e2e.db",
        pronunciation_dict_path=ROOT / "data" / "pronunciation_dict.tsv",
        remotion_project_dir=ROOT / "remotion",
        master_key="browser-e2e-master-key",
        default_auth_token="mvp-token",
        sync_pipeline=True,
        force_render_double=False,
        remotion_timeout_sec=150,
    )
    settings.ensure_dirs()
    mocks = install_mocks()
    mocks.start()
    atexit.register(mocks.stop)
    store = open_store(settings)
    return create_app(settings=settings, store=store, http_client=httpx.Client())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18002)
    args = parser.parse_args()
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="warning")
