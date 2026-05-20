#!/usr/bin/env python3
"""Live Boya/BYKC probe aligned with /Users/denerate/project/UBAA.

The script reads the BUAA test account from
/Users/denerate/ELSE/BUAA-test-account.txt. It never prints credentials, cookies,
or real Boya tokens.

Default behavior is safe:
- WebVPN login preflight and optional captcha-assisted login.
- Read-only BYKC calls after login if possible.
- Invalid-token probes for write endpoints to verify request shape without
  mutating the account.

Set AUTOBOYA_ALLOW_WRITE=1 to attempt real select/drop/sign requests. Real writes
are intentionally conservative and will only target a newly selected course for
drop, never an existing selected course.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import html.parser
import json
import math
import os
import random
import re
import secrets
import ssl
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


ACCOUNT_FILE = Path("/Users/denerate/ELSE/BUAA-test-account.txt")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)

WEBVPN_GATEWAY = "https://d.buaa.edu.cn"
WEBVPN_KEY = b"wrdvpnisthebest!"

SSO_LOGIN = "https://sso.buaa.edu.cn/login"
SSO_CAPTCHA = "https://sso.buaa.edu.cn/captcha"
UC_ACTIVATE = (
    "https://uc.buaa.edu.cn/api/login?"
    "target=https%3A%2F%2Fuc.buaa.edu.cn%2F%23%2Fuser%2Flogin"
)
UC_STATUS = "https://uc.buaa.edu.cn/api/user/info"
BYKC_BASE = "https://bykc.buaa.edu.cn/sscv"
BYKC_CAS = "https://bykc.buaa.edu.cn/sscv/cas/login"
BYKC_CAS_EMPTY_TOKEN = "https://bykc.buaa.edu.cn/cas-login?token="
BYKC_REFERER = "https://bykc.buaa.edu.cn/system/course-select"
BYKC_ORIGIN = "https://bykc.buaa.edu.cn"

BYKC_RSA_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDlHMQ3B5GsWnCe7Nlo1YiG/YmH
dlOiKOST5aRm4iaqYSvhvWmwcigoyWTM+8bv2+sf6nQBRDWTY4KmNV7DBk1eDnTI
Qo6ENA31k5/tYCLEXgjPbEjCK9spiyB62fCT6cqOhbamJB0lcDJRO6Vo1m3dy+fD
0jbxfDVBBNtyltIsDQIDAQAB
-----END PUBLIC KEY-----
"""


class FormParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: (v or "") for k, v in attrs}
        if tag.lower() == "form":
            self.current = {"attrs": attrs_dict, "inputs": []}
            self.forms.append(self.current)
        elif tag.lower() == "input" and self.current is not None:
            self.current["inputs"].append(attrs_dict)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self.current = None


@dataclasses.dataclass
class HttpResult:
    status: int
    url: str
    headers: dict[str, str]
    body: bytes


class BoyaProbe:
    def __init__(self, use_vpn: bool = True) -> None:
        lines = [line.strip() for line in ACCOUNT_FILE.read_text(encoding="utf-8").splitlines()]
        self.username = lines[0]
        self.password = lines[1]
        self.use_vpn = use_vpn
        self.ctx = ssl.create_default_context()
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=self.ctx),
        )
        self.bykc_token: str | None = None
        self.results: dict[str, Any] = {
            "account": self.username[:3] + "***",
            "mode": "WEBVPN" if use_vpn else "DIRECT",
            "allow_write": os.getenv("AUTOBOYA_ALLOW_WRITE") == "1",
            "checks": {},
        }

    def upstream(self, url: str) -> str:
        return to_webvpn_url(url) if self.use_vpn else url

    def request(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        method: str | None = None,
        timeout: int = 25,
    ) -> HttpResult:
        merged = {"User-Agent": UA}
        if headers:
            merged.update(headers)
        req = urllib.request.Request(url, data=data, headers=merged, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return HttpResult(resp.status, resp.url, dict(resp.headers), resp.read())
        except urllib.error.HTTPError as exc:
            return HttpResult(exc.code, exc.url, dict(exc.headers), exc.read())

    def login_page(self) -> tuple[str, dict[str, Any]]:
        url = self.upstream(SSO_LOGIN)
        res = self.request(url)
        text = res.body.decode("utf-8", "ignore")
        parser = FormParser()
        parser.feed(text)
        form = parser.forms[0] if parser.forms else {"attrs": {}, "inputs": []}
        inputs = form["inputs"]
        captcha_match = re.search(
            r"config\.captcha\s*=\s*\{\s*type:\s*['\"]([^'\"]+)['\"],\s*id:\s*['\"]([^'\"]+)['\"]",
            text,
        )
        execution = next((i.get("value", "") for i in inputs if i.get("name") == "execution"), "")
        info = {
            "http_status": res.status,
            "final_url_host": urllib.parse.urlparse(res.url).netloc,
            "form_id": form["attrs"].get("id"),
            "input_names": [i.get("name") for i in inputs if i.get("name")],
            "execution_present": bool(execution),
            "execution_len": len(execution),
            "captcha_required": captcha_match is not None,
            "captcha_id": captcha_match.group(2) if captcha_match else None,
            "locked_marker": "Access Denied" in text or "Locked" in text,
        }
        self.results["checks"]["sso_login_page"] = info
        return text, info

    def fetch_captcha(self, captcha_id: str) -> Path:
        url = self.upstream(f"{SSO_CAPTCHA}?captchaId={urllib.parse.quote(captcha_id)}")
        res = self.request(url)
        suffix = ".jpg"
        content_type = res.headers.get("Content-Type", "")
        if "png" in content_type:
            suffix = ".png"
        path = Path(tempfile.gettempdir()) / f"autoboya_captcha_{os.getpid()}{suffix}"
        path.write_bytes(res.body)
        self.results["checks"]["captcha_fetch"] = {
            "http_status": res.status,
            "content_type": content_type,
            "bytes": len(res.body),
            "path": str(path),
        }
        return path

    def submit_login(self, login_html: str, captcha: str | None = None) -> None:
        params = build_cas_login_params(login_html, self.username, self.password, captcha)
        if not params.get("execution"):
            self.results["checks"]["sso_submit"] = {"ok": False, "reason": "no_execution"}
            return
        res = self.request(
            self.upstream(SSO_LOGIN),
            data=urllib.parse.urlencode(params).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        final = self.follow_redirects_and_password_expiry(res)
        body = final.body.decode("utf-8", "ignore")
        err = find_login_error(body)
        self.results["checks"]["sso_submit"] = {
            "http_status": final.status,
            "final_url_host": urllib.parse.urlparse(final.url).netloc,
            "ok": final.status < 400 and not err and "Access Denied" not in body,
            "error": err or extract_access_denied(body),
            "body_head": body[:120].replace("\n", " "),
        }

    def follow_redirects_and_password_expiry(self, res: HttpResult) -> HttpResult:
        current = res
        ignored = False
        while True:
            while 300 <= current.status <= 399 and current.headers.get("Location"):
                current = self.request(resolve_url(current.url, current.headers["Location"]))
            body = current.body.decode("utf-8", "ignore")
            if ("continueForm" in body or "ignoreAndContinue" in body) and not ignored:
                execution = extract_execution(body)
                ignore_url = current.url.split("?", 1)[0]
                current = self.request(
                    ignore_url,
                    data=urllib.parse.urlencode(
                        {"execution": execution, "_eventId": "ignoreAndContinue"}
                    ).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                ignored = True
                continue
            return current

    def activate_uc(self) -> None:
        res = self.request(self.upstream(UC_ACTIVATE))
        status = self.request(
            self.upstream(UC_STATUS),
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        text = status.body.decode("utf-8", "ignore")
        ok = text.lstrip().startswith("{")
        self.results["checks"]["uc_session"] = {
            "activate_http_status": res.status,
            "status_http_status": status.status,
            "json_like": ok,
            "body_head": text[:160].replace("\n", " "),
        }

    def bykc_login(self) -> None:
        res = self.request(self.upstream(BYKC_CAS))
        url = res.url
        location = res.headers.get("Location", "")
        token = extract_token(url) or extract_token(location)
        if not token:
            # UBAA has a defensive empty-token fallback. It does not itself
            # produce a token, but it is useful evidence when login is partial.
            fallback = self.request(self.upstream(BYKC_CAS_EMPTY_TOKEN))
            self.results["checks"]["bykc_login"] = {
                "http_status": res.status,
                "final_url_host": urllib.parse.urlparse(url).netloc,
                "token_present": False,
                "fallback_status": fallback.status,
                "fallback_host": urllib.parse.urlparse(fallback.url).netloc,
            }
            return
        self.bykc_token = token
        self.results["checks"]["bykc_login"] = {
            "http_status": res.status,
            "final_url_host": urllib.parse.urlparse(url).netloc,
            "token_present": True,
            "token_len": len(token),
        }

    def bykc_call(
        self,
        api: str,
        payload: dict[str, Any],
        token: str | None = None,
        force_direct: bool = False,
    ) -> dict[str, Any]:
        token = self.bykc_token if token is None else token
        upstream = (lambda url: url) if force_direct else self.upstream
        plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        aes_key = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16)).encode()
        ak = rsa_encrypt(aes_key)
        sk = rsa_encrypt(hashlib.sha1(plain).hexdigest().encode())
        body = json.dumps(base64.b64encode(openssl_aes_ecb(plain, aes_key)).decode()).encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": upstream(BYKC_REFERER),
            "Origin": upstream(BYKC_ORIGIN),
            "Ak": ak,
            "Sk": sk,
            "Ts": str(int(time.time() * 1000)),
        }
        if token:
            headers["Authtoken"] = token
            headers["auth_token"] = token
            headers["authtoken"] = token
        res = self.request(upstream(f"{BYKC_BASE}/{api}"), data=body, headers=headers, method="POST")
        text = res.body.decode("utf-8", "ignore").strip()
        decoded: Any
        try:
            resp_b64 = json.loads(text)
            decoded = json.loads(openssl_aes_ecb(base64.b64decode(resp_b64), aes_key, decrypt=True).decode())
        except Exception:
            try:
                decoded = json.loads(text)
            except Exception:
                decoded = {"raw_head": text[:240]}
        return {
            "http_status": res.status,
            "final_url_host": urllib.parse.urlparse(res.url).netloc,
            "connection_mode": "DIRECT" if force_direct else ("WEBVPN" if self.use_vpn else "DIRECT"),
            "decoded": decoded,
        }

    def safe_endpoint_probes(self) -> None:
        cases = {
            "getAllConfig": {},
            "queryStudentSemesterCourseByPage": {"pageNumber": 1, "pageSize": 20},
            "queryCourseById": {"id": 1},
            "queryChosenCourse": {"startDate": "2026-03-01 00:00:00", "endDate": "2026-06-21 00:00:00"},
            "queryStatisticByUserId": {},
            "choseCourse": {"courseId": 1},
            "delChosenCourse": {"id": 1},
            "signCourseByUser_checkin": {
                "api": "signCourseByUser",
                "payload": {"courseId": 1, "signLat": 39.981, "signLng": 116.344, "signType": 1},
            },
            "signCourseByUser_checkout": {
                "api": "signCourseByUser",
                "payload": {"courseId": 1, "signLat": 39.981, "signLng": 116.344, "signType": 2},
            },
        }
        out = {}
        for name, payload in cases.items():
            api = name
            if isinstance(payload, dict) and "api" in payload:
                api = payload["api"]
                payload = payload["payload"]
            result = self.bykc_call(
                api,
                payload,
                token="invalid-token-for-shape-probe",
                force_direct=True,
            )
            decoded = result["decoded"]
            out[name] = {
                "http_status": result["http_status"],
                "connection_mode": result["connection_mode"],
                "decoded_status": decoded.get("status") if isinstance(decoded, dict) else None,
                "errmsg": decoded.get("errmsg") if isinstance(decoded, dict) else None,
                "keys": list(decoded.keys())[:8] if isinstance(decoded, dict) else type(decoded).__name__,
            }
        self.results["checks"]["invalid_token_endpoint_probes"] = out

    def read_tests(self) -> dict[str, Any]:
        if not self.bykc_token:
            self.results["checks"]["read_tests"] = {"ok": False, "reason": "no_bykc_token"}
            return {}
        config = self.bykc_call("getAllConfig", {})
        course_page = self.bykc_call("queryStudentSemesterCourseByPage", {"pageNumber": 1, "pageSize": 50})
        cfg = config["decoded"]
        page = course_page["decoded"]
        semesters = ((cfg.get("data") or {}).get("semester") or []) if isinstance(cfg, dict) else []
        semester = semesters[0] if semesters else {}
        start = semester.get("semesterStartDate") or "2026-03-01 00:00:00"
        end = semester.get("semesterEndDate") or "2026-06-21 00:00:00"
        selected = self.bykc_call("queryChosenCourse", {"startDate": start, "endDate": end})
        statistic = self.bykc_call("queryStatisticByUserId", {})
        courses = (((page.get("data") or {}).get("content") or []) if isinstance(page, dict) else [])
        detail = None
        if courses:
            detail = self.bykc_call("queryCourseById", {"id": courses[0].get("id")})

        now = datetime.now()
        selected_courses = []
        selected_decoded = selected["decoded"]
        for item in (((selected_decoded.get("data") or {}).get("courseList") or []) if isinstance(selected_decoded, dict) else []):
            info = item.get("courseInfo") or item
            selected_courses.append(info)

        grouped = {"已开始上课": 0, "未开始上课": 0, "未知": 0}
        for course in selected_courses:
            dt = parse_dt(course.get("courseStartDate"))
            if dt is None:
                grouped["未知"] += 1
            elif dt <= now:
                grouped["已开始上课"] += 1
            else:
                grouped["未开始上课"] += 1

        summary = {
            "ok": all(
                isinstance(x.get("decoded"), dict) and x["decoded"].get("status") in ("0", 0, "200", 200, None)
                for x in [config, course_page, selected, statistic]
            ),
            "semester": {"start": start, "end": end},
            "courses_page_count": len(courses),
            "course_sample": [summarize_course(c) for c in courses[:5]],
            "first_course_detail": summarize_course(((detail or {}).get("decoded") or {}).get("data") if detail else {}),
            "selected_count": len(selected_courses),
            "selected_grouped": grouped,
            "selected_sample": [summarize_course(c) for c in selected_courses[:5]],
            "statistics_keys": list((((statistic["decoded"].get("data") or {}).get("statistical") or {}).get("60|博雅课程") or {}).keys())
            if isinstance(statistic["decoded"], dict)
            else [],
        }
        self.results["checks"]["read_tests"] = summary
        return {"courses": courses, "selected_courses": selected_courses, "semester": semester}

    def guarded_write_tests(self, read_state: dict[str, Any]) -> None:
        if os.getenv("AUTOBOYA_ALLOW_WRITE") != "1":
            self.results["checks"]["write_tests"] = {
                "ok": True,
                "mode": "guarded",
                "note": "Real write operations skipped; invalid-token probes verified request shape.",
            }
            return
        if not self.bykc_token:
            self.results["checks"]["write_tests"] = {"ok": False, "reason": "no_bykc_token"}
            return

        now = datetime.now()
        courses = read_state.get("courses") or []
        chosen_for_select = None
        for course in courses:
            if course.get("selected") is True:
                continue
            if not within_window(course.get("courseSelectStartDate"), course.get("courseSelectEndDate"), now):
                continue
            if int(course.get("courseCurrentCount") or 0) >= int(course.get("courseMaxCount") or 0):
                continue
            chosen_for_select = course
            break

        write: dict[str, Any] = {}
        if chosen_for_select:
            cid = chosen_for_select.get("id")
            select_result = self.bykc_call("choseCourse", {"courseId": cid})
            write["select"] = response_brief(select_result["decoded"])
            # Re-query and only drop the newly selected course id if visible.
            semester = read_state.get("semester") or {}
            start = semester.get("semesterStartDate") or "2026-03-01 00:00:00"
            end = semester.get("semesterEndDate") or "2026-06-21 00:00:00"
            chosen = self.bykc_call("queryChosenCourse", {"startDate": start, "endDate": end})
            selected_items = (((chosen["decoded"].get("data") or {}).get("courseList") or []) if isinstance(chosen["decoded"], dict) else [])
            new_item = next((it for it in selected_items if (it.get("courseInfo") or {}).get("id") == cid), None)
            if new_item:
                drop_id = new_item.get("id") or (new_item.get("courseInfo") or {}).get("id")
                drop_result = self.bykc_call("delChosenCourse", {"id": drop_id})
                write["drop_newly_selected"] = response_brief(drop_result["decoded"])
            else:
                write["drop_newly_selected"] = {"ok": False, "reason": "new_selected_course_not_found"}
        else:
            write["select_drop"] = {"ok": False, "reason": "no_safe_selectable_course_in_page"}

        selected_courses = read_state.get("selected_courses") or []
        sign_course = None
        for course in selected_courses:
            sign_config = parse_sign_config(course.get("courseSignConfig"))
            if sign_config and sign_config.get("signPointList"):
                sign_course = (course, sign_config)
                break
        if sign_course:
            course, config = sign_course
            point = config["signPointList"][-1]
            lat, lng = random_point(point["lat"], point["lng"], float(point.get("radius") or 8))
            cid = course.get("id")
            write["checkin"] = response_brief(
                self.bykc_call("signCourseByUser", {"courseId": cid, "signLat": lat, "signLng": lng, "signType": 1})["decoded"]
            )
            write["checkout"] = response_brief(
                self.bykc_call("signCourseByUser", {"courseId": cid, "signLat": lat, "signLng": lng, "signType": 2})["decoded"]
            )
        else:
            write["checkin_checkout"] = {"ok": False, "reason": "no_selected_course_with_sign_points"}

        self.results["checks"]["write_tests"] = write

    def run(self) -> None:
        if os.getenv("AUTOBOYA_SKIP_LOGIN") == "1":
            self.results["checks"]["sso_login_page"] = {
                "skipped": True,
                "reason": "AUTOBOYA_SKIP_LOGIN=1",
            }
        else:
            login_html, login_info = self.login_page()
            captcha = os.getenv("AUTOBOYA_CAPTCHA")
            if login_info.get("captcha_required") and not captcha:
                path = self.fetch_captcha(login_info["captcha_id"])
                print(f"CAPTCHA_IMAGE={path}", flush=True)
                print("CAPTCHA_CODE?", flush=True)
                captcha = sys.stdin.readline().strip()
            if captcha or not login_info.get("captcha_required"):
                self.submit_login(login_html, captcha=captcha or None)
                self.activate_uc()
                self.bykc_login()
            else:
                self.results["checks"]["sso_submit"] = {"ok": False, "reason": "captcha_required_no_code"}
        self.safe_endpoint_probes()
        state = self.read_tests()
        self.guarded_write_tests(state)
        print("AUTOBOYA_RESULT_JSON_BEGIN")
        print(json.dumps(redact(self.results), ensure_ascii=False, indent=2))
        print("AUTOBOYA_RESULT_JSON_END")


def to_webvpn_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname == "d.buaa.edu.cn":
        return url
    if parsed.port is None:
        proto = parsed.scheme
    elif parsed.scheme == "http" and parsed.port == 80:
        proto = "http"
    elif parsed.scheme == "https" and parsed.port == 443:
        proto = "https"
    else:
        proto = f"{parsed.scheme}-{parsed.port}"
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{WEBVPN_GATEWAY}/{proto}/{encrypt_webvpn_host(parsed.hostname or '')}{parsed.path}{query}{fragment}"


def encrypt_webvpn_host(host: str) -> str:
    plain = host.encode()
    padded = plain + b"0" * ((16 - len(plain) % 16) % 16)
    proc = subprocess.run(
        ["openssl", "enc", "-aes-128-cfb", "-K", WEBVPN_KEY.hex(), "-iv", WEBVPN_KEY.hex(), "-nosalt"],
        input=padded,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return WEBVPN_KEY.hex() + proc.stdout.hex()[: len(plain) * 2]


def rsa_encrypt(data: bytes) -> str:
    with tempfile.NamedTemporaryFile("w", delete=False) as handle:
        handle.write(BYKC_RSA_PEM)
        key_path = handle.name
    try:
        proc = subprocess.run(
            ["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", key_path, "-pkeyopt", "rsa_padding_mode:pkcs1"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return base64.b64encode(proc.stdout).decode()
    finally:
        os.unlink(key_path)


def openssl_aes_ecb(data: bytes, key: bytes, decrypt: bool = False) -> bytes:
    cmd = ["openssl", "enc", "-aes-128-ecb", "-K", key.hex(), "-nosalt"]
    if decrypt:
        cmd.insert(2, "-d")
    proc = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return proc.stdout


def extract_execution(html: str) -> str:
    match = re.search(r'name=["\']execution["\']\s+value=["\']([^"\']+)["\']', html)
    if not match:
        match = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']execution["\']', html)
    return match.group(1) if match else ""


def build_cas_login_params(
    html: str,
    username: str,
    password: str,
    captcha: str | None = None,
) -> dict[str, str]:
    """Mirror UBAA CasParser: preserve hidden/default fields from the real form."""
    parser = FormParser()
    parser.feed(html)
    form = next(
        (
            candidate
            for candidate in parser.forms
            if candidate["attrs"].get("id") in {"fm1", "loginForm"} or candidate["attrs"].get("action")
        ),
        parser.forms[0] if parser.forms else {"inputs": []},
    )
    params: dict[str, str] = {}
    present: set[str] = set()
    inputs = form.get("inputs") or []
    for input_attrs in inputs:
        name = (input_attrs.get("name") or "").strip()
        if not name:
            continue
        input_type = (input_attrs.get("type") or "").strip().lower()
        value = input_attrs.get("value") or ""
        if name in {"username", "password"}:
            present.add(name)
            continue
        if input_type in {"submit", "button", "image"}:
            continue
        if input_type == "checkbox":
            present.add(name)
            if "checked" in input_attrs:
                params[name] = value or "on"
            continue
        if value:
            params[name] = value
        present.add(name)

    params["username"] = username
    params["password"] = password
    params["submit"] = "登录"
    if "type" not in present and "type" not in params:
        params["type"] = "username_password"
    if "_eventId" not in present and "_eventId" not in params:
        params["_eventId"] = "submit"
    if "execution" not in params:
        params["execution"] = extract_execution(html)
    if captcha:
        params["captcha"] = captcha
        params["captchaResponse"] = captcha
    return params


def extract_token(url: str) -> str | None:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    token = urllib.parse.parse_qs(parsed.query).get("token", [None])[0]
    if token:
        return token
    match = re.search(r"[?&]token=([^&\s]+)", url)
    return match.group(1) if match else None


def resolve_url(base: str, location: str) -> str:
    return urllib.parse.urljoin(base, location)


def find_login_error(html: str) -> str | None:
    if not html:
        return None
    for pattern in [
        r"Invalid credentials\.",
        r"Access Denied[^<\"]*",
        r"<div class=\"tip-text\">([^<]+)</div>",
        r"<p[^>]*>([^<]*(?:错误|密码|验证码|失败)[^<]*)</p>",
    ]:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1) if match.groups() else match.group(0)).strip()
    return None


def extract_access_denied(text: str) -> str | None:
    if "Access Denied" not in text:
        return None
    try:
        data = json.loads(text)
        message = data.get("message")
        if isinstance(message, str):
            return re.sub(r"user \[[^\]]+\]", "user [REDACTED]", message)
    except Exception:
        pass
    return "Access Denied"


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            pass
    return None


def within_window(start: Any, end: Any, now: datetime) -> bool:
    s, e = parse_dt(start), parse_dt(end)
    return bool(s and e and s <= now <= e)


def parse_sign_config(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.replace('\\"', '"')
    try:
        return json.loads(text)
    except Exception:
        return None


def random_point(lat: float, lng: float, radius_m: float) -> tuple[float, float]:
    # Uniform point in a circle, converted approximately to degrees.
    r = radius_m * math.sqrt(random.random()) * 0.65
    theta = random.random() * 2 * math.pi
    dlat = (r * math.sin(theta)) / 111_320
    dlng = (r * math.cos(theta)) / (111_320 * max(0.2, math.cos(math.radians(lat))))
    return lat + dlat, lng + dlng


def summarize_course(course: Any) -> dict[str, Any]:
    if not isinstance(course, dict):
        return {}
    sign_config = parse_sign_config(course.get("courseSignConfig"))
    return {
        "id": course.get("id"),
        "name": course.get("courseName"),
        "location": course.get("coursePosition"),
        "category": ((course.get("courseNewKind2") or {}).get("kindName") if isinstance(course.get("courseNewKind2"), dict) else course.get("courseKind")),
        "selected": course.get("selected", course.get("isSelected")),
        "course_start": course.get("courseStartDate"),
        "course_end": course.get("courseEndDate"),
        "select_start": course.get("courseSelectStartDate"),
        "select_end": course.get("courseSelectEndDate"),
        "cancel_end": course.get("courseCancelEndDate"),
        "capacity": [course.get("courseCurrentCount"), course.get("courseMaxCount")],
        "campus": course.get("courseCampusList"),
        "courseSignType": course.get("courseSignType"),
        "sign_method": "自主签到" if sign_config and sign_config.get("signPointList") else "常规/无位置配置",
        "sign_windows": {
            "in": [sign_config.get("signStartDate"), sign_config.get("signEndDate")] if sign_config else None,
            "out": [sign_config.get("signOutStartDate"), sign_config.get("signOutEndDate")] if sign_config else None,
        },
    }


def response_brief(decoded: Any) -> dict[str, Any]:
    if not isinstance(decoded, dict):
        return {"ok": False, "type": type(decoded).__name__}
    status = decoded.get("status")
    return {
        "ok": status in ("0", 0, "200", 200, None) and not decoded.get("errmsg"),
        "status": status,
        "errmsg": decoded.get("errmsg") or decoded.get("msg"),
        "keys": list(decoded.keys())[:8],
    }


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("<redacted>" if k.lower() in {"password", "token", "bykctoken"} else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"user \[[^\]]+\]", "user [REDACTED]", value)
        value = re.sub(r"223\d{5}", "223*****", value)
    return value


if __name__ == "__main__":
    BoyaProbe(use_vpn=os.getenv("AUTOBOYA_USE_VPN", "1") != "0").run()
