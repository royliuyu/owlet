"""Redirect choice, PKCE, and which calendars start enabled."""

from core.config import GoogleSettings, Settings
from core.connectors.google import (
    _plain,
    _repeat_label,
    authorization_url,
    choose_redirect,
    initially_enabled,
    pkce,
)


def test_loopback_and_cloud_origins_finish_in_the_browser() -> None:
    settings = Settings(google=GoogleSettings(redirect_origins="https://owlet.example.com"))

    local, local_server = choose_redirect("http://127.0.0.1:8000/", settings)
    assert local == "http://127.0.0.1:8000/api/v1/google/callback"
    assert local_server is False

    cloud, cloud_server = choose_redirect("https://owlet.example.com", settings)
    assert cloud == "https://owlet.example.com/api/v1/google/callback"
    assert cloud_server is False


def test_phone_on_another_host_opens_on_this_machine() -> None:
    settings = Settings(port=8000)
    redirect, on_server = choose_redirect("http://100.64.0.2:8000", settings)
    assert redirect == "http://127.0.0.1:8000/api/v1/google/callback"
    assert on_server is True


def test_new_account_may_pick_a_login_and_mail_pins_it() -> None:
    fresh = authorization_url(
        client_id="client",
        redirect_uri="http://127.0.0.1:8000/api/v1/google/callback",
        scopes=("openid", "email"),
        state="state",
        challenge="challenge",
        login_hint=None,
        existing_account=False,
    )
    assert "prompt=select_account+consent" in fresh
    assert "include_granted_scopes" not in fresh

    mail = authorization_url(
        client_id="client",
        redirect_uri="http://127.0.0.1:8000/api/v1/google/callback",
        scopes=("openid", "email"),
        state="state",
        challenge="challenge",
        login_hint="you@gmail.com",
        existing_account=True,
    )
    assert "prompt=consent" in mail
    assert "include_granted_scopes=true" in mail
    assert "login_hint=you%40gmail.com" in mail


def test_pkce_challenge_matches_the_verifier() -> None:
    import base64
    import hashlib

    verifier, challenge = pkce()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge == expected
    assert 43 <= len(verifier) <= 128


def test_repeat_label_and_description_match_the_calendar_card() -> None:
    assert _repeat_label(["RRULE:FREQ=WEEKLY;BYDAY=WE"]) == "Weekly on Wednesday"
    assert _plain("Zoom:<br>https://example.com/j") == "Zoom:\nhttps://example.com/j"


def test_primary_starts_on_and_holiday_calendars_stay_off() -> None:
    assert initially_enabled("you@gmail.com", primary=True) is True
    assert initially_enabled("team@group.calendar.google.com", primary=False) is False
    assert (
        initially_enabled("en.usa#holiday@group.v.calendar.google.com", primary=True) is False
    )
    assert (
        initially_enabled("addressbook#contacts@group.v.calendar.google.com", primary=False)
        is False
    )
