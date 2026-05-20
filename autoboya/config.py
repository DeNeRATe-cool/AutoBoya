from __future__ import annotations

import os
from pathlib import Path

USERS_FILE = "users.json"
SETTINGS_FILE = "settings.json"
SECRETS_FILE = "secrets.json"
COURSE_CACHE_FILE = "cache/courses.json"
SELECTED_CACHE_FILE = "cache/selected.json"
STATISTICS_CACHE_FILE = "cache/statistics.json"
ACTION_JOURNAL_FILE = "cache/action_journal.json"
RUN_PID_FILE = "run/autoboya.pid"
STOP_FILE = "run/stop.request"
LOG_FILE = "logs/autoboya.log"
SESSION_DIR = "sessions"


def app_dir() -> Path:
    override = os.environ.get("AUTOBOYA_HOME")
    return Path(override).expanduser() if override else Path.home() / ".autoboya"
