from __future__ import annotations

import os
import random
import time
from datetime import datetime
from typing import Iterable

from .bykc import BykcClient
from .cache import CourseCache
from .config import ACTION_JOURNAL_FILE, RUN_PID_FILE, STOP_FILE
from .models import ActionResult, AutomationDecision, BoyaCourse, UserRecord
from .rules import is_auto_select_candidate, random_point_in_radius, sign_window_for
from .storage import AutoBoyaStore


def decide_actions(
    courses: Iterable[BoyaCourse],
    selected_by_user: dict[str, list[BoyaCourse]],
    now: datetime | None = None,
) -> list[AutomationDecision]:
    now = now or datetime.now()
    decisions: list[AutomationDecision] = []
    decisions.extend(
        AutomationDecision(action="select", course_id=course.id)
        for course in courses
        if is_auto_select_candidate(course, now)
    )
    for username, selected_courses in selected_by_user.items():
        for course in selected_courses:
            if sign_window_for(course, 1, now):
                decisions.append(AutomationDecision(action="sign", course_id=course.id, username=username))
            if sign_window_for(course, 2, now):
                decisions.append(AutomationDecision(action="signout", course_id=course.id, username=username))
    return decisions


class AutomationRunner:
    def __init__(self, store: AutoBoyaStore) -> None:
        self.store = store
        self.cache = CourseCache(store)

    def run_forever(self) -> None:
        self.store.init()
        self.store.path(RUN_PID_FILE).write_text(str(os.getpid()), encoding="utf-8")
        stop = self.store.path(STOP_FILE)
        if stop.exists():
            stop.unlink()
        last_refresh = 0.0
        try:
            while not stop.exists():
                now = time.time()
                if now - last_refresh >= 3600:
                    self.refresh_once()
                    last_refresh = now
                self.execute_decisions(self.scan_once())
                time.sleep(60)
        finally:
            pid = self.store.path(RUN_PID_FILE)
            if pid.exists():
                pid.unlink()

    def request_stop(self) -> None:
        self.store.init()
        self.store.path(STOP_FILE).write_text(datetime.now().isoformat(), encoding="utf-8")

    def refresh_once(self) -> None:
        users = [user for user in self.store.user_records() if user.enabled]
        if not users:
            return
        pool_user = random.choice(users)
        pool_client = self.bykc_client_for(pool_user.username)
        config = pool_client.get_all_config()
        self.cache.save_courses(pool_client.query_courses())
        start, end = current_semester_window(config)
        for user in users:
            client = self.bykc_client_for(user.username)
            self.cache.save_selected(user.username, client.query_chosen_courses(start, end))
            self.cache.save_statistics(user.username, client.query_statistics())

    def scan_once(self) -> list[AutomationDecision]:
        courses = self.cache.parsed_courses()
        return decide_actions(courses, self._selected_by_user(self.cache.load_selected()), datetime.now())

    def run_once(self) -> list[ActionResult]:
        self.refresh_once()
        return self.execute_decisions(self.scan_once())

    def execute_decisions(self, decisions: list[AutomationDecision]) -> list[ActionResult]:
        results: list[ActionResult] = []
        selected_raw = self.cache.load_selected()
        selected_by_user = self._selected_by_user(selected_raw)
        journal = self.store.load_json(ACTION_JOURNAL_FILE, {})
        users = [user for user in self.store.user_records() if user.enabled]
        for decision in decisions:
            if decision.action == "select":
                for user in users:
                    key = journal_key(user.username, "select", decision.course_id)
                    if journal.get(key):
                        continue
                    result = self._select_for_user(user, decision.course_id)
                    results.append(result)
                    if result.ok:
                        journal[key] = result.message
                continue
            username = decision.username
            if not username:
                continue
            key = journal_key(username, decision.action, decision.course_id)
            if journal.get(key):
                continue
            course = next((item for item in selected_by_user.get(username, []) if item.id == decision.course_id), None)
            result = self._sign_for_user(username, course, decision.action)
            results.append(result)
            if result.ok:
                journal[key] = result.message
        self.store.save_json(ACTION_JOURNAL_FILE, journal)
        return results

    def _select_for_user(self, user: UserRecord, course_id: int) -> ActionResult:
        try:
            self.bykc_client_for(user.username).select_course(course_id)
            return ActionResult(user.username, "select", course_id, True, "selected")
        except Exception as exc:
            return ActionResult(user.username, "select", course_id, False, str(exc))

    def _sign_for_user(self, username: str, course: BoyaCourse | None, action: str) -> ActionResult:
        if not course or not course.sign_config.get("signPointList"):
            return ActionResult(username, action, course.id if course else 0, False, "missing sign point")
        point = course.sign_config["signPointList"][-1]
        lat, lng = random_point_in_radius(float(point["lat"]), float(point["lng"]), float(point.get("radius") or 8))
        sign_type = 1 if action == "sign" else 2
        try:
            self.bykc_client_for(username).sign_course(course.id, lat, lng, sign_type)
            return ActionResult(username, action, course.id, True, "signed")
        except Exception as exc:
            return ActionResult(username, action, course.id, False, str(exc))

    def _selected_by_user(self, selected_raw: object) -> dict[str, list[BoyaCourse]]:
        if not isinstance(selected_raw, dict):
            return {}
        from .bykc import parse_course

        return {
            username: [parse_course(item) for item in items]
            for username, items in selected_raw.items()
            if isinstance(items, list)
        }

    def token_for(self, username: str) -> str:
        session = self.store.load_json(f"sessions/{username}.json", {})
        token = session.get("bykc_token") if isinstance(session, dict) else None
        if not token:
            raise RuntimeError(f"No Boya token for {username}")
        return token

    def bykc_client_for(self, username: str) -> BykcClient:
        session = self.store.load_json(f"sessions/{username}.json", {})
        token = session.get("bykc_token") if isinstance(session, dict) else None
        cookies = session.get("cookies") if isinstance(session, dict) else None
        if not token:
            raise RuntimeError(f"No Boya token for {username}")
        if not isinstance(cookies, list):
            raise RuntimeError(f"Stored session for {username} has no WebVPN cookies; run autoboya login again")
        return BykcClient(str(token), cookies=cookies)


def journal_key(username: str, action: str, course_id: int, when: datetime | None = None) -> str:
    when = when or datetime.now()
    return f"{when.date()}:{username}:{action}:{course_id}"


def current_semester_window(config: dict[str, object]) -> tuple[str, str]:
    semesters = (((config.get("data") or {}).get("semester") or []) if isinstance(config, dict) else [])
    first = semesters[0] if semesters else {}
    return (
        first.get("semesterStartDate") or "2026-03-01 00:00:00",
        first.get("semesterEndDate") or "2026-06-21 00:00:00",
    )
