"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from koebinar.config import Settings, reset_settings_cache
from koebinar.main import create_app
from koebinar.storage import Store, set_store
from tests.mocks.providers import (
    VALID_EL_KEY,
    VALID_ORCA_KEY,
    install_mocks,
)


@pytest.fixture()
def tmp_dirs(tmp_path: Path):
    data = tmp_path / "data"
    artifacts = tmp_path / "artifacts"
    data.mkdir()
    artifacts.mkdir()
    dict_path = Path(__file__).resolve().parents[1] / "data" / "pronunciation_dict.tsv"
    return data, artifacts, dict_path


@pytest.fixture()
def settings(tmp_dirs) -> Settings:
    reset_settings_cache()
    data, artifacts, dict_path = tmp_dirs
    s = Settings(
        data_dir=data,
        artifacts_dir=artifacts,
        db_path=data / "test.db",
        pronunciation_dict_path=dict_path,
        master_key="test-master-key",
        allow_system_llm_key=False,
        allow_system_tts_key=False,
        orcarouter_api_key="",
        elevenlabs_api_key="",
        default_auth_token="mvp-token",
        confidence_threshold=0.7,
        # Unit/E2E table tests run pipeline in-process by default.
        sync_pipeline=True,
        force_render_double=True,
        remotion_project_dir=Path(__file__).resolve().parents[1] / "remotion",
    )
    s.ensure_dirs()
    return s


@pytest.fixture()
def store(settings: Settings) -> Store:
    st = Store(settings=settings, memory=False)
    set_store(st)
    return st


@pytest.fixture()
def mock_providers():
    with install_mocks() as router:
        yield router


@pytest.fixture()
def client(settings: Settings, store: Store, mock_providers):
    app = create_app(settings=settings, store=store, http_client=httpx.Client())
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer mvp-token"})
        yield c


@pytest.fixture()
def auth_headers():
    return {"Authorization": "Bearer mvp-token"}


@pytest.fixture()
def register_keys(client: TestClient):
    def _reg():
        r1 = client.post(
            "/api/v1/integrations/orcarouter",
            json={"api_key": VALID_ORCA_KEY},
        )
        assert r1.status_code == 200, r1.text
        r2 = client.post(
            "/api/v1/integrations/elevenlabs",
            json={"api_key": VALID_EL_KEY, "accept_free_tier": False},
        )
        assert r2.status_code == 200, r2.text
        return r1.json(), r2.json()

    return _reg
