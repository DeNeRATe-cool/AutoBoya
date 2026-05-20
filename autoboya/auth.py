from __future__ import annotations

import html.parser
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from .exceptions import CaptchaRequired, LoginError
from .storage import AutoBoyaStore
from .webvpn import to_webvpn_url

SSO_LOGIN = "https://sso.buaa.edu.cn/login"
SSO_CAPTCHA = "https://sso.buaa.edu.cn/captcha"
UC_ACTIVATE = "https://uc.buaa.edu.cn/api/login?target=https%3A%2F%2Fuc.buaa.edu.cn%2F%23%2Fuser%2Flogin"
BYKC_CAS = "https://bykc.buaa.edu.cn/sscv/cas/login"
BYKC_CAS_EMPTY_TOKEN = "https://bykc.buaa.edu.cn/cas-login?token="


@dataclass
class CaptchaChallenge:
    captcha_id: str
    captcha_type: str
    image_path: Path
    execution: str


@dataclass
class AuthSession:
    username: str
    bykc_token: str
    cookies: list[dict[str, object]]


class _FormParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, object]] = []
        self.current: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: (value or "") for key, value in attrs}
        if tag.lower() == "form":
            self.current = {"attrs": attrs_dict, "inputs": []}
            self.forms.append(self.current)
        elif tag.lower() == "input" and self.current is not None:
            self.current["inputs"].append(attrs_dict)  # type: ignore[index,union-attr]

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self.current = None


class AuthClient:
    def __init__(
        self,
        store: AutoBoyaStore,
        http_client: httpx.Client | None = None,
        use_vpn: bool = True,
    ) -> None:
        self.store = store
        self.client = http_client or httpx.Client(timeout=25, follow_redirects=False)
        self.use_vpn = use_vpn
        self._last_login_html: str | None = None

    def upstream(self, url: str) -> str:
        return to_webvpn_url(url) if self.use_vpn else url

    def preflight_login(self) -> str:
        response = self.client.get(self.upstream(SSO_LOGIN))
        if response.status_code >= 400:
            raise LoginError(f"SSO login page returned HTTP {response.status_code}")
        html = response.text
        self._last_login_html = html
        captcha = detect_captcha(html)
        if captcha:
            image = self.fetch_captcha(captcha[1])
            raise CaptchaRequired(
                CaptchaChallenge(
                    captcha_id=captcha[1],
                    captcha_type=captcha[0],
                    image_path=image,
                    execution=extract_execution(html),
                )
            )
        return extract_execution(html)

    def fetch_captcha(self, captcha_id: str) -> Path:
        response = self.client.get(self.upstream(f"{SSO_CAPTCHA}?captchaId={captcha_id}"))
        response.raise_for_status()
        suffix = ".png" if "png" in response.headers.get("content-type", "") else ".jpg"
        path = self.store.path(f"captcha/{captcha_id}{suffix}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return path

    def login(self, username: str, password: str, captcha: str | None = None) -> AuthSession:
        html = self._last_login_html
        if html is None:
            try:
                self.preflight_login()
                html = self._last_login_html
            except CaptchaRequired as exc:
                if not captcha:
                    raise
                html = self._last_login_html
        if html is None:
            raise LoginError("Unable to load SSO login form")
        params = build_login_params(html, username, password, captcha)
        response = self.client.post(
            self.upstream(SSO_LOGIN),
            data=params,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        final = self.follow_redirects_and_password_expiry(response)
        error = find_login_error(final.text)
        if final.status_code >= 400 or error:
            raise LoginError(error or f"SSO login failed with HTTP {final.status_code}")
        self.activate_uc()
        token = self.acquire_bykc_token()
        if not token:
            raise LoginError("Boya token was not returned after SSO login")
        return AuthSession(username=username, bykc_token=token, cookies=serialize_cookies(self.client))

    def follow_redirects_and_password_expiry(self, response: httpx.Response) -> httpx.Response:
        current = response
        ignored = False
        while True:
            while 300 <= current.status_code <= 399 and current.headers.get("location"):
                current = self.client.get(urljoin(str(current.url), current.headers["location"]))
            if ("continueForm" in current.text or "ignoreAndContinue" in current.text) and not ignored:
                execution = extract_execution(current.text)
                current = self.client.post(
                    str(current.url).split("?", 1)[0],
                    data={"execution": execution, "_eventId": "ignoreAndContinue"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                ignored = True
                continue
            return current

    def activate_uc(self) -> None:
        self.client.get(self.upstream(UC_ACTIVATE))

    def acquire_bykc_token(self) -> str | None:
        token = self._follow_for_token(self.upstream(BYKC_CAS))
        if token:
            return token
        return self._follow_for_token(self.upstream(BYKC_CAS_EMPTY_TOKEN))

    def _follow_for_token(self, url: str, max_redirects: int = 10) -> str | None:
        current_url = url
        for _ in range(max_redirects + 1):
            response = self.client.get(current_url)
            token = extract_token(str(response.url)) or extract_token(response.headers.get("location", ""))
            if token:
                return token
            location = response.headers.get("location")
            if not (300 <= response.status_code <= 399 and location):
                return None
            current_url = urljoin(str(response.url), location)
        return None


def detect_captcha(html: str) -> tuple[str, str] | None:
    match = re.search(
        r"config\.captcha\s*=\s*\{\s*type:\s*['\"]([^'\"]+)['\"],\s*id:\s*['\"]([^'\"]+)['\"]",
        html,
    )
    return (match.group(1), match.group(2)) if match else None


def extract_execution(html: str) -> str:
    match = re.search(r'name=["\']execution["\'][^>]*value=["\']([^"\']+)["\']', html)
    if not match:
        match = re.search(r'value=["\']([^"\']+)["\'][^>]*name=["\']execution["\']', html)
    return match.group(1) if match else ""


def build_login_params(html: str, username: str, password: str, captcha: str | None = None) -> dict[str, str]:
    parser = _FormParser()
    parser.feed(html)
    form = parser.forms[0] if parser.forms else {"inputs": []}
    params: dict[str, str] = {}
    present: set[str] = set()
    for attrs in form.get("inputs", []):  # type: ignore[union-attr]
        name = (attrs.get("name") or "").strip()
        if not name:
            continue
        input_type = (attrs.get("type") or "").strip().lower()
        value = attrs.get("value") or ""
        if name in {"username", "password"}:
            present.add(name)
            continue
        if input_type in {"submit", "button", "image"}:
            continue
        if value:
            params[name] = value
        present.add(name)
    params["username"] = username
    params["password"] = password
    params["submit"] = "登录"
    params.setdefault("type", "username_password")
    params.setdefault("execution", extract_execution(html))
    params.setdefault("_eventId", "submit")
    if captcha:
        params["captcha"] = captcha
        params["captchaResponse"] = captcha
    return params


def find_login_error(html: str) -> str | None:
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


def extract_token(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    token = parse_qs(parsed.query).get("token", [None])[0]
    if token:
        return token
    match = re.search(r"[?&]token=([^&\s]+)", url)
    return match.group(1) if match else None


def serialize_cookies(client: httpx.Client) -> list[dict[str, object]]:
    cookies: list[dict[str, object]] = []
    for cookie in client.cookies.jar:
        cookies.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": bool(cookie.secure),
                "expires": cookie.expires,
            }
        )
    return cookies
