"""Google sign-in, calendar checklist, and the callback that carries no owlet token."""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from core.config import GoogleSettings, Settings
from core.interfaces.http.app import create_app
from core.store.tokens import MemoryTokenStore

CLIENT_ID = "123456789012-abc.apps.googleusercontent.com"
CALENDAR = "https://www.googleapis.com/auth/calendar.readonly"
GMAIL = "https://www.googleapis.com/auth/gmail.readonly"
_ORIGIN = {"origin": "http://127.0.0.1:8000"}


class _Google:
    def __init__(self) -> None:
        self.sub = "sub-1"
        self.email = "you@gmail.com"
        self.scopes = f"openid email {CALENDAR}"
        self.refresh = "refresh-1"
        self.invalid_grant = False
        self.calendar_error: dict[str, object] | None = None
        self.events: list[dict[str, object]] = []
        self.event_paths: list[str] = []
        self.masters: dict[str, dict[str, object]] = {}
        self.revoked: list[str] = []
        self.token_bodies: list[str] = []
        self.calendars: list[dict[str, object]] = [
            {"id": "you@gmail.com", "summary": "Work", "primary": True},
            {
                "id": "en.usa#holiday@group.v.calendar.google.com",
                "summary": "Holidays in the United States",
            },
            {
                "id": "addressbook#contacts@group.v.calendar.google.com",
                "summary": "Birthdays",
            },
            {"id": "team@group.calendar.google.com", "summary": "Team"},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/token":
            self.token_bodies.append(request.content.decode())
            if self.invalid_grant:
                return httpx.Response(400, json={"error": "invalid_grant"})
            body: dict[str, str] = {"access_token": "access", "scope": self.scopes}
            if self.refresh:
                body["refresh_token"] = self.refresh
            return httpx.Response(200, json=body)
        if path == "/oauth2/v3/userinfo":
            return httpx.Response(200, json={"sub": self.sub, "email": self.email})
        if path == "/calendar/v3/users/me/calendarList":
            if self.calendar_error is not None:
                return httpx.Response(403, json=self.calendar_error)
            return httpx.Response(200, json={"items": self.calendars})
        if path.endswith("/events"):
            self.event_paths.append(path)
            return httpx.Response(200, json={"items": self.events})
        if "/events/" in path:
            series_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self.masters.get(series_id, {}))
        if path == "/revoke":
            self.revoked.append(request.content.decode())
            return httpx.Response(200, content=b"")
        return httpx.Response(404, json={"error": "missing"})


def _client(
    tmp_path: Path,
    google: _Google,
    *,
    token: str = "",
    client_id: str = CLIENT_ID,
    origins: str = "",
) -> TestClient:
    app = create_app(
        Settings(
            auth_token=token,
            data_dir=tmp_path / "state",
            port=8000,
            google=GoogleSettings(
                client_id=client_id,
                client_secret="secret",
                redirect_origins=origins,
            ),
        )
    )
    app.state.engine.google.tokens = MemoryTokenStore()
    app.state.engine.google.transport = httpx.MockTransport(google.handler)
    app.state.engine.google._opener = lambda _url: False
    return TestClient(app)


def _finish(
    client: TestClient,
    google: _Google,
    body: dict[str, object],
    *,
    origin: dict[str, str] = _ORIGIN,
):
    started = client.post("/api/v1/google/connect", json=body, headers=origin)
    assert started.status_code == 200, started.text
    state = started.json()["attempt_id"]
    page = client.get("/api/v1/google/callback", params={"code": "abc", "state": state})
    assert page.status_code == 200
    assert google.refresh not in page.text
    return started.json(), page.text


def test_connect_checks_primary_and_leaves_holiday_calendars_off(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    started, page = _finish(client, google, {"product": "calendar"})

    assert started["opened_on_server"] is False
    assert "prompt=select_account+consent" in started["url"]
    assert "code_verifier=" in google.token_bodies[0]
    assert "client_secret=secret" in google.token_bodies[0]
    assert "Connected you@gmail.com" in page

    overview = client.get("/api/v1/google/accounts").json()
    assert overview["configured"] is True
    account = overview["accounts"][0]
    assert account["email"] == "you@gmail.com"
    enabled = {item["summary"]: item["enabled"] for item in account["calendars"]}
    assert enabled == {
        "Work": True,
        "Holidays in the United States": False,
        "Birthdays": False,
        "Team": False,
    }
    assert client.app.state.engine.google.tokens.get("sub-1") == "refresh-1"


def test_callback_does_not_require_the_owlet_token(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google, token="secret")
    denied = client.post("/api/v1/google/connect", json={"product": "calendar"})
    assert denied.status_code == 401

    started = client.post(
        "/api/v1/google/connect",
        json={"product": "calendar"},
        headers={**_ORIGIN, "authorization": "Bearer secret"},
    )
    assert started.status_code == 200
    page = client.get(
        "/api/v1/google/callback",
        params={"code": "abc", "state": started.json()["attempt_id"]},
    )
    assert page.status_code == 200
    assert "Connected you@gmail.com" in page.text


def test_phone_origin_asks_this_machine_to_open_the_window(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    started = client.post(
        "/api/v1/google/connect",
        json={"product": "calendar"},
        headers={"origin": "http://100.64.0.2:8000"},
    )
    assert started.status_code == 200
    body = started.json()
    assert body["opened_on_server"] is True
    assert body["opened_locally"] is False
    assert "127.0.0.1%3A8000" in body["url"] or "127.0.0.1:8000" in body["url"]


def test_cloud_origin_stays_on_that_host(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google, origins="https://owlet.example.com")
    started = client.post(
        "/api/v1/google/connect",
        json={"product": "calendar"},
        headers={"origin": "https://owlet.example.com"},
    )
    assert started.status_code == 200
    body = started.json()
    assert body["opened_on_server"] is False
    assert "owlet.example.com" in body["url"]


def test_client_saved_in_settings_is_used_without_restart(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google, client_id="", origins="")
    saved = client.put(
        "/api/v1/google/client",
        json={"client_id": CLIENT_ID, "client_secret": "sek"},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["configured"] is True
    assert body["client_id"] == CLIENT_ID
    assert "sek" not in saved.text
    assert any(uri.endswith("/api/v1/google/callback") for uri in body["redirect_uris"])

    _finish(client, google, {"product": "calendar"})
    assert f"client_id={CLIENT_ID}" in google.token_bodies[0]
    assert "client_secret=sek" in google.token_bodies[0]


def test_sign_in_names_the_google_account(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google, client_id="")
    saved = client.put(
        "/api/v1/google/client",
        json={
            "client_id": CLIENT_ID,
            "client_secret": "sek",
            "account_email": "you@gmail.com",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["account_email"] == "you@gmail.com"
    started = client.post(
        "/api/v1/google/connect",
        json={"product": "calendar"},
        headers=_ORIGIN,
    )
    assert started.status_code == 200
    assert "login_hint=you%40gmail.com" in started.json()["url"]


def test_a_project_name_is_not_a_client_id(tmp_path: Path) -> None:
    client = _client(tmp_path, _Google(), client_id="")
    saved = client.put(
        "/api/v1/google/client",
        json={"client_id": "owlet.example", "client_secret": "sek"},
    )
    assert saved.status_code == 400
    assert "apps.googleusercontent.com" in saved.json()["detail"]
    assert client.get("/api/v1/google/accounts").json()["configured"] is False


def test_missing_client_id_is_a_clear_error(tmp_path: Path) -> None:
    client = _client(tmp_path, _Google(), client_id="")
    started = client.post("/api/v1/google/connect", json={"product": "calendar"}, headers=_ORIGIN)
    assert started.status_code == 400
    assert "apps.googleusercontent.com" in started.json()["detail"]
    assert client.get("/api/v1/google/accounts").json()["configured"] is False


def test_cancelling_google_stores_nothing(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    started = client.post("/api/v1/google/connect", json={"product": "calendar"}, headers=_ORIGIN)
    state = started.json()["attempt_id"]
    page = client.get("/api/v1/google/callback", params={"error": "access_denied", "state": state})
    assert "cancelled" in page.text.lower()
    assert client.get("/api/v1/google/accounts").json()["accounts"] == []
    poll = client.get(f"/api/v1/google/attempts/{state}")
    assert poll.json()["status"] == "cancelled"


def _age_sync(client: TestClient, account_id: str, *, minutes: int) -> None:
    old = (datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)).isoformat()
    path = client.app.state.settings.db_path
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE google_accounts SET last_sync_at = ? WHERE id = ?",
            (old, account_id),
        )


def test_expired_attempt_asks_to_start_again(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    started = client.post("/api/v1/google/connect", json={"product": "calendar"}, headers=_ORIGIN)
    state = started.json()["attempt_id"]
    old = (datetime.now(tz=timezone.utc) - timedelta(minutes=11)).isoformat()
    path = client.app.state.settings.db_path
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE oauth_attempts SET created_at = ? WHERE id = ?", (old, state))

    page = client.get("/api/v1/google/callback", params={"code": "abc", "state": state})
    assert "too long" in page.text
    assert google.token_bodies == []


def test_same_account_twice_does_not_duplicate(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    _, page = _finish(client, google, {"product": "calendar"})
    assert "already connected" in page
    accounts = client.get("/api/v1/google/accounts").json()["accounts"]
    assert len(accounts) == 1


def test_mail_on_the_same_account_keeps_calendar(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]

    google.scopes = f"openid email {CALENDAR} {GMAIL}"
    google.refresh = "refresh-mail"
    started, page = _finish(client, google, {"product": "mail", "account_id": account_id})
    assert "prompt=consent" in started["url"]
    assert "include_granted_scopes=true" in started["url"]
    assert "login_hint=" in started["url"]
    assert "Connected you@gmail.com" in page

    account = client.get("/api/v1/google/accounts").json()["accounts"][0]
    assert CALENDAR in account["scopes"]
    assert GMAIL in account["scopes"]
    assert client.app.state.engine.google.tokens.get(account_id) == "refresh-mail"


def test_mail_signed_in_as_someone_else_connects_that_account(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    google.sub = "sub-other"
    google.email = "other@gmail.com"
    google.scopes = f"openid email {GMAIL}"
    google.refresh = "refresh-other"
    _, page = _finish(client, google, {"product": "mail", "account_id": account_id})
    assert "Connected other@gmail.com" in page
    assert "different Google account" not in page
    accounts = client.get("/api/v1/google/accounts").json()["accounts"]
    assert [item["email"] for item in accounts] == ["you@gmail.com", "other@gmail.com"]
    assert GMAIL not in accounts[0]["scopes"]
    assert GMAIL in accounts[1]["scopes"]
    assert CALENDAR not in accounts[1]["scopes"]
    assert client.app.state.engine.google.tokens.get(account_id) == "refresh-1"
    assert client.app.state.engine.google.tokens.get("sub-other") == "refresh-other"


def test_reconnect_signed_in_as_someone_else_changes_nothing(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    google.sub = "sub-other"
    google.email = "other@gmail.com"
    google.refresh = "refresh-other"
    _, page = _finish(client, google, {"product": "calendar", "account_id": account_id})
    assert "different Google account" in page
    accounts = client.get("/api/v1/google/accounts").json()["accounts"]
    assert len(accounts) == 1
    assert accounts[0]["email"] == "you@gmail.com"
    assert client.app.state.engine.google.tokens.get(account_id) == "refresh-1"
    assert client.app.state.engine.google.tokens.get("sub-other") is None


def test_stop_adding_discards_a_later_grant(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    started = client.post("/api/v1/google/connect", json={"product": "mail"}, headers=_ORIGIN)
    assert started.status_code == 200
    state = started.json()["attempt_id"]
    stopped = client.post(f"/api/v1/google/attempts/{state}/cancel")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "cancelled"
    page = client.get("/api/v1/google/callback", params={"code": "abc", "state": state})
    assert "cancelled" in page.text.lower()
    assert client.get("/api/v1/google/accounts").json()["accounts"] == []
    assert google.token_bodies == []


def test_shared_calendar_stays_with_the_first_account(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    first = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    enabled = client.patch(
        f"/api/v1/google/accounts/{first}/calendars",
        json={"calendar_id": "team@group.calendar.google.com", "enabled": True},
    )
    assert enabled.status_code == 200

    google.sub = "sub-2"
    google.email = "other@gmail.com"
    google.refresh = "refresh-2"
    _finish(client, google, {"product": "calendar"})
    accounts = client.get("/api/v1/google/accounts").json()["accounts"]
    second = accounts[1]
    shared = next(item for item in second["calendars"] if item["summary"] == "Team")
    assert shared["enabled"] is False
    assert shared["held_by"] == "you@gmail.com"
    rejected = client.patch(
        f"/api/v1/google/accounts/{second['id']}/calendars",
        json={"calendar_id": "team@group.calendar.google.com", "enabled": True},
    )
    assert rejected.status_code == 409
    assert "you@gmail.com" in rejected.json()["detail"]


def test_disabled_calendar_api_names_the_cause(tmp_path: Path) -> None:
    google = _Google()
    google.calendar_error = {
        "error": {
            "code": 403,
            "message": (
                "Google Calendar API has not been used in project 1 before or it is disabled. "
                "Enable it by visiting https://console.developers.google.com/apis/api/"
                "calendar-json.googleapis.com/overview?project=1 then retry."
            ),
            "status": "PERMISSION_DENIED",
        }
    }
    client = _client(tmp_path, google)
    _, page = _finish(client, google, {"product": "calendar"})
    assert "turned off" in page
    assert "Already connected" not in page


def test_sync_saves_events_from_checked_calendars(tmp_path: Path) -> None:
    google = _Google()
    google.events = [
        {
            "id": "evt-1",
            "summary": "Standup",
            "location": "Lab",
            "description": "Zoom:<br>https://example.com/j",
            "recurringEventId": "series-1",
            "start": {"dateTime": "2026-10-07T15:00:00Z"},
            "end": {"dateTime": "2026-10-07T15:30:00Z"},
        },
        {
            "id": "evt-2",
            "summary": "Dropped",
            "status": "cancelled",
            "start": {"dateTime": "2026-10-07T16:00:00Z"},
            "end": {"dateTime": "2026-10-07T16:30:00Z"},
        },
    ]
    google.masters = {"series-1": {"recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=WE"]}}
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    listed = client.get("/api/v1/google/events")
    assert listed.status_code == 200
    body = listed.json()
    assert [item["summary"] for item in body] == ["Standup"]
    assert body[0]["location"] == "Lab"
    assert body[0]["description"] == "Zoom:\nhttps://example.com/j"
    assert body[0]["recurrence"] == "Weekly on Wednesday"
    assert body[0]["all_day"] is False
    assert google.event_paths
    assert all("holiday" not in path for path in google.event_paths)
    account = client.get("/api/v1/google/accounts").json()["accounts"][0]
    assert account["event_count"] == 1


def test_sync_without_calendar_access_says_so(tmp_path: Path) -> None:
    google = _Google()
    google.scopes = f"openid email {GMAIL}"
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "mail"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    synced = client.post(f"/api/v1/google/accounts/{account_id}/sync")
    assert synced.status_code == 502
    assert "not granted" in synced.json()["detail"]


def test_calendar_sign_in_without_the_scope_says_so(tmp_path: Path) -> None:
    google = _Google()
    google.scopes = "openid email"
    client = _client(tmp_path, google)
    _, page = _finish(client, google, {"product": "calendar"})
    assert "did not grant calendar" in page
    account = client.get("/api/v1/google/accounts").json()["accounts"][0]
    assert account["calendars"] == []


def test_unchecked_calendar_stays_off_after_sync(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    client.patch(
        f"/api/v1/google/accounts/{account_id}/calendars",
        json={"calendar_id": "you@gmail.com", "enabled": False},
    )
    synced = client.post(f"/api/v1/google/accounts/{account_id}/sync")
    assert synced.status_code == 200
    work = next(item for item in synced.json()["calendars"] if item["summary"] == "Work")
    assert work["enabled"] is False


def test_revoked_refresh_asks_for_reconnect(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    google.invalid_grant = True
    synced = client.post(f"/api/v1/google/accounts/{account_id}/sync")
    assert synced.status_code == 409
    account = client.get("/api/v1/google/accounts").json()["accounts"][0]
    assert account["status"] == "reconnect"


def test_automatic_sync_refreshes_a_stale_calendar_and_waits_when_fresh(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    connector = client.app.state.engine.google
    before = len(google.token_bodies)

    assert asyncio.run(connector.sync_due()) == []
    assert len(google.token_bodies) == before

    _age_sync(client, account_id, minutes=20)
    assert asyncio.run(connector.sync_due()) == [account_id]
    assert len(google.token_bodies) == before + 1
    account = client.get("/api/v1/google/accounts").json()["accounts"][0]
    assert account["status"] == "connected"
    assert account["event_count"] == 0


def test_automatic_sync_skips_reconnect_and_mail_only(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    path = client.app.state.settings.db_path
    old = (datetime.now(tz=timezone.utc) - timedelta(minutes=20)).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE google_accounts SET last_sync_at = ?, status = 'reconnect' WHERE id = ?",
            (old, account_id),
        )
    before = len(google.token_bodies)
    assert asyncio.run(client.app.state.engine.google.sync_due()) == []
    assert len(google.token_bodies) == before

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE google_accounts SET status = 'connected', scopes = ? WHERE id = ?",
            (f"openid email {GMAIL}", account_id),
        )
    assert asyncio.run(client.app.state.engine.google.sync_due()) == []
    assert len(google.token_bodies) == before


def test_automatic_sync_stops_after_the_sign_in_expires(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    _age_sync(client, account_id, minutes=20)
    google.invalid_grant = True
    connector = client.app.state.engine.google
    before = len(google.token_bodies)

    assert asyncio.run(connector.sync_due()) == []
    assert len(google.token_bodies) == before + 1
    account = client.get("/api/v1/google/accounts").json()["accounts"][0]
    assert account["status"] == "reconnect"

    assert asyncio.run(connector.sync_due()) == []
    assert len(google.token_bodies) == before + 1


def test_automatic_sync_backs_off_after_a_refusal(tmp_path: Path) -> None:
    google = _Google()
    google.calendar_error = {"error": {"message": "disabled", "status": "PERMISSION_DENIED"}}
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    _age_sync(client, account_id, minutes=20)
    connector = client.app.state.engine.google
    before = len(google.token_bodies)

    assert asyncio.run(connector.sync_due()) == []
    assert len(google.token_bodies) == before + 1
    assert asyncio.run(connector.sync_due()) == []
    assert len(google.token_bodies) == before + 1

    later = datetime.now(tz=timezone.utc) + timedelta(minutes=16)
    assert asyncio.run(connector.sync_due(now=later)) == []
    assert len(google.token_bodies) == before + 2


def test_automatic_sync_leaves_an_account_that_is_already_syncing(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    _age_sync(client, account_id, minutes=20)
    connector = client.app.state.engine.google
    before = len(google.token_bodies)

    async def held() -> list[str]:
        lock = connector._lock_for(account_id)
        await lock.acquire()
        try:
            return await connector.sync_due()
        finally:
            lock.release()

    assert asyncio.run(held()) == []
    assert len(google.token_bodies) == before


def test_disconnect_revokes_and_forgets_the_token(tmp_path: Path) -> None:
    google = _Google()
    client = _client(tmp_path, google)
    _finish(client, google, {"product": "calendar"})
    account_id = client.get("/api/v1/google/accounts").json()["accounts"][0]["id"]
    removed = client.delete(f"/api/v1/google/accounts/{account_id}")
    assert removed.status_code == 204
    assert google.revoked
    assert "refresh-1" in google.revoked[0]
    assert client.get("/api/v1/google/accounts").json()["accounts"] == []
    assert client.app.state.engine.google.tokens.get(account_id) is None
