# AutoBoya CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an installable Python CLI named `autoboya` that logs into BUAA Boya through WebVPN, caches course state, supports multi-user course operations, and runs a guarded automation loop for autonomous-sign course selection plus check-in/check-out.

**Architecture:** Split the tool into small modules: auth/WebVPN, Boya encrypted API, local store, domain rules, scheduler, and CLI. The automation loop refreshes remote state hourly with one random login-capable account, then evaluates cached state every minute and executes per-user actions only when local time windows match. Credentials are handled separately from course/cache state so `~/.autoboya` remains inspectable while secrets are not casually leaked.

**Tech Stack:** Python 3.11+, `typer` for CLI, `httpx` for HTTP/cookies, `cryptography` for AES/RSA, `rich` for tables/log display, `keyring` for OS credential storage, `pytest` for tests.

---

## Product Decisions Locked For V1

- Auto select is course-property driven: the daemon only selects courses whose sign method is `自主签到`, derived from non-empty `courseSignConfig.signPointList`, and never selects `常规签到` or courses with no location sign config.
- The CLI must provide a preview command so users can inspect which cached courses would be automatically selected before starting the daemon.
- Auto drop is not daemon-driven in V1. Dropping is explicit via `autoboya drop <course_id>` to avoid accidental removal.
- Auto sign and sign-out operate on all users' selected courses when the sign config and time window match.
- CAPTCHA handling follows UBAA: detect CAPTCHA, fetch image, prompt the operator to type the code, then submit it as both `captcha` and `captchaResponse`. No OCR or CAPTCHA bypass is implemented.
- `~/.autoboya` contains config, cache, logs, pid/stop files, and local session metadata. Passwords should use OS keychain through `keyring` if available; if not available, the CLI must require `--unsafe-store-password` before storing a password in `~/.autoboya/secrets.json` with mode `0600`.
- All network requests use WebVPN by default for SSO and Boya login. Direct BYKC is used only for unauthenticated endpoint-shape diagnostics, not for normal operation.

## Planned File Structure

- Create: `pyproject.toml` - package metadata, console script, dependencies.
- Create: `autoboya/__init__.py` - package version.
- Create: `autoboya/__main__.py` - `python -m autoboya` entry.
- Create: `autoboya/cli.py` - Typer command tree.
- Create: `autoboya/config.py` - constants and `~/.autoboya` path helpers.
- Create: `autoboya/models.py` - dataclasses/enums for courses, users, results, errors.
- Create: `autoboya/rules.py` - time-window, selectability, grouping, sign-point rules.
- Create: `autoboya/storage.py` - JSON store, cache, locks, credentials.
- Create: `autoboya/webvpn.py` - UBAA-compatible WebVPN URL transform.
- Create: `autoboya/crypto.py` - BYKC request encryption/decryption.
- Create: `autoboya/http.py` - shared HTTP session wrapper and redaction.
- Create: `autoboya/auth.py` - SSO login, CAPTCHA flow, UC activation, Boya token acquisition.
- Create: `autoboya/bykc.py` - typed Boya endpoints.
- Create: `autoboya/exceptions.py` - domain exception classes and message mapping.
- Create: `autoboya/scheduler.py` - hourly refresh plus minute scanner.
- Create: `autoboya/logging.py` - logging config and JSON/event helpers.
- Create: `tests/` - unit tests with mocked HTTP.
- Rename: `AGENT.md` to `AGENTS.md` so future Codex runs and user-facing notes use the conventional filename. Keep investigation notes intact.
- Keep: `boya_live_probe.py` as an investigation utility and mark it deprecated in README after the package reaches equivalent coverage.

---

### Task 1: Package Skeleton

**Files:**
- Create: `/Users/denerate/project/autoboya/pyproject.toml`
- Create: `/Users/denerate/project/autoboya/autoboya/__init__.py`
- Create: `/Users/denerate/project/autoboya/autoboya/__main__.py`
- Create: `/Users/denerate/project/autoboya/autoboya/cli.py`
- Create: `/Users/denerate/project/autoboya/tests/test_cli_smoke.py`

- [ ] **Step 1: Write the failing CLI smoke test**

```python
# tests/test_cli_smoke.py
from typer.testing import CliRunner

from autoboya.cli import app


def test_cli_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "autoboya" in result.output
```

- [ ] **Step 2: Run the smoke test and verify it fails**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli_smoke.py -q`

Expected: FAIL because `autoboya` package does not exist.

- [ ] **Step 3: Add package metadata and the minimal CLI**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "autoboya"
version = "0.1.0"
description = "BUAA Boya WebVPN CLI automation tool"
requires-python = ">=3.11"
dependencies = [
  "cryptography>=42",
  "httpx>=0.27",
  "keyring>=25",
  "rich>=13",
  "typer>=0.12",
]

[project.scripts]
autoboya = "autoboya.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

```python
# autoboya/__init__.py
__version__ = "0.1.0"
```

```python
# autoboya/__main__.py
from .cli import main

if __name__ == "__main__":
    main()
```

```python
# autoboya/cli.py
import typer

from . import __version__

app = typer.Typer(no_args_is_help=True)


@app.command()
def version() -> None:
    typer.echo(f"autoboya {__version__}")


def main() -> None:
    app()
```

- [ ] **Step 4: Run the smoke test and verify it passes**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli_smoke.py -q`

Expected: PASS.

---

### Task 2: Local Config And Storage

**Files:**
- Create: `/Users/denerate/project/autoboya/autoboya/config.py`
- Create: `/Users/denerate/project/autoboya/autoboya/storage.py`
- Create: `/Users/denerate/project/autoboya/tests/test_storage.py`

- [ ] **Step 1: Write tests for `~/.autoboya` layout**

```python
# tests/test_storage.py
from pathlib import Path

from autoboya.storage import AutoBoyaStore


def test_store_initializes_expected_directories(tmp_path: Path):
    store = AutoBoyaStore(root=tmp_path / ".autoboya")
    store.init()

    assert (tmp_path / ".autoboya" / "cache").is_dir()
    assert (tmp_path / ".autoboya" / "logs").is_dir()
    assert (tmp_path / ".autoboya" / "run").is_dir()
    assert (tmp_path / ".autoboya" / "captcha").is_dir()
    assert (tmp_path / ".autoboya" / "users.json").exists()
    assert store.load_users() == []


def test_atomic_json_round_trip(tmp_path: Path):
    store = AutoBoyaStore(root=tmp_path / ".autoboya")
    store.init()
    store.save_json("settings.json", {"auto_select_mode": "autonomous_sign_only"})

    assert store.load_json("settings.json") == {"auto_select_mode": "autonomous_sign_only"}
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_storage.py -q`

Expected: FAIL because storage does not exist.

- [ ] **Step 3: Implement config and JSON store**

```python
# autoboya/config.py
import os
from pathlib import Path

USERS_FILE = "users.json"
SETTINGS_FILE = "settings.json"
COURSE_CACHE_FILE = "cache/courses.json"
SELECTED_CACHE_FILE = "cache/selected.json"
STATISTICS_CACHE_FILE = "cache/statistics.json"
RUN_PID_FILE = "run/autoboya.pid"
STOP_FILE = "run/stop.request"
LOG_FILE = "logs/autoboya.log"


def app_dir() -> Path:
    override = os.environ.get("AUTOBOYA_HOME")
    return Path(override).expanduser() if override else Path.home() / ".autoboya"
```

```python
# autoboya/storage.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import SETTINGS_FILE, USERS_FILE, app_dir


class AutoBoyaStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or app_dir()

    def path(self, relative: str) -> Path:
        return self.root / relative

    def init(self) -> None:
        for relative in ["cache", "logs", "run", "captcha"]:
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

    def save_json(self, relative: str, value: Any) -> None:
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load_users(self) -> list[dict[str, Any]]:
        return list(self.load_json(USERS_FILE, []))
```

- [ ] **Step 4: Run storage tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_storage.py -q`

Expected: PASS.

---

### Task 3: Domain Models And Rules

**Files:**
- Create: `/Users/denerate/project/autoboya/autoboya/models.py`
- Create: `/Users/denerate/project/autoboya/autoboya/rules.py`
- Create: `/Users/denerate/project/autoboya/tests/test_rules.py`

- [ ] **Step 1: Write tests for course grouping, selectability, autonomous-sign selection, and sign coordinates**

```python
# tests/test_rules.py
from datetime import datetime

from autoboya.models import BoyaCourse
from autoboya.rules import (
    classify_selected_courses,
    is_auto_select_candidate,
    is_selectable,
    random_point_in_radius,
)


def test_is_selectable_requires_window_capacity_and_not_selected():
    course = BoyaCourse(
        id=1001,
        name="劳动教育示例",
        location="学院路",
        category="劳动教育",
        selected=False,
        course_start="2026-05-20 10:00:00",
        course_end="2026-05-20 11:00:00",
        select_start="2026-05-20 08:00:00",
        select_end="2026-05-20 09:00:00",
        cancel_end="2026-05-20 09:30:00",
        current_count=5,
        max_count=10,
        sign_config={},
        sign_type=None,
    )
    assert is_selectable(course, datetime(2026, 5, 20, 8, 30))
    assert not is_selectable(course, datetime(2026, 5, 20, 7, 59))


def test_classify_selected_courses_by_start_time():
    started = BoyaCourse(id=1, name="A", course_start="2026-05-20 08:00:00")
    pending = BoyaCourse(id=2, name="B", course_start="2026-05-20 12:00:00")

    grouped = classify_selected_courses([started, pending], datetime(2026, 5, 20, 10, 0))

    assert [c.id for c in grouped["已开始上课"]] == [1]
    assert [c.id for c in grouped["未开始上课"]] == [2]


def test_auto_select_candidate_requires_autonomous_sign_config():
    autonomous = BoyaCourse(
        id=1001,
        selected=False,
        select_start="2026-05-20 08:00:00",
        select_end="2026-05-20 09:00:00",
        current_count=1,
        max_count=20,
        sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]},
    )
    regular = BoyaCourse(
        id=1002,
        selected=False,
        select_start="2026-05-20 08:00:00",
        select_end="2026-05-20 09:00:00",
        current_count=1,
        max_count=20,
        sign_config={},
    )
    now = datetime(2026, 5, 20, 8, 30)

    assert is_auto_select_candidate(autonomous, now)
    assert not is_auto_select_candidate(regular, now)


def test_random_point_stays_inside_radius():
    lat, lng = random_point_in_radius(39.981, 116.344, 8, seed=7)
    assert 39.9809 < lat < 39.9811
    assert 116.3439 < lng < 116.3441
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_rules.py -q`

Expected: FAIL because models and rules do not exist.

- [ ] **Step 3: Implement models and rules**

```python
# autoboya/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    sign_config: dict[str, Any] = field(default_factory=dict)
    sign_type: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
```

```python
# autoboya/rules.py
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
    return is_selectable(course, now) and has_autonomous_sign(course)


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


def random_point_in_radius(lat: float, lng: float, radius_m: float, seed: int | None = None) -> tuple[float, float]:
    rng = random.Random(seed)
    distance = radius_m * math.sqrt(rng.random()) * 0.65
    theta = rng.random() * 2 * math.pi
    dlat = (distance * math.sin(theta)) / 111_320
    dlng = (distance * math.cos(theta)) / (111_320 * max(0.2, math.cos(math.radians(lat))))
    return lat + dlat, lng + dlng
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_rules.py -q`

Expected: PASS.

---

### Task 4: WebVPN And BYKC Crypto

**Files:**
- Create: `/Users/denerate/project/autoboya/autoboya/webvpn.py`
- Create: `/Users/denerate/project/autoboya/autoboya/crypto.py`
- Create: `/Users/denerate/project/autoboya/tests/test_webvpn_crypto.py`

- [ ] **Step 1: Write deterministic tests from UBAA-observed URLs**

```python
# tests/test_webvpn_crypto.py
import json

from autoboya.crypto import BykcCrypto
from autoboya.webvpn import to_webvpn_url


def test_webvpn_host_encryption_matches_known_sso_url():
    url = to_webvpn_url("https://sso.buaa.edu.cn/login")
    assert url == (
        "https://d.buaa.edu.cn/https/"
        "77726476706e69737468656265737421e3e44ed225256951300d8db9d6562d/login"
    )


def test_webvpn_host_encryption_matches_known_bykc_url():
    url = to_webvpn_url("https://bykc.buaa.edu.cn/sscv/cas/login")
    assert url == (
        "https://d.buaa.edu.cn/https/"
        "77726476706e69737468656265737421f2ee4a9f69327d517f468ca88d1b203b/sscv/cas/login"
    )


def test_bykc_crypto_round_trip_response_body():
    crypto = BykcCrypto.fixed_key_for_test("ABCDEFGHJKMNPQRS")
    encrypted = crypto.encrypt_plaintext(json.dumps({"status": "0"}, separators=(",", ":")).encode())
    decrypted = crypto.decrypt_response(encrypted)
    assert decrypted == {"status": "0"}
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_webvpn_crypto.py -q`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement WebVPN URL conversion and BYKC AES/RSA envelope**

Implementation requirements:

- `to_webvpn_url()` must match UBAA `VpnCipher`.
- WebVPN host encryption uses AES-CFB with key/IV `wrdvpnisthebest!`, ASCII `0` padding, and output `iv_hex + ciphertext_hex[:host_len*2]`.
- BYKC request crypto uses AES-128-ECB PKCS7 for body, RSA/PKCS1v1.5 for `Ak`, RSA/PKCS1v1.5 over SHA1 hex plaintext for `Sk`.
- `BykcCrypto.encrypt_request(payload)` returns headers `Ak`, `Sk`, `Ts` and a JSON-string body containing Base64 ciphertext.
- `BykcCrypto.decrypt_response(body)` accepts the JSON-string Base64 response and returns parsed JSON.

- [ ] **Step 4: Run tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_webvpn_crypto.py -q`

Expected: PASS.

---

### Task 5: Auth And CAPTCHA Flow

**Files:**
- Create: `/Users/denerate/project/autoboya/autoboya/auth.py`
- Create: `/Users/denerate/project/autoboya/autoboya/http.py`
- Create: `/Users/denerate/project/autoboya/autoboya/exceptions.py`
- Create: `/Users/denerate/project/autoboya/tests/test_auth.py`

- [ ] **Step 1: Write mocked auth tests**

```python
# tests/test_auth.py
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

    client = AuthClient(store=AutoBoyaStore(tmp_path), http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(CaptchaRequired) as exc:
        client.preflight_login()

    challenge = exc.value.challenge
    assert isinstance(challenge, CaptchaChallenge)
    assert challenge.captcha_id == "cap-1"
    assert challenge.execution == "exec-1"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_auth.py -q`

Expected: FAIL because auth classes do not exist.

- [ ] **Step 3: Implement auth client**

Implementation requirements:

- Always route SSO login and CAPTCHA URLs through `to_webvpn_url()`.
- Detect CAPTCHA using the same regex as UBAA: `config.captcha = { type: '...', id: '...' }`.
- Save CAPTCHA images to `~/.autoboya/captcha/<captcha_id>.png`.
- Raise `CaptchaRequired(challenge)` when no CAPTCHA value is supplied.
- Submit form fields from the real login page, including hidden fields, plus `captcha` and `captchaResponse` when provided.
- Follow password-expiry `continueForm` / `ignoreAndContinue` when present.
- Activate UC by requesting the UBAA-compatible UC login URL.
- Acquire Boya token by visiting WebVPN `https://bykc.buaa.edu.cn/sscv/cas/login` and extracting `token=` from URL or `Location`.
- Persist only session metadata and cookies that are required for reuse; redact tokens in logs.

- [ ] **Step 4: Run auth tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_auth.py -q`

Expected: PASS.

---

### Task 6: BYKC API Client And Error Mapping

**Files:**
- Create: `/Users/denerate/project/autoboya/autoboya/bykc.py`
- Modify: `/Users/denerate/project/autoboya/autoboya/exceptions.py`
- Create: `/Users/denerate/project/autoboya/tests/test_bykc.py`

- [ ] **Step 1: Write mocked endpoint tests**

```python
# tests/test_bykc.py
import pytest

from autoboya.bykc import parse_course
from autoboya.exceptions import CourseFull, SessionExpired, SelectionLimitReached, map_boya_error


def test_parse_course_preserves_required_fields():
    course = parse_course({
        "id": 1001,
        "courseName": "美育课程",
        "coursePosition": "沙河校区 J3",
        "courseNewKind2": {"kindName": "美育"},
        "selected": False,
        "courseStartDate": "2026-05-20 10:00:00",
        "courseEndDate": "2026-05-20 11:00:00",
        "courseSelectStartDate": "2026-05-20 08:00:00",
        "courseSelectEndDate": "2026-05-20 09:00:00",
        "courseCurrentCount": 1,
        "courseMaxCount": 20,
        "courseSignConfig": "{\"signPointList\":[{\"lat\":39.981,\"lng\":116.344,\"radius\":8}]}",
    })
    assert course.id == 1001
    assert course.category == "美育"
    assert course.location == "沙河校区 J3"
    assert course.sign_config["signPointList"][0]["radius"] == 8


def test_error_mapping():
    assert isinstance(map_boya_error("您的会话已失效,请重新登录后再试,谢谢!"), SessionExpired)
    assert isinstance(map_boya_error("课程容量已满"), CourseFull)
    assert isinstance(map_boya_error("已达到选课上限"), SelectionLimitReached)
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_bykc.py -q`

Expected: FAIL because API parsing and error mapping do not exist.

- [ ] **Step 3: Implement API client**

Endpoint methods:

- `get_all_config()`
- `query_courses(page_number=1, page_size=50)`
- `query_course_detail(course_id)`
- `query_chosen_courses(start_date, end_date)`
- `query_statistics()`
- `select_course(course_id)`
- `drop_course(chosen_or_course_id)`
- `sign_course(course_id, lat, lng, sign_type)`

Exception mapping rules:

- `status == "98005399"` or errmsg contains `会话已失效` -> `SessionExpired`
- errmsg contains `容量已满` or `人数已满` -> `CourseFull`
- errmsg contains `未到选课时间` or `不在选课时间` -> `CourseNotOpen`
- errmsg contains `选课上限` or `达到上限` -> `SelectionLimitReached`
- errmsg contains `已选` -> `AlreadySelected`
- errmsg contains `签到时间` or `签退时间` -> `SignWindowClosed`
- unknown non-success response -> `BoyaApiError(status, errmsg)`

- [ ] **Step 4: Run BYKC tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_bykc.py -q`

Expected: PASS.

---

### Task 7: User CLI Commands

**Files:**
- Modify: `/Users/denerate/project/autoboya/autoboya/cli.py`
- Modify: `/Users/denerate/project/autoboya/autoboya/storage.py`
- Create: `/Users/denerate/project/autoboya/tests/test_cli_users.py`

- [ ] **Step 1: Write CLI tests for init and user listing**

```python
# tests/test_cli_users.py
from typer.testing import CliRunner

from autoboya.cli import app


def test_init_and_empty_user_list(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOBOYA_HOME", str(tmp_path / ".autoboya"))
    runner = CliRunner()

    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0

    listed = runner.invoke(app, ["user", "list"])
    assert listed.exit_code == 0
    assert "No users" in listed.output
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli_users.py -q`

Expected: FAIL because commands are missing.

- [ ] **Step 3: Implement CLI commands**

Required commands:

- `autoboya init`
- `autoboya user add <username> [--password-stdin] [--unsafe-store-password]`
- `autoboya user list`
- `autoboya user remove <username>`
- `autoboya login <username>`

Behavior:

- `AUTOBOYA_HOME` overrides `~/.autoboya` for tests.
- `user add` writes metadata to `users.json`, stores secret in keyring when available, and refuses plaintext unless `--unsafe-store-password` is present.
- All commands call `store.init()` before read/write.
- Output should be human-readable and not print passwords, cookies, or tokens.

- [ ] **Step 4: Run CLI tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cli_users.py -q`

Expected: PASS.

---

### Task 8: Course Cache, Views, And Statistics Commands

**Files:**
- Modify: `/Users/denerate/project/autoboya/autoboya/cli.py`
- Create: `/Users/denerate/project/autoboya/autoboya/cache.py`
- Create: `/Users/denerate/project/autoboya/tests/test_cache_views.py`

- [ ] **Step 1: Write tests for cache projection**

```python
# tests/test_cache_views.py
from datetime import datetime
from pathlib import Path

from autoboya.cache import CourseCache, preview_auto_select_courses
from autoboya.storage import AutoBoyaStore


def test_course_cache_round_trip(tmp_path: Path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    cache = CourseCache(store)
    cache.save_courses([{"id": 1001, "courseName": "美育", "coursePosition": "沙河"}])

    assert cache.load_courses()[0]["id"] == 1001


def test_auto_preview_keeps_only_autonomous_sign_courses(tmp_path: Path):
    store = AutoBoyaStore(tmp_path / ".autoboya")
    store.init()
    cache = CourseCache(store)
    cache.save_courses([
        {
            "id": 1001,
            "courseName": "自主签到课程",
            "selected": False,
            "courseSelectStartDate": "2026-05-20 08:00:00",
            "courseSelectEndDate": "2026-05-20 09:00:00",
            "courseCurrentCount": 1,
            "courseMaxCount": 20,
            "courseSignConfig": "{\"signPointList\":[{\"lat\":39.981,\"lng\":116.344,\"radius\":8}]}",
        },
        {
            "id": 1002,
            "courseName": "常规签到课程",
            "selected": False,
            "courseSelectStartDate": "2026-05-20 08:00:00",
            "courseSelectEndDate": "2026-05-20 09:00:00",
            "courseCurrentCount": 1,
            "courseMaxCount": 20,
            "courseSignConfig": "",
        },
    ])

    preview = preview_auto_select_courses(cache.load_courses(), now=datetime(2026, 5, 20, 8, 30))

    assert [course.id for course in preview.candidates] == [1001]
    assert preview.excluded[1002] == "常规签到或无位置配置"
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cache_views.py -q`

Expected: FAIL because cache module is missing.

- [ ] **Step 3: Implement cache and view commands**

Required commands:

- `autoboya courses refresh [--user <username>]`
- `autoboya courses list [--only-selectable] [--json]`
- `autoboya courses show <course_id> [--json]`
- `autoboya courses auto-preview [--json]`
- `autoboya selected [--user <username>] [--json]`
- `autoboya stats [--user <username>] [--json]`

View requirements:

- Courses show selectable status, course time, sign method `自主签到` / `常规签到或无位置配置`, course type, location, campus, selected flag, capacity, select/drop windows.
- `courses auto-preview` lists cached courses that currently satisfy the daemon's auto-selection policy: selectable now and `自主签到`. It must also show why similar courses were excluded when `--json` is used, such as `常规签到`, full capacity, already selected, or outside select window.
- Selected courses group by `已开始上课` and `未开始上课`.
- Statistics show `assessmentCount`, `selectAssessmentCount`, `completeAssessmentCount`, `failAssessmentCount`, `undoneAssessmentCount` for keys such as `德育`, `美育`, `劳动教育`, `安全健康`.

- [ ] **Step 4: Run cache/view tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_cache_views.py -q`

Expected: PASS.

---

### Task 9: Automation Scheduler

**Files:**
- Create: `/Users/denerate/project/autoboya/autoboya/scheduler.py`
- Modify: `/Users/denerate/project/autoboya/autoboya/cli.py`
- Create: `/Users/denerate/project/autoboya/tests/test_scheduler.py`

- [ ] **Step 1: Write fake-clock scheduler tests**

```python
# tests/test_scheduler.py
from datetime import datetime

from autoboya.models import BoyaCourse
from autoboya.scheduler import AutomationDecision, decide_actions


def test_decide_selects_only_autonomous_sign_courses_inside_window():
    courses = [
        BoyaCourse(
            id=1001,
            selected=False,
            select_start="2026-05-20 08:00:00",
            select_end="2026-05-20 09:00:00",
            current_count=1,
            max_count=20,
            sign_config={"signPointList": [{"lat": 39.981, "lng": 116.344, "radius": 8}]},
        ),
        BoyaCourse(
            id=1002,
            selected=False,
            select_start="2026-05-20 08:00:00",
            select_end="2026-05-20 09:00:00",
            current_count=1,
            max_count=20,
            sign_config={},
        ),
    ]

    decisions = decide_actions(courses, selected_by_user={}, now=datetime(2026, 5, 20, 8, 30))

    assert AutomationDecision(action="select", course_id=1001) in decisions
    assert AutomationDecision(action="select", course_id=1002) not in decisions
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_scheduler.py -q`

Expected: FAIL because scheduler does not exist.

- [ ] **Step 3: Implement scheduler decisions and run loop**

Runtime requirements:

- `autoboya run` creates `~/.autoboya/run/autoboya.pid`, removes stale stop files, and starts foreground loop.
- `autoboya stop` creates `~/.autoboya/run/stop.request`; the loop exits within one minute.
- Hourly refresh picks one random account that can log in, refreshes course cache, then refreshes selected/statistics per user.
- Minute scan reads local cache and determines operations without hitting network unless an action is due.
- Selection action: for every user, call `select_course(course_id)` only if the course is locally selectable and has autonomous sign config. Courses marked `常规签到` or with empty sign points must be skipped even if they are otherwise selectable.
- Sign action: for every user and selected course, parse sign windows and sign points; if inside sign-in window call `signType=1`, if inside sign-out window call `signType=2`.
- Deduplicate operations using `~/.autoboya/cache/action_journal.json`, keyed by `date`, `username`, `course_id`, and action.
- Failed actions are logged with mapped exception class and backend message; retry on next minute only for retryable errors.

- [ ] **Step 4: Run scheduler tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_scheduler.py -q`

Expected: PASS.

---

### Task 10: Logging And Diagnostics

**Files:**
- Create: `/Users/denerate/project/autoboya/autoboya/logging.py`
- Modify: `/Users/denerate/project/autoboya/autoboya/cli.py`
- Create: `/Users/denerate/project/autoboya/tests/test_logging_redaction.py`

- [ ] **Step 1: Write redaction test**

```python
# tests/test_logging_redaction.py
from autoboya.logging import redact


def test_redact_sensitive_values():
    text = "Authtoken abc123 password=secret CASTGC=TGT-1 user [22312345]"
    redacted = redact(text)

    assert "secret" not in redacted
    assert "TGT-1" not in redacted
    assert "22312345" not in redacted
```

- [ ] **Step 2: Run test and verify it fails**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_logging_redaction.py -q`

Expected: FAIL because logging module is missing.

- [ ] **Step 3: Implement logging**

Requirements:

- Write logs to `~/.autoboya/logs/autoboya.log`.
- Console uses concise Rich messages; file log includes timestamp, level, username mask, operation, course id, and result.
- Redact passwords, cookies, `CASTGC`, `JSESSIONID`, `Authtoken`, `auth_token`, `ak`, `sk`, and full student ids.
- Add `autoboya logs tail` command that prints the last N lines.
- Add `autoboya doctor` command that checks Python version, app directory permissions, keyring availability, and whether a login session can reach SSO preflight.

- [ ] **Step 4: Run logging tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_logging_redaction.py -q`

Expected: PASS.

---

### Task 11: Operational Commands For Drop, Manual Sign, And One-Shot Run

**Files:**
- Modify: `/Users/denerate/project/autoboya/autoboya/cli.py`
- Modify: `/Users/denerate/project/autoboya/autoboya/scheduler.py`
- Create: `/Users/denerate/project/autoboya/tests/test_manual_operations.py`

- [ ] **Step 1: Write command-shape tests**

```python
# tests/test_manual_operations.py
from typer.testing import CliRunner

from autoboya.cli import app


def test_manual_commands_show_help_without_network():
    runner = CliRunner()
    for command in [
        ["drop", "--help"],
        ["sign", "--help"],
        ["signout", "--help"],
        ["run-once", "--help"],
    ]:
        result = runner.invoke(app, command)
        assert result.exit_code == 0
```

- [ ] **Step 2: Run test and verify it fails**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_manual_operations.py -q`

Expected: FAIL because commands do not exist.

- [ ] **Step 3: Implement manual operation commands**

Required commands:

- `autoboya drop <course_id> [--user <username>] [--all-users]`
- `autoboya sign <course_id> [--user <username>] [--all-users]`
- `autoboya signout <course_id> [--user <username>] [--all-users]`
- `autoboya run-once` to refresh once, scan once, execute due actions, and exit.

Safety behavior:

- `drop` requires either `--user` or `--all-users`.
- `drop` prints the course name and selected users, then requires `--yes` before performing a real drop.
- `sign` and `signout` derive coordinates only from live or cached sign config. They must fail if no sign point exists.
- `run-once` is the preferred verification path before `autoboya run`.

- [ ] **Step 4: Run manual command tests and verify they pass**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest tests/test_manual_operations.py -q`

Expected: PASS.

---

### Task 12: Documentation, Investigation Notes, And Live Verification

**Files:**
- Rename: `/Users/denerate/project/autoboya/AGENT.md` to `/Users/denerate/project/autoboya/AGENTS.md`
- Create: `/Users/denerate/project/autoboya/README.md`
- Keep unchanged: `/Users/denerate/project/autoboya/boya_live_probe.py`

- [ ] **Step 1: Normalize investigation-note filename**

Run: `rtk mv AGENT.md AGENTS.md`

Expected: `/Users/denerate/project/autoboya/AGENTS.md` exists and contains the existing investigation notes.

- [ ] **Step 2: Add README quickstart**

README must include:

```bash
python -m pip install -e .
autoboya init
autoboya user add 223xxxxx --password-stdin
autoboya login 223xxxxx
autoboya courses refresh
autoboya courses list --only-selectable
autoboya courses auto-preview
autoboya run-once
autoboya run
autoboya stop
```

- [ ] **Step 3: Update investigation notes**

Add a section to `AGENTS.md` named `AutoBoya CLI Implementation Notes` with:

- Module map.
- State files under `~/.autoboya`.
- CAPTCHA flow.
- Automation timing rules.
- Auto-selection policy: only autonomous-sign courses are selected; regular-sign courses are previewed as excluded.
- Exception mapping table.
- Live-test checklist.

- [ ] **Step 4: Run full local test suite**

Run: `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pytest -q`

Expected: PASS.

- [ ] **Step 5: Run package CLI smoke checks**

Run:

```bash
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya version
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya --help
```

Expected: both commands exit 0.

- [ ] **Step 6: Run guarded live checks**

Use a real CAPTCHA value when prompted:

```bash
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya login <masked-test-username>
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya courses refresh --user <masked-test-username>
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya courses list --only-selectable
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya courses auto-preview
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya selected --user <masked-test-username>
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya stats --user <masked-test-username>
rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m autoboya run-once
```

Expected:

- Login obtains a Boya token and does not print it.
- Refresh writes course, selected-course, and statistics caches.
- List output includes selectable status, time, sign method, type, and location.
- `courses auto-preview` lists only currently selectable autonomous-sign courses as planned auto-selection candidates.
- `run-once` does not perform selection unless a cached course is both currently selectable and autonomous-sign.
- No credentials, cookies, or tokens are written to README, `AGENTS.md`, or test output.

---

## Final Acceptance Checklist

- `autoboya` command is installable with `python -m pip install -e .`.
- `~/.autoboya` is created with `cache`, `logs`, `run`, `captcha`, `users.json`, and `settings.json`.
- Login uses WebVPN and UBAA-style CAPTCHA prompting.
- Course list displays selectable status, course time, sign method, course type, and location.
- Selected courses are grouped into `已开始上课` and `未开始上课`.
- Statistics are shown per Boya type.
- Auto selection only touches currently selectable autonomous-sign courses and skips regular-sign courses.
- Sign-in/sign-out generates random coordinates inside the configured sign radius.
- Multi-user actions apply to all configured users when requested by the scheduler.
- Exceptions are mapped to actionable logs for session expiry, closed windows, full courses, selection limit, already selected, and sign window failures.
- `autoboya stop` can terminate a running foreground loop from another shell.
- Tests pass with `pytest -q`.
