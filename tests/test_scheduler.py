from datetime import datetime
import logging

from autoboya.models import BoyaCourse
from autoboya.scheduler import AutomationDecision, AutomationRunner, decide_actions
from autoboya.storage import AutoBoyaStore


def test_decide_selects_only_autonomous_sign_courses_inside_window():
    courses = [
        BoyaCourse(
            id=1001,
            selected=True,
            select_start="2026-05-20 08:00:00",
            select_end="2026-05-20 09:00:00",
            current_count=1,
            max_count=20,
            sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]},
            raw={
                "id": 1001,
                "selected": True,
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
        BoyaCourse(
            id=1003,
            category="其他方面",
            selected=False,
            select_start="2026-05-20 08:00:00",
            select_end="2026-05-20 09:00:00",
            current_count=1,
            max_count=20,
            sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]},
            raw={
                "id": 1003,
                "selected": False,
                "courseNewKind2": {"kindName": "其他方面"},
                "courseSelectStartDate": "2026-05-20 08:00:00",
                "courseSelectEndDate": "2026-05-20 09:00:00",
                "courseCurrentCount": 1,
                "courseMaxCount": 20,
                "courseSignConfig": '{"signPointList":[{"lat":39.981,"lng":116.344,"radius":8}]}',
            },
        ),
    ]

    decisions = decide_actions(courses, selected_by_user={}, now=datetime(2026, 5, 20, 8, 30))

    assert AutomationDecision(action="select", course_id=1001) in decisions
    assert AutomationDecision(action="select", course_id=1002) not in decisions
    assert AutomationDecision(action="select", course_id=1003) not in decisions


def test_decide_signs_only_autonomous_selected_courses():
    selected_by_user = {
        "test-user": [
            BoyaCourse(
                id=2001,
                name="自主签到课",
                sign_config={
                    "signStartDate": "2026-05-20 08:00:00",
                    "signEndDate": "2026-05-20 09:00:00",
                    "signOutStartDate": "2026-05-20 10:00:00",
                    "signOutEndDate": "2026-05-20 11:00:00",
                    "signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}],
                },
            ),
            BoyaCourse(
                id=2002,
                name="常规签到课",
                sign_config={
                    "signStartDate": "2026-05-20 08:00:00",
                    "signEndDate": "2026-05-20 09:00:00",
                    "signOutStartDate": "2026-05-20 10:00:00",
                    "signOutEndDate": "2026-05-20 11:00:00",
                },
            ),
        ]
    }

    decisions = decide_actions([], selected_by_user=selected_by_user, now=datetime(2026, 5, 20, 8, 30))

    assert decisions == [AutomationDecision(action="sign", course_id=2001, username="test-user")]


def test_execute_decisions_skips_users_who_already_selected(monkeypatch, tmp_path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.save_users(
        [
            {"username": "already-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True},
            {"username": "new-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True},
        ]
    )
    store.save_json("cache/selected.json", {"already-user": [{"id": 1001, "courseName": "已选"}], "new-user": []})
    selected_users = []

    def fake_select(self, user, course_id):
        selected_users.append(user.username)
        from autoboya.models import ActionResult

        return ActionResult(user.username, "select", course_id, True, "selected")

    monkeypatch.setattr(AutomationRunner, "_select_for_user", fake_select)

    AutomationRunner(store).execute_decisions([AutomationDecision(action="select", course_id=1001)])

    assert selected_users == ["new-user"]


def test_execute_decisions_filters_auto_select_by_user_campus(monkeypatch, tmp_path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.save_users(
        [
            {"username": "beijing-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True, "campus": "北京"},
            {"username": "hangzhou-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True, "campus": "杭州"},
        ]
    )
    store.save_json("cache/selected.json", {"beijing-user": [], "hangzhou-user": []})
    store.save_json(
        "cache/courses.json",
        [
            {"id": 1001, "courseName": "杭州课程", "coursePosition": "杭州校区体育馆", "courseCampusList": ["杭州校区"]},
            {"id": 1002, "courseName": "北京课程", "coursePosition": "学院路主楼", "courseCampusList": ["全部校区"]},
        ],
    )
    selected = []

    def fake_select(self, user, course_id):
        selected.append((user.username, course_id))
        from autoboya.models import ActionResult

        return ActionResult(user.username, "select", course_id, True, "selected")

    monkeypatch.setattr(AutomationRunner, "_select_for_user", fake_select)

    AutomationRunner(store).execute_decisions(
        [
            AutomationDecision(action="select", course_id=1001),
            AutomationDecision(action="select", course_id=1002),
        ]
    )

    assert selected == [("hangzhou-user", 1001), ("beijing-user", 1002)]


def test_heartbeat_logs_per_user_auto_check_count_only(caplog, tmp_path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.save_users(
        [
            {"username": "22375080", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True},
            {"username": "23371098", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True},
            {"username": "disabled", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": False},
        ]
    )

    runner = AutomationRunner(store)

    with caplog.at_level(logging.INFO, logger="autoboya.scheduler"):
        runner.log_heartbeat(
            [
                AutomationDecision(action="select", course_id=1001),
                AutomationDecision(action="sign", course_id=2001, username="22375080"),
                AutomationDecision(action="signout", course_id=2002, username="22375080"),
            ]
        )

    message = caplog.text
    assert "automation heartbeat user=223*** auto_boya_check=2" in message
    assert "automation heartbeat user=233*** auto_boya_check=0" in message
    assert "disabled" not in message
    assert "decisions=" not in message
    assert "next_refresh_seconds=" not in message


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


def test_select_success_refreshes_user_cache(monkeypatch, tmp_path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    store.save_users([{"username": "test-user", "password_ref": "unsafe-file", "unsafe_password": True, "enabled": True}])

    class FakeClient:
        def select_course(self, course_id):
            assert course_id == 1001
            return {"status": "0"}

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

        def query_chosen_courses(self, start_date, end_date):
            return [BoyaCourse(id=1001, name="刚选上的课")]

        def query_statistics(self):
            return {"validCount": 1}

    monkeypatch.setattr("autoboya.scheduler.ensure_bykc_client", lambda store, username, captcha_provider=None: FakeClient())
    result = AutomationRunner(store)._select_for_user(store.user_records()[0], 1001)

    assert result.ok
    assert store.load_json("cache/selected.json")["test-user"][0]["id"] == 1001
    assert store.load_json("cache/statistics.json")["test-user"]["validCount"] == 1


def test_sign_success_refreshes_user_cache(monkeypatch, tmp_path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()

    class FakeClient:
        def sign_course(self, course_id, lat, lng, sign_type):
            assert course_id == 1001
            return {"status": "0"}

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

        def query_chosen_courses(self, start_date, end_date):
            return [BoyaCourse(id=1001, name="已刷新")]

        def query_statistics(self):
            return {"validCount": 1}

    monkeypatch.setattr("autoboya.scheduler.ensure_bykc_client", lambda store, username, captcha_provider=None: FakeClient())
    course = BoyaCourse(id=1001, sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]})

    result = AutomationRunner(store)._sign_for_user("test-user", course, "sign")

    assert result.ok
    assert store.load_json("cache/selected.json")["test-user"][0]["id"] == 1001
