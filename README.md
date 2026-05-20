# AutoBoya

<p align="center">
  <a href="https://pypi.org/project/autoboya/"><img alt="PyPI" src="https://img.shields.io/pypi/v/autoboya"></a>
  <a href="https://pypi.org/project/autoboya/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/autoboya"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoBoya/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/DeNeRATe-cool/AutoBoya"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoBoya/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/DeNeRATe-cool/AutoBoya?style=flat"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoBoya/commits/main"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/DeNeRATe-cool/AutoBoya/main"></a>
</p>

Python CLI for BUAA Boya course viewing and guarded automation through WebVPN.

AutoBoya can cache Boya course data, display selected courses and statistics,
preview autonomous-sign course candidates, and run a local scheduler for
automatic course selection, check-in, and check-out.

## Quickstart

PyPI package: [`autoboya`](https://pypi.org/project/autoboya/) (`0.1.0`).

```bash
# 1) Install from PyPI
pip install autoboya

# 2) Initialize local state under ~/.autoboya
autoboya init

# 3) Add a BUAA account. The password is stored in the system keyring when possible.
autoboya user add 223xxxxx --password-stdin

# 4) Login through WebVPN. Type the CAPTCHA shown by the CLI when prompted.
autoboya login 223xxxxx

# 5) Refresh course cache and inspect candidates.
autoboya courses refresh
autoboya courses list --only-selectable
autoboya courses auto-preview

# 6) Run one automation pass for debugging, or keep the scheduler running.
autoboya run-once
autoboya run
autoboya stop
```

## PATH Notes

If `autoboya` is not found after installation, use Python's module entry point
first:

```bash
python -m autoboya --help
```

Then add the user script directory to your shell PATH.

macOS / Linux:

```bash
python -m pip install --user autoboya
echo 'export PATH="$(python3 -m site --user-base)/bin:$PATH"' >> ~/.zprofile
```

Windows PowerShell:

```powershell
py -m pip install --user autoboya
$d = py -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"; [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";" + $d, "User")
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
autoboya select <course_id> --user <username> --yes
autoboya select <course_id> --all-users --yes
autoboya drop <course_id> --user <username> --yes
autoboya drop <course_id> --all-users --yes
autoboya sign <course_id> --user <username>
autoboya sign <course_id> --all-users
autoboya signout <course_id> --user <username>
autoboya signout <course_id> --all-users
```

`sign` and `signout` require the course to already be selected. Use `select` first, then sign during the configured sign window. `drop` accepts a course ID and refreshes the selected-course cache after a successful drop.

Diagnostics:

```bash
autoboya logs tail
autoboya logs tail --lines 200
```

Every command and command group accepts both `-h` and `--help`.

## Automation Policy

AutoBoya does not select every selectable course. The daemon only auto-selects cached courses that are currently selectable, whose sign method is `自主签到`, derived from a non-empty `courseSignConfig.signPointList`, and whose category is not `其他方面`. Courses with `常规签到`, no location sign config, or category `其他方面` are skipped. Use `autoboya courses auto-preview` to inspect the courses that would be selected before running the daemon.

CAPTCHA handling follows UBAA: the CLI fetches the SSO CAPTCHA image and asks the operator to type the code. It does not OCR or bypass CAPTCHA.

State is stored under `~/.autoboya`: users, settings, cache, logs, run files, CAPTCHA images, and session metadata.
