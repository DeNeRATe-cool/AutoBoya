from typer.testing import CliRunner

from autoboya import cli
from autoboya.cli import app


def test_cli_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "autoboya" in result.output


def test_help_short_alias():
    result = CliRunner().invoke(app, ["-h"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_nested_help_short_alias():
    result = CliRunner().invoke(app, ["courses", "auto-preview", "-h"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_courses_refresh_without_user_refreshes_all_enabled_users(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = cli.AutoBoyaStore()
    store.init()
    store.save_users(
        [
            {"username": "u1", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True},
            {"username": "u2", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True},
        ]
    )
    calls = []

    class FakeClient:
        def __init__(self, username):
            self.username = username

        def query_courses(self):
            calls.append((self.username, "courses"))
            return [{"id": 1001, "courseName": "课程"}]

        def get_all_config(self):
            return {"data": {"semester": [{"semesterStartDate": "2026-03-01", "semesterEndDate": "2026-06-21"}]}}

        def query_chosen_courses(self, start, end):
            calls.append((self.username, "selected"))
            return [{"id": 2001, "courseName": f"已选-{self.username}"}]

        def query_statistics(self):
            calls.append((self.username, "stats"))
            return {"validCount": 1}

    def fake_call_with_reauth(store, username, operation, captcha_provider=None):
        return operation(FakeClient(username))

    monkeypatch.setattr(cli, "call_with_reauth", fake_call_with_reauth)

    result = CliRunner().invoke(app, ["courses", "refresh"])

    assert result.exit_code == 0
    assert "Refreshed 1 courses" in result.output
    assert store.load_json("cache/selected.json")["u1"][0]["courseName"] == "已选-u1"
    assert store.load_json("cache/selected.json")["u2"][0]["courseName"] == "已选-u2"
    assert calls == [
        ("u1", "courses"),
        ("u1", "selected"),
        ("u1", "stats"),
        ("u2", "selected"),
        ("u2", "stats"),
    ]


def test_run_starts_background_worker_without_entering_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    popen_calls = []

    class FakePopen:
        pid = 4321

        def __init__(self, args, **kwargs):
            popen_calls.append((args, kwargs))

    def fail_run_forever(self):
        raise AssertionError("run should not enter foreground loop")

    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(cli.AutomationRunner, "run_forever", fail_run_forever)

    result = CliRunner().invoke(app, ["run"])

    assert result.exit_code == 0
    assert "background" in result.output
    assert "4321" in result.output
    assert popen_calls
