from __future__ import annotations

import getpass
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .auth import AuthClient
from .bykc import BykcClient, parse_course
from .cache import CourseCache, preview_auto_select_courses
from .config import LOG_FILE
from .exceptions import CaptchaRequired, LoginError, MissingSignPoint
from .logging import configure_logging
from .models import UserRecord
from .rules import classify_selected_courses, random_point_in_radius
from .scheduler import AutomationRunner
from .session import call_with_reauth, ensure_bykc_client
from .storage import AutoBoyaStore, try_get_keyring_password, try_store_keyring_password

HELP_CONTEXT = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, context_settings=HELP_CONTEXT)
user_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, context_settings=HELP_CONTEXT)
courses_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, context_settings=HELP_CONTEXT)
logs_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, context_settings=HELP_CONTEXT)
app.add_typer(user_app, name="user")
app.add_typer(courses_app, name="courses")
app.add_typer(logs_app, name="logs")


@app.command()
def version() -> None:
    typer.echo(f"autoboya {__version__}")


@app.command()
def init() -> None:
    store = AutoBoyaStore()
    store.init()
    typer.echo(f"Initialized {store.root}")


@user_app.command("add")
def user_add(
    username: str,
    password_stdin: bool = typer.Option(False, "--password-stdin"),
    unsafe_store_password: bool = typer.Option(False, "--unsafe-store-password"),
) -> None:
    store = AutoBoyaStore()
    store.init()
    password = sys.stdin.readline().rstrip("\n") if password_stdin else getpass.getpass("Password: ")
    password_ref = "keyring"
    unsafe = False
    if not try_store_keyring_password(username, password):
        if not unsafe_store_password:
            raise typer.BadParameter("Keyring unavailable; rerun with --unsafe-store-password to store in ~/.autoboya/secrets.json")
        store.save_unsafe_password(username, password)
        password_ref = "unsafe-file"
        unsafe = True
    store.upsert_user(UserRecord(username=username, password_ref=password_ref, unsafe_password=unsafe))
    typer.echo(f"Added user {mask(username)}")


@user_app.command("list")
def user_list() -> None:
    store = AutoBoyaStore()
    store.init()
    users = store.user_records()
    if not users:
        typer.echo("No users")
        return
    for user in users:
        status = "enabled" if user.enabled else "disabled"
        typer.echo(f"{mask(user.username)} {status} password={user.password_ref or 'missing'}")


@user_app.command("remove")
def user_remove(username: str) -> None:
    store = AutoBoyaStore()
    store.init()
    removed = store.remove_user(username)
    typer.echo("Removed" if removed else "User not found")


@app.command()
def login(username: str) -> None:
    store = AutoBoyaStore()
    store.init()
    password = password_for(store, username)
    client = AuthClient(store)
    captcha_value: str | None = None
    try:
        try:
            client.preflight_login()
        except CaptchaRequired as exc:
            typer.echo(f"CAPTCHA image: {exc.challenge.image_path}")
            captcha_value = typer.prompt("CAPTCHA")
        session = client.login(username, password, captcha=captcha_value)
    except LoginError as exc:
        typer.echo(f"Login failed: {exc}", err=True)
        raise typer.Exit(1) from None
    store.save_json(
        f"sessions/{username}.json",
        {"bykc_token": session.bykc_token, "cookies": session.cookies},
        mode=0o600,
    )
    typer.echo(f"Logged in {mask(username)}")


@courses_app.command("refresh")
def courses_refresh(username: Optional[str] = typer.Option(None, "--user")) -> None:
    store = AutoBoyaStore()
    store.init()
    user = username or first_username(store)
    cache = CourseCache(store)
    try:
        def refresh(client: BykcClient) -> int:
            courses = client.query_courses()
            cache.save_courses(courses)
            start, end = current_semester_window(client.get_all_config())
            selected = client.query_chosen_courses(start, end)
            cache.save_selected(user, selected)
            cache.save_statistics(user, client.query_statistics())
            return len(courses)

        count = call_with_reauth(store, user, refresh, captcha_provider=prompt_captcha)
    except Exception as exc:
        fail_command(exc)
    typer.echo(f"Refreshed {count} courses using {mask(user)}")


def prompt_captcha(challenge) -> str:
    typer.echo(f"CAPTCHA image: {challenge.image_path}")
    return typer.prompt("CAPTCHA")


@courses_app.command("list")
def courses_list(only_selectable: bool = False, as_json: bool = typer.Option(False, "--json")) -> None:
    from .rules import is_selectable

    cache = CourseCache(AutoBoyaStore())
    now = datetime.now()
    courses = cache.parsed_courses()
    if only_selectable:
        courses = [course for course in courses if is_selectable(course, now)]
    if as_json:
        typer.echo(json.dumps([course_to_view(course) for course in courses], ensure_ascii=False, indent=2))
        return
    for course in courses:
        typer.echo(format_course_line(course))


@courses_app.command("show")
def courses_show(course_id: int, as_json: bool = typer.Option(False, "--json")) -> None:
    cache = CourseCache(AutoBoyaStore())
    course = next((item for item in cache.parsed_courses() if item.id == course_id), None)
    if not course:
        raise typer.BadParameter("Course not found in cache")
    typer.echo(json.dumps(course_to_view(course), ensure_ascii=False, indent=2) if as_json else format_course_line(course))


@courses_app.command("auto-preview")
def courses_auto_preview(as_json: bool = typer.Option(False, "--json")) -> None:
    cache = CourseCache(AutoBoyaStore())
    preview = preview_auto_select_courses(cache.load_courses(), now=datetime.now())
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "candidates": [course_to_view(course) for course in preview.candidates],
                    "excluded": preview.excluded,
                    "generated_at": preview.generated_at.isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not preview.candidates:
        typer.echo("No autonomous-sign courses are currently auto-select candidates")
        return
    for course in preview.candidates:
        typer.echo(format_course_line(course))


@app.command()
def selected(username: Optional[str] = typer.Option(None, "--user"), as_json: bool = typer.Option(False, "--json")) -> None:
    store = AutoBoyaStore()
    cache = CourseCache(store)
    raw = cache.load_selected(username)
    if username:
        courses = [parse_course(item) for item in raw] if isinstance(raw, list) else []
        grouped = classify_selected_courses(courses, datetime.now())
        output = {key: [course_to_view(course) for course in value] for key, value in grouped.items()}
        if not as_json:
            print_selected_table({username: grouped}, include_user=False)
            return
    else:
        output = raw
        if not as_json:
            grouped_by_user = {}
            if isinstance(raw, dict):
                for user, items in raw.items():
                    courses = [parse_course(item) for item in items] if isinstance(items, list) else []
                    grouped_by_user[user] = classify_selected_courses(courses, datetime.now())
            print_selected_table(grouped_by_user, include_user=True)
            return
    typer.echo(json.dumps(output, ensure_ascii=False, indent=2) if as_json else json.dumps(output, ensure_ascii=False))


@app.command()
def stats(username: Optional[str] = typer.Option(None, "--user"), as_json: bool = typer.Option(False, "--json")) -> None:
    data = CourseCache(AutoBoyaStore()).load_statistics(username)
    if not as_json:
        print_stats_table(data, username=username)
        return
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2 if as_json else None))


@app.command()
def run() -> None:
    configure_logging()
    AutomationRunner(AutoBoyaStore()).run_forever()


@app.command()
def stop() -> None:
    AutomationRunner(AutoBoyaStore()).request_stop()
    typer.echo("Stop requested")


@app.command("run-once")
def run_once() -> None:
    results = AutomationRunner(AutoBoyaStore()).run_once()
    typer.echo(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))


@app.command()
def drop(course_id: int, username: Optional[str] = typer.Option(None, "--user"), all_users: bool = False, yes: bool = False) -> None:
    if not username and not all_users:
        raise typer.BadParameter("Use --user or --all-users")
    if not yes:
        raise typer.BadParameter("Real drop requires --yes")
    store = AutoBoyaStore()
    users = [username] if username else [user.username for user in store.user_records()]
    failed = False
    for user in users:
        try:
            call_with_reauth(store, user, lambda client: client.drop_course(course_id), captcha_provider=prompt_captcha)
            typer.echo(f"Dropped {course_id} for {mask(user)}")
        except Exception as exc:
            typer.echo(f"Failed to drop {course_id} for {mask(user)}: {exc}", err=True)
            failed = True
    if failed:
        raise typer.Exit(1)


@app.command()
def sign(course_id: int, username: Optional[str] = typer.Option(None, "--user"), all_users: bool = False) -> None:
    manual_sign(course_id, 1, username, all_users)


@app.command()
def signout(course_id: int, username: Optional[str] = typer.Option(None, "--user"), all_users: bool = False) -> None:
    manual_sign(course_id, 2, username, all_users)


@logs_app.command("tail")
def logs_tail(lines: int = 80) -> None:
    path = AutoBoyaStore().path(LOG_FILE)
    if not path.exists():
        typer.echo("No log file")
        return
    typer.echo("\n".join(path.read_text(encoding="utf-8").splitlines()[-lines:]))


@app.command()
def doctor() -> None:
    store = AutoBoyaStore()
    store.init()
    typer.echo(f"Python: {sys.version.split()[0]}")
    typer.echo(f"Home: {store.root}")
    typer.echo(f"Users: {len(store.user_records())}")
    typer.echo(f"Writable: {store.root.exists() and os_access_writable(store.root)}")


def manual_sign(course_id: int, sign_type: int, username: str | None, all_users: bool) -> None:
    if not username and not all_users:
        raise typer.BadParameter("Use --user or --all-users")
    store = AutoBoyaStore()
    cache = CourseCache(store)
    cached = next((course for course in cache.parsed_courses() if course.id == course_id), None)
    if not cached or not cached.sign_config.get("signPointList"):
        fail_command(MissingSignPoint("No sign point available"))
    point = cached.sign_config["signPointList"][-1]
    lat, lng = random_point_in_radius(float(point["lat"]), float(point["lng"]), float(point.get("radius") or 8))
    users = [username] if username else [user.username for user in store.user_records()]
    action = "sign" if sign_type == 1 else "signout"
    failed = False
    for user in users:
        try:
            call_with_reauth(
                store,
                user,
                lambda client: client.sign_course(course_id, lat, lng, sign_type),
                captcha_provider=prompt_captcha,
            )
            typer.echo(f"{action} {course_id} for {mask(user)}")
        except Exception as exc:
            typer.echo(f"Failed to {action} {course_id} for {mask(user)}: {exc}", err=True)
            failed = True
    if failed:
        raise typer.Exit(1)


def current_semester_window(config: dict[str, object]) -> tuple[str, str]:
    semesters = (((config.get("data") or {}).get("semester") or []) if isinstance(config, dict) else [])
    first = semesters[0] if semesters else {}
    return (
        first.get("semesterStartDate") or "2026-03-01 00:00:00",
        first.get("semesterEndDate") or "2026-06-21 00:00:00",
    )


def first_username(store: AutoBoyaStore) -> str:
    users = store.user_records()
    if not users:
        raise typer.BadParameter("No users configured")
    return users[0].username


def password_for(store: AutoBoyaStore, username: str) -> str:
    password = try_get_keyring_password(username) or store.load_unsafe_password(username)
    if not password:
        raise typer.BadParameter(f"No stored password for {mask(username)}")
    return password


def token_for(store: AutoBoyaStore, username: str) -> str:
    session = store.load_json(f"sessions/{username}.json", {})
    token = session.get("bykc_token")
    if not token:
        raise typer.BadParameter(f"No Boya token for {mask(username)}; run autoboya login {username}")
    return token


def bykc_client_for(store: AutoBoyaStore, username: str) -> BykcClient:
    try:
        return ensure_bykc_client(store, username)
    except LoginError as exc:
        raise typer.BadParameter(str(exc)) from exc


def fail_command(exc: Exception) -> None:
    message = str(exc) or exc.__class__.__name__
    typer.echo(f"Command failed: {message}", err=True)
    raise typer.Exit(1) from None


def console() -> Console:
    return Console(file=sys.stdout, force_terminal=False, color_system=None, width=160)


def print_selected_table(grouped_by_user: dict[str, dict[str, list[object]]], include_user: bool) -> None:
    table = Table(show_header=True, header_style="bold")
    if include_user:
        table.add_column("用户")
    table.add_column("状态")
    table.add_column("课程ID", justify="right")
    table.add_column("课程名称")
    table.add_column("类型")
    table.add_column("签到方式")
    table.add_column("课程时间")
    table.add_column("地点")
    rows = 0
    for username, grouped in grouped_by_user.items():
        for status in ["未开始上课", "已开始上课", "未知"]:
            for course in grouped.get(status, []):
                row = [
                    status,
                    str(course.id),
                    course.name,
                    course.category or "-",
                    course.sign_method,
                    format_time_range(course.course_start, course.course_end),
                    course.location or "-",
                ]
                if include_user:
                    row.insert(0, mask(username))
                table.add_row(*row)
                rows += 1
    if rows == 0:
        empty = ["-", "-", "No selected courses", "-", "-", "-", "-"]
        if include_user:
            empty.insert(0, "-")
        table.add_row(*empty)
    console().print(table)


def print_stats_table(data: dict[str, object], username: str | None = None) -> None:
    table = Table(show_header=True, header_style="bold")
    include_user = username is None
    if include_user:
        table.add_column("用户")
    table.add_column("类型")
    table.add_column("要求", justify="right")
    table.add_column("已选", justify="right")
    table.add_column("完成", justify="right")
    table.add_column("未通过", justify="right")
    table.add_column("未完成", justify="right")
    table.add_column("有效数", justify="right")

    rows = 0
    stats_by_user = {username: data} if username else data
    if isinstance(stats_by_user, dict):
        for user, stats in stats_by_user.items():
            if not isinstance(stats, dict):
                continue
            valid_count = stats.get("validCount", "-")
            for category, item in iter_stat_rows(stats):
                row = [
                    category,
                    str(item.get("assessmentCount", "-")),
                    str(item.get("selectAssessmentCount", "-")),
                    str(item.get("completeAssessmentCount", "-")),
                    str(item.get("failAssessmentCount", "-")),
                    str(item.get("undoneAssessmentCount", "-")),
                    str(valid_count),
                ]
                if include_user:
                    row.insert(0, mask(str(user)))
                table.add_row(*row)
                rows += 1
    if rows == 0:
        empty = ["No statistics", "-", "-", "-", "-", "-", "-"]
        if include_user:
            empty.insert(0, "-")
        table.add_row(*empty)
    console().print(table)


def iter_stat_rows(stats: dict[str, object]):
    statistical = stats.get("statistical")
    if not isinstance(statistical, dict):
        return
    for categories in statistical.values():
        if not isinstance(categories, dict):
            continue
        for key, value in categories.items():
            if isinstance(value, dict):
                yield label_after_pipe(str(key)), value


def label_after_pipe(value: str) -> str:
    return value.split("|", 1)[1] if "|" in value else value


def format_time_range(start: str | None, end: str | None) -> str:
    if start and end:
        return f"{start} - {end}"
    return start or end or "-"


def course_to_view(course) -> dict[str, object]:
    return {
        "id": course.id,
        "name": course.name,
        "selectable": course.selected is False,
        "time": [course.course_start, course.course_end],
        "sign_method": course.sign_method,
        "category": course.category,
        "location": course.location,
        "campus": course.campus,
        "capacity": [course.current_count, course.max_count],
        "select_window": [course.select_start, course.select_end],
        "cancel_end": course.cancel_end,
    }


def format_course_line(course) -> str:
    return f"{course.id} {course.name} {course.category} {course.sign_method} {course.location} {course.course_start or ''}"


def mask(username: str) -> str:
    return username[:3] + "***" if len(username) > 3 else "***"


def os_access_writable(path: Path) -> bool:
    import os

    return os.access(path, os.W_OK)


def main() -> None:
    app()
