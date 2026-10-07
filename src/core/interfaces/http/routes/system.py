"""Health and session cookie used by the PDF viewer iframe."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from core.config import Settings
from core.interfaces.http.deps import get_settings

router = APIRouter()


class SessionBody(BaseModel):
    token: str = ""


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/session")
async def session(
    body: SessionBody,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    if settings.auth_token and not secrets.compare_digest(body.token, settings.auth_token):
        raise HTTPException(status_code=401, detail="Invalid token")
    if settings.auth_token:
        response.set_cookie(
            "owlet_token",
            settings.auth_token,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return {"ok": True}
