"""Domain errors. No framework types."""


class CoreError(Exception):
    """Base class for errors callers are expected to handle."""


class SourceNotFoundError(CoreError):
    """A configured root or source id cannot be read."""


class InvalidSourceIdError(CoreError):
    """A source id is malformed or points outside its root."""


class DuplicateSourceError(CoreError):
    """A source id is taken, or the folder is already covered by another root."""


class ParseError(CoreError):
    """Bytes could not be parsed as the declared format."""


class GoogleNotConfiguredError(CoreError):
    """Sign-in was started before a Google client id was set."""


class CalendarHeldError(CoreError):
    """Another connected account already reads this calendar."""

    def __init__(self, email: str) -> None:
        super().__init__(f"Already included from {email}")
        self.email = email


class GoogleAuthError(CoreError):
    """Google rejected a token exchange or a calendar call."""


class GoogleReconnectError(GoogleAuthError):
    """The stored refresh token no longer works."""
