# 儿童手表 / 终端协议 TCP 网关（V4.2）

本仓库实现《设备通信协议 V4.2》的 **TCP 接收**、**按长度字段组帧**、**指令解析与平台侧默认应答**，以及基于 FastAPI + Jinja2 + HTMX 的 **Web 管理界面**（设备列表、报文流、指令 JSON、UD 坐标地图、媒体下载）。

## 目录说明

- `app/protocol/framing.py`：字节级组帧与 `build_frame` / `frame_to_bytes`
- `app/protocol/dispatch.py`：平台默认下行应答（`INIT` / `LGZONE` / `LK` / `UD` / `JXTK` / `SENDPHOTO` 等）
- `app/protocol/parsers/`：各指令解析与 `SENDPHOTO` 十六进制或原始二进制、`JXTK` 转义
- `app/tcp_server.py`：asyncio TCP 服务，入库并写回应答
- `app/main.py`：FastAPI 应用与页面路由；启动时同时监听 TCP
- `app/web/templates/`：管理端模板
- `data/`：默认 SQLite 与上传媒体（首次运行自动创建）

## 数据存储（接收到的数据是否保存？）

**会保存。** 手表每发来一帧（以及服务器回的每一帧），都会在**服务器本机磁盘**上留下记录，重启进程后仍在（除非删库或换路径）。

| 存什么 | 存在哪 | 说明 |
|--------|--------|------|
| 每台手表档案 | SQLite 表 `devices` | 编号、厂商、首次/最后在线、上次电量、上次经纬度等 |
| 每一条原始通信 | SQLite 表 `raw_messages` | 方向（手表→服务器 / 服务器→手表）、完整一帧文本、时间、是否解析成功 |
| 按指令解析后的摘要 | SQLite 表 `command_events` | 指令名、流水号、结构化 JSON 摘要、可选十六进制预览 |
| 照片 / 语音附件 | 目录 `data/files/`（可用 `FILES_DIR` 改） | `SENDPHOTO`、终端上报的 `JXTK` 音频等二进制落盘；库里记文件路径 |

默认数据库文件路径见环境变量 **`DATABASE_URL`**（一般为项目下 `data/watch.db`）。部署时请**备份**该文件和 **`data/files/`**，以免重装或误删丢历史数据。

实现入口：收到 TCP 完整帧后在 [`app/tcp_server.py`](app/tcp_server.py) 的 `process_inbound_frame` 里 `session.add(...)` 并 `commit`；模型定义见 [`app/db/models.py`](app/db/models.py)。

## 依赖

见 `requirements.txt`。请在**你本机**自行创建虚拟环境并安装（本仓库脚本不代你执行安装）：

```bash
cd /path/to/watch
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `TCP_HOST` | `0.0.0.0` | TCP 监听地址 |
| `TCP_PORT` | `9000` | TCP 端口（设备连此端口） |
| `WEB_HOST` | `127.0.0.1` | HTTP 仅作文档提示；实际由 uvicorn 参数决定 |
| `WEB_PORT` | `8000` | 同上 |
| `DATABASE_URL` | `sqlite+aiosqlite:///.../data/watch.db` | 异步 SQLite |
| `ADMIN_USER` / `ADMIN_PASS` | `admin` / `change-me` | 管理端 Basic 认证 |
| `FILES_DIR` | `./data/files` | `SENDPHOTO` / `JXTK` 媒体落盘目录 |
| `PLATFORM_TZ_OFFSET_HOURS` | `8` | `LGZONE` 回复中的时区偏移（相对 UTC） |

## 运行（本机调试）

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- **设备 TCP**：`TCP_HOST:TCP_PORT`（默认 `0.0.0.0:9000`）
- **管理 Web**：浏览器访问 `http://<主机>:8000/`，使用 Basic 账号登录

### 出现 Internal Server Error（500）时

1. **看运行 `uvicorn` 的终端**：一般会打印 Python 报错栈（Traceback），把这一段保存下来排查。
2. **先试无需登录的接口**：`curl http://127.0.0.1:8000/health` 若返回 `{"status":"ok"}`，说明进程正常，问题多半在具体页面或数据库。
3. **SQLite 并发**：TCP 与 Web 同时访问同一库时，旧版本可能出现 `database is locked`。当前代码已对 SQLite 开启 **WAL** 与 **busy_timeout**（见 `app/db/session.py`），请拉取最新代码后重启。
4. **权限**：确保项目目录下能创建并写入 `data/watch.db` 与 `data/files/`（`chmod` / 不要用只读用户跑在无写权限目录）。
5. **模板是否齐全**：若手工上传代码，确认 `app/web/templates/` 下文件完整。

## 部署到服务器

### 用图形界面还是命令行？

- **云服务器本身**：一般用 **无桌面的 Linux（命令行 + SSH）**。不装 GNOME/KDE，省内存、更稳定，这是行业常规做法。
- **你操作的方式**：
  - 在自己电脑上打开 **云厂商控制台网页**（算「图形化」）创建机器、开安全组、看监控；
  - 登录服务器用 **SSH 终端**（Windows 可用 PowerShell、`ssh`；Mac/Linux 用终端）执行安装和启动命令。
- **管理业务数据**：用浏览器打开本项目的 **Web 后台**（图形界面），给客户看即可，无需在服务器上开桌面。

### 操作系统推荐

| 场景 | 建议 |
|------|------|
| 通用、资料多 | **Ubuntu Server 22.04 / 24.04 LTS** 或 **Debian 12** |
| 国内云、要兼容 RHEL 系 | **AlmaLinux 8/9**、**Rocky Linux** |
| 不推荐 | 带完整桌面的服务器镜像（浪费资源）；过旧已停更的系统 |

本项目是 Python 3.10+ 即可，与具体发行版关系不大，选 **长期支持（LTS）** 版本更省心。

### 重要限制：进程数必须为 1

当前架构里 **TCP 监听与 HTTP 在同一个进程里** 启动。部署时请使用 **单个 Uvicorn 进程**（**不要**把 `uvicorn --workers` 或 Gunicorn 多 worker 开到大于 1，否则多个进程会争抢同一个 TCP 端口导致启动失败或行为异常）。

### 部署步骤概要

1. **安全组 / 防火墙** 放行：
   - **TCP 端口**（默认 `9000`）：给手表连；
   - **HTTP 端口**（默认 `8000`）：给浏览器访问后台；生产建议前面加 **Nginx** 并只对外暴露 **443（HTTPS）**。
2. 把本仓库拷到服务器（`git clone` 或上传）。
3. 安装 **Python 3.10+**，创建虚拟环境并 `pip install -r requirements.txt`。
4. 设置环境变量（至少改 `ADMIN_PASS`；`DATABASE_URL` / `FILES_DIR` 若改路径请保证目录存在且进程可写）。
5. 用 **systemd** 常驻运行 Uvicorn（示例见下）。
6. 手表后台或短信 **SETIP** 里填：**服务器公网 IP + TCP 端口**（与 `TCP_PORT` 一致）。

### systemd 示例（`/etc/systemd/system/watch-gateway.service`）

请把 `User`、`WorkingDirectory`、`EnvironmentFile` 换成你的实际路径与配置。

```ini
[Unit]
Description=Watch TCP + Web gateway
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/watch
EnvironmentFile=-/opt/watch/.env
ExecStart=/opt/watch/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

在 `.env` 中可写（示例）：

```bash
TCP_HOST=0.0.0.0
TCP_PORT=9000
ADMIN_USER=admin
ADMIN_PASS=你的强密码
```

注意：`EnvironmentFile` 里的变量需被进程读取；若你用 `export` 手动启动则直接 `export` 即可。若 systemd 未自动加载 `.env`，可在 `ExecStart` 前使用 `Environment=` 逐行写，或让启动脚本 `source .env`。

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now watch-gateway
sudo systemctl status watch-gateway
```

### 生产环境可选增强

- **HTTPS**：前面加 **Nginx**（或 Caddy），`proxy_pass` 到 `127.0.0.1:8000`，证书用 Let’s Encrypt。
- **数据库**：访问量变大时把 `DATABASE_URL` 换成 **PostgreSQL**（需自行改连接串并保证 SQLAlchemy 兼容；表结构可沿用）。
- **备份**：定期备份 `data/watch.db` 与 `data/files/`。

## 协议注意点

1. **组帧**：`内容长度` 为「指令内容」的 **字节长度**（十六进制 4 位），二进制指令必须按字节计数。
2. **`INIT`**：必须回复 `INIT,1`，否则设备可能不再发后续包。
3. **`LK` / 部分时间字段**：文档要求平台使用 **UTC**；若你服务器系统时间为北京时间，实现中已按 UTC 生成 `LK` 与 `GETLOC` 内时间戳。
4. **`LGZONE`**：回复格式中带本地时区偏移，由 `PLATFORM_TZ_OFFSET_HOURS` 控制。
5. **厂商前缀**：下行帧使用与上行相同的 `vendor` 字段（不硬编码 `ZJ`）。
6. **默认应答**：部分社交/业务指令（如 `MFD`/`QFD`/`WT`）为 **占位数据**，接入生产前请按业务替换。

## 测试

```bash
pytest
```

## 许可证

按你的项目需要自行补充。
