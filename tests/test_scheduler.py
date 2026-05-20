from datetime import datetime

from autoboya.models import BoyaCourse
from autoboya.scheduler import AutomationDecision, decide_actions


def test_decide_selects_only_autonomous_sign_courses_inside_window():
    courses = [
        BoyaCourse(
            id=1001,
            selected=False,
            select_start="2026-05-20 08:00:00",
            select_end="2026-05-20 09:00:00",
            current_count=1,
            max_count=20,
            sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]},
            raw={
                "id": 1001,
                "selected": False,
                "courseSelectStartDate": "2026-05-20 08:00:00",
                "courseSelectEndDate": "2026-05-20 09:00:00",
                "courseCurrentCount": 1,
                "courseMaxCount": 20,
                "courseSignConfig": '{"signPointList":[{"lat":39.981,"lng":116.344,"radius":8}]}',
            },
        ),
        BoyaCourse(
            id=1002,
            selected=False,
            select_start="2026-05-20 08:00:00",
            select_end="2026-05-20 09:00:00",
            current_count=1,
            max_count=20,
            sign_config={},
            raw={
                "id": 1002,
                "selected": False,
                "courseSelectStartDate": "2026-05-20 08:00:00",
                "courseSelectEndDate": "2026-05-20 09:00:00",
                "courseCurrentCount": 1,
                "courseMaxCount": 20,
                "courseSignConfig": "",
            },
        ),
    ]

    decisions = decide_actions(courses, selected_by_user={}, now=datetime(2026, 5, 20, 8, 30))

    assert AutomationDecision(action="select", course_id=1001) in decisions
    assert AutomationDecision(action="select", course_id=1002) not in decisions
