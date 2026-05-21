# AutoBoya

<p align="center">
  <a href="https://pypi.org/project/autoboya/"><img alt="PyPI" src="https://img.shields.io/pypi/v/autoboya"></a>
  <a href="https://pypi.org/project/autoboya/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/autoboya"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoBoya/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/DeNeRATe-cool/AutoBoya"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoBoya/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/DeNeRATe-cool/AutoBoya?style=flat"></a>
  <a href="https://github.com/DeNeRATe-cool/AutoBoya/commits/main"><img alt="Last Commit" src="https://img.shields.io/github/last-commit/DeNeRATe-cool/AutoBoya/main"></a>
</p>

AutoBoya 是一个用于北航博雅系统的 Python 命令行工具。它通过 WebVPN 登录博雅系统，支持课程缓存、课程列表查看、已选课程与课程类型统计展示，并可以在本地后台循环中执行自主签到课程的自动选课、签到和签退。

## 快速开始

PyPI 包名：[`autoboya`](https://pypi.org/project/autoboya/)（当前版本 `0.1.3`）。

```bash
# 1. 从 PyPI 安装
pip install autoboya

# 2. 初始化本地数据目录，默认位于 ~/.autoboya
autoboya init

# 3. 添加北航账号。优先使用系统钥匙串保存密码
#    --campus 支持 北京 / 杭州，默认北京
autoboya user add 223xxxxx --campus 北京 --password-stdin

# 4. 通过 WebVPN 登录。若需要验证码，命令会显示验证码图片路径并等待输入
autoboya login 223xxxxx

# 5. 刷新课程缓存并查看可选课程、自动选课预览
autoboya courses refresh
autoboya courses list --only-selectable
autoboya courses auto-preview

# 6. 调试时执行一轮自动化，或启动长期后台循环
autoboya run-once
autoboya run
autoboya stop
```

## PATH 说明

如果安装后提示找不到 `autoboya` 命令，可以先使用 Python 模块入口：

```bash
python -m autoboya --help
```

然后将 Python 用户脚本目录加入系统 PATH。

macOS / Linux：

```bash
python -m pip install --user autoboya
echo 'export PATH="$(python3 -m site --user-base)/bin:$PATH"' >> ~/.zprofile
```

Windows PowerShell：

```powershell
py -m pip install --user autoboya
$d = py -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))"; [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";" + $d, "User")
```

## 命令速查

通用命令：

```bash
autoboya -h
autoboya --help
autoboya version
autoboya init
autoboya doctor
```

账号与登录：

```bash
autoboya user add <username> --password-stdin
autoboya user add <username> --campus 北京 --password-stdin
autoboya user add <username> --campus 杭州 --password-stdin
autoboya user add <username> --unsafe-store-password
autoboya user list
autoboya user remove <username>
autoboya login <username>
```

`--campus` 表示用户所属校区，只接受 `北京` 或 `杭州`，默认值为 `北京`。旧版本已经添加过的用户会按 `北京` 处理；重新执行 `autoboya user add <username> --campus 杭州 ...` 可以更新用户校区。

课程与缓存：

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

`autoboya courses refresh` 会完整分页拉取课程列表，并为所有已启用用户刷新已选课程和统计缓存。使用 `--user` 可以只刷新指定用户的已选课程和统计缓存。

已选课程与统计：

```bash
autoboya selected
autoboya selected --user <username>
autoboya selected --json
autoboya stats
autoboya stats --user <username>
autoboya stats --json
```

后台自动化：

```bash
autoboya run
autoboya run-once
autoboya stop
```

`autoboya run` 会启动后台进程后立即返回，不会在当前终端持续输出循环日志。后台日志写入 `~/.autoboya/logs/autoboya.log`，可以用 `autoboya logs tail` 查看。后台每分钟扫描本地缓存时会写入 `automation heartbeat`，其中包含本轮参与轮询的已启用用户、命中的动作数量和距离下次远端刷新约多少秒。`autoboya run-once` 仍在当前终端执行单轮扫描，适合调试。

手动操作：

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

`select` 和 `drop` 是真实选课/退课操作，需要显式传入 `--yes` 确认。`sign` 和 `signout` 要求课程已经被对应用户选中，并会在签到点范围内随机生成坐标后提交真实签到或签退请求。

日志：

```bash
autoboya logs tail
autoboya logs tail --lines 200
```

所有命令和命令组都支持 `-h` 与 `--help`。

## 自动化策略

AutoBoya 不会自动选择所有可选课程。后台循环只会自动选择同时满足以下条件的缓存课程：

- 当前处于可选时间窗口内；
- 课程未满；
- 签到方式为“自主签到”，依据是 `courseSignConfig.signPointList` 非空；
- 课程分类不是“其他方面”。

“常规签到”、没有位置签到配置、分类为“其他方面”的课程都会被跳过。运行 `autoboya courses auto-preview` 可以在启动后台自动化前查看当前会被自动选课策略纳入的课程。

后台执行真实自动选课时还会按用户校区过滤课程：系统会扫描课程名 `name`、课程地点 `location` 和校区字段 `campus`，只要其中出现“杭州”，就判定为杭州课程。`--campus 杭州` 的用户只会自动选择杭州课程；`--campus 北京` 的用户会自动选择非杭州课程。手动 `autoboya select` 不做这层校区过滤，仍以操作者明确指定的课程 ID 为准。

验证码处理方式与 UBAA 保持一致：命令会下载 SSO 验证码图片并提示操作者手动输入，不进行 OCR，也不绕过验证码。

## 本地数据

AutoBoya 的本地状态默认存储在 `~/.autoboya`，包括账号元数据、设置、课程缓存、已选课程缓存、统计缓存、日志、运行状态文件、验证码图片和会话元数据。
