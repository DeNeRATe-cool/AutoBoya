from datetime import datetime
from pathlib import Path

from autoboya.cache import CourseCache, preview_auto_select_courses
from autoboya.storage import AutoBoyaStore


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
