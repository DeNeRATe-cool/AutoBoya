from typer.testing import CliRunner

from autoboya import cli
from autoboya.cli import app
from autoboya.exceptions import LoginError, SignWindowClosed


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


def test_refresh_with_missing_password_is_user_facing(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = cli.AutoBoyaStore()
    store.init()
    store.upsert_user(cli.UserRecord(username="test-user", password_ref="unsafe-file", unsafe_password=True))
    store.save_json("sessions/test-user.json", {"bykc_token": "legacy-token"}, mode=0o600)

    result = CliRunner().invoke(app, ["courses", "refresh", "--user", "test-user"])

    assert result.exit_code == 1
    assert "No stored password" in result.output
    assert "Traceback" not in result.output


def test_drop_api_error_is_user_facing(monkeypatch):
    def failing_call_with_reauth(store, username, operation, captcha_provider=None):
        raise RuntimeError("course is not droppable")

    monkeypatch.setattr(cli, "call_with_reauth", failing_call_with_reauth)
    result = CliRunner().invoke(app, ["drop", "123", "--user", "test-user", "--yes"])

    assert result.exit_code == 1
    assert "Failed to drop 123 for tes***: course is not droppable" in result.output
    assert "Traceback" not in result.output


def test_sign_api_error_is_user_facing(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = cli.AutoBoyaStore()
    store.init()
    store.save_json(
        "cache/courses.json",
        [
            {
                "id": 123,
                "courseName": "Test",
                "courseSignConfig": {
                    "signPointList": [{"lat": 40.0, "lng": 116.0, "radius": 10}],
                },
            }
        ],
    )

    def failing_call_with_reauth(store, username, operation, captcha_provider=None):
        raise SignWindowClosed("not in sign window")

    monkeypatch.setattr(cli, "call_with_reauth", failing_call_with_reauth)
    result = CliRunner().invoke(app, ["sign", "123", "--user", "test-user"])

    assert result.exit_code == 1
    assert "Failed to sign 123 for tes***: not in sign window" in result.output
    assert "Traceback" not in result.output
