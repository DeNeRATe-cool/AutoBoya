from typer.testing import CliRunner

from autoboya import cli
from autoboya.cli import app
from autoboya.exceptions import LoginError


def test_login_error_is_user_facing_without_traceback(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = cli.AutoBoyaStore()
    store.init()
    store.save_unsafe_password("test-user", "secret")
    store.upsert_user(cli.UserRecord(username="test-user", password_ref="unsafe-file", unsafe_password=True))

    class FailingAuthClient:
        def __init__(self, store):
            pass

        def preflight_login(self):
            return "exec"

        def login(self, username, password, captcha=None):
            raise LoginError("Boya token was not returned after SSO login")

    monkeypatch.setattr(cli, "AuthClient", FailingAuthClient)
    result = CliRunner().invoke(app, ["login", "test-user"])

    assert result.exit_code == 1
    assert "Login failed" in result.output
    assert "Traceback" not in result.output
    assert "secret" not in result.output
