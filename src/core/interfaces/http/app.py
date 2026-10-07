"""FastAPI application: one origin for the API and, when built, the web app."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response

from core.config import REPO_ROOT, Settings, load_settings
from core.domain.errors import (
    DuplicateSourceError,
    InvalidSourceIdError,
    ParseError,
    SourceNotFoundError,
)
from core.interfaces.http.engine import Engine
from core.interfaces.http.routes import router

_WEB_DIST = REPO_ROOT / "web" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(app.state.engine.google.run_sync_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="owlet", lifespan=_lifespan)
    app.state.settings = settings or load_settings()
    app.state.engine = Engine(app.state.settings)

    @app.middleware("http")
    async def authenticate(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        current: Settings = request.app.state.settings
        if _allows(request, current):
            return await call_next(request)
        supplied = _presented_token(request)
        if supplied is None or not secrets.compare_digest(supplied, current.auth_token):
            return JSONResponse({"message": "Authentication required"}, status_code=401)
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    _register_errors(app)
    _mount_frontend(app, _WEB_DIST)
    return app


def _allows(request: Request, settings: Settings) -> bool:
    if not settings.auth_token:
        return True
    path = request.url.path
    if path in {"/api/v1/health", "/api/v1/session", "/api/v1/google/callback"}:
        return True
    return not path.startswith("/api/")


def _presented_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        return token or None
    cookie = request.cookies.get("owlet_token", "")
    return cookie or None


def _register_errors(app: FastAPI) -> None:
    @app.exception_handler(InvalidSourceIdError)
    async def invalid_source(_: Request, exc: InvalidSourceIdError) -> JSONResponse:
        return JSONResponse({"message": str(exc) or "Invalid document id"}, status_code=400)

    @app.exception_handler(SourceNotFoundError)
    async def missing_source(_: Request, exc: SourceNotFoundError) -> JSONResponse:
        return JSONResponse({"message": str(exc) or "Not found"}, status_code=404)

    @app.exception_handler(DuplicateSourceError)
    async def duplicate_source(_: Request, exc: DuplicateSourceError) -> JSONResponse:
        return JSONResponse({"message": str(exc) or "Already added"}, status_code=409)

    @app.exception_handler(ParseError)
    async def bad_parse(_: Request, exc: ParseError) -> JSONResponse:
        return JSONResponse({"message": str(exc) or "Could not parse document"}, status_code=422)


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    if not dist.is_dir():
        return

    @app.get("/{full_path:path}")
    async def frontend(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Unknown endpoint")
        candidate = (dist / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
