# AGENTS.md

fotil 是一个相机照片/视频处理工具。

功能：

1. 导入去重
2. 从 GPS 日志/其他文件/Sony sidecar XML 恢复时间与 GPS 元数据
3. 本地 Web UI 选片并清理 raw 文件

## Python coding

1. 使用 uv 管理依赖
2. 使用 ruff 格式化代码和 lint，规则文件 `ruff.toml`
   - 不动已有代码的格式，仅针对新、改动代码使用 ruff 格式化
3. 使用 Python 3.14
4. 优先使用 `pathlib` 而不是 `os.path`
5. 注释语言与代码文件中其他地方保持一致

## 目录

- `src/fotil/` — 核心模块：`config.py`（msgspec Struct 配置）、`exiftool.py`（exiftool 命令封装）、`importer.py`、`filedb.py`（导入去重哈希库）、`fs.py`、`library.py`
- `src/fotil/cli/` — typer 命令：`geotag.py`（最大最复杂）、`importer.py`、`library.py`、`web.py`、`filedb.py`
- `src/fotil/web/` — Litestar + Jinja2 + htmx 的 Web UI：`routes.py`、`service.py`、`transcode.py`（HEIF→JPEG 预览），`static/` 中 htmx/alpine 为内嵌 vendor 文件；Tailwind 经 `tailwind.input.css` 预编译为 `static/tw.css`（依赖见同目录 `package.json`）
- `tests/` — pytest，测试媒体在 `tests/data/`
- `docs/samples/` — iPhone 16 / Sony A7M4 样本文件的元数据行为详解

## 命令

```bash
uv sync                              # 安装依赖
uv run pytest                        # 全部测试
uv run pytest tests/test_geotag.py   # 单个文件
uv run pytest tests/test_web_routes.py -k cleanup   # 按名筛选
uv run ruff check --fix .            # lint（规则见 ruff.toml）
uv run ruff format .                 # 格式化
uv run fotil -h                      # 运行 CLI（需 exiftool 在 PATH）
uv run fotil web                     # 启动 web 服务
```

无独立 typechecker。Python 要求 >=3.14。

修改模板或 `static/app.js` 用到新 Tailwind class 后，必须重跑再生成命令更新 `static/tw.css`，否则新类无样式（首次需先 `cd src/fotil/web && npm install`）：

```bash
npx @tailwindcss/cli@4.3.3 -i src/fotil/web/tailwind.input.css -o src/fotil/web/static/tw.css
```

## 架构边界

- CLI 入口 `fotil.__main__:app`；新增命令模块后必须在 `__main__.py` 中 import 注册（参考现有写法）。
- 配置在 `~/.config/fotil/fotil.toml`（`--config` 可覆盖），`cli/__init__.py` 的 `get_config()` 惰性加载；Web 端每请求重新读配置文件。
- CLI 层做参数解析与输出，业务逻辑放核心模块；web 的 `service.py` 不 import typer。
- 库（Library）三目录：`pic_dir`/`raw_dir` 按文件 stem（不含扩展名）一一对应，`trash_dir` 是清理目标。

## 关键约束与坑

- **永不删除文件**：清理只把文件 move 到 `trash_dir`，保持原目录结构，便于手工恢复。不要引入 unlink/delete。
- **视频时间戳语义微妙**（改 geotag 前必读 `docs/samples/README.md` 和 `exiftool.py` 中 `EXIF_VIDEO_ALL_DATE_TAGS` 的注释）
- **exiftool 是外部二进制**，需在 PATH 中；改动 geotag 后 exiftool 读回并不保证一定正确
  - 照片，视频分别需要用 Preview.app, QuickTime.app 打开 inspector 查看确认
- HEIF/HIF 预览转码：macOS 优先 `sips` 后端，Pillow 兜底，`FOTIL_TRANSCODER=sips|pillow` 可强制；缓存在 `~/.cache/fotil/web`。
- `tests/data/` 里的样本文件是真实相机文件，测试依赖其真实元数据，不要重新生成或压缩。

## 代码风格

- ruff：行长 90、单引号、isort（fotil 为 first-party，import 后空 2 行、import/from 之间空 1 行）
  - 以 `ruff.toml` 为准
- 代码注释与 docstring 用英文；README 等文档用英文；调查/计划笔记可用中文

## Git

- 主分支 `main`；提交信息为祈使句、以句号结尾，常带领域前缀
  - 如 `web: add lightbox viewer with keyboard culling.`
