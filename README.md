# AutoBoya

Python CLI for BUAA Boya course viewing and guarded automation through WebVPN.

## Quickstart

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

## Command Reference

General:

```bash
autoboya -h
autoboya --help
autoboya version
autoboya init
autoboya doctor
```

Users and login:

```bash
autoboya user add <username> --password-stdin
autoboya user add <username> --unsafe-store-password
autoboya user list
autoboya user remove <username>
autoboya login <username>
```

Courses and cache:

```bash
autoboya courses refresh
autoboya courses refresh --user <username>
autoboya courses list
autoboya courses list --only-selectable
autoboya courses list --json
autoboya courses show <course_id>
autoboya courses show <course_id> --json
autoboya courses auto-preview
autoboya courses auto-preview --json
```

`autoboya courses refresh` fetches the full paginated course list once and refreshes selected-course/statistics caches for every enabled user. Use `--user` to refresh selected-course/statistics caches for only one user.

Selected courses and statistics:

```bash
autoboya selected
autoboya selected --user <username>
autoboya selected --json
autoboya stats
autoboya stats --user <username>
autoboya stats --json
```

Automation:

```bash
autoboya run
autoboya run-once
autoboya stop
```

Manual operations:

```bash
autoboya drop <course_id> --user <username> --yes
autoboya drop <course_id> --all-users --yes
autoboya sign <course_id> --user <username>
autoboya sign <course_id> --all-users
autoboya signout <course_id> --user <username>
autoboya signout <course_id> --all-users
```

Diagnostics:

```bash
autoboya logs tail
autoboya logs tail --lines 200
```

Every command and command group accepts both `-h` and `--help`.

## Automation Policy

AutoBoya does not select every selectable course. The daemon only auto-selects cached courses that are currently selectable and whose sign method is `自主签到`, derived from a non-empty `courseSignConfig.signPointList`. Courses with `常规签到` or no location sign config are skipped. Use `autoboya courses auto-preview` to inspect the courses that would be selected before running the daemon.

CAPTCHA handling follows UBAA: the CLI fetches the SSO CAPTCHA image and asks the operator to type the code. It does not OCR or bypass CAPTCHA.

State is stored under `~/.autoboya`: users, settings, cache, logs, run files, CAPTCHA images, and session metadata.
