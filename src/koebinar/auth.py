"""Tenant configuration and stateless bearer-token authentication."""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass

from koebinar.config import Settings

_TENANT_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class AuthConfigurationError(ValueError):
    """Raised when operator authentication is missing or malformed."""


@dataclass(frozen=True)
class TenantConfig:
    id: str
    name: str
    access_token: str


@dataclass(frozen=True)
class AuthPrincipal:
    tenant_id: str
    tenant_name: str


def configured_tenants(settings: Settings) -> list[TenantConfig]:
    if settings.tenants_json.strip():
        try:
            raw = json.loads(settings.tenants_json)
        except json.JSONDecodeError as exc:
            raise AuthConfigurationError("KOEBINAR_TENANTS_JSON is invalid JSON") from exc
        if not isinstance(raw, list) or not raw:
            raise AuthConfigurationError("KOEBINAR_TENANTS_JSON must be a non-empty array")
        tenants: list[TenantConfig] = []
        for item in raw:
            if not isinstance(item, dict):
                raise AuthConfigurationError("each tenant must be an object")
            tenant_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            access_token = str(item.get("access_token") or "")
            if not _TENANT_ID.fullmatch(tenant_id):
                raise AuthConfigurationError(f"invalid tenant id: {tenant_id or '<empty>'}")
            if not name or not access_token:
                raise AuthConfigurationError(f"tenant {tenant_id} requires name and access_token")
            tenants.append(TenantConfig(tenant_id, name, access_token))
    elif settings.default_auth_token:
        tenants = [TenantConfig("default", settings.app_name, settings.default_auth_token)]
    else:
        raise AuthConfigurationError("operator authentication is not configured")

    ids = [tenant.id for tenant in tenants]
    tokens = [tenant.access_token for tenant in tenants]
    if len(set(ids)) != len(ids):
        raise AuthConfigurationError("tenant ids must be unique")
    if len(set(tokens)) != len(tokens):
        raise AuthConfigurationError("tenant access tokens must be unique")
    return tenants


def authenticate_login(settings: Settings, workspace_id: str, access_token: str) -> AuthPrincipal | None:
    for tenant in configured_tenants(settings):
        id_matches = hmac.compare_digest(workspace_id, tenant.id)
        token_matches = hmac.compare_digest(access_token, tenant.access_token)
        if id_matches and token_matches:
            return AuthPrincipal(tenant_id=tenant.id, tenant_name=tenant.name)
    return None


def authenticate_token(settings: Settings, access_token: str) -> AuthPrincipal | None:
    match: TenantConfig | None = None
    for tenant in configured_tenants(settings):
        if hmac.compare_digest(access_token, tenant.access_token):
            match = tenant
    if match is None:
        return None
    return AuthPrincipal(tenant_id=match.id, tenant_name=match.name)
