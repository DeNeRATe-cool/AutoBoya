from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from .bykc import parse_course
from .config import COURSE_CACHE_FILE, SELECTED_CACHE_FILE, STATISTICS_CACHE_FILE
from .models import AutoPreview, BoyaCourse
from .rules import auto_select_exclusion_reason
from .storage import AutoBoyaStore


class CourseCache:
    def __init__(self, store: AutoBoyaStore) -> None:
        self.store = store

    def save_courses(self, courses: list[dict[str, Any] | BoyaCourse]) -> None:
        self.store.save_json(COURSE_CACHE_FILE, [serialize_course(item) for item in courses])

    def load_courses(self) -> list[dict[str, Any]]:
        return list(self.store.load_json(COURSE_CACHE_FILE, []))

    def parsed_courses(self) -> list[BoyaCourse]:
        return [parse_course(item) for item in self.load_courses()]

    def save_selected(self, username: str, courses: list[dict[str, Any] | BoyaCourse]) -> None:
        selected = self.store.load_json(SELECTED_CACHE_FILE, {})
        selected[username] = [serialize_course(item) for item in courses]
        self.store.save_json(SELECTED_CACHE_FILE, selected)

    def load_selected(self, username: str | None = None) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
        selected = self.store.load_json(SELECTED_CACHE_FILE, {})
        return selected.get(username, []) if username else selected

    def save_statistics(self, username: str, statistics: dict[str, Any]) -> None:
        all_stats = self.store.load_json(STATISTICS_CACHE_FILE, {})
        all_stats[username] = statistics
        self.store.save_json(STATISTICS_CACHE_FILE, all_stats)

    def load_statistics(self, username: str | None = None) -> dict[str, Any]:
        stats = self.store.load_json(STATISTICS_CACHE_FILE, {})
        return stats.get(username, {}) if username else stats


def serialize_course(item: dict[str, Any] | BoyaCourse) -> dict[str, Any]:
    if isinstance(item, BoyaCourse):
        return item.raw or {
            "id": item.id,
            "courseName": item.name,
            "coursePosition": item.location,
            "selected": item.selected,
            "courseStartDate": item.course_start,
            "courseEndDate": item.course_end,
            "courseSelectStartDate": item.select_start,
            "courseSelectEndDate": item.select_end,
            "courseCurrentCount": item.current_count,
            "courseMaxCount": item.max_count,
            "courseSignConfig": item.sign_config,
        }
    return item


def preview_auto_select_courses(raw_courses: list[dict[str, Any]], now: datetime | None = None) -> AutoPreview:
    now = now or datetime.now()
    candidates: list[BoyaCourse] = []
    excluded: dict[int, str] = {}
    for raw in raw_courses:
        course = parse_course(raw)
        reason = auto_select_exclusion_reason(course, now, ignore_selected=True)
        if reason is None:
            candidates.append(course)
        else:
            excluded[course.id] = reason
    return AutoPreview(candidates=candidates, excluded=excluded, generated_at=now)
