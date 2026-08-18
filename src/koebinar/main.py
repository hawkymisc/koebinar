"""Koebinar API application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from koebinar.api.deps import AppState
from koebinar.api.routes import VOICE_CLONE_MAX_REQUEST_BYTES, build_router
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
    if store is None:
        from koebinar.storage import open_store

        # Prefer durable store when db_path is set (B-stack)
        store = open_store(settings) if settings.db_path else get_store()
    set_store(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        client = getattr(app.state, "http_client", None)
        if client is not None:
            client.close()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    # Authentication uses an explicit Bearer token (no cookies), so a permissive
    # CORS policy lets the separately hosted web UI call the API without exposing
    # ambient browser credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def reject_oversized_voice_clone_request(request: Request, call_next):
        """Reject declared oversized multipart bodies before Starlette parses/spools them."""
        clone_path = f"{settings.api_prefix.rstrip('/')}/integrations/elevenlabs/voices/clone"
        if request.method == "POST" and request.url.path.rstrip("/") == clone_path:
            content_length = request.headers.get("content-length")
            try:
                declared_bytes = int(content_length) if content_length is not None else 0
            except ValueError:
                declared_bytes = 0
            if declared_bytes <= 0:
                return JSONResponse(
                    status_code=411,
                    content={"detail": "valid Content-Length is required for voice clone uploads"},
                )
            if declared_bytes > VOICE_CLONE_MAX_REQUEST_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "voice clone request must be 26 MiB or smaller"},
                )
        return await call_next(request)
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
