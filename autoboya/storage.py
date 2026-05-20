from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import SECRETS_FILE, SETTINGS_FILE, USERS_FILE, app_dir
from .models import UserRecord


class AutoBoyaStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_dir()

    def path(self, relative: str) -> Path:
        return self.root / relative

    def init(self) -> None:
        for relative in ["cache", "logs", "run", "captcha", "sessions"]:
            self.path(relative).mkdir(parents=True, exist_ok=True)
        if not self.path(USERS_FILE).exists():
            self.save_json(USERS_FILE, [])
        if not self.path(SETTINGS_FILE).exists():
            self.save_json(SETTINGS_FILE, {"auto_select_mode": "autonomous_sign_only"})

    def load_json(self, relative: str, default: Any = None) -> Any:
        path = self.path(relative)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def save_json(self, relative: str, value: Any, mode: int | None = None) -> None:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
        if mode is not None:
            os.chmod(path, mode)

    def load_users(self) -> list[dict[str, Any]]:
        return list(self.load_json(USERS_FILE, []))

    def save_users(self, users: list[dict[str, Any]]) -> None:
        self.save_json(USERS_FILE, users)

    def user_records(self) -> list[UserRecord]:
        return [UserRecord(**item) for item in self.load_users()]

    def get_user(self, username: str) -> UserRecord | None:
        for user in self.user_records():
            if user.username == username:
                return user
        return None

    def upsert_user(self, user: UserRecord) -> None:
        users = [item for item in self.user_records() if item.username != user.username]
        users.append(user)
        users.sort(key=lambda record: record.username)
        self.save_users([asdict(item) for item in users])

    def remove_user(self, username: str) -> bool:
        users = self.user_records()
        kept = [item for item in users if item.username != username]
        self.save_users([asdict(item) for item in kept])
        return len(kept) != len(users)

    def save_unsafe_password(self, username: str, password: str) -> None:
        secrets = self.load_json(SECRETS_FILE, {})
        secrets[username] = password
        self.save_json(SECRETS_FILE, secrets, mode=0o600)

    def load_unsafe_password(self, username: str) -> str | None:
        secrets = self.load_json(SECRETS_FILE, {})
        value = secrets.get(username)
        return value if isinstance(value, str) else None


def try_store_keyring_password(username: str, password: str) -> bool:
    try:
        import keyring

        keyring.set_password("autoboya", username, password)
        return True
    except Exception:
        return False


def try_get_keyring_password(username: str) -> str | None:
    try:
        import keyring

        return keyring.get_password("autoboya", username)
    except Exception:
        return None
