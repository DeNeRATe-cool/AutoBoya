# AutoBoya Investigation Notes

This workspace is for follow-up Boya automation work. Shell commands should follow
`/Users/denerate/.codex/RTK.md`: prefix commands with `rtk`.

## Primary Source

Primary reference repo: `/Users/denerate/project/buaa-api`.

Key files checked:

- `/Users/denerate/project/buaa-api/src/api/sso/auth.rs`: BUAA SSO login form flow.
- `/Users/denerate/project/buaa-api/src/api/boya/core.rs`: Boya secondary login and encrypted request wrapper.
- `/Users/denerate/project/buaa-api/src/api/boya/opt.rs`: Boya business endpoints.
- `/Users/denerate/project/buaa-api/src/api/boya/data.rs`: response fields for courses, selected courses, statistics, sign config, and sign result.
- `/Users/denerate/project/buaa-api/examples/boya.rs`: ignored test examples for query/select/drop/sign.

Adjacent local reference used only to clarify raw fields:

- `/Users/denerate/BUAA/软件过程与质量/大作业/Agent API 文档/UBAA/server/src/main/kotlin/cn/edu/ubaa/bykc/BykcModels.kt` records `courseSignType`: observed `1=仅签到`, `2=签到+签退`.
- Its UI labels courses with non-empty sign points as `自主签到`. Treat this as supplementary; `buaa-api` itself only parses sign windows and coordinates.

## 2026-05-20 Request Practice

Runtime notes:

- The local workspace has no Rust toolchain, so `cargo test --example boya` could not run here.
- macOS `/usr/bin/curl` timed out during TLS to BUAA hosts, but the bundled Python runtime worked:
  `/Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.
- The test account was read from `/Users/denerate/ELSE/BUAA-test-account.txt`; credentials were not written to this file.

Actual requests made:

| Request | Result |
| --- | --- |
| `GET https://sso.buaa.edu.cn/login` | HTTP 200, login form available, `execution` field present. |
| `POST https://sso.buaa.edu.cn/login` with test account | First direct attempt returned HTTP 401 `Invalid credentials`; later attempts returned HTTP 423 `Access Denied ... from IP Address ...`. Stop retrying this account from this environment. |
| `GET https://d.buaa.edu.cn/` | HTTP 200; final page is proxied SSO login for `d.buaa.edu.cn/login?cas_login=true`. |
| `POST` WebVPN SSO URL with test account | HTTP 423 locked/access denied from current IP. |
| `GET https://d.buaa.edu.cn/https/.../sscv/cas/login` | Redirected to WebVPN SSO login; no Boya token without successful SSO. |
| Encrypted `POST https://bykc.buaa.edu.cn/sscv/getAllConfig` with invalid token | HTTP 200, decrypted `status="0"`; config/semester/campus is public enough to load without a valid Boya token. |
| Encrypted POST to `queryStudentSemesterCourseByPage`, `queryCourseById`, `queryChosenCourse`, `queryStatisticByUserId`, `choseCourse`, `delChosenCourse`, `signCourseByUser` with invalid token | HTTP 200, decrypted `status="98005399"`, `errmsg="您的会话已失效,请重新登录后再试,谢谢!"`. This confirms endpoint shape and auth boundary without mutating account state. |

Public config observed from `getAllConfig`:

- Current first semester entry: `2025-2026学年第二学期（春季）`, `2026-03-01 00:00:00` to `2026-06-21 00:00:00`.
- Campuses include `学院路校区`, `沙河校区`, `杭州校区`.

## 2026-05-20 Python Reprobe With UBAA Reference

Local probe script:

- `/Users/denerate/project/autoboya/boya_live_probe.py`
- Run with bundled Python:
  `rtk /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -u boya_live_probe.py`
- Safe endpoint-only probe without login:
  `rtk env AUTOBOYA_SKIP_LOGIN=1 /Users/denerate/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -u boya_live_probe.py`
- Real writes are guarded behind `AUTOBOYA_ALLOW_WRITE=1`; default mode does not select, drop, sign, or sign out with a valid account.

UBAA reference checked:

- `/Users/denerate/project/UBAA/server/src/main/kotlin/cn/edu/ubaa/auth/upstream/CasParser.kt`
- `/Users/denerate/project/UBAA/server/src/main/kotlin/cn/edu/ubaa/auth/api/AuthService.kt`
- `/Users/denerate/project/UBAA/shared/src/commonMain/kotlin/cn/edu/ubaa/api/local/LocalConnectionAuth.kt`
- `/Users/denerate/project/UBAA/server/src/main/kotlin/cn/edu/ubaa/bykc/BykcClient.kt`
- `/Users/denerate/project/UBAA/server/src/main/kotlin/cn/edu/ubaa/bykc/BykcCrypto.kt`
- `/Users/denerate/project/UBAA/server/src/main/kotlin/cn/edu/ubaa/utils/VpnCipher.kt`

UBAA SSO CAPTCHA behavior:

- SSO login pages may contain JavaScript `config.captcha = { type: 'image', id: '...' }`.
- UBAA detects that config, fetches `https://sso.buaa.edu.cn/captcha?captchaId=<id>` through the same direct/VPN route, and returns the image/base64 plus `execution` to the caller.
- UBAA does not auto-solve the SSO image CAPTCHA. The caller must supply the CAPTCHA text.
- When a CAPTCHA is supplied, UBAA submits both `captcha=<value>` and `captchaResponse=<value>`, with `username`, `password`, `execution`, `_eventId=submit`, `submit=登录`, and `type=username_password`.
- The Python probe now mirrors this behavior and preserves hidden fields from the real login form.

Actual Python SSO attempt:

| Request | Result |
| --- | --- |
| `GET` WebVPN SSO login page | HTTP 200, form id `loginForm`, `execution` present, CAPTCHA required, not locked. |
| `GET` WebVPN SSO CAPTCHA image | HTTP 200, `image/png;charset=UTF-8`, image downloaded locally. |
| Submit WebVPN SSO with CAPTCHA value `1234` | HTTP 401, page error `Invalid credentials.` |
| UC activation/status after failed submit | HTTP 200, JSON says session expired / not logged in. |
| Boya `/sscv/cas/login` after failed submit | HTTP 200 through WebVPN, but no `token=` obtained. |

Conclusion: the `1234` trial did not pass login, so full valid-token Boya read/write tests are still blocked on a real SSO CAPTCHA value or a reusable authenticated UBAA session.

Endpoint shape retest with Python:

- Command used: `AUTOBOYA_SKIP_LOGIN=1` safe endpoint-only mode.
- Important connection detail: without a logged-in WebVPN SSO cookie, WebVPN business calls can return the login page as HTTP 200. For invalid-token endpoint-shape probes, use direct BYKC URLs.
- Direct encrypted invalid-token probes all returned HTTP 200 and decrypted correctly.

Observed direct invalid-token statuses:

| Endpoint | Decrypted result |
| --- | --- |
| `getAllConfig` | `status="0"`, includes public config data. |
| `queryStudentSemesterCourseByPage` | `status="98005399"`, session expired. |
| `queryCourseById` | `status="98005399"`, session expired. |
| `queryChosenCourse` | `status="98005399"`, session expired. |
| `queryStatisticByUserId` | `status="98005399"`, session expired. |
| `choseCourse` | `status="98005399"`, session expired. |
| `delChosenCourse` | `status="98005399"`, session expired. |
| `signCourseByUser` with `signType=1` | `status="98005399"`, session expired. |
| `signCourseByUser` with `signType=2` | `status="98005399"`, session expired. |

Valid-token tests not yet completed:

- Course list/detail with real account selection status.
- User selected courses grouped by `已开始上课` / `未开始上课`.
- User course-type statistics with real account counts.
- Real select/drop rollback flow.
- Real check-in/check-out response with a course currently inside a sign window.

Do not claim those valid-token tests passed until a real CAPTCHA-assisted SSO login obtains a Boya token.

## Login Flow

Direct SSO login in `buaa-api`:

1. `GET https://sso.buaa.edu.cn/login`.
2. Parse `execution` from the login HTML.
3. `POST https://sso.buaa.edu.cn/login` form:
   `username`, `password`, `submit`, `type=username_password`, `execution`, `_eventId=submit`.
4. If response contains `continueForm`, post `execution` and `_eventId=ignoreAndContinue`.

WebVPN login URLs are present as comments in the Rust source:

- SSO/VPN:
  `https://d.buaa.edu.cn/https/77726476706e69737468656265737421e3e44ed225256951300d8db9d6562d/login?service=https%3A%2F%2Fd.buaa.edu.cn%2Flogin%3Fcas_login%3Dtrue`
- Boya/VPN:
  `https://d.buaa.edu.cn/https/77726476706e69737468656265737421f2ee4a9f69327d517f468ca88d1b203b/sscv/cas/login`

Boya secondary login:

1. Ensure SSO cookie is valid.
2. Direct mode: `GET https://sso.buaa.edu.cn/login?noAutoRedirect=true&service=https%3A%2F%2Fbykc.buaa.edu.cn%2Fsscv%2Fcas%2Flogin`.
3. VPN mode: after VPN SSO succeeds, visit the Boya/VPN `/sscv/cas/login` URL above.
4. Extract `token=` from the final redirect URL. This becomes the Boya `Authtoken`.

## Encrypted Boya Request Contract

All business APIs are `POST` under:

- Direct: `https://bykc.buaa.edu.cn/sscv/{apiName}`
- VPN: `https://d.buaa.edu.cn/https/77726476706e69737468656265737421f2ee4a9f69327d517f468ca88d1b203b/sscv/{apiName}`

Headers:

- `Authtoken: <boya-token>`; adding `auth_token` and `authtoken` as aliases is harmless and used by adjacent code.
- `Ak`: RSA/PKCS1v1.5 encrypt the random 16-byte AES key, then Base64.
- `Sk`: SHA1 hex digest of the plaintext JSON, RSA/PKCS1v1.5 encrypted, then Base64.
- `Ts`: current milliseconds timestamp.
- `Content-Type: application/json`.

Body:

- Serialize plaintext JSON with compact separators.
- AES-128-ECB with PKCS7 padding using the random key.
- Base64 the ciphertext.
- Send that Base64 string as a JSON string.

Response:

- Usually a JSON string containing Base64 AES ciphertext.
- Base64 decode, AES decrypt with the same request key, then parse JSON.
- Success usually has `status="0"`; auth expiry returns `status="98005399"`.

## Course List And Detail

List endpoint:

```json
POST /queryStudentSemesterCourseByPage
{"pageNumber":1,"pageSize":20}
```

Detail endpoint:

```json
POST /queryCourseById
{"id":1001}
```

Fields to preserve:

- `id`: course id, used by detail, select, sign, and in `buaa-api` drop.
- `courseName`: course name.
- `coursePosition`: course location.
- `courseStartDate`, `courseEndDate`: course time.
- `courseSelectStartDate`, `courseSelectEndDate`, `courseCancelEndDate`: select/drop windows.
- `courseNewKind2.kindName`: type such as `德育`, `美育`, `劳动教育`, `安全健康`.
- `courseMaxCount`, `courseCurrentCount`: capacity.
- `courseCampusList`: campus labels.
- `selected`: whether current user has selected it. Current `buaa-api` expects `selected`; some adjacent older wrappers handled `isSelected`, so inspect raw decrypted JSON if parsing breaks.
- `courseSignType`: raw sign type if present; `buaa-api` does not parse it yet.
- `courseSignConfig`: escaped JSON string; empty means no autonomous location sign config.
- Schedule fields are flattened in current `buaa-api`; adjacent older wrappers also handled a nested `courseDateArrangement`. Preserve whichever shape the live decrypted response uses.

Whether a course is selectable should be derived conservatively from:

- `selected == false`.
- current time within `courseSelectStartDate <= now <= courseSelectEndDate`.
- capacity not full: `courseCurrentCount < courseMaxCount`.
- backend response from `choseCourse` is final; local derivation is only a UI hint.

## Selected Courses And Statistics

Get semester first:

```json
POST /getAllConfig
{}
```

Use the first/current semester entry, then query selected courses:

```json
POST /queryChosenCourse
{"startDate":"2026-03-01 00:00:00","endDate":"2026-06-21 00:00:00"}
```

Group selected courses by start state:

- `已开始上课`: `courseStartDate <= now`.
- `未开始上课`: `courseStartDate > now`.

Statistics:

```json
POST /queryStatisticByUserId
{}
```

Response path is:

```text
data.statistical["60|博雅课程"]
```

Expected type keys:

- `55|德育`
- `56|美育`
- `57|劳动教育`
- `58|安全健康`

Each type has:

- `assessmentCount`: required quantity.
- `selectAssessmentCount`: selected quantity.
- `completeAssessmentCount`: completed quantity.
- `failAssessmentCount`: failed quantity.
- `undoneAssessmentCount`: unfinished quantity.

## Select And Drop

Select:

```json
POST /choseCourse
{"courseId":1001}
```

Drop:

```json
POST /delChosenCourse
{"id":1001}
```

Important: in `/Users/denerate/project/buaa-api`, `drop_course(id)` passes the course id as `id`, and its comments say the id can come from `Course` or `Selected`. Some adjacent older docs describe this as a selected-record id. Before dropping a real course, inspect live `queryChosenCourse` raw JSON and prefer the exact id field that the current implementation returns as `Selected.id`.

Select/drop are real write operations. For probes, do not use a valid token unless the user explicitly confirms the target course and rollback plan.

## Check-In And Check-Out

The sign endpoint is shared:

```json
POST /signCourseByUser
{
  "courseId": 1001,
  "signLat": 39.981,
  "signLng": 116.344,
  "signType": 1
}
```

- `signType=1`: check-in.
- `signType=2`: check-out.

Use `queryCourseById` first and parse `courseSignConfig`:

```json
{
  "signStartDate": "2026-04-20 08:50:00",
  "signEndDate": "2026-04-20 09:20:00",
  "signOutStartDate": "2026-04-20 09:50:00",
  "signOutEndDate": "2026-04-20 10:20:00",
  "signPointList": [{"lat": 40.1001, "lng": 116.3001, "radius": 8.0}]
}
```

`buaa-api` uses the last point in `signPointList`. Its current implementation adds a random offset in `[-1e-5, 1e-5]` degrees to both longitude and latitude before sending the request. This is roughly meter-level jitter near the target point and should remain within an 8-meter radius in normal cases, but a future implementation should generate a point inside the configured radius rather than a square offset.

Sign result parsing:

- Response contains `data.signInfo` as an escaped JSON string.
- It parses to `signIn` and optional `signOut`.
- Each sign info has `lng`, `lat`, `inSignArea`.

Interpretation:

- A non-empty `courseSignConfig.signPointList` is the evidence for autonomous/location-based signing.
- `courseSignType=1` means only check-in has been observed; `courseSignType=2` means check-in plus check-out has been observed.
- If there is no sign config, do not invent coordinates. Query detail again or present the course as non-location/autonomous-sign unavailable.

## Safe Reprobe Checklist

1. Stop if SSO returns HTTP 423. The test account or current IP is blocked; repeated attempts are counterproductive.
2. Use bundled Python or another OpenSSL-backed client if `/usr/bin/curl` times out on BUAA TLS.
3. Verify login first, then Boya token extraction.
4. Read-only calls safe to run with valid token: `getAllConfig`, `queryStudentSemesterCourseByPage`, `queryCourseById`, `queryChosenCourse`, `queryStatisticByUserId`.
5. Treat `choseCourse`, `delChosenCourse`, and `signCourseByUser` as real mutations. Use invalid-token probes or explicit user confirmation only.
6. When writing automation, keep raw decrypted JSON logs locally during development, but redact tokens, cookies, and credentials before committing any report.

## AutoBoya CLI Implementation Notes

Module map:

- `autoboya/auth.py`: WebVPN SSO login, UBAA-style CAPTCHA prompting, UC activation, Boya token acquisition.
- `autoboya/webvpn.py`: UBAA-compatible WebVPN URL transform.
- `autoboya/crypto.py`: BYKC AES/RSA encrypted request envelope.
- `autoboya/bykc.py`: typed Boya endpoints and response parsing.
- `autoboya/rules.py`: course time windows, selectability, autonomous-sign policy, sign coordinate generation.
- `autoboya/cache.py`: cached course, selected-course, and statistics projections.
- `autoboya/scheduler.py`: hourly refresh/minute scan decisions and stop-file loop.
- `autoboya/cli.py`: `autoboya` command tree.

State files under `~/.autoboya`:

- `users.json`: user metadata only.
- `settings.json`: currently stores `auto_select_mode=autonomous_sign_only`.
- `secrets.json`: password fallback only when `--unsafe-store-password` is explicitly used; mode `0600`.
- `sessions/<username>.json`: Boya token/session metadata; mode `0600`.
- `cache/courses.json`, `cache/selected.json`, `cache/statistics.json`, `cache/action_journal.json`.
- `logs/autoboya.log`, `run/autoboya.pid`, `run/stop.request`, `captcha/<captcha_id>.png`.

CAPTCHA flow:

1. Load SSO login page through WebVPN.
2. Detect `config.captcha = { type: 'image', id: '...' }`.
3. Fetch CAPTCHA image to `~/.autoboya/captcha`.
4. Prompt operator for the code.
5. Submit both `captcha` and `captchaResponse`, matching UBAA.

Automation timing rules:

- Remote refresh: once per hour, using one random login-capable account for the shared course pool, then per-user selected/statistics refresh.
- Local scan: once per minute, using cached state unless an action is due.
- `autoboya stop` writes `run/stop.request`; the foreground loop exits within one minute.

Auto-selection policy:

- Select only courses that are currently selectable and have autonomous sign config: non-empty `courseSignConfig.signPointList`.
- Skip regular-sign courses and courses without location sign config even if they are otherwise selectable.
- `autoboya courses auto-preview [--json]` shows planned candidates and JSON exclusion reasons such as `常规签到或无位置配置`, `容量已满`, `已选`, or `不在选课时间`.

Exception mapping:

- `会话已失效` / status `98005399`: `SessionExpired`.
- `容量已满` / `人数已满`: `CourseFull`.
- `未到选课时间` / `不在选课时间`: `CourseNotOpen`.
- `选课上限` / `达到上限`: `SelectionLimitReached`.
- `已选` / duplicate selection: `AlreadySelected`.
- `签到时间` / `签退时间`: `SignWindowClosed`.

Live-test checklist:

1. `python -m pip install -e .`
2. `autoboya init`
3. `autoboya user add <username> --password-stdin`
4. `autoboya login <username>` and enter the real CAPTCHA.
5. `autoboya courses refresh --user <username>`
6. `autoboya courses list --only-selectable`
7. `autoboya courses auto-preview`
8. `autoboya selected --user <username>`
9. `autoboya stats --user <username>`
10. `autoboya run-once`
