from datetime import datetime

from autoboya.models import BoyaCourse
from autoboya.rules import (
    classify_selected_courses,
    is_auto_select_candidate,
    is_selectable,
    random_point_in_radius,
)


def test_is_selectable_requires_window_capacity_and_not_selected():
    course = BoyaCourse(
        id=1001,
        name="劳动教育示例",
        location="学院路",
        category="劳动教育",
        selected=False,
        course_start="2026-05-20 10:00:00",
        course_end="2026-05-20 11:00:00",
        select_start="2026-05-20 08:00:00",
        select_end="2026-05-20 09:00:00",
        cancel_end="2026-05-20 09:30:00",
        current_count=5,
        max_count=10,
        sign_config={},
        sign_type=None,
    )
    assert is_selectable(course, datetime(2026, 5, 20, 8, 30))
    assert not is_selectable(course, datetime(2026, 5, 20, 7, 59))


def test_classify_selected_courses_by_start_time():
    started = BoyaCourse(id=1, name="A", course_start="2026-05-20 08:00:00")
    pending = BoyaCourse(id=2, name="B", course_start="2026-05-20 12:00:00")

    grouped = classify_selected_courses([started, pending], datetime(2026, 5, 20, 10, 0))

    assert [c.id for c in grouped["已开始上课"]] == [1]
    assert [c.id for c in grouped["未开始上课"]] == [2]


def test_auto_select_candidate_requires_autonomous_sign_config():
    autonomous = BoyaCourse(
        id=1001,
        selected=False,
        select_start="2026-05-20 08:00:00",
        select_end="2026-05-20 09:00:00",
        current_count=1,
        max_count=20,
        sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]},
    )
    regular = BoyaCourse(
        id=1002,
        selected=False,
        select_start="2026-05-20 08:00:00",
        select_end="2026-05-20 09:00:00",
        current_count=1,
        max_count=20,
        sign_config={},
    )
    now = datetime(2026, 5, 20, 8, 30)

    assert is_auto_select_candidate(autonomous, now)
    assert not is_auto_select_candidate(regular, now)


def test_auto_select_candidate_excludes_other_category():
    course = BoyaCourse(
        id=1003,
        category="其他方面",
        selected=False,
        select_start="2026-05-20 08:00:00",
        select_end="2026-05-20 09:00:00",
        current_count=1,
        max_count=20,
        sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]},
    )

    assert not is_auto_select_candidate(course, datetime(2026, 5, 20, 8, 30))


def test_random_point_stays_inside_radius():
    lat, lng = random_point_in_radius(39.981, 116.344, 8, seed=7)
    assert 39.9809 < lat < 39.9811
    assert 116.3439 < lng < 116.3441
