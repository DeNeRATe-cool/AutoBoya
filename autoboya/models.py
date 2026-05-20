from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class UserRecord:
    username: str
    password_ref: str | None = None
    unsafe_password: bool = False
    enabled: bool = True


@dataclass
class BoyaCourse:
    id: int
    name: str = ""
    location: str = ""
    category: str = ""
    selected: bool = False
    course_start: str | None = None
    course_end: str | None = None
    select_start: str | None = None
    select_end: str | None = None
    cancel_end: str | None = None
    current_count: int | None = None
    max_count: int | None = None
    campus: Any = None
    sign_config: dict[str, Any] = field(default_factory=dict)
    sign_type: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def sign_method(self) -> str:
        points = self.sign_config.get("signPointList") if isinstance(self.sign_config, dict) else None
        return "自主签到" if isinstance(points, list) and points else "常规签到或无位置配置"


@dataclass(frozen=True)
class AutomationDecision:
    action: Literal["select", "sign", "signout"]
    course_id: int
    username: str | None = None


@dataclass
class AutoPreview:
    candidates: list[BoyaCourse]
    excluded: dict[int, str]
    generated_at: datetime


@dataclass
class ActionResult:
    username: str
    action: str
    course_id: int
    ok: bool
    message: str
