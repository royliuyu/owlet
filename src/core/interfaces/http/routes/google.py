"""Connect a Google account and choose which calendars owlet reads.

The callback is a browser navigation from Google, so it cannot carry the
owlet bearer token. The one-time `state` is the credential. Refresh tokens
never appear in these responses.
"""

from __future__ import annotations

import html
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from core.connectors.google import GoogleConnector, SignInPage, valid_client_id
from core.domain.errors import (
    CalendarHeldError,
    GoogleAuthError,
    GoogleNotConfiguredError,
    GoogleReconnectError,
    SourceNotFoundError,
)
from core.interfaces.http.deps import get_google
from core.store.google_accounts import AccountRecord, CalendarRecord

router = APIRouter()


class ConnectBody(BaseModel):
    product: str = "calendar"
    account_id: str | None = None


class SignInOut(BaseModel):
    attempt_id: str
    url: str
    opened_on_server: bool
    opened_locally: bool


class AttemptOut(BaseModel):
    status: str
    email: str | None = None
    message: str = ""


class CalendarOut(BaseModel):
    calendar_id: str
    summary: str
    primary: bool
    enabled: bool
    held_by: str | None = None


class AccountOut(BaseModel):
    id: str
    email: str
    status: str
    scopes: list[str]
    last_sync_at: datetime | None
    calendars: list[CalendarOut]
    event_count: int = 0


class EventOut(BaseModel):
    id: str
    summary: str
    start: str
    end: str
    all_day: bool
    location: str = ""
    description: str = ""
    recurrence: str = ""
    calendar: str


class GoogleOverview(BaseModel):
    configured: bool
    client_id: str = ""
    account_email: str = ""
    redirect_uris: list[str] = Field(default_factory=list)
    accounts: list[AccountOut]


class GoogleClientBody(BaseModel):
    client_id: str = Field(min_length=1)
    client_secret: str = ""
    account_email: str | None = None


class CalendarPatch(BaseModel):
    calendar_id: str = Field(min_length=1)
    enabled: bool


@router.get("/google/accounts")
async def list_accounts(google: GoogleConnector = Depends(get_google)) -> GoogleOverview:
    return _overview(google)


@router.put("/google/client")
async def save_client(
    body: GoogleClientBody,
    google: GoogleConnector = Depends(get_google),
) -> GoogleOverview:
    client_id = body.client_id.strip()
    if not valid_client_id(client_id):
        raise HTTPException(
            status_code=400,
            detail=(
                "Paste the OAuth client ID from Google Cloud. "
                "It ends with .apps.googleusercontent.com."
            ),
        )
    email = None if body.account_email is None else body.account_email.strip()
    if email is not None and not _account_email(email):
        raise HTTPException(
            status_code=400,
            detail="Enter the Google account address that sign-in should open.",
        )
    google.save_client(client_id, body.client_secret, email)
    return _overview(google)


@router.post("/google/connect")
async def connect(
    body: ConnectBody,
    request: Request,
    google: GoogleConnector = Depends(get_google),
) -> SignInOut:
    try:
        started = await google.start(
            product=body.product,
            account_id=body.account_id,
            origin=_origin(request),
        )
    except GoogleNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That Google account is not connected") from exc
    except GoogleAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SignInOut(
        attempt_id=started.attempt_id,
        url=started.url,
        opened_on_server=started.opened_on_server,
        opened_locally=started.opened_locally,
    )


@router.get("/google/callback", response_class=HTMLResponse)
async def callback(
    request: Request,
    google: GoogleConnector = Depends(get_google),
) -> HTMLResponse:
    page = await google.finish(
        code=request.query_params.get("code"),
        error=request.query_params.get("error"),
        state=request.query_params.get("state"),
    )
    return HTMLResponse(_page(page))


@router.post("/google/attempts/{attempt_id}/cancel")
async def cancel_attempt(
    attempt_id: str,
    google: GoogleConnector = Depends(get_google),
) -> AttemptOut:
    found = google.cancel(attempt_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That sign-in attempt has expired")
    status = "pending" if found.status == "finishing" else found.status
    return AttemptOut(status=status, email=found.email, message=found.message)


@router.get("/google/attempts/{attempt_id}")
async def attempt(
    attempt_id: str,
    google: GoogleConnector = Depends(get_google),
) -> AttemptOut:
    found = google.read_attempt(attempt_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That sign-in attempt has expired")
    status = "pending" if found.status == "finishing" else found.status
    return AttemptOut(status=status, email=found.email, message=found.message)


@router.get("/google/events")
async def events(google: GoogleConnector = Depends(get_google)) -> list[EventOut]:
    return [
        EventOut(
            id=item.id,
            summary=item.summary,
            start=item.start,
            end=item.end,
            all_day=item.all_day,
            location=item.location,
            description=item.description,
            recurrence=item.recurrence,
            calendar=item.calendar,
        )
        for item in google.list_events()
    ]


@router.post("/google/accounts/{account_id}/sync")
async def sync_account(
    account_id: str,
    google: GoogleConnector = Depends(get_google),
) -> AccountOut:
    try:
        account = await google.sync_account(account_id)
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That Google account is not connected") from exc
    except GoogleReconnectError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GoogleAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _account(account)


@router.delete("/google/accounts/{account_id}", status_code=204)
async def disconnect(
    account_id: str,
    google: GoogleConnector = Depends(get_google),
) -> Response:
    await google.disconnect(account_id)
    return Response(status_code=204)


@router.patch("/google/accounts/{account_id}/calendars")
async def update_calendar(
    account_id: str,
    body: CalendarPatch,
    google: GoogleConnector = Depends(get_google),
) -> AccountOut:
    try:
        account = google.set_calendar(account_id, body.calendar_id, body.enabled)
    except CalendarHeldError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That calendar is not on this account") from exc
    return _account(account)


def _origin(request: Request) -> str:
    origin = request.headers.get("origin", "").strip()
    if origin:
        return origin.rstrip("/")
    return str(request.base_url).rstrip("/")


def _overview(google: GoogleConnector) -> GoogleOverview:
    client_id = google.client_id()
    if not valid_client_id(client_id):
        client_id = ""
    return GoogleOverview(
        configured=google.configured,
        client_id=client_id,
        account_email=google.account_email(),
        redirect_uris=google.redirect_uris(),
        accounts=[_account(item) for item in google.list_accounts()],
    )


def _account_email(value: str) -> bool:
    local, sep, domain = value.partition("@")
    return bool(sep and local and "." in domain and " " not in value)


def _account(account: AccountRecord) -> AccountOut:
    return AccountOut(
        id=account.id,
        email=account.email,
        status=account.status,
        scopes=list(account.scopes),
        last_sync_at=account.last_sync_at,
        calendars=[_calendar(item) for item in account.calendars],
        event_count=account.event_count,
    )


def _calendar(calendar: CalendarRecord) -> CalendarOut:
    return CalendarOut(
        calendar_id=calendar.calendar_id,
        summary=calendar.summary,
        primary=calendar.is_primary,
        enabled=calendar.enabled,
        held_by=calendar.held_by,
    )


def _page(page: SignInPage) -> str:
    title = html.escape(page.title)
    message = html.escape(page.message)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
      background: #f3efe6; color: #1c1916; font-family: Georgia, serif;
    }}
    main {{ max-width: 28rem; padding: 2rem; }}
    h1 {{ font-size: 1.75rem; font-weight: 500; margin: 0 0 0.75rem; }}
    p {{ margin: 0; line-height: 1.5; color: #6b645a; font-family: system-ui, sans-serif; }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <p>{message}</p>
  </main>
</body>
</html>
"""
