"""Connected Google accounts and the calendars each one may read.

One row per Google subject. A calendar that is enabled on an earlier
account is reported as held, so a shared calendar is not composed twice.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.domain.errors import CalendarHeldError, SourceNotFoundError
from core.store.db import migrate, session

ATTEMPT_TTL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class CalendarRecord:
    calendar_id: str
    summary: str
    is_primary: bool
    enabled: bool
    held_by: str | None = None


@dataclass(frozen=True, slots=True)
class AccountRecord:
    id: str
    email: str
    scopes: tuple[str, ...]
    status: str
    last_sync_at: datetime | None
    created_at: datetime
    calendars: tuple[CalendarRecord, ...] = ()
    event_count: int = 0


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: str
    summary: str
    start: str
    end: str
    all_day: bool
    location: str
    description: str
    recurrence: str
    calendar: str


@dataclass(frozen=True, slots=True)
class Attempt:
    id: str
    verifier: str
    redirect_uri: str
    product: str
    account_id: str | None
    status: str
    email: str | None
    message: str
    created_at: datetime


class GoogleAccountStore:
    """Accounts, calendar checklists, and short-lived sign-in attempts."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._ready = False

    def saved_client_id(self) -> str:
        row = self._client_row()
        if row is None:
            return ""
        return str(row["client_id"]).strip()

    def saved_account_email(self) -> str:
        row = self._client_row()
        if row is None:
            return ""
        return str(row["account_email"] or "").strip()

    def save_client_id(self, client_id: str, account_email: str | None = None) -> None:
        email = self.saved_account_email() if account_email is None else account_email.strip()
        now = _now()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO google_client (id, client_id, account_email, updated_at)"
                " VALUES (1, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " client_id = excluded.client_id,"
                " account_email = excluded.account_email,"
                " updated_at = excluded.updated_at",
                (client_id, email, now),
            )

    def _client_row(self) -> sqlite3.Row | None:
        with self._session() as connection:
            return connection.execute(
                "SELECT client_id, account_email FROM google_client WHERE id = 1"
            ).fetchone()

    def list_accounts(self) -> list[AccountRecord]:
        with self._session() as connection:
            accounts = connection.execute(
                "SELECT * FROM google_accounts ORDER BY created_at, id"
            ).fetchall()
            calendars = connection.execute(
                "SELECT * FROM google_calendars ORDER BY is_primary DESC, summary, calendar_id"
            ).fetchall()
            counts = {
                row["account_id"]: int(row["n"])
                for row in connection.execute(
                    "SELECT e.account_id AS account_id, COUNT(*) AS n"
                    " FROM google_events AS e"
                    " JOIN google_calendars AS c"
                    " ON c.account_id = e.account_id AND c.calendar_id = e.calendar_id"
                    " WHERE c.enabled = 1"
                    " GROUP BY e.account_id"
                )
            }
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in calendars:
            grouped.setdefault(row["account_id"], []).append(row)
        records = [
            _account(row, grouped.get(row["id"], []), counts.get(row["id"], 0)) for row in accounts
        ]
        return _with_holders(records)

    def get(self, account_id: str) -> AccountRecord | None:
        for account in self.list_accounts():
            if account.id == account_id:
                return account
        return None

    def upsert_account(self, account_id: str, email: str, scopes: Sequence[str]) -> None:
        now = _now()
        scope_text = " ".join(scopes)
        with self._session() as connection:
            connection.execute(
                "INSERT INTO google_accounts"
                " (id, email, scopes, status, last_sync_at, created_at, updated_at)"
                " VALUES (?, ?, ?, 'connected', ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " email = excluded.email, scopes = excluded.scopes,"
                " status = 'connected', updated_at = excluded.updated_at",
                (account_id, email, scope_text, now, now, now),
            )

    def mark_synced(self, account_id: str) -> None:
        now = _now()
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE google_accounts"
                " SET last_sync_at = ?, status = 'connected', updated_at = ?"
                " WHERE id = ?",
                (now, now, account_id),
            )
            if cursor.rowcount == 0:
                raise SourceNotFoundError(account_id)

    def mark_reconnect(self, account_id: str) -> None:
        now = _now()
        with self._session() as connection:
            connection.execute(
                "UPDATE google_accounts SET status = 'reconnect', updated_at = ? WHERE id = ?",
                (now, account_id),
            )

    def replace_calendars(
        self,
        account_id: str,
        calendars: Sequence[tuple[str, str, bool, bool]],
    ) -> None:
        """Replace the checklist. (id, summary, primary, default_enabled).

        A calendar the user already toggled keeps that choice. A new one
        stays off when another account already has it enabled.
        """
        now = _now()
        with self._session() as connection:
            if connection.execute(
                "SELECT 1 FROM google_accounts WHERE id = ?", (account_id,)
            ).fetchone() is None:
                raise SourceNotFoundError(account_id)
            previous = {
                row["calendar_id"]: bool(row["enabled"])
                for row in connection.execute(
                    "SELECT calendar_id, enabled FROM google_calendars WHERE account_id = ?",
                    (account_id,),
                )
            }
            held = {
                row["calendar_id"]
                for row in connection.execute(
                    "SELECT calendar_id FROM google_calendars"
                    " WHERE enabled = 1 AND account_id != ?",
                    (account_id,),
                )
            }
            connection.execute(
                "DELETE FROM google_calendars WHERE account_id = ?", (account_id,)
            )
            connection.executemany(
                "INSERT INTO google_calendars"
                " (account_id, calendar_id, summary, is_primary, enabled, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        account_id,
                        calendar_id,
                        summary,
                        int(is_primary),
                        int(_kept_enabled(calendar_id, default_enabled, previous, held)),
                        now,
                    )
                    for calendar_id, summary, is_primary, default_enabled in calendars
                ],
            )

    def set_calendar_enabled(self, account_id: str, calendar_id: str, enabled: bool) -> None:
        now = _now()
        with self._session() as connection:
            if enabled:
                holder = connection.execute(
                    "SELECT a.email FROM google_calendars AS c"
                    " JOIN google_accounts AS a ON a.id = c.account_id"
                    " WHERE c.calendar_id = ? AND c.enabled = 1 AND c.account_id != ?",
                    (calendar_id, account_id),
                ).fetchone()
                if holder is not None:
                    raise CalendarHeldError(holder["email"])
            cursor = connection.execute(
                "UPDATE google_calendars SET enabled = ?, updated_at = ?"
                " WHERE account_id = ? AND calendar_id = ?",
                (int(enabled), now, account_id, calendar_id),
            )
            if cursor.rowcount == 0:
                raise SourceNotFoundError(calendar_id)

    def replace_events(
        self,
        account_id: str,
        events: Sequence[tuple[str, str, str, str, str, bool, str, str, str]],
    ) -> None:
        """Replace this account's event window.

        Each item is (calendar id, event id, summary, start, end, all_day,
        location, description, recurrence).
        """
        with self._session() as connection:
            if connection.execute(
                "SELECT 1 FROM google_accounts WHERE id = ?", (account_id,)
            ).fetchone() is None:
                raise SourceNotFoundError(account_id)
            connection.execute("DELETE FROM google_events WHERE account_id = ?", (account_id,))
            connection.executemany(
                "INSERT INTO google_events"
                " (account_id, calendar_id, event_id, summary, start_at, end_at,"
                " all_day, location, description, recurrence)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        account_id,
                        calendar_id,
                        event_id,
                        summary,
                        start,
                        end,
                        int(all_day),
                        location,
                        description,
                        recurrence,
                    )
                    for (
                        calendar_id,
                        event_id,
                        summary,
                        start,
                        end,
                        all_day,
                        location,
                        description,
                        recurrence,
                    ) in events
                ],
            )

    def list_events(self) -> list[EventRecord]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT e.event_id, e.summary, e.start_at, e.end_at, e.all_day, e.location,"
                " e.description, e.recurrence, c.summary AS calendar"
                " FROM google_events AS e"
                " JOIN google_calendars AS c"
                " ON c.account_id = e.account_id AND c.calendar_id = e.calendar_id"
                " WHERE c.enabled = 1"
                " ORDER BY e.all_day DESC, e.start_at, e.summary"
            ).fetchall()
        return [
            EventRecord(
                id=row["event_id"],
                summary=row["summary"],
                start=row["start_at"],
                end=row["end_at"],
                all_day=bool(row["all_day"]),
                location=row["location"],
                description=row["description"],
                recurrence=row["recurrence"],
                calendar=row["calendar"],
            )
            for row in rows
        ]

    def remove(self, account_id: str) -> bool:
        with self._session() as connection:
            cursor = connection.execute(
                "DELETE FROM google_accounts WHERE id = ?", (account_id,)
            )
        return cursor.rowcount > 0

    def create_attempt(
        self,
        attempt_id: str,
        *,
        verifier: str,
        redirect_uri: str,
        product: str,
        account_id: str | None,
    ) -> None:
        now = _now()
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        with self._session() as connection:
            connection.execute("DELETE FROM oauth_attempts WHERE created_at < ?", (cutoff,))
            connection.execute(
                "INSERT INTO oauth_attempts"
                " (id, verifier, redirect_uri, product, account_id, status, email,"
                " message, created_at)"
                " VALUES (?, ?, ?, ?, ?, 'pending', NULL, '', ?)",
                (attempt_id, verifier, redirect_uri, product, account_id, now),
            )

    def claim_attempt(self, attempt_id: str) -> Attempt | None:
        """Take a pending attempt. A second callback finds nothing to claim."""
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None or row["status"] != "pending":
                return None
            created = datetime.fromisoformat(row["created_at"])
            if datetime.now(tz=timezone.utc) - created > ATTEMPT_TTL:
                connection.execute(
                    "UPDATE oauth_attempts SET status = 'expired',"
                    " message = ? WHERE id = ? AND status = 'pending'",
                    ("That sign-in took too long. Start again from Settings.", attempt_id),
                )
                return None
            connection.execute(
                "UPDATE oauth_attempts SET status = 'finishing'"
                " WHERE id = ? AND status = 'pending'",
                (attempt_id,),
            )
        return self.read_attempt(attempt_id)

    def read_attempt(self, attempt_id: str) -> Attempt | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM oauth_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                return None
            if row["status"] == "pending":
                created = datetime.fromisoformat(row["created_at"])
                if datetime.now(tz=timezone.utc) - created > ATTEMPT_TTL:
                    connection.execute(
                        "UPDATE oauth_attempts SET status = 'expired',"
                        " message = ? WHERE id = ? AND status = 'pending'",
                        ("That sign-in took too long. Start again from Settings.", attempt_id),
                    )
                    row = connection.execute(
                        "SELECT * FROM oauth_attempts WHERE id = ?", (attempt_id,)
                    ).fetchone()
        return _attempt(row) if row is not None else None

    def cancel_attempt(self, attempt_id: str) -> Attempt | None:
        """Cancel a sign-in that is still waiting. A finished one is left as it is."""
        with self._session() as connection:
            connection.execute(
                "UPDATE oauth_attempts SET status = 'cancelled', message = ?"
                " WHERE id = ? AND status = 'pending'",
                ("Sign-in was cancelled.", attempt_id),
            )
        return self.read_attempt(attempt_id)

    def complete_attempt(
        self,
        attempt_id: str,
        *,
        status: str,
        email: str | None = None,
        message: str = "",
    ) -> None:
        with self._session() as connection:
            connection.execute(
                "UPDATE oauth_attempts SET status = ?, email = ?, message = ?"
                " WHERE id = ? AND status = 'finishing'",
                (status, email, message, attempt_id),
            )

    def _session(self) -> AbstractContextManager[sqlite3.Connection]:
        if not self._ready:
            migrate(self._db_path)
            self._ready = True
        return session(self._db_path)


def _kept_enabled(
    calendar_id: str,
    default_enabled: bool,
    previous: dict[str, bool],
    held: set[str],
) -> bool:
    if calendar_id in previous:
        return previous[calendar_id]
    if calendar_id in held:
        return False
    return default_enabled


def _with_holders(accounts: list[AccountRecord]) -> list[AccountRecord]:
    """The earliest account to enable a calendar is the one that owns it."""
    holders: dict[str, str] = {}
    for account in accounts:
        for calendar in account.calendars:
            if calendar.enabled and calendar.calendar_id not in holders:
                holders[calendar.calendar_id] = account.email
    marked: list[AccountRecord] = []
    for account in accounts:
        calendars = tuple(
            CalendarRecord(
                calendar_id=calendar.calendar_id,
                summary=calendar.summary,
                is_primary=calendar.is_primary,
                enabled=calendar.enabled,
                held_by=_other_holder(holders, calendar.calendar_id, account.email),
            )
            for calendar in account.calendars
        )
        marked.append(
            AccountRecord(
                id=account.id,
                email=account.email,
                scopes=account.scopes,
                status=account.status,
                last_sync_at=account.last_sync_at,
                created_at=account.created_at,
                calendars=calendars,
                event_count=account.event_count,
            )
        )
    return marked


def _other_holder(holders: dict[str, str], calendar_id: str, email: str) -> str | None:
    holder = holders.get(calendar_id)
    if holder is None or holder == email:
        return None
    return holder


def _account(row: sqlite3.Row, calendars: list[sqlite3.Row], event_count: int) -> AccountRecord:
    synced = row["last_sync_at"]
    return AccountRecord(
        id=row["id"],
        email=row["email"],
        scopes=tuple(part for part in row["scopes"].split() if part),
        status=row["status"],
        last_sync_at=datetime.fromisoformat(synced) if synced else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        calendars=tuple(_calendar(item) for item in calendars),
        event_count=event_count,
    )


def _calendar(row: sqlite3.Row) -> CalendarRecord:
    return CalendarRecord(
        calendar_id=row["calendar_id"],
        summary=row["summary"],
        is_primary=bool(row["is_primary"]),
        enabled=bool(row["enabled"]),
    )


def _attempt(row: sqlite3.Row) -> Attempt:
    return Attempt(
        id=row["id"],
        verifier=row["verifier"],
        redirect_uri=row["redirect_uri"],
        product=row["product"],
        account_id=row["account_id"],
        status=row["status"],
        email=row["email"],
        message=row["message"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
