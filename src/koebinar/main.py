"""Koebinar API application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI

from koebinar.api.deps import AppState
from koebinar.api.routes import build_router
from koebinar.config import Settings, get_settings, reset_settings_cache
from koebinar.storage import Store, get_store, set_store


def create_app(
    *,
    settings: Optional[Settings] = None,
    store: Optional[Store] = None,
    http_client: Optional[httpx.Client] = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    store = store or get_store()
    set_store(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        client = getattr(app.state, "http_client", None)
        if client is not None:
            client.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    state = AppState(settings=settings, store=store, http_client=http_client)
    app.state.koebinar = state
    app.state.http_client = http_client
    app.include_router(build_router(), prefix=settings.api_prefix)

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "docs": "/docs", "api": settings.api_prefix}

    return app


def cli() -> None:
    import uvicorn

    uvicorn.run("koebinar.main:create_app", factory=True, host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    cli()
