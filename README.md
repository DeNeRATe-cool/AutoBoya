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

## Automation Policy

AutoBoya does not select every selectable course. The daemon only auto-selects cached courses that are currently selectable and whose sign method is `自主签到`, derived from a non-empty `courseSignConfig.signPointList`. Courses with `常规签到` or no location sign config are skipped. Use `autoboya courses auto-preview` to inspect the courses that would be selected before running the daemon.

CAPTCHA handling follows UBAA: the CLI fetches the SSO CAPTCHA image and asks the operator to type the code. It does not OCR or bypass CAPTCHA.

State is stored under `~/.autoboya`: users, settings, cache, logs, run files, CAPTCHA images, and session metadata.
