from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from .auth import AuthClient, AuthSession, CaptchaChallenge
from .bykc import BykcClient
from .exceptions import CaptchaRequired, LoginError, SessionExpired
from .logging import mask_username
from .storage import AutoBoyaStore, try_get_keyring_password

CaptchaProvider = Callable[[CaptchaChallenge], str | None]
T = TypeVar("T")


def password_for(store: AutoBoyaStore, username: str) -> str:
    password = try_get_keyring_password(username) or store.load_unsafe_password(username)
    if not password:
        raise LoginError(f"No stored password for {mask_username(username)}")
    return password


def save_session(store: AutoBoyaStore, session: AuthSession) -> None:
    store.save_json(
        f"sessions/{session.username}.json",
        {"bykc_token": session.bykc_token, "cookies": session.cookies},
        mode=0o600,
    )


def login_and_save(
    store: AutoBoyaStore,
    username: str,
    captcha_provider: CaptchaProvider | None = None,
) -> AuthSession:
    password = password_for(store, username)
    client = AuthClient(store)
    captcha_value: str | None = None
    try:
        try:
            client.preflight_login()
        except CaptchaRequired as exc:
            if captcha_provider is None:
                raise LoginError(f"CAPTCHA required; run autoboya login {username} interactively") from exc
            captcha_value = captcha_provider(exc.challenge)
            if not captcha_value:
                raise LoginError("CAPTCHA required but no CAPTCHA value was provided") from exc
        session = client.login(username, password, captcha=captcha_value)
    except CaptchaRequired as exc:
        raise LoginError(f"CAPTCHA required; run autoboya login {username} interactively") from exc
    save_session(store, session)
    return session


def ensure_bykc_client(
    store: AutoBoyaStore,
    username: str,
    captcha_provider: CaptchaProvider | None = None,
) -> BykcClient:
    store.init()
    session = store.load_json(f"sessions/{username}.json", {})
    token = session.get("bykc_token") if isinstance(session, dict) else None
    cookies = session.get("cookies") if isinstance(session, dict) else None
    if not token or not isinstance(cookies, list):
        fresh = login_and_save(store, username, captcha_provider=captcha_provider)
        token = fresh.bykc_token
        cookies = fresh.cookies
    return BykcClient(str(token), cookies=cookies)


def force_login_bykc_client(
    store: AutoBoyaStore,
    username: str,
    captcha_provider: CaptchaProvider | None = None,
) -> BykcClient:
    session = login_and_save(store, username, captcha_provider=captcha_provider)
    return BykcClient(session.bykc_token, cookies=session.cookies)


def call_with_reauth(
    store: AutoBoyaStore,
    username: str,
    operation: Callable[[BykcClient], T],
    captcha_provider: CaptchaProvider | None = None,
) -> T:
    client = ensure_bykc_client(store, username, captcha_provider=captcha_provider)
    try:
        return operation(client)
    except SessionExpired:
        client = force_login_bykc_client(store, username, captcha_provider=captcha_provider)
        return operation(client)
