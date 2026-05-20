from pathlib import Path

import httpx
import pytest

from autoboya.auth import AuthClient, CaptchaChallenge
from autoboya.exceptions import CaptchaRequired
from autoboya.storage import AutoBoyaStore


CAPTCHA_HTML = """
<html><form id="loginForm">
<input name="username"><input name="password">
<input name="execution" value="exec-1"><input name="_eventId" value="submit">
</form><script>config.captcha = { type: 'image', id: 'cap-1' };</script></html>
"""


def test_preflight_returns_captcha_challenge(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/login"):
            return httpx.Response(200, text=CAPTCHA_HTML)
        if "captcha" in str(request.url):
            return httpx.Response(200, content=b"png")
        return httpx.Response(404)

    client = AuthClient(
        store=AutoBoyaStore(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(CaptchaRequired) as exc:
        client.preflight_login()

    challenge = exc.value.challenge
    assert isinstance(challenge, CaptchaChallenge)
    assert challenge.captcha_id == "cap-1"
    assert challenge.execution == "exec-1"


def test_acquire_bykc_token_follows_redirect_chain(tmp_path: Path):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(302, headers={"Location": "https://sso.buaa.edu.cn/login?service=bykc"})
        if "sso.buaa.edu.cn/login" in str(request.url):
            return httpx.Response(302, headers={"Location": "https://bykc.buaa.edu.cn/sscv/cas-login?token=token-123"})
        return httpx.Response(200, text="ok")

    client = AuthClient(
        store=AutoBoyaStore(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
        use_vpn=False,
    )

    assert client.acquire_bykc_token() == "token-123"
    assert len(seen) == 2
    assert "sso.buaa.edu.cn/login" in seen[1]
