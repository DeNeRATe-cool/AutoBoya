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

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    context_settings=HELP_CONTEXT,
    help="北航博雅课程查看、选课、签到和后台自动化工具。",
)
user_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, context_settings=HELP_CONTEXT, help="管理本地账号。")
courses_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, context_settings=HELP_CONTEXT, help="查看课程、刷新缓存和预览自动选课。")
logs_app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False, context_settings=HELP_CONTEXT, help="查看后台运行日志。")
app.add_typer(user_app, name="user", help="管理账号。")
app.add_typer(courses_app, name="courses", help="查看课程。")
app.add_typer(logs_app, name="logs", help="查看日志。")


@app.command(help="显示 autoboya 版本。")
def version() -> None:
    typer.echo(f"autoboya {__version__}")


@app.command(help="初始化 ~/.autoboya 数据目录。")
def init() -> None:
    store = AutoBoyaStore()
    store.init()
    typer.echo(f"Initialized {store.root}")


@user_app.command("add", help="添加账号并保存密码。默认优先保存到系统钥匙串。")
def user_add(
    username: str = typer.Argument(..., help="学号或统一认证账号。"),
    campus: str = typer.Option("北京", "--campus", help="用户所属校区：北京或杭州。后台自动选课会按此过滤课程。"),
    password_stdin: bool = typer.Option(False, "--password-stdin", help="从标准输入读取密码，适合脚本使用。"),
    unsafe_store_password: bool = typer.Option(False, "--unsafe-store-password", help="钥匙串不可用时明文保存到 ~/.autoboya/secrets.json。"),
) -> None:
    store = AutoBoyaStore()
    store.init()
    if campus not in {"北京", "杭州"}:
        raise typer.BadParameter("--campus must be 北京 or 杭州")
    password = sys.stdin.readline().rstrip("\n") if password_stdin else getpass.getpass("Password: ")
    password_ref = "keyring"
    unsafe = False
    if not try_store_keyring_password(username, password):
        if not unsafe_store_password:
            raise typer.BadParameter("Keyring unavailable; rerun with --unsafe-store-password to store in ~/.autoboya/secrets.json")
        store.save_unsafe_password(username, password)
        password_ref = "unsafe-file"
        unsafe = True
    store.upsert_user(UserRecord(username=username, password_ref=password_ref, unsafe_password=unsafe, campus=campus))
    typer.echo(f"Added user {mask(username)}")


@user_app.command("list", help="列出已添加账号。")
def user_list() -> None:
    store = AutoBoyaStore()
    store.init()
    users = store.user_records()
    if not users:
        typer.echo("No users")
        return
    for user in users:
        status = "enabled" if user.enabled else "disabled"
        typer.echo(f"{mask(user.username)} {status} campus={user.campus} password={user.password_ref or 'missing'}")


@user_app.command("remove", help="移除本地账号记录。")
def user_remove(username: str = typer.Argument(..., help="要移除的账号。")) -> None:
    store = AutoBoyaStore()
    store.init()
    removed = store.remove_user(username)
    typer.echo("Removed" if removed else "User not found")


@app.command(help="交互式登录账号；如果需要验证码会显示图片路径并提示输入。")
def login(username: str = typer.Argument(..., help="要登录的账号。")) -> None:
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


@courses_app.command("refresh", help="刷新课程缓存；默认刷新全量课程和所有启用账号的已选/统计缓存。")
def courses_refresh(username: Optional[str] = typer.Option(None, "--user", help="只刷新指定账号的已选课程和统计。")) -> None:
    store = AutoBoyaStore()
    store.init()
    users = [username] if username else enabled_usernames(store)
    if not users:
        raise typer.BadParameter("No enabled users configured")
    pool_user = users[0]
    cache = CourseCache(store)
    try:
        def refresh_pool(client: BykcClient) -> tuple[int, str, str]:
            courses = client.query_courses()
            cache.save_courses(courses)
            start, end = current_semester_window(client.get_all_config())
            return len(courses), start, end

        count, start, end = call_with_reauth(store, pool_user, refresh_pool, captcha_provider=prompt_captcha)
        for user in users:
            refresh_user_caches(store, user, start, end)
    except Exception as exc:
        fail_command(exc)
    typer.echo(f"Refreshed {count} courses using {mask(pool_user)}; updated {len(users)} user(s)")


def prompt_captcha(challenge) -> str:
    typer.echo(f"CAPTCHA image: {challenge.image_path}")
    return typer.prompt("CAPTCHA")


def enabled_usernames(store: AutoBoyaStore) -> list[str]:
    return [user.username for user in store.user_records() if user.enabled]


def refresh_user_caches(store: AutoBoyaStore, user: str, start: str, end: str) -> None:
    cache = CourseCache(store)

    def refresh_user(client: BykcClient) -> None:
        selected = client.query_chosen_courses(start, end)
        cache.save_selected(user, selected)
        cache.save_statistics(user, client.query_statistics())

    call_with_reauth(store, user, refresh_user, captcha_provider=prompt_captcha)


def select_and_refresh_user(store: AutoBoyaStore, user: str, course_id: int) -> None:
    cache = CourseCache(store)

    def select_and_refresh(client: BykcClient) -> None:
        client.select_course(course_id)
        start, end = current_semester_window(client.get_all_config())
        cache.save_selected(user, client.query_chosen_courses(start, end))
        cache.save_statistics(user, client.query_statistics())

    call_with_reauth(store, user, select_and_refresh, captcha_provider=prompt_captcha)


@courses_app.command("list", help="查看本地缓存课程列表。")
def courses_list(
    only_selectable: bool = typer.Option(False, "--only-selectable", help="只显示当前处于选课窗口、未满员、未选中的课程。"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出。"),
) -> None:
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


@courses_app.command("show", help="查看某一门课程详情。")
def courses_show(
    course_id: int = typer.Argument(..., help="课程 ID。"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出。"),
) -> None:
    cache = CourseCache(AutoBoyaStore())
    course = next((item for item in cache.parsed_courses() if item.id == course_id), None)
    if not course:
        raise typer.BadParameter("Course not found in cache")
    typer.echo(json.dumps(course_to_view(course), ensure_ascii=False, indent=2) if as_json else format_course_line(course))


@courses_app.command("auto-preview", help="预览后台会自动选择的课程。只包含自主签到课程，并排除其他方面。")
def courses_auto_preview(as_json: bool = typer.Option(False, "--json", help="以 JSON 输出候选和排除原因。")) -> None:
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


@app.command(help="查看已选课程；默认表格展示，可按账号筛选。")
def selected(
    username: Optional[str] = typer.Option(None, "--user", help="只查看指定账号。"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出。"),
) -> None:
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


@app.command(help="查看博雅课程类型统计。")
def stats(
    username: Optional[str] = typer.Option(None, "--user", help="只查看指定账号。"),
    as_json: bool = typer.Option(False, "--json", help="以 JSON 输出。"),
) -> None:
    data = CourseCache(AutoBoyaStore()).load_statistics(username)
    if not as_json:
        print_stats_table(data, username=username)
        return
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2 if as_json else None))


@app.command(help="启动后台自动化循环：每小时刷新、每分钟扫描可选/可签到/可签退动作。")
def run() -> None:
    configure_logging()
    AutomationRunner(AutoBoyaStore()).run_forever()


@app.command(help="请求停止后台自动化循环。")
def stop() -> None:
    AutomationRunner(AutoBoyaStore()).request_stop()
    typer.echo("Stop requested")


@app.command("run-once", help="立即执行一次刷新、自动选课、签到和签退扫描。会产生真实操作。")
def run_once() -> None:
    results = AutomationRunner(AutoBoyaStore()).run_once()
    typer.echo(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))


@app.command("select", help="手动选课。会产生真实选课操作，需要 --yes 确认。")
def select_course_command(
    course_id: int = typer.Argument(..., help="要选择的课程 ID。"),
    username: Optional[str] = typer.Option(None, "--user", help="只为指定账号选课。"),
    all_users: bool = typer.Option(False, "--all-users", help="为所有本地账号选课。"),
    yes: bool = typer.Option(False, "--yes", help="确认执行真实选课操作。"),
) -> None:
    if not username and not all_users:
        raise typer.BadParameter("Use --user or --all-users")
    if not yes:
        raise typer.BadParameter("Real select requires --yes")
    store = AutoBoyaStore()
    users = [username] if username else [user.username for user in store.user_records()]
    failed = False
    for user in users:
        try:
            select_and_refresh_user(store, user, course_id)
            typer.echo(f"Selected {course_id} for {mask(user)}")
        except Exception as exc:
            typer.echo(f"Failed to select {course_id} for {mask(user)}: {exc}", err=True)
            failed = True
    if failed:
        raise typer.Exit(1)


@app.command(help="手动退课。使用课程 ID 退课；会产生真实操作，需要 --yes 确认。")
def drop(
    course_id: int = typer.Argument(..., help="要退选的课程 ID。"),
    username: Optional[str] = typer.Option(None, "--user", help="只为指定账号退课。"),
    all_users: bool = typer.Option(False, "--all-users", help="为所有本地账号退课。"),
    yes: bool = typer.Option(False, "--yes", help="确认执行真实退课操作。"),
) -> None:
    if not username and not all_users:
        raise typer.BadParameter("Use --user or --all-users")
    if not yes:
        raise typer.BadParameter("Real drop requires --yes")
    store = AutoBoyaStore()
    users = [username] if username else [user.username for user in store.user_records()]
    failed = False
    for user in users:
        try:
            selected_course = selected_course_for_user(store, user, course_id)
            if not selected_course:
                raise RuntimeError(f"course {course_id} is not selected for {mask(user)}; run autoboya selected --user {user}")
            call_with_reauth(store, user, lambda client: client.drop_course(course_id), captcha_provider=prompt_captcha)
            refresh_current_user_cache(store, user)
            typer.echo(f"Dropped {course_id} for {mask(user)}")
        except Exception as exc:
            typer.echo(f"Failed to drop {course_id} for {mask(user)}: {exc}", err=True)
            failed = True
    if failed:
        raise typer.Exit(1)


@app.command(help="手动签到。会从签到点范围内随机生成坐标并提交真实签到。")
def sign(
    course_id: int = typer.Argument(..., help="要签到的课程 ID。"),
    username: Optional[str] = typer.Option(None, "--user", help="只为指定账号签到。"),
    all_users: bool = typer.Option(False, "--all-users", help="为所有本地账号签到。"),
) -> None:
    manual_sign(course_id, 1, username, all_users)


@app.command(help="手动签退。会从签到点范围内随机生成坐标并提交真实签退。")
def signout(
    course_id: int = typer.Argument(..., help="要签退的课程 ID。"),
    username: Optional[str] = typer.Option(None, "--user", help="只为指定账号签退。"),
    all_users: bool = typer.Option(False, "--all-users", help="为所有本地账号签退。"),
) -> None:
    manual_sign(course_id, 2, username, all_users)


@logs_app.command("tail", help="查看日志文件末尾内容。")
def logs_tail(lines: int = typer.Option(80, "--lines", help="显示最后多少行日志。")) -> None:
    path = AutoBoyaStore().path(LOG_FILE)
    if not path.exists():
        typer.echo("No log file")
        return
    typer.echo("\n".join(path.read_text(encoding="utf-8").splitlines()[-lines:]))


@app.command(help="检查 Python 版本、数据目录、用户数量和目录可写性。")
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
    users = [username] if username else [user.username for user in store.user_records()]
    action = "sign" if sign_type == 1 else "signout"
    failed = False
    for user in users:
        try:
            selected_course = selected_course_for_user(store, user, course_id)
            if not selected_course:
                raise RuntimeError(f"course {course_id} is not selected for {mask(user)}; run autoboya select {course_id} --user {user} --yes first")
            sign_course = selected_course if selected_course.sign_config.get("signPointList") else cached
            if not sign_course or not sign_course.sign_config.get("signPointList"):
                raise MissingSignPoint("No sign point available")
            point = sign_course.sign_config["signPointList"][-1]
            lat, lng = random_point_in_radius(float(point["lat"]), float(point["lng"]), float(point.get("radius") or 8))
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


def selected_course_for_user(store: AutoBoyaStore, username: str, course_id: int):
    raw = CourseCache(store).load_selected(username)
    if not isinstance(raw, list):
        return None
    for item in raw:
        course = parse_course(item)
        if course.id == course_id:
            return course
    return None


def refresh_current_user_cache(store: AutoBoyaStore, user: str) -> None:
    cache = CourseCache(store)

    def refresh(client: BykcClient) -> None:
        start, end = current_semester_window(client.get_all_config())
        cache.save_selected(user, client.query_chosen_courses(start, end))
        cache.save_statistics(user, client.query_statistics())

    call_with_reauth(store, user, refresh, captcha_provider=prompt_captcha)


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
            show_valid_count = True
            for category, item in iter_stat_rows(stats):
                row = [
                    category,
                    str(item.get("assessmentCount", "-")),
                    str(item.get("selectAssessmentCount", "-")),
                    str(item.get("completeAssessmentCount", "-")),
                    str(item.get("failAssessmentCount", "-")),
                    str(item.get("undoneAssessmentCount", "-")),
                    str(valid_count) if show_valid_count else "",
                ]
                show_valid_count = False
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
