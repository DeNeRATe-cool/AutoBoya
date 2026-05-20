from __future__ import annotations

import math
import random
from datetime import datetime
from typing import Iterable

from .models import BoyaCourse


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def in_window(start: str | None, end: str | None, now: datetime) -> bool:
    parsed_start = parse_dt(start)
    parsed_end = parse_dt(end)
    return bool(parsed_start and parsed_end and parsed_start <= now <= parsed_end)


def is_selectable(course: BoyaCourse, now: datetime) -> bool:
    if course.selected:
        return False
    if not in_window(course.select_start, course.select_end, now):
        return False
    if course.current_count is not None and course.max_count is not None:
        if course.current_count >= course.max_count:
            return False
    return True


def has_autonomous_sign(course: BoyaCourse) -> bool:
    points = course.sign_config.get("signPointList") if isinstance(course.sign_config, dict) else None
    return isinstance(points, list) and len(points) > 0


def is_auto_select_candidate(course: BoyaCourse, now: datetime) -> bool:
    return is_selectable(course, now) and has_autonomous_sign(course) and course.category != "其他方面"


def auto_select_exclusion_reason(course: BoyaCourse, now: datetime) -> str | None:
    if course.selected:
        return "已选"
    if not has_autonomous_sign(course):
        return "常规签到或无位置配置"
    if course.category == "其他方面":
        return "其他方面不自动选课"
    if not in_window(course.select_start, course.select_end, now):
        return "不在选课时间"
    if course.current_count is not None and course.max_count is not None:
        if course.current_count >= course.max_count:
            return "容量已满"
    return None


def classify_selected_courses(courses: Iterable[BoyaCourse], now: datetime) -> dict[str, list[BoyaCourse]]:
    grouped = {"已开始上课": [], "未开始上课": [], "未知": []}
    for course in courses:
        start = parse_dt(course.course_start)
        if start is None:
            grouped["未知"].append(course)
        elif start <= now:
            grouped["已开始上课"].append(course)
        else:
            grouped["未开始上课"].append(course)
    return grouped


def sign_window_for(course: BoyaCourse, sign_type: int, now: datetime) -> bool:
    cfg = course.sign_config or {}
    if sign_type == 1:
        return in_window(cfg.get("signStartDate"), cfg.get("signEndDate"), now)
    if sign_type == 2:
        return in_window(cfg.get("signOutStartDate"), cfg.get("signOutEndDate"), now)
    return False


def random_point_in_radius(lat: float, lng: float, radius_m: float, seed: int | None = None) -> tuple[float, float]:
    rng = random.Random(seed)
    distance = radius_m * math.sqrt(rng.random()) * 0.65
    theta = rng.random() * 2 * math.pi
    dlat = (distance * math.sin(theta)) / 111_320
    dlng = (distance * math.cos(theta)) / (111_320 * max(0.2, math.cos(math.radians(lat))))
    return lat + dlat, lng + dlng
