from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AutoBoyaError(Exception):
    """Base exception for AutoBoya."""


class LoginError(AutoBoyaError):
    pass


class SessionExpired(AutoBoyaError):
    pass


class CourseFull(AutoBoyaError):
    pass


class CourseNotOpen(AutoBoyaError):
    pass


class SelectionLimitReached(AutoBoyaError):
    pass


class AlreadySelected(AutoBoyaError):
    pass


class SignWindowClosed(AutoBoyaError):
    pass


class MissingSignPoint(AutoBoyaError):
    pass


@dataclass
class BoyaApiError(AutoBoyaError):
    status: Any
    errmsg: str

    def __str__(self) -> str:
        return f"Boya API error status={self.status!r}: {self.errmsg}"


class CaptchaRequired(LoginError):
    def __init__(self, challenge: Any, message: str = "需要验证码验证") -> None:
        super().__init__(message)
        self.challenge = challenge


def map_boya_error(errmsg: str, status: str | int | None = None) -> AutoBoyaError:
    text = errmsg or ""
    if status == "98005399" or "会话已失效" in text or "重新登录" in text:
        return SessionExpired(text)
    if "容量已满" in text or "人数已满" in text or "名额已满" in text:
        return CourseFull(text)
    if "未到选课时间" in text or "不在选课时间" in text:
        return CourseNotOpen(text)
    if "选课上限" in text or "达到上限" in text:
        return SelectionLimitReached(text)
    if "已选" in text or "重复选择" in text:
        return AlreadySelected(text)
    if "签到时间" in text or "签退时间" in text:
        return SignWindowClosed(text)
    return BoyaApiError(status, text)
