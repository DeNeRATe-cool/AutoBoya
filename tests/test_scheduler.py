from datetime import datetime

from autoboya.models import BoyaCourse
from autoboya.scheduler import AutomationDecision, AutomationRunner, decide_actions
from autoboya.storage import AutoBoyaStore


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


def test_refresh_once_auto_logs_in_when_session_missing(monkeypatch, tmp_path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.save_users([{"username": "test-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True}])

    class FakeClient:
        def get_all_config(self):
            return {
                "data": {
                    "semester": [
                        {
                            "semesterStartDate": "2026-03-01 00:00:00",
                            "semesterEndDate": "2026-06-21 00:00:00",
                        }
                    ]
                }
            }

        def query_courses(self):
            return [BoyaCourse(id=1001, name="课程")]

        def query_chosen_courses(self, start_date, end_date):
            return [BoyaCourse(id=1002, name="已选")]

        def query_statistics(self):
            return {"validCount": 1}

    seen_users = []

    def fake_ensure_bykc_client(store, username, captcha_provider=None):
        seen_users.append(username)
        return FakeClient()

    monkeypatch.setattr("autoboya.scheduler.ensure_bykc_client", fake_ensure_bykc_client)

    AutomationRunner(store).refresh_once()

    assert seen_users == ["test-user", "test-user"]
    assert store.load_json("cache/courses.json")[0]["id"] == 1001
    assert store.load_json("cache/selected.json")["test-user"][0]["id"] == 1002
    assert store.load_json("cache/statistics.json")["test-user"]["validCount"] == 1
