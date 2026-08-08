"""FastAPI dependencies and app state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx
from fastapi import Header, HTTPException, Request

from koebinar.config import Settings, get_settings
from koebinar.integrations.service import IntegrationsService
from koebinar.knowledge.service import KnowledgeService
from koebinar.pipeline.orchestrator import PipelineOrchestrator
from koebinar.qa.service import QAService
from koebinar.storage import Store, get_store


@dataclass
class AppState:
    settings: Settings
    store: Store
    http_client: Optional[httpx.Client] = None
    knowledge: KnowledgeService = field(init=False)
    integrations: IntegrationsService = field(init=False)
    pipeline: PipelineOrchestrator = field(init=False)
    qa: QAService = field(init=False)

    def __post_init__(self) -> None:
        self.knowledge = KnowledgeService(store=self.store)
        self.integrations = IntegrationsService(
            store=self.store, settings=self.settings, http_client=self.http_client
        )
        self.pipeline = PipelineOrchestrator(
            store=self.store, settings=self.settings, http_client=self.http_client
        )
        self.qa = QAService(
            store=self.store,
            settings=self.settings,
            knowledge=self.knowledge,
            integrations=self.integrations,
            http_client=self.http_client,
        )


def get_app_state(request: Request) -> AppState:
    return request.app.state.koebinar


def require_auth(
    authorization: Optional[str] = Header(default=None),
    x_api_token: Optional[str] = Header(default=None),
) -> None:
    # Do not accept Settings as a FastAPI param (it would be treated as a body model).
    settings = get_settings()
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif x_api_token:
        token = x_api_token.strip()
    if token != settings.default_auth_token:
        raise HTTPException(status_code=401, detail="unauthorized")
