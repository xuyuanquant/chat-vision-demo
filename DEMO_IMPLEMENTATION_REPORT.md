# Demo Implementation Report

## 技术栈

Python 3.10+，`requests` HTTP 客户端，`chat-vision-sdk==0.1.0` SDK 客户端，标准库 `http.server` 本地 Viewer，SSE 推送。可选依赖：`mss` 用于 Windows 屏幕截图，`qrcode[pil]` 用于二维码，`pytest` 用于测试。

## 当前目标

本 Demo harness 用于演示一台 Windows 电脑上的完整链路：

1. 检测并截图可见桌面聊天窗口；
2. 新画面通过 `push frame` 上传到 Chat Vision Session；
3. 轮询 frame 状态和 `/messages` cursor；
4. 电脑端显示控制台、消息、结构化数据和 API Calls；
5. 手机扫码进入只读 `/mobile` 消息页；
6. API Key 只存在于本地 Python 进程。

不包含解析内核、目录回放、宣传页、账户、支付、平台 Hook、注入、协议逆向、数据库读取、自动发送、自动点击、自动滚动或远程手机控制。

## 目录结构

- `src/chat_vision_demo/clients.py`：统一客户端接口、Raw HTTP 驱动、SDK 驱动适配。
- `src/chat_vision_demo/runner.py`：Session、Frame、消息 cursor 轮询协调。
- `src/chat_vision_demo/capture.py`：屏幕截图、变化检测、临时截图清理。
- `src/chat_vision_demo/windows_window.py`：Windows 目标聊天窗口定位、DPI-aware 坐标、前台/topmost 处理。
- `src/chat_vision_demo/server.py`：本地 Viewer API、SSE、二维码、截图缩略图接口。
- `src/chat_vision_demo/static/`：桌面控制台和手机只读消息页。
- `scripts/start-windows-demo.ps1`：Windows 启动、pull/install/log 调试脚本。
- `scripts/stop-windows-demo.ps1`：停止 Windows demo 进程。
- `openapi/openapi.json`：实际部署 OpenAPI 副本。
- `tests/`：客户端契约、消息同步、本地服务测试。

## 实际 OpenAPI 契约摘要

已读取 `https://chat.trendflowing.com/openapi.json`。实际契约：

- `POST /v1/sessions` body 为 `platform` 和 `retention_mode`，返回 `session_id/status/created_at/expires_at/retention/request_id`。
- `POST /v1/sessions/{session_id}/frames` 是 multipart，字段为 `file`、必填 `frame_id`、可选 `captured_at`，成功为 `202`，重复/既有状态也可能 `200`。
- `GET /v1/sessions/{session_id}/frames/{frame_id}` 返回 frame 处理状态和 summary。
- `GET /v1/sessions/{session_id}/messages` 使用 opaque `cursor`、`limit`，返回 `items/next_cursor/has_more/request_id`。
- message event 的 `operation` 当前为 `upsert`。
- `/v1/sessions/{session_id}/history` 存在但 deprecated，本 Demo 未作为主路径使用。

需求描述中的 `system` role 与实际契约不同：实际 PublicMessage role 不包含 `system`，`system` 是 `message_type` 枚举。

## HTTP 与 SDK 驱动状态

Raw HTTP 已实现：ready、create、push frame、frame status、messages cursor、close、delete；处理 `X-API-Key`、multipart、`202/200`、ErrorResponse、网络超时/连接失败和 request id。

SDK 驱动已接入 `chat-vision-sdk==0.1.0`：复用 SDK 的 `ChatVision`、sessions、frame push/status、messages cursor、close、delete 能力，并将 SDK dataclass 返回值转换成本地 Viewer 现有的 dict 状态结构。`CHAT_VISION_DRIVER=sdk` 或 `--driver sdk` 可启用；如果 SDK 未安装，会给出明确错误，不会静默 fallback 到 HTTP。

## 启动命令

```powershell
cd C:\path\to\chat-vision-demo
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows-demo.ps1 -ForegroundWindow
```

SDK 模式：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows-demo.ps1 -Driver sdk -ForegroundWindow
```

默认桌面 Viewer：

```text
http://127.0.0.1:8080/
```

手机只读 Viewer：

```text
http://<LAN-IP>:8080/mobile
```

## 当前界面

桌面端：

- 状态栏；
- Target Chat Window 控制区；
- `Detect`、`Manual Once`、`Auto 5s`、`Pause/Resume`、`New Demo`；
- Messages 聊天气泡；
- Structured Data；
- 底部满宽 API Calls 列表，包含截图缩略图、请求参数、request id、状态和 summary；
- 点击缩略图可放大预览。

手机端：

- 只显示 Messages 和轻量状态；
- 无控制按钮；
- 不直接请求云端 API。

## 验证结果

Windows 本机验证：

- Microsoft Store 目标聊天进程：`WeChatStore.exe`；
- 主窗口标题匹配目标聊天窗口；
- 隐藏辅助窗口 `ChatContactMenu` 已过滤；
- DPI-aware 坐标修复后截图区域与可见目标聊天窗口对齐；
- 截图期间临时 topmost，避免从浏览器按钮触发时截到浏览器；
- 手机二维码指向 `/mobile`。

真实云端测试中确认 demo 链路可完成：截图、push frame、frame completed、messages cursor 更新。另发现一例服务端识别问题：截图包含新聊天文本，但 `/messages` 未产出对应新消息；该问题归因于 Chat Vision API 识别/结构化输出，不属于 Demo 本地链路。

## 已运行测试

```text
.venv/bin/pytest
9 passed
```

覆盖：HTTP/SDK 客户端契约、消息 append/upsert/revision/cursor、本地服务状态不泄露 API Key、远程控制限制、二维码 URL。

## API Key 和隐私处理

API Key 来源为环境变量、`.env` 或启动参数，仅保存在本地后端内存中。状态接口只返回是否配置和脱敏标识，不返回完整 Key。Viewer、二维码、JSON 下载不包含完整 Key。截图仅临时保存在系统 temp 目录，用于 push、缩略图展示和调试；`New Demo` 或删除 session 时清理。

## 已知限制

- SDK 适配需要官方 SDK 包名、接口和示例后才能完成。
- 只支持 Windows 可见目标聊天窗口或手动矩形参数，不提供跨平台交互式框选 UI。
- 手机页默认只读；服务不要暴露公网。
- 真实云端 smoke test 需要显式提供脱敏截图目录。

## 推荐演示流程

1. Windows 启动脚本运行 demo。
2. 电脑打开 `http://127.0.0.1:8080/`。
3. 点击 `Detect`，确认识别到目标聊天窗口。
4. 点击 `New Demo`。
5. 点击 `Auto 5s` 或 `Manual Once`。
6. 手机扫码查看 `/mobile` 消息滚动。
7. 需要排查时看底部 API Calls，点击缩略图核对实际上传画面。
