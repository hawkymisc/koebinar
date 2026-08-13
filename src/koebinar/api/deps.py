"""FastAPI dependencies and app state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx
from fastapi import Header, HTTPException, Request

from koebinar.auth import AuthConfigurationError, AuthPrincipal, authenticate_token
from koebinar.config import Settings
from koebinar.integrations.service import IntegrationsService
from koebinar.knowledge.service import KnowledgeService
from koebinar.pipeline.orchestrator import PipelineOrchestrator
from koebinar.qa.service import QAService
from koebinar.rate_limit import RateLimiter
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
    public_qa_limiter: RateLimiter = field(default_factory=RateLimiter)

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

    def for_tenant(self, tenant_id: str) -> "TenantServices":
        if tenant_id == "default":
            return TenantServices(
                knowledge=self.knowledge,
                integrations=self.integrations,
                pipeline=self.pipeline,
                qa=self.qa,
            )
        knowledge = KnowledgeService(store=self.store, tenant_id=tenant_id)
        integrations = IntegrationsService(
            store=self.store,
            settings=self.settings,
            http_client=self.http_client,
            tenant_id=tenant_id,
        )
        pipeline = PipelineOrchestrator(
            store=self.store,
            settings=self.settings,
            http_client=self.http_client,
            tenant_id=tenant_id,
        )
        qa = QAService(
            store=self.store,
            settings=self.settings,
            knowledge=knowledge,
            integrations=integrations,
            http_client=self.http_client,
            tenant_id=tenant_id,
        )
        return TenantServices(
            knowledge=knowledge,
            integrations=integrations,
            pipeline=pipeline,
            qa=qa,
        )


@dataclass(frozen=True)
class TenantServices:
    knowledge: KnowledgeService
    integrations: IntegrationsService
    pipeline: PipelineOrchestrator
    qa: QAService


def get_app_state(request: Request) -> AppState:
    return request.app.state.koebinar


def get_tenant_services(request: Request) -> TenantServices:
    principal = getattr(request.state, "auth_principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return get_app_state(request).for_tenant(principal.tenant_id)


def require_auth(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_token: Optional[str] = Header(default=None),
) -> AuthPrincipal:
    # Do not accept Settings as a FastAPI param (it would be treated as a body model).
    settings = get_app_state(request).settings
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif x_api_token:
        token = x_api_token.strip()
    try:
        principal = authenticate_token(settings, token or "")
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    request.state.auth_principal = principal
    return principal
