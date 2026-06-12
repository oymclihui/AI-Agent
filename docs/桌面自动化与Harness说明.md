# 桌面自动化与 Agent Harness 说明

本文档说明 **桌面 GUI 自动化（Sidecar）** 与 **Agent Harness（工具策略与确认门控）** 的使用方式、配置项与 API。面向 Windows 办公机用户与平台管理员。

**相关文档：** [用户操作手册](./用户操作手册.md) · [Windows 交付说明](./Windows交付说明.md) · [platform-roadmap.md](../backend/app/knowledge/data/platform-roadmap.md)

---

## 一、架构概览

```
浏览器（Chat / 桌面自动化页 / 智能体）
        ↓ API
   平台后端（:8000）
        ↓ 任务队列 / Harness 门控
   本机 Sidecar（Windows .exe 或 Python）
        ↓
   用户桌面（GUI 录放）
```

- **平台**（Docker 或本机 `:8000`）：任务调度、权限、确认门控、审计
- **Sidecar**（必须在 **用户 Windows 电脑** 上运行）：实际执行录屏/回放
- **Harness**：包裹 Agent 工具调用的策略层（风险分级、人工确认、超时与轨迹）

---

## 二、桌面自动化

### 2.1 前置条件

| 组件 | 要求 |
|------|------|
| 平台后端 | `http://127.0.0.1:8000` 或远程服务器地址可达 |
| 平台前端 | `http://localhost:3000`（或局域网 IP） |
| Sidecar | 本机 Windows，与浏览器同一用户会话 |

### 2.2 启动 Sidecar

**方式 A：双击 exe（推荐）**

```
release\desktop-sidecar\AIAGNET-Desktop-Sidecar.exe
```

同目录 `sidecar.env` 示例：

```env
AIAGNET_BASE_URL=http://127.0.0.1:8000
AIAGNET_FRONTEND_URL=http://localhost:3000
AIAGNET_LOGIN=admin
AIAGNET_PASSWORD=admin123
AIAGNET_OPEN_BROWSER=1
```

**方式 B：命令行**

```powershell
cd E:\AIAGNET\backend
$env:AIAGNET_BASE_URL="http://127.0.0.1:8000"
$env:AIAGNET_LOGIN="admin"
$env:AIAGNET_PASSWORD="admin123"
.\.venv\Scripts\python.exe E:\AIAGNET\scripts\desktop_sidecar.py
```

**打包 exe：** `.\scripts\build_desktop_sidecar.ps1` → 输出至 `release\desktop-sidecar\`

### 2.3 Web 页操作

路径：**侧边栏 → 桌面自动化** → `/desktop-automation`

1. 确认页头 **Sidecar 在线**
2. **录制**：开始录制 → 操作 GUI → 填演示名 → 停止并保存
3. **回放**：演示列表点播放（页面点击视为已确认）
4. **待确认回放**：来自 Chat/智能体的回放会出现在列表或 Chat 横幅，需 **批准/拒绝**

### 2.4 对话中使用

1. **智能体** 选择「桌面操作员」（含 `desktop_*` 工具）
2. **Chat** 绑定该智能体，例如：「列出桌面演示」「回放 xxx」
3. 若需确认，在 Chat **待确认的桌面回放** 横幅点 **批准执行**

### 2.5 后端配置（`backend/.env`）

```env
DESKTOP_REQUIRE_CONFIRMATION=true
DESKTOP_OPENADAPT_DATA_DIR=./desktop_openadapt_data
```

| 变量 | 说明 |
|------|------|
| `DESKTOP_REQUIRE_CONFIRMATION` | `true` 时 Agent/Chat 触发的回放默认待确认 |
| `DESKTOP_OPENADAPT_DATA_DIR` | Sidecar 本地录放数据目录 |

未安装第三方录放组件时为 **mock 模式**（验证流程，非真实 GUI 录屏）。可选：`pip install -r backend/requirements-openadapt.txt`

### 2.6 API 速查

前缀 `/api/v1/desktop-automation`（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/demos` | 演示列表 |
| POST | `/tasks/replay` | 下发回放（`confirmed: true` 跳过门控） |
| GET | `/tasks/awaiting-confirmation` | 待确认任务 |
| POST | `/tasks/{id}/confirm` | 批准 |
| POST | `/tasks/{id}/reject` | 拒绝 |
| GET | `/sidecar/status` | Sidecar 是否在线 |

---

## 三、Agent Harness（工具策略）

### 3.1 作用

Harness 在 Agent 调用工具 **之前** 执行策略检查，避免 LLM 直接发起 HTTP 请求、读邮件等外部操作而无人知晓。

### 3.2 工具风险分级

| 级别 | 代表工具 | 行为 |
|------|----------|------|
| **L0** | calculator, web_search, get_datetime, desktop_list_demos | 直接执行 |
| **L1** | create_presentation | 执行 + 审计日志 |
| **L2** | http_request, fetch_mail | **需用户在 Chat 批准**（可关闭） |
| 自管 | desktop_replay, desktop_capture | 走桌面模块自有确认，Harness 不重复拦截 |

查看分级：`GET /api/v1/harness/tools/risk` 或 `GET /api/v1/tools/`（含 `risk_level` 字段）

### 3.3 Chat 中批准工具调用

1. 绑定带 L2 工具（如 `http_request`）的智能体
2. 让 Agent 发起相应操作
3. Chat 输入区上方出现 **待确认的工具调用**（紫色横幅）
4. 点击 **批准执行** 或 **拒绝**

### 3.4 不同入口的策略

| 入口 | 确认策略 |
|------|----------|
| Chat / 智能体手动运行 | L2 工具默认需确认 |
| 数字员工定时任务 | `auto_confirm=true`，自动放行 |
| 桌面页直接点播放 | `confirmed=true`，跳过桌面门控 |

### 3.5 配置（`backend/.env`）

```env
HARNESS_REQUIRE_TOOL_CONFIRMATION=true
HARNESS_LLM_TIMEOUT_SEC=120
HARNESS_MAX_ITERATIONS_CAP=25
```

| 变量 | 说明 |
|------|------|
| `HARNESS_REQUIRE_TOOL_CONFIRMATION` | `false` 关闭 L2 人工确认（不推荐生产） |
| `HARNESS_LLM_TIMEOUT_SEC` | 单次 LLM 调用超时（秒） |
| `HARNESS_MAX_ITERATIONS_CAP` | Agent ReAct 循环上限 |

### 3.6 执行轨迹

- 智能体运行 API 响应含 `steps`、`harness_trace`
- Chat 使用 Agent 工具时，助手消息 `metadata` 可含 `harness_trace`
- 服务端 structlog 输出 `harness_tool_before` / `harness_tool_after`

### 3.7 API 速查

前缀 `/api/v1/harness`（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tools/risk` | 工具风险表 |
| GET | `/actions/awaiting-confirmation` | 待确认工具调用 |
| POST | `/actions/{id}/confirm` | 批准并执行 |
| POST | `/actions/{id}/reject` | 拒绝 |

---

## 四、测试脚本

```powershell
cd E:\AIAGNET\backend
$env:PYTHONPATH="E:\AIAGNET\backend"

# 桌面自动化（17 项）
$env:TEST_BASE_URL="http://127.0.0.1:8000"
.\.venv\Scripts\python.exe scripts\test_desktop_automation.py

# Harness API
.\.venv\Scripts\python.exe scripts\test_harness.py

# 全平台冒烟（需 admin 登录）
.\.venv\Scripts\python.exe smoke_test.py
```

---

## 五、常见问题

**Q：Sidecar 一直离线？**  
检查 `sidecar.env` 中 `AIAGNET_BASE_URL`、账号密码；exe 需在 `backend` 同机或能访问后端的网络；控制台窗口勿关。

**Q：3000 页面空白？**  
删除 `frontend\.next` 后 `npm run dev` 重启；或访问 `/login` 强制刷新。

**Q：回放点了批准没反应？**  
看 Sidecar 控制台是否有 `running task`；mock 模式约 2 秒完成。

**Q：http_request 不执行？**  
需在 Chat **待确认的工具调用** 中批准；或临时设 `HARNESS_REQUIRE_TOOL_CONFIRMATION=false`（仅开发）。

**Q：Docker 里能跑 Sidecar 吗？**  
不能。Sidecar 必须在 **用户 Windows 桌面** 运行，Docker 仅跑平台后端/前端。

---

*文档版本：2026-06-12 · 对应平台 Phase 3 桌面自动化 + Harness H1/H2*
