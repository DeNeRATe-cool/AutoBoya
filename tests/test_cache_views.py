from datetime import datetime
from pathlib import Path

from autoboya.cache import CourseCache, preview_auto_select_courses
from autoboya.cli import app
from autoboya.storage import AutoBoyaStore
from typer.testing import CliRunner


def test_course_cache_round_trip(tmp_path: Path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    cache = CourseCache(store)
    cache.save_courses([{"id": 1001, "courseName": "美育", "coursePosition": "沙河"}])

    assert cache.load_courses()[0]["id"] == 1001


def test_auto_preview_keeps_only_autonomous_sign_courses(tmp_path: Path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    cache = CourseCache(store)
    cache.save_courses(
        [
            {
                "id": 1001,
                "courseName": "自主签到课程",
                "selected": False,
                "courseSelectStartDate": "2026-05-20 08:00:00",
                "courseSelectEndDate": "2026-05-20 09:00:00",
                "courseCurrentCount": 1,
                "courseMaxCount": 20,
                "courseSignConfig": '{"signPointList":[{"lat":39.981,"lng":116.344,"radius":8}]}',
            },
            {
                "id": 1002,
                "courseName": "常规签到课程",
                "selected": False,
                "courseSelectStartDate": "2026-05-20 08:00:00",
                "courseSelectEndDate": "2026-05-20 09:00:00",
                "courseCurrentCount": 1,
                "courseMaxCount": 20,
                "courseSignConfig": "",
            },
        ]
    )

    preview = preview_auto_select_courses(cache.load_courses(), now=datetime(2026, 5, 20, 8, 30))

    assert [course.id for course in preview.candidates] == [1001]
    assert preview.excluded[1002] == "常规签到或无位置配置"


def test_selected_user_defaults_to_readable_table(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = AutoBoyaStore()
    store.init()
    CourseCache(store).save_selected(
        "test-user",
        [
            {
                "id": 1001,
                "courseName": "表格课程",
                "coursePosition": "沙河",
                "courseNewKind2": {"kindName": "美育"},
                "courseStartDate": "2026-05-20 08:00:00",
                "courseEndDate": "2026-05-20 09:00:00",
                "courseSignConfig": "",
            }
        ],
    )

    result = CliRunner().invoke(app, ["selected", "--user", "test-user"])

    assert result.exit_code == 0
    assert "状态" in result.output
    assert "课程ID" in result.output
    assert "表格课程" in result.output
    assert not result.output.lstrip().startswith("{")


def test_stats_user_defaults_to_readable_table(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = AutoBoyaStore()
    store.init()
    CourseCache(store).save_statistics(
        "test-user",
        {
            "statistical": {
                "60|博雅课程": {
                    "55|德育": {
                        "assessmentCount": 2,
                        "selectAssessmentCount": 1,
                        "completeAssessmentCount": 1,
                        "failAssessmentCount": 0,
                        "undoneAssessmentCount": 1,
                    }
                }
            },
            "validCount": 1,
        },
    )

    result = CliRunner().invoke(app, ["stats", "--user", "test-user"])

    assert result.exit_code == 0
    assert "类型" in result.output
    assert "德育" in result.output
    assert "要求" in result.output
    assert not result.output.lstrip().startswith("{")


def test_stats_shows_valid_count_once_per_user(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    store = AutoBoyaStore()
    store.init()
    CourseCache(store).save_statistics(
        "test-user",
        {
            "statistical": {
                "60|博雅课程": {
                    "55|德育": {"assessmentCount": 2, "selectAssessmentCount": 1},
                    "56|美育": {"assessmentCount": 1, "selectAssessmentCount": 0},
                }
            },
            "validCount": 3,
        },
    )

    result = CliRunner().invoke(app, ["stats", "--user", "test-user"])

    assert result.exit_code == 0
    assert result.output.count("│      3 │") == 1
