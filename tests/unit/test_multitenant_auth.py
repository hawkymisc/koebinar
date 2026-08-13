"""Acceptance tests for tenant authentication and operator data isolation."""

from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from koebinar.config import Settings
from koebinar.main import create_app
from koebinar.storage import Store
from tests.mocks.providers import VALID_ORCA_KEY


def _tenant_client(settings: Settings, mock_providers) -> tuple[TestClient, Store]:
    tenant_settings = settings.model_copy(
        update={
            "default_auth_token": "",
            "sync_pipeline": False,
            "tenants_json": json.dumps(
                [
                    {"id": "acme", "name": "Acme株式会社", "access_token": "acme-secret"},
                    {"id": "globex", "name": "Globex株式会社", "access_token": "globex-secret"},
                ]
            ),
        }
    )
    store = Store(settings=tenant_settings, memory=True)
    app = create_app(settings=tenant_settings, store=store, http_client=httpx.Client())
    return TestClient(app), store


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_and_session_resolve_the_configured_tenant(settings, mock_providers):
    client, _ = _tenant_client(settings, mock_providers)
    with client:
        login = client.post(
            "/api/v1/auth/login",
            json={"workspace_id": "acme", "access_token": "acme-secret"},
        )
        assert login.status_code == 200
        assert login.json() == {
            "tenant": {"id": "acme", "name": "Acme株式会社"},
            "token": "acme-secret",
        }

        session = client.get("/api/v1/auth/session", headers=_headers("acme-secret"))
        assert session.status_code == 200
        assert session.json() == {"tenant": {"id": "acme", "name": "Acme株式会社"}}

        denied = client.post(
            "/api/v1/auth/login",
            json={"workspace_id": "acme", "access_token": "globex-secret"},
        )
        assert denied.status_code == 401
        assert "token" not in denied.text.lower()


def test_documents_and_webinars_are_isolated_between_tenants(settings, mock_providers):
    client, _ = _tenant_client(settings, mock_providers)
    with client:
        acme_doc = client.post(
            "/api/v1/knowledge/documents",
            headers=_headers("acme-secret"),
            json={"title": "Acme handbook", "source_type": "text", "content": "Acme only"},
        )
        globex_doc = client.post(
            "/api/v1/knowledge/documents",
            headers=_headers("globex-secret"),
            json={"title": "Globex handbook", "source_type": "text", "content": "Globex only"},
        )
        assert acme_doc.status_code == globex_doc.status_code == 200
        assert acme_doc.json()["tenant_id"] == "acme"
        assert globex_doc.json()["tenant_id"] == "globex"

        acme_list = client.get("/api/v1/knowledge/documents", headers=_headers("acme-secret"))
        globex_list = client.get("/api/v1/knowledge/documents", headers=_headers("globex-secret"))
        assert [item["id"] for item in acme_list.json()] == [acme_doc.json()["id"]]
        assert [item["id"] for item in globex_list.json()] == [globex_doc.json()["id"]]

        hidden = client.get(
            f"/api/v1/knowledge/documents/{acme_doc.json()['id']}",
            headers=_headers("globex-secret"),
        )
        assert hidden.status_code == 404

        webinar = client.post(
            "/api/v1/webinars",
            headers=_headers("acme-secret"),
            json={
                "theme": "Acme launch",
                "document_ids": [acme_doc.json()["id"]],
                "auto_run": False,
            },
        )
        assert webinar.status_code == 200
        assert webinar.json()["tenant_id"] == "acme"
        assert client.get(
            f"/api/v1/webinars/{webinar.json()['id']}",
            headers=_headers("globex-secret"),
        ).status_code == 404

        cross_tenant_document = client.post(
            "/api/v1/webinars",
            headers=_headers("globex-secret"),
            json={
                "theme": "Must not use Acme data",
                "document_ids": [acme_doc.json()["id"]],
                "auto_run": False,
            },
        )
        assert cross_tenant_document.status_code == 404

        queued = client.post(
            "/api/v1/webinars",
            headers=_headers("acme-secret"),
            json={"theme": "Tenant job", "auto_run": True},
        )
        assert queued.status_code == 200
        assert queued.json()["job_id"]
        assert client.get(
            f"/api/v1/webinars/{queued.json()['id']}/jobs",
            headers=_headers("globex-secret"),
        ).status_code == 404
        assert client.get(
            f"/api/v1/jobs/{queued.json()['job_id']}",
            headers=_headers("globex-secret"),
        ).status_code == 404


def test_byok_integrations_are_tenant_scoped(settings, mock_providers):
    client, store = _tenant_client(settings, mock_providers)
    with client:
        registered = client.post(
            "/api/v1/integrations/orcarouter",
            headers=_headers("acme-secret"),
            json={"api_key": VALID_ORCA_KEY},
        )
        assert registered.status_code == 200
        globex_registered = client.post(
            "/api/v1/integrations/orcarouter",
            headers=_headers("globex-secret"),
            json={"api_key": VALID_ORCA_KEY},
        )
        assert globex_registered.status_code == 200
        assert globex_registered.json()["id"] != registered.json()["id"]

        acme = client.get("/api/v1/integrations", headers=_headers("acme-secret"))
        globex = client.get("/api/v1/integrations", headers=_headers("globex-secret"))
        assert [item["provider"] for item in acme.json()] == ["orcarouter"]
        assert [item["provider"] for item in globex.json()] == ["orcarouter"]

        deleted = client.delete(
            "/api/v1/integrations/orcarouter",
            headers=_headers("globex-secret"),
        )
        assert deleted.status_code == 200
        assert client.get("/api/v1/integrations", headers=_headers("globex-secret")).json() == []
        assert len(client.get("/api/v1/integrations", headers=_headers("acme-secret")).json()) == 1

        records = [record for record in store.integrations.values() if record.status.value != "deleted"]
        assert len(records) == 1
        assert records[0].tenant_id == "acme"


def test_legacy_single_token_maps_to_default_tenant(settings, store, mock_providers):
    app = create_app(settings=settings, store=store, http_client=httpx.Client())
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/session", headers=_headers("mvp-token"))
        assert response.status_code == 200
        assert response.json() == {"tenant": {"id": "default", "name": "Koebinar"}}
