from typer.testing import CliRunner

from autoboya import cli
from autoboya.cache import CourseCache
from autoboya.cli import app
from autoboya.storage import AutoBoyaStore


def test_manual_commands_show_help_without_network():
    runner = CliRunner()
    for command in [
        ["select", "--help"],
        ["drop", "--help"],
        ["sign", "--help"],
        ["signout", "--help"],
        ["run-once", "--help"],
    ]:
        result = runner.invoke(app, command)
        assert result.exit_code == 0


def test_sign_requires_selected_course_before_api_call(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = AutoBoyaStore()
    store.init()
    store.save_users([{"username": "test-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True}])
    CourseCache(store).save_courses(
        [
            {
                "id": 9580,
                "courseName": "法语电影工坊",
                "courseSignConfig": '{"signPointList":[{"lat":39.981,"lng":116.344,"radius":8}]}',
            }
        ]
    )
    called = False

    def fake_call_with_reauth(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "call_with_reauth", fake_call_with_reauth)
    result = CliRunner().invoke(app, ["sign", "9580", "--user", "test-user"])

    assert result.exit_code == 1
    assert "not selected" in result.output
    assert "autoboya select 9580 --user test-user --yes" in result.output
    assert not called


def test_drop_uses_selected_record_id_when_available(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = AutoBoyaStore()
    store.init()
    store.save_users([{"username": "test-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True}])
    store.save_json(
        "cache/selected.json",
        {
            "test-user": [
                {
                    "id": 9580,
                    "chosenCourseId": 3972171,
                    "courseName": "法语电影工坊",
                }
            ]
        },
    )
    dropped = []

    class FakeClient:
        def drop_course(self, course_id):
            dropped.append(course_id)

    monkeypatch.setattr(cli, "call_with_reauth", lambda store, username, operation, captcha_provider=None: operation(FakeClient()))
    result = CliRunner().invoke(app, ["drop", "9580", "--user", "test-user", "--yes"])

    assert result.exit_code == 0
    assert dropped == [3972171]


def test_manual_select_calls_select_course(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = AutoBoyaStore()
    store.init()
    store.save_users([{"username": "test-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True}])
    selected = []

    class FakeClient:
        def select_course(self, course_id):
            selected.append(course_id)

        def get_all_config(self):
            return {"data": {"semester": [{"semesterStartDate": "2026-03-01", "semesterEndDate": "2026-06-21"}]}}

        def query_chosen_courses(self, start, end):
            return []

        def query_statistics(self):
            return {}

    monkeypatch.setattr(cli, "call_with_reauth", lambda store, username, operation, captcha_provider=None: operation(FakeClient()))
    result = CliRunner().invoke(app, ["select", "9580", "--user", "test-user", "--yes"])

    assert result.exit_code == 0
    assert selected == [9580]


def test_root_help_has_chinese_command_descriptions():
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "查看课程" in result.output
    assert "手动选课" in result.output
