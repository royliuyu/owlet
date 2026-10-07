"""Google sign-in for Calendar, with Mail added later on an account.

The browser that is already on an allowed origin completes sign-in there.
A phone on Tailscale is not that origin, so Google is sent back to loopback
and this machine opens the window. A cloud host is just another allowed
origin: same route, different redirect, and no window opened on the server.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import secrets
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from core.config import Settings
from core.domain.errors import (
    GoogleAuthError,
    GoogleNotConfiguredError,
    GoogleReconnectError,
    SourceNotFoundError,
)
from core.store.google_accounts import AccountRecord, Attempt, EventRecord, GoogleAccountStore
from core.store.tokens import TokenStore

CALLBACK_PATH = "/api/v1/google/callback"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CALENDAR_LIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
EVENT_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"
_EVENT_PAST = timedelta(days=1)
_EVENT_AHEAD = timedelta(days=14)
SYNC_EVERY = timedelta(minutes=15)
SYNC_TICK_SECONDS = 60.0

_CLIENT_SECRET = "google-oauth-client"
_CLIENT_ID = re.compile(r"^\d+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$")
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_IDENTITY = ("openid", "email")

Opener = Callable[[str], bool]
_EventWrite = tuple[str, str, str, str, str, bool, str, str, str]


@dataclass(frozen=True, slots=True)
class _Occurrence:
    calendar_id: str
    event_id: str
    summary: str
    start: str
    end: str
    all_day: bool
    location: str
    description: str
    series_id: str


@dataclass(frozen=True, slots=True)
class SignInStart:
    attempt_id: str
    url: str
    opened_on_server: bool
    opened_locally: bool


@dataclass(frozen=True, slots=True)
class SignInPage:
    title: str
    message: str


@dataclass(frozen=True, slots=True)
class TokenGrant:
    access_token: str
    refresh_token: str | None
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    sub: str
    email: str


def allowed_origins(settings: Settings) -> list[str]:
    """Loopback plus any origin configured for a later cloud host."""
    port = settings.port
    origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    origins.extend(settings.google.origins)
    return origins


def choose_redirect(origin: str, settings: Settings) -> tuple[str, bool]:
    """Return (redirect_uri, open_on_this_machine).

    `open_on_this_machine` is true when the browser that asked cannot
    receive Google's redirect, which is the Tailscale phone case.
    """
    cleaned = origin.strip().rstrip("/")
    if cleaned in allowed_origins(settings):
        return f"{cleaned}{CALLBACK_PATH}", False
    loopback = f"http://127.0.0.1:{settings.port}"
    return f"{loopback}{CALLBACK_PATH}", True


def initially_enabled(calendar_id: str, *, primary: bool) -> bool:
    """Primary calendars start on. Holiday and birthday calendars stay off."""
    if _noisy(calendar_id):
        return False
    return primary


def authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    state: str,
    challenge: str,
    login_hint: str | None,
    existing_account: bool,
) -> str:
    """Build the Google consent URL.

    A new account may pick any Google login. Consent is always requested:
    after an earlier approval Google omits the refresh token unless asked.
    Adding mail, or reconnecting, hints the account on the card. Reconnect
    still refuses a different login. Add mail connects that other login.
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent" if existing_account else "select_account consent",
    }
    if login_hint:
        params["login_hint"] = login_hint
    if existing_account:
        params["include_granted_scopes"] = "true"
    return f"{AUTH_URL}?{urlencode(params)}"


def valid_client_id(client_id: str) -> bool:
    """A Google OAuth client id carries the Cloud project number before the hyphen."""
    return _CLIENT_ID.fullmatch(client_id.strip()) is not None


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def scopes_for(product: str) -> tuple[str, ...]:
    if product == "mail":
        return (*_IDENTITY, GMAIL_SCOPE)
    return (*_IDENTITY, CALENDAR_SCOPE)


class GoogleConnector:
    """OAuth plus the calendar checklist. Events refresh on a timer."""

    def __init__(
        self,
        settings: Settings,
        accounts: GoogleAccountStore,
        tokens: TokenStore,
        *,
        opener: Opener | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._accounts = accounts
        self.tokens = tokens
        self._opener = opener or _open_browser
        self.transport = transport
        self._locks: dict[str, asyncio.Lock] = {}
        self._retry_after: dict[str, datetime] = {}

    def client_id(self) -> str:
        """The client saved in Settings, or the one given in configuration."""
        saved = self._accounts.saved_client_id()
        if saved:
            return saved
        return self._settings.google.client_id.strip()

    def client_secret(self) -> str:
        saved = (self.tokens.get(_CLIENT_SECRET) or "").strip()
        if saved:
            return saved
        return self._settings.google.client_secret.strip()

    def redirect_uris(self) -> list[str]:
        return [f"{origin}{CALLBACK_PATH}" for origin in allowed_origins(self._settings)]

    def account_email(self) -> str:
        return self._accounts.saved_account_email()

    def save_client(
        self,
        client_id: str,
        client_secret: str,
        account_email: str | None = None,
    ) -> None:
        self._accounts.save_client_id(client_id.strip(), account_email)
        if client_secret.strip():
            self.tokens.put(_CLIENT_SECRET, client_secret.strip())

    @property
    def configured(self) -> bool:
        return valid_client_id(self.client_id())

    def list_accounts(self) -> list[AccountRecord]:
        return self._accounts.list_accounts()

    def list_events(self) -> list[EventRecord]:
        return self._accounts.list_events()

    def read_attempt(self, attempt_id: str) -> Attempt | None:
        return self._accounts.read_attempt(attempt_id)

    async def start(
        self,
        *,
        product: str,
        account_id: str | None,
        origin: str,
    ) -> SignInStart:
        if product not in {"calendar", "mail"}:
            raise GoogleAuthError("Choose calendar or mail")
        if not valid_client_id(self.client_id()):
            raise GoogleNotConfiguredError(
                "Paste the OAuth client ID from Google Cloud. "
                "It ends with .apps.googleusercontent.com."
            )
        login_hint = self.account_email() or None
        if account_id is not None:
            account = self._accounts.get(account_id)
            if account is None:
                raise SourceNotFoundError(account_id)
            login_hint = account.email
        redirect_uri, on_server = choose_redirect(origin, self._settings)
        verifier, challenge = pkce()
        attempt_id = secrets.token_urlsafe(32)
        self._accounts.create_attempt(
            attempt_id,
            verifier=verifier,
            redirect_uri=redirect_uri,
            product=product,
            account_id=account_id,
        )
        url = authorization_url(
            client_id=self.client_id(),
            redirect_uri=redirect_uri,
            scopes=scopes_for(product),
            state=attempt_id,
            challenge=challenge,
            login_hint=login_hint,
            existing_account=account_id is not None,
        )
        opened_locally = self._opener(url) if on_server else False
        return SignInStart(
            attempt_id=attempt_id,
            url=url,
            opened_on_server=on_server,
            opened_locally=opened_locally,
        )

    async def finish(
        self,
        *,
        code: str | None,
        error: str | None,
        state: str | None,
    ) -> SignInPage:
        if not state:
            return SignInPage(
                "Sign-in failed",
                "This sign-in link is missing its check. Start again from Settings.",
            )
        attempt = self._accounts.claim_attempt(state)
        if attempt is None:
            return _page_for_existing(self._accounts.read_attempt(state))
        if error:
            status = "cancelled" if error == "access_denied" else "error"
            message = (
                "Sign-in was cancelled."
                if status == "cancelled"
                else "Google did not complete sign-in."
            )
            self._accounts.complete_attempt(attempt.id, status=status, message=message)
            title = "Sign-in cancelled" if status == "cancelled" else "Sign-in failed"
            return SignInPage(title, f"{message} You can close this tab.")
        if not code:
            self._accounts.complete_attempt(
                attempt.id, status="error", message="Google returned no sign-in code."
            )
            return SignInPage("Sign-in failed", "Google returned no sign-in code.")
        try:
            grant = await self._exchange(attempt, code)
            identity = await self._userinfo(grant.access_token)
            await self._accept(attempt, grant, identity)
        except GoogleAuthError as exc:
            self._accounts.complete_attempt(attempt.id, status="error", message=str(exc))
            return SignInPage("Sign-in failed", str(exc))
        except Exception:
            self._accounts.complete_attempt(
                attempt.id,
                status="error",
                message="Could not finish sign-in.",
            )
            return SignInPage(
                "Sign-in failed",
                "Could not finish sign-in. Start again from Settings.",
            )
        saved = self._accounts.read_attempt(attempt.id)
        if saved is None:
            return SignInPage("Sign-in failed", "Could not finish sign-in.")
        if saved.status == "mismatch":
            return SignInPage("Different account", saved.message)
        if saved.status == "connected" and saved.message:
            return _connected_page(saved.message)
        email = saved.email or identity.email
        return SignInPage("Connected", f"Connected {email}. You can close this tab.")

    def cancel(self, attempt_id: str) -> Attempt | None:
        """Drop a sign-in that has not finished. A later grant is ignored."""
        return self._accounts.cancel_attempt(attempt_id)

    async def sync_account(self, account_id: str) -> AccountRecord:
        async with self._lock_for(account_id):
            return await self._sync_account(account_id)

    async def sync_due(self, *, now: datetime | None = None) -> list[str]:
        """Refresh calendar accounts whose last sync is older than 15 minutes.

        A sign-in that needs reconnect is left alone. An account already
        syncing is left for that run. A refused call waits another interval.
        """
        moment = now or datetime.now(tz=timezone.utc)
        done: list[str] = []
        for account in self.list_accounts():
            if not self._due(account, moment):
                continue
            lock = self._lock_for(account.id)
            if lock.locked():
                continue
            async with lock:
                current = self._accounts.get(account.id)
                if current is None or not self._due(current, moment):
                    continue
                try:
                    await self._sync_account(current.id)
                except GoogleReconnectError:
                    self._retry_after.pop(current.id, None)
                    continue
                except GoogleAuthError:
                    self._retry_after[current.id] = moment
                    continue
                done.append(current.id)
        return done

    async def run_sync_loop(self) -> None:
        """Check once a minute, including at startup, so a wake catches up."""
        while True:
            try:
                await self.sync_due()
            except Exception:
                pass
            await asyncio.sleep(SYNC_TICK_SECONDS)

    async def _sync_account(self, account_id: str) -> AccountRecord:
        account = self._require(account_id)
        if CALENDAR_SCOPE not in account.scopes:
            raise GoogleAuthError(
                "Calendar access was not granted. Allow calendar on this account, then sync."
            )
        access = await self._access_token(account)
        try:
            await self._load_calendars(account.id, access)
            fresh = self._require(account.id)
            await self._load_events(fresh, access)
        except GoogleReconnectError:
            self._accounts.mark_reconnect(account.id)
            raise
        self._retry_after.pop(account.id, None)
        self._accounts.mark_synced(account.id)
        return self._require(account.id)

    def _due(self, account: AccountRecord, now: datetime) -> bool:
        if account.status == "reconnect" or CALENDAR_SCOPE not in account.scopes:
            return False
        retry = self._retry_after.get(account.id)
        if retry is not None and now - _aware(retry) < SYNC_EVERY:
            return False
        if account.last_sync_at is None:
            return True
        return now - _aware(account.last_sync_at) >= SYNC_EVERY

    def _lock_for(self, account_id: str) -> asyncio.Lock:
        lock = self._locks.get(account_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[account_id] = lock
        return lock

    async def disconnect(self, account_id: str) -> bool:
        refresh = self.tokens.get(account_id)
        if refresh:
            try:
                await self._revoke(refresh)
            except GoogleAuthError:
                pass
        self.tokens.delete(account_id)
        return self._accounts.remove(account_id)

    def set_calendar(self, account_id: str, calendar_id: str, enabled: bool) -> AccountRecord:
        self._require(account_id)
        self._accounts.set_calendar_enabled(account_id, calendar_id, enabled)
        return self._require(account_id)

    async def _accept(self, attempt: Attempt, grant: TokenGrant, identity: GoogleIdentity) -> None:
        # Reconnect and "allow calendar" must stay on the card that started them.
        # Add mail may be a different Gmail: connect that account and leave the card.
        if (
            attempt.product != "mail"
            and attempt.account_id is not None
            and attempt.account_id != identity.sub
        ):
            self._accounts.complete_attempt(
                attempt.id,
                status="mismatch",
                email=identity.email,
                message="That was a different Google account. Nothing was changed.",
            )
            return
        existing = self._accounts.get(identity.sub)
        refresh = grant.refresh_token
        if refresh is None and existing is not None:
            refresh = self.tokens.get(existing.id)
        if not refresh:
            raise GoogleAuthError("Google did not return a refresh token. Try again.")
        scopes = grant.scopes or scopes_for(attempt.product)
        if existing is not None:
            scopes = tuple(dict.fromkeys((*existing.scopes, *scopes)))
        self.tokens.put(identity.sub, refresh)
        self._accounts.upsert_account(identity.sub, identity.email, scopes)
        message = ""
        if attempt.product == "calendar" and CALENDAR_SCOPE not in scopes:
            message = (
                "Signed in, but Google did not grant calendar access. "
                "Add the Calendar read-only scope under Data Access, then allow calendar again."
            )
        elif attempt.account_id is None and existing is not None:
            message = f"{identity.email} is already connected."
        if CALENDAR_SCOPE in scopes:
            try:
                await self._load_calendars(identity.sub, grant.access_token)
                fresh = self._require(identity.sub)
                await self._load_events(fresh, grant.access_token)
            except GoogleAuthError as exc:
                message = str(exc)
        self._accounts.mark_synced(identity.sub)
        self._accounts.complete_attempt(
            attempt.id,
            status="connected",
            email=identity.email,
            message=message,
        )

    async def _load_events(self, account: AccountRecord, access_token: str) -> None:
        start = datetime.now(tz=timezone.utc) - _EVENT_PAST
        end = datetime.now(tz=timezone.utc) + _EVENT_AHEAD
        found: list[_Occurrence] = []
        for calendar in account.calendars:
            if not calendar.enabled or calendar.held_by:
                continue
            found.extend(await self._event_page(access_token, calendar.calendar_id, start, end))
        labels = await self._series_labels(access_token, found)
        rows: list[_EventWrite] = [
            (
                item.calendar_id,
                item.event_id,
                item.summary,
                item.start,
                item.end,
                item.all_day,
                item.location,
                item.description,
                labels.get((item.calendar_id, item.series_id), ""),
            )
            for item in found
        ]
        self._accounts.replace_events(account.id, rows)

    async def _series_labels(
        self,
        access_token: str,
        events: list[_Occurrence],
    ) -> dict[tuple[str, str], str]:
        """One lookup per repeating series. An instance does not carry the rule."""
        labels: dict[tuple[str, str], str] = {}
        for item in events:
            if not item.series_id:
                continue
            key = (item.calendar_id, item.series_id)
            if key in labels:
                continue
            url = EVENT_URL.format(
                calendar_id=quote(item.calendar_id, safe=""),
                event_id=quote(item.series_id, safe=""),
            )
            try:
                payload = await self._get(url, access_token)
            except GoogleAuthError:
                labels[key] = ""
                continue
            rules = payload.get("recurrence")
            labels[key] = _repeat_label(rules if isinstance(rules, list) else [])
        return labels

    async def _event_page(
        self,
        access_token: str,
        calendar_id: str,
        start: datetime,
        end: datetime,
    ) -> list[_Occurrence]:
        url = EVENTS_URL.format(calendar_id=quote(calendar_id, safe=""))
        found: list[_Occurrence] = []
        page_token = ""
        window = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": _stamp(start),
            "timeMax": _stamp(end),
            "maxResults": "250",
        }
        for _ in range(10):
            params = dict(window)
            if page_token:
                params["pageToken"] = page_token
            payload = await self._get(url, access_token, params=params)
            items = payload.get("items")
            if isinstance(items, list):
                for item in items:
                    row = _event_row(calendar_id, item)
                    if row is not None:
                        found.append(row)
            token = payload.get("nextPageToken")
            if not isinstance(token, str) or not token:
                break
            page_token = token
        return found

    async def _load_calendars(self, account_id: str, access_token: str) -> None:
        items = await self._calendar_list(access_token)
        self._accounts.replace_calendars(
            account_id,
            [
                (
                    item_id,
                    summary,
                    primary,
                    initially_enabled(item_id, primary=primary),
                )
                for item_id, summary, primary in items
            ],
        )

    async def _access_token(self, account: AccountRecord) -> str:
        refresh = self.tokens.get(account.id)
        if not refresh:
            self._accounts.mark_reconnect(account.id)
            raise GoogleReconnectError("Reconnect this Google account")
        try:
            grant = await self._refresh(refresh)
        except GoogleReconnectError:
            self._accounts.mark_reconnect(account.id)
            raise
        if grant.refresh_token:
            self.tokens.put(account.id, grant.refresh_token)
        return grant.access_token

    async def _exchange(self, attempt: Attempt, code: str) -> TokenGrant:
        data = {
            "code": code,
            "client_id": self.client_id(),
            "redirect_uri": attempt.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": attempt.verifier,
        }
        secret = self.client_secret()
        if secret:
            data["client_secret"] = secret
        return await self._token(data)

    async def _refresh(self, refresh_token: str) -> TokenGrant:
        data = {
            "client_id": self.client_id(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        secret = self.client_secret()
        if secret:
            data["client_secret"] = secret
        return await self._token(data)

    async def _token(self, data: dict[str, str]) -> TokenGrant:
        payload = await self._form(TOKEN_URL, data)
        access = payload.get("access_token")
        if not isinstance(access, str) or not access:
            raise GoogleAuthError("Google did not return an access token.")
        refresh = payload.get("refresh_token")
        scope = payload.get("scope")
        return TokenGrant(
            access_token=access,
            refresh_token=refresh if isinstance(refresh, str) and refresh else None,
            scopes=tuple(str(scope).split()) if isinstance(scope, str) else (),
        )

    async def _userinfo(self, access_token: str) -> GoogleIdentity:
        payload = await self._get(USERINFO_URL, access_token)
        sub = payload.get("sub")
        email = payload.get("email")
        if not isinstance(sub, str) or not sub:
            raise GoogleAuthError("Google did not share an account id.")
        if not isinstance(email, str) or not email:
            raise GoogleAuthError("Google did not share the account address.")
        return GoogleIdentity(sub=sub, email=email)

    async def _calendar_list(self, access_token: str) -> list[tuple[str, str, bool]]:
        found: list[tuple[str, str, bool]] = []
        page_token = ""
        for _ in range(10):
            params = {"pageToken": page_token} if page_token else None
            payload = await self._get(CALENDAR_LIST_URL, access_token, params=params)
            items = payload.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    calendar_id = item.get("id")
                    if not isinstance(calendar_id, str) or not calendar_id:
                        continue
                    summary = item.get("summary")
                    label = summary if isinstance(summary, str) and summary else calendar_id
                    found.append((calendar_id, label, bool(item.get("primary"))))
            token = payload.get("nextPageToken")
            if not isinstance(token, str) or not token:
                break
            page_token = token
        return found

    async def _revoke(self, refresh_token: str) -> None:
        await self._form(REVOKE_URL, {"token": refresh_token})

    async def _form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.post(url, data=data)
        except httpx.HTTPError as exc:
            raise GoogleAuthError("Could not reach Google.") from exc
        return _payload(response)

    async def _get(
        self,
        url: str,
        access_token: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            raise GoogleAuthError("Could not reach Google.") from exc
        return _payload(response)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, timeout=20.0)

    def _require(self, account_id: str) -> AccountRecord:
        account = self._accounts.get(account_id)
        if account is None:
            raise SourceNotFoundError(account_id)
        return account


def _page_for_existing(attempt: Attempt | None) -> SignInPage:
    if attempt is None:
        return SignInPage(
            "Sign-in failed",
            "This sign-in link is not valid. Start again from Settings.",
        )
    if attempt.status == "expired":
        return SignInPage("Sign-in expired", attempt.message or "Start again from Settings.")
    if attempt.status == "cancelled":
        return SignInPage("Sign-in cancelled", "Sign-in was cancelled. You can close this tab.")
    if attempt.status == "mismatch":
        return SignInPage("Different account", attempt.message)
    if attempt.status == "connected":
        if attempt.message:
            return _connected_page(attempt.message)
        email = attempt.email or "the account"
        return SignInPage("Connected", f"Connected {email}. You can close this tab.")
    if attempt.status == "finishing":
        return SignInPage("Sign-in in progress", "This sign-in is already being finished.")
    return SignInPage("Sign-in failed", attempt.message or "Start again from Settings.")


def _payload(response: httpx.Response) -> dict[str, Any]:
    body: dict[str, Any] = {}
    try:
        loaded = response.json()
    except ValueError:
        loaded = None
    if isinstance(loaded, dict):
        body = loaded
    if response.is_success:
        return body
    error = body.get("error")
    if error == "invalid_grant" or (
        isinstance(error, dict) and error.get("status") == "UNAUTHENTICATED"
    ):
        raise GoogleReconnectError("Reconnect this Google account")
    raise GoogleAuthError(_refusal(body))


def _connected_page(message: str) -> SignInPage:
    if "already connected" in message.lower():
        return SignInPage("Already connected", message)
    return SignInPage("Connected", message)


def _refusal(body: dict[str, Any]) -> str:
    error = body.get("error")
    detail = ""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            detail = message
    lowered = detail.lower()
    if "has not been used in project" in lowered or (
        "calendar" in lowered and "disabled" in lowered
    ):
        return (
            "The Google Calendar API is turned off for this Cloud project. "
            "Enable it, wait a minute, then click Sync now."
        )
    return "Google refused the request."


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event_row(calendar_id: str, item: object) -> _Occurrence | None:
    if not isinstance(item, dict) or item.get("status") == "cancelled":
        return None
    event_id = item.get("id")
    if not isinstance(event_id, str) or not event_id:
        return None
    summary = item.get("summary")
    title = summary if isinstance(summary, str) and summary else "(No title)"
    location = item.get("location")
    place = location if isinstance(location, str) else ""
    series = item.get("recurringEventId")
    series_id = series if isinstance(series, str) else ""
    detail = _plain(item.get("description"))
    link = item.get("hangoutLink")
    if isinstance(link, str) and link and link not in detail:
        detail = f"{detail}\n{link}".strip()
    start = item.get("start")
    end = item.get("end")
    if not isinstance(start, dict):
        return None
    if isinstance(start.get("date"), str):
        start_at = start["date"]
        end_at = start_at
        if isinstance(end, dict) and isinstance(end.get("date"), str):
            end_at = end["date"]
        return _Occurrence(
            calendar_id, event_id, title, start_at, end_at, True, place, detail, series_id
        )
    if isinstance(start.get("dateTime"), str):
        start_at = start["dateTime"]
        end_at = (
            end.get("dateTime")
            if isinstance(end, dict) and isinstance(end.get("dateTime"), str)
            else start_at
        )
        return _Occurrence(
            calendar_id, event_id, title, start_at, end_at, False, place, detail, series_id
        )
    return None


_WEEKDAYS = {
    "MO": "Monday",
    "TU": "Tuesday",
    "WE": "Wednesday",
    "TH": "Thursday",
    "FR": "Friday",
    "SA": "Saturday",
    "SU": "Sunday",
}


def _repeat_label(rules: list[object]) -> str:
    rule = ""
    for item in rules:
        if isinstance(item, str) and item.startswith("RRULE:"):
            rule = item[6:]
            break
    if not rule:
        return ""
    parts: dict[str, str] = {}
    for piece in rule.split(";"):
        key, sep, value = piece.partition("=")
        if sep:
            parts[key] = value
    days = [
        _WEEKDAYS.get(day[-2:], day)
        for day in parts.get("BYDAY", "").split(",")
        if day
    ]
    freq = parts.get("FREQ", "")
    if freq == "DAILY":
        return "Daily"
    if freq == "WEEKLY" and len(days) == 1:
        return f"Weekly on {days[0]}"
    if freq == "WEEKLY" and days:
        return "Weekly on " + ", ".join(days)
    if freq == "WEEKLY":
        return "Weekly"
    if freq == "MONTHLY" and len(days) == 1:
        return f"Monthly on {days[0]}"
    if freq == "MONTHLY":
        return "Monthly"
    if freq == "YEARLY":
        return "Yearly"
    return ""


def _plain(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    lines = [line.rstrip() for line in text.split("\n")]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if line:
            collapsed.append(line)
            blank = False
        elif not blank:
            collapsed.append("")
            blank = True
    return "\n".join(collapsed).strip()[:8000]


def _noisy(calendar_id: str) -> bool:
    lowered = calendar_id.lower()
    return "holiday@group.v.calendar.google.com" in lowered or lowered.startswith(
        "addressbook#contacts@"
    )


def _open_browser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url, new=1))
    except Exception:
        return False
