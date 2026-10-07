"""Refresh tokens for connected Google accounts.

The database remembers which account exists. The refresh token itself
stays in this store: the OS keyring on a home machine, or another
implementation when owlet runs in the cloud. Callers never see which.
"""

from __future__ import annotations

from typing import Protocol


class TokenStore(Protocol):
    def get(self, account_id: str) -> str | None:
        """The refresh token, or None when this account has none stored."""
        ...

    def put(self, account_id: str, refresh_token: str) -> None:
        """Replace whatever token was stored for this account."""
        ...

    def delete(self, account_id: str) -> None:
        """Forget the token. Missing entries are not an error."""
        ...


class MemoryTokenStore:
    """In-process store for tests and for a process that has no keyring."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def get(self, account_id: str) -> str | None:
        return self._tokens.get(account_id)

    def put(self, account_id: str, refresh_token: str) -> None:
        self._tokens[account_id] = refresh_token

    def delete(self, account_id: str) -> None:
        self._tokens.pop(account_id, None)


class KeyringTokenStore:
    """OS keyring. The service name is stable so a restart finds the same token."""

    service = "owlet.google"

    def get(self, account_id: str) -> str | None:
        import keyring

        return keyring.get_password(self.service, account_id)

    def put(self, account_id: str, refresh_token: str) -> None:
        import keyring

        keyring.set_password(self.service, account_id, refresh_token)

    def delete(self, account_id: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self.service, account_id)
        except PasswordDeleteError:
            return
