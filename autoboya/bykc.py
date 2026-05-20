from __future__ import annotations

import json
from typing import Any

import httpx

from .crypto import BykcCrypto
from .exceptions import BoyaApiError, SessionExpired, map_boya_error
from .models import BoyaCourse
from .webvpn import to_webvpn_url

BYKC_BASE = "https://bykc.buaa.edu.cn/sscv"
BYKC_REFERER = "https://bykc.buaa.edu.cn/system/course-select"
BYKC_ORIGIN = "https://bykc.buaa.edu.cn"


class BykcClient:
    def __init__(
        self,
        token: str,
        http_client: httpx.Client | None = None,
        use_vpn: bool = True,
        cookies: list[dict[str, Any]] | None = None,
    ) -> None:
        self.token = token
        self.client = http_client or httpx.Client(timeout=25, follow_redirects=True)
        self.use_vpn = use_vpn
        if cookies:
            restore_cookies(self.client, cookies)

    def endpoint(self, api: str) -> str:
        url = f"{BYKC_BASE}/{api}"
        return to_webvpn_url(url) if self.use_vpn else url

    def upstream(self, url: str) -> str:
        return to_webvpn_url(url) if self.use_vpn else url

    def call(self, api: str, payload: dict[str, Any] | str | None = None) -> dict[str, Any]:
        crypto = BykcCrypto()
        request = crypto.encrypt_request(payload or {})
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": self.upstream(BYKC_REFERER),
            "Origin": self.upstream(BYKC_ORIGIN),
            "Authtoken": self.token,
            "auth_token": self.token,
            "authtoken": self.token,
            **request.headers,
        }
        response = self.client.post(self.endpoint(api), content=request.body, headers=headers)
        response.raise_for_status()
        try:
            decoded = crypto.decrypt_response(response.content)
        except Exception as exc:
            text = response.text[:240].replace("\n", " ")
            if looks_like_login_page(response.text):
                raise SessionExpired("WebVPN session missing or expired; run `autoboya login <user>` again") from exc
            raise BoyaApiError("decode_error", f"Unable to decrypt BYKC response: {text}") from exc
        status = decoded.get("status") if isinstance(decoded, dict) else None
        errmsg = decoded.get("errmsg") or decoded.get("msg") if isinstance(decoded, dict) else ""
        if status not in ("0", 0, "200", 200, None):
            error = map_boya_error(str(errmsg), status)
            raise error
        return decoded

    def get_all_config(self) -> dict[str, Any]:
        return self.call("getAllConfig", {})

    def query_course_page(self, page_number: int = 1, page_size: int = 100) -> dict[str, Any]:
        return self.call("queryStudentSemesterCourseByPage", {"pageNumber": page_number, "pageSize": page_size})

    def query_courses(self, page_number: int = 1, page_size: int = 100) -> list[BoyaCourse]:
        courses: list[BoyaCourse] = []
        current_page = page_number
        while True:
            data = self.query_course_page(current_page, page_size)
            page_data = (data.get("data") or {}) if isinstance(data, dict) else {}
            content = page_data.get("content") or []
            courses.extend(parse_course(item) for item in content)
            total_pages = parse_int(page_data.get("totalPages"))
            if page_data.get("last") is True:
                break
            if total_pages is not None and current_page >= total_pages:
                break
            if not content:
                break
            current_page += 1
        return courses

    def query_course_detail(self, course_id: int) -> BoyaCourse:
        data = self.call("queryCourseById", {"id": course_id})
        return parse_course((data.get("data") or {}) if isinstance(data, dict) else {})

    def query_chosen_courses(self, start_date: str, end_date: str) -> list[BoyaCourse]:
        data = self.call("queryChosenCourse", {"startDate": start_date, "endDate": end_date})
        items = (((data.get("data") or {}).get("courseList") or []) if isinstance(data, dict) else [])
        return [parse_course(item.get("courseInfo") or item) for item in items]

    def query_statistics(self) -> dict[str, Any]:
        data = self.call("queryStatisticByUserId", {})
        return (data.get("data") or {}) if isinstance(data, dict) else {}

    def select_course(self, course_id: int) -> dict[str, Any]:
        return self.call("choseCourse", {"courseId": course_id})

    def drop_course(self, chosen_or_course_id: int) -> dict[str, Any]:
        return self.call("delChosenCourse", {"id": chosen_or_course_id})

    def sign_course(self, course_id: int, lat: float, lng: float, sign_type: int) -> dict[str, Any]:
        return self.call(
            "signCourseByUser",
            {"courseId": course_id, "signLat": lat, "signLng": lng, "signType": sign_type},
        )


def parse_course(raw: dict[str, Any]) -> BoyaCourse:
    sign_config = parse_sign_config(raw.get("courseSignConfig"))
    return BoyaCourse(
        id=int(raw.get("id") or 0),
        name=raw.get("courseName") or raw.get("name") or "",
        location=raw.get("coursePosition") or "",
        category=parse_category(raw),
        selected=bool(raw.get("selected", raw.get("isSelected", False))),
        course_start=raw.get("courseStartDate"),
        course_end=raw.get("courseEndDate"),
        select_start=raw.get("courseSelectStartDate"),
        select_end=raw.get("courseSelectEndDate"),
        cancel_end=raw.get("courseCancelEndDate"),
        current_count=parse_int(raw.get("courseCurrentCount")),
        max_count=parse_int(raw.get("courseMaxCount")),
        campus=raw.get("courseCampusList"),
        sign_config=sign_config,
        sign_type=parse_int(raw.get("courseSignType")),
        raw=raw,
    )


def parse_category(raw: dict[str, Any]) -> str:
    kind = raw.get("courseNewKind2")
    if isinstance(kind, dict):
        return kind.get("kindName") or ""
    return raw.get("courseKind") or raw.get("kindName") or ""


def parse_sign_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    text = raw.replace('\\"', '"')
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def parse_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def restore_cookies(client: httpx.Client, cookies: list[dict[str, Any]]) -> None:
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        client.cookies.set(
            name,
            value,
            domain=cookie.get("domain") if isinstance(cookie.get("domain"), str) else None,
            path=cookie.get("path") if isinstance(cookie.get("path"), str) else "/",
        )


def looks_like_login_page(text: str) -> bool:
    head = text[:1000].lower()
    return "<html" in head and ("cas login" in head or "loginform" in head or "sso.buaa.edu.cn" in head)
