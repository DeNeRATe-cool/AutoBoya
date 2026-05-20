from pathlib import Path

import pytest

from autoboya.auth import AuthSession
from autoboya.exceptions import SessionExpired
from autoboya.models import UserRecord
from autoboya.storage import AutoBoyaStore


def test_ensure_bykc_client_logs_in_when_session_missing(monkeypatch, tmp_path: Path):
    from autoboya import session as session_module

    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.upsert_user(UserRecord(username="test-user", password_ref="unsafe-file", unsafe_password=True))
    store.save_unsafe_password("test-user", "secret")

    class FakeAuthClient:
        def __init__(self, store):
            pass

        def preflight_login(self):
            return "exec"

        def login(self, username, password, captcha=None):
            assert username == "test-user"
            assert password == "secret"
            return AuthSession(
                username=username,
                bykc_token="fresh-token",
                cookies=[{"name": "CASTGC", "value": "tgt", "domain": "sso.buaa.edu.cn", "path": "/"}],
            )

    monkeypatch.setattr(session_module, "AuthClient", FakeAuthClient)

    client = session_module.ensure_bykc_client(store, "test-user")

    assert client.token == "fresh-token"
    assert store.load_json("sessions/test-user.json")["cookies"][0]["name"] == "CASTGC"


def test_call_with_reauth_retries_once_after_session_expiry(monkeypatch, tmp_path: Path):
    from autoboya import session as session_module

    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.upsert_user(UserRecord(username="test-user", password_ref="unsafe-file", unsafe_password=True))
    store.save_unsafe_password("test-user", "secret")
    store.save_json(
        "sessions/test-user.json",
        {"bykc_token": "old-token", "cookies": [{"name": "CASTGC", "value": "old", "domain": "sso.buaa.edu.cn", "path": "/"}]},
    )

    class FakeAuthClient:
        def __init__(self, store):
            pass

        def preflight_login(self):
            return "exec"

        def login(self, username, password, captcha=None):
            return AuthSession(
                username=username,
                bykc_token="new-token",
                cookies=[{"name": "CASTGC", "value": "new", "domain": "sso.buaa.edu.cn", "path": "/"}],
            )

    seen_tokens = []

    def operation(client):
        seen_tokens.append(client.token)
        if len(seen_tokens) == 1:
            raise SessionExpired("expired")
        return client.token

    monkeypatch.setattr(session_module, "AuthClient", FakeAuthClient)

    assert session_module.call_with_reauth(store, "test-user", operation) == "new-token"
    assert seen_tokens == ["old-token", "new-token"]


def test_background_login_fails_cleanly_when_captcha_is_required(monkeypatch, tmp_path: Path):
    from autoboya import session as session_module
    from autoboya.auth import CaptchaChallenge
    from autoboya.exceptions import CaptchaRequired, LoginError

    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.upsert_user(UserRecord(username="test-user", password_ref="unsafe-file", unsafe_password=True))
    store.save_unsafe_password("test-user", "secret")

    class FakeAuthClient:
        def __init__(self, store):
            pass

        def preflight_login(self):
            raise CaptchaRequired(CaptchaChallenge("captcha-id", "image", tmp_path / "captcha.png", "exec"))

    monkeypatch.setattr(session_module, "AuthClient", FakeAuthClient)

    with pytest.raises(LoginError, match="CAPTCHA required"):
        session_module.ensure_bykc_client(store, "test-user", captcha_provider=None)
