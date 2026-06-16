# AI-AGENT

**数字员工平台** — 用数字员工把「会思考、有技能、懂流程、有知识、能定时干活」连成一条完整的 AI 上岗链路。

[![Repository](https://img.shields.io/badge/GitHub-AI--Agent-blue)](https://github.com/oymclihui/AI-Agent)

**语言 / Languages：** **中文** · [English](README.en.md)

<p align="center">
  <img src="docs/screenshot.png" alt="AI-AGENT 系统界面（中文）" width="900" />
</p>

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **Agents** | 创建与管理智能体；**默认私有**；支持重命名、**分享给用户/部门**、**组织内发布**、复制共享智能体；列表按 scope 筛选（我的 / 共享 / 组织 / 平台 / 可用） |
| **Skills** | 可复用 SOP / 方法论沉淀（对齐 Cursor `SKILL.md`），在线技能库（约 1123 模板）、运行时注入；**删除仅限管理员** |
| **Digital Employees** | **数字员工**：岗位化绑定智能体，Cron / 间隔定时任务；**从模板一键创建**（含 11 个 bundled 岗位模板） |
| **Operations Screen** | 运营大屏 **`/screen`**：KPI、员工状态、任务趋势；**按组织 RBAC 过滤**；Dashboard API + SSE（需登录） |
| **Organization RBAC** | **8 角色**、部门树、**接口人 / 高管秘书** 分层赋权；数字员工与大屏按 scope 隔离 |
| **Workflows** | n8n 风格可视化设计器（675+ 节点库）、**自然语言生成工作流**、节点 AI 配置助手 |
| **Chat** | 多轮对话、流式输出、**SessionContext**、**语音对话**（STT 自动发送 + TTS 朗读）、智能沉淀、附件与推荐问题 |
| **Knowledge** | 文档上传、向量检索（RAG，对话多库联合检索）；平台路线图自动种子与 **content_sha256 再索引** |
| **Model Hub** | 模型配置 **增删改查**、设默认、**推理参数**（temperature / top_p / max_tokens 等）、OpenAI 兼容 Base URL |
| **用户与权限** | 工号 / 邮箱登录、JWT、**组织 RBAC + 分层赋权**、**Excel 批量导入权限**、个人模型 API Key |
| **Tools** | 内置计算器、HTTP 请求、网页搜索、日期时间等工具 |
| **Orchestrator** | 多智能体协同编排（CrewAI 风格 sequential 流程） |

前端支持 **中 / 英** 双语界面。

---

## 更新日志

### 2026-06 — 组织权限 Excel 批量导入与界面优化

**一句话：** 组织管理员和部门接口人可用 Excel 批量调整用户角色；权限页改为表格 + 搜索 + 快捷角色模板。

| 能力 | 说明 |
|------|------|
| **Excel 模板** | 4 个 Sheet：权限导入、填写说明、角色对照、部门对照 |
| **下载** | 空白模板 / **导出当前权限**（改完再上传） |
| **导入流程** | 上传 → **预览**（绿=将更新 / 黄=无变更 / 红=错误）→ 确认应用 |
| **组织管理员** | `设置 → 组织与权限 → 批量导入`；API：`/organization/permissions/import/*` |
| **部门接口人** | `设置 → 本部门权限` 内同样支持导入（仅子树用户，角色受限） |
| **高管秘书** | `设置 → 高管权限`：表格 + 搜索 + Excel 导入（高管名单池） |
| **用户与角色页** | 搜索 / 部门筛选 / 角色筛选；点行编辑；**快捷模板**（一线员工、负责人、接口人、审计、高管） |

**新增 API：**

- `GET /organization/permissions/import/template` — 下载模板（`?include_current=true` 导出当前）
- `POST /organization/permissions/import/preview` — 上传预览
- `POST /organization/permissions/import/apply` — 确认应用
- `GET/POST /organization/delegation/permissions/import/*` — 接口人 / 秘书 scoped 版本

**涉及模块：** `backend/app/core/auth/permission_import.py`、`backend/app/api/organization.py`、`frontend/src/app/settings/organization/page.tsx`、`frontend/src/components/organization/PermissionImportPanel.tsx`

**冒烟测试：**

```bash
cd backend
python scripts/smoke_test_permission_import.py          # 权限 Excel 导入（7 项）
python scripts/run_launch_preflight.py                  # 上线前全量预检（多套件）
```

> 赋权操作写入 `permission_audit_logs`（action=`permission_import`）。详见 [组织权限与赋权说明](docs/组织权限与赋权说明.md)。

### 2026-06 — 数字员工与前端稳定性

- **`/employees` 加载修复**：API 代理默认端口、集合路径尾斜杠、Nginx 重写，避免 307/401 误报
- **对话沉淀**：`deposit.py` 扩展制造 / 零售 / 银行 / 医疗 / 教育等行业提示
- **测试脚本**：`integration_test.py` / `deep_test.py` 支持 `SMOKE_ADMIN_PASSWORD` 登录；`scripts/test_deposit_employee_industries.py`（12 行业 seed 模式）

### 2026-06 — Windows 自包含交付包

**一句话：** 解压 zip 后双击 `AI-AGENT.bat` 即可运行，**目标机无需安装 Python / Node.js**。

| 能力 | 说明 |
|------|------|
| **内置运行时** | `runtime/python/`（Python 3.12 + 全部后端依赖）、`runtime/node/`（Node 20） |
| **预装依赖** | 打包机已完成 `pip install` 与 `npm ci` + `next build`，含 `frontend/node_modules` 与 `.next` |
| **一键启动** | `AI-AGENT.bat` → `launch.ps1` → `start_prod.ps1`；出错暂停并写入 `ai-agent-start.log` |
| **首次配置** | 仅生成 `backend/.env`、`SETUP_TOKEN.admin.txt` 与数据目录；数据库在 `/setup` 向导配置 |
| **仍须自备** | **PostgreSQL 或 VastBase**（业务库无法打入 zip） |

**开发机打包：**

```powershell
cd E:\AIAGNET
.\scripts\package_win_release.ps1
```

输出：`release\aiagnet-win-YYYYMMDD-HHmm\` 与同目录 `.zip`（体积较大，含完整运行时）。

**目标机使用：**

1. 完整解压 zip（勿在压缩包内直接双击）
2. 双击 **`AI-AGENT.bat`**
3. 管理员打开 **`SETUP_TOKEN.admin.txt`**，浏览器访问 `http://localhost:3000/setup` 配置数据库
4. 重启后使用 `admin / admin123` 登录

相关脚本：`win_runtime.ps1`、`launch.ps1`、`install.ps1`、`start_prod.ps1`；详见 [单位部署与首次登录](docs/单位部署与首次登录.md)。

### 2026-06 — 语音对话

- **语音对话模式**：对话页扬声器按钮开启；麦克风录音 → 自动转写发送 → AI 回复 **浏览器 TTS 朗读**
- **普通语音输入**：关闭语音对话模式时，识别结果仍填入输入框（原行为）
- 依赖：`ollama pull whisper` 或 `OPENAI_API_KEY`；详见 [用户操作手册](docs/用户操作手册.md) 5.5 节

### 2026-06 — 智能体可见性与分享

**一句话：** 新建智能体默认私有；所有者可重命名、分享给指定用户/部门、组织内发布，或复制他人共享的智能体。

| 能力 | 说明 |
|------|------|
| **可见性** | `private`（仅自己）→ `shared`（指定用户/部门）→ `org`（组织内）→ `platform`（平台预置，无 owner） |
| **列表 scope** | `?scope=mine\|shared\|org\|platform\|usable\|all`；对话 / 数字员工选 Agent 时用 `usable` |
| **分享设置** | 所有者 `GET/PUT /agents/{id}/sharing`；`GET /agents/share-targets` 搜索用户与部门 |
| **复制** | `POST /agents/{id}/copy` — 将共享/组织/平台智能体复制为我的私有副本 |
| **重命名** | 所有者可修改自己智能体名称（同步 `metadata.i18n.name`） |
| **删除** | 所有者删自己的；管理员删平台智能体；技能删除仍仅限管理员 |
| **审计** | 分享变更写入 `agent_share_audit_logs` |
| **DB 迁移** | 启动时自动添加 `agents.visibility`、`agent_shares`、`agent_share_audit_logs` |

**冒烟测试：**

```bash
cd backend
python scripts/smoke_test_agent_permissions.py   # 21 项（注册用户 A/B/C + 分享/复制/org/删除）
```

**涉及模块：** `backend/app/core/auth/agent_access.py`、`backend/app/api/agents.py`、`frontend/src/app/agents/page.tsx`

### 2026-06 — SessionContext 整合（P0）

**一句话：** 对话里选的技能 / 资料库 = 运行时真正生效 = 沉淀后自动互绑。

| 能力 | 说明 |
|------|------|
| **会话上下文包** | 对话页下拉（智能体 · 技能 · 资料库 · 模型 · 连接器）统一为 `SessionContext`，切换即 `PATCH` 持久化 |
| **技能注入** | 合并 `conversation.skills_config` + `agent.skills_config`；**只选技能、不选智能体** 也能注入 SOP |
| **对话 RAG** | 合并会话资料库 + 技能关联资料库，多库向量检索注入（含 BYD KMS）；流式与非流式均支持 |
| **智能沉淀互绑** | `deposit/confirm` 时 Skill ↔ KB 自动关联，并回写当前会话；新建 Agent / 员工与对话上下文一致 |
| **一次抽取** | `suggest-deposit` 生成含 `instructions_md` / `document_md` 的草案；confirm 优先物化草案（缺正文时 LLM 兜底） |
| **权限** | 技能、智能体 **删除仅限管理员**（`user.is_admin`） |

**新增 / 变更 API：**

- `GET /chat/conversations/{id}` — 含 `skills_config`
- `PATCH /chat/conversations/{id}/context` — 更新 SessionContext
- `POST /chat/conversations/{id}/messages` — 合并技能注入 + 多库 RAG

**涉及模块：** `backend/app/api/chat.py`、`core/chat/deposit.py`、`core/chat/export.py`、`core/skills/injector.py`、`knowledge/retriever.py`、`frontend/src/app/chat/page.tsx`

**冒烟测试：**

```bash
cd backend
python scripts/smoke_test_agent_permissions.py   # 智能体权限 ACL（21 项）
python scripts/smoke_test_session_context.py   # SessionContext P0（ASGI 进程内，19 项）
python scripts/smoke_test_new_features.py        # 需 uvicorn :8000
python scripts/smoke_test_new_features_asgi.py   # 新特性 ASGI 快速检
python smoke_test.py                             # 全量冒烟
```

---

## 近期新增功能

### 技能（Skills）

- 平台内创建 / 编辑技能（Markdown 指令 + 描述 + 发布状态）
- **在线技能库**：从 [Anthropic 官方](https://github.com/anthropics/skills)、[Agent Skills Hub](https://github.com/agent-skills-hub/agent-skills-hub) 与 [SkillHub 中国社区](https://skillhub.cn/) 浏览并批量导入（约 **1123** 模板，含热门/飙升/精选榜）
- 内置 **`data-qa-intent`** 技能（数据问答意图识别，借鉴 smart-qa）；启动种子含代码审查、Git 提交信息
- **技能中英双语**：`metadata.i18n` + API `?lang=zh|en`，随界面语言切换
- 智能体创建 / 编辑时可绑定技能；对话与 Agent 任务执行时自动注入 SOP
- 与知识库分工：Knowledge = 事实文档，Skill = 怎么做

### 数字员工（Digital Employees）

- 将智能体包装为「岗位」：名称、职责、绑定 Agent、时区
- 每个员工可配置 **多个定时任务**（Cron 或固定间隔）
- 任务类型（当前）：**Agent 指令任务**（`task_config.prompt`）
- **`GET /employees/templates` + 从模板导入**：11 个 bundled 模板（研究 / 营销 / 安全 / 数据分析等）
- 后台调度器每 30 秒扫描到期任务；支持 **立即执行** 与 **执行记录** 查询
- 启动时自动加载示例：员工「小研」+ 工作日 9:00 早报任务

### 运营大屏（Operations Screen）

- 全屏页面 **`/screen`**：KPI、数字员工卡片、今日任务、小时趋势、执行排行
- 后端 **`/api/v1/dashboard/overview`** 与 **`/stream`**（SSE）；时区 **Asia/Shanghai**
- 首页与侧边栏入口「运营大屏」

### 工作流增强

- 新建工作流支持 **自然语言** 与 **手动填写** 两种模式，AI 生成后跳转设计器
- 节点库从 n8n 官方仓库生成，含触发器、AI、集成等 **675+ 节点**
- 设计器：分类折叠节点面板、拖拽 / 添加、右侧 AI 辅助配置

### 品牌与部署

- 产品名称统一为 **AI-AGENT**（界面、API 文档、配置项 `APP_NAME`）
- **Windows 自包含交付包**：`scripts/package_win_release.ps1` → zip 内含 Python + Node + 依赖，双击 `AI-AGENT.bat` 启动（见 [Windows 交付包](#windows-交付包自包含)）
- **远程 Linux 部署脚本**：`backend/scripts/remote_deploy.py`、`scripts/remote_docker_deploy.py`（Docker / systemd + Nginx）
- 根目录 **`docker-compose.yml`** 初版（PG / Redis / Chroma / 前后端 / Nginx）；Ollama 需宿主机

### Model Hub 增强

- **完整 CRUD**：在 **`/models`** 页面或 API 创建 / 编辑 / 删除模型配置，支持设为默认
- **推理参数**：temperature、top_p、top_k、max_tokens、frequency_penalty、presence_penalty、stop、seed、timeout 等（写入 `config.inference`）
- **OpenAI 兼容接口**：provider 选 `openai`，填写 **Base URL** 即可对接内部网关或第三方 OpenAI 兼容服务
- 启动种子仅补全缺失模型，**用户修改不会被覆盖**

### 对话（Chat）增强

- **SessionContext（会话上下文包）**：智能体 / 技能 / 资料库 / 模型 / 连接器下拉统一持久化
- **语音对话**：扬声器开关 + 麦克风；识别后自动发送、回复自动朗读
- **对话 RAG**：选定资料库后自动检索注入
- **智能沉淀（Deposit）**：AI 分析对话 → 推荐技能 / 知识 / 智能体 / 数字员工 → 确认发布并互绑
- **附件上传**：支持文档类附件；上传后 LLM 自动生成 **3 条推荐问题**
- **会话管理**：单条删除、清空全部；超过 **30 天** 自动清理
- **快捷导出**：存为技能 / 存入知识库（`save-as-skill` / `save-to-knowledge`）

### 智能体可见性与分享（Agents ACL）

- 新建智能体 **默认 `private`**，仅创建者可见、可用
- **分享弹窗**：设为 `shared` 并授权用户或部门（含子部门匹配）；设为 `org` 后组织内所有人可见
- **列表 Tab**：我的 / 共享给我 / 组织 / 平台 / 全部（管理员）
- **复制**：对他人共享或组织/平台智能体一键复制为私有副本
- **重命名**：我的智能体支持铅笔图标改名
- **权限校验**：对话绑定、数字员工选 Agent、`POST /agents/{id}/run` 均走 `require_agent_use`
- **平台智能体**：Agency 库导入、`owner_id IS NULL` 的预置 Agent 为 `platform` 可见性

### 技能与智能体权限

- 技能 **删除仅限管理员**
- 智能体：**所有者删自己的**；**平台智能体由管理员下架/删除**；非授权用户 GET 返回 404

### 用户登录、组织权限与数据隔离

- **登录**：工号或邮箱 + 密码；首次启动自动创建默认管理员（工号 `admin`，密码可在 `.env` 用 `DEFAULT_ADMIN_PASSWORD` 覆盖）
- **JWT 鉴权**：除 `/login`、`/register`、`/health` 外，API 与前端页面需登录后访问
- **组织 RBAC**：部门树 + 8 角色；**部门接口人**（本部门权限）、**高管秘书**（高管权限）分层赋权
- **Excel 批量导入**：组织管理员 / 接口人 / 秘书可按模板批量调整角色（预览后确认，写入审计日志）
- **组织与权限 UI**：用户表格、搜索筛选、快捷角色模板、独立「批量导入」Tab
- **数字员工 / 大屏**：普通 `operator` 仅见自己的员工且无大屏；部门负责人见子树；高管见全公司
- **赋权审计**：`GET /organization/audit-logs`
- **个人模型 Key**：在 **设置** 页配置各 provider 的 API Key / Base URL

> 组织权限详见 **[组织权限与赋权说明](docs/组织权限与赋权说明.md)**；操作步骤见 **[用户操作手册](docs/用户操作手册.md)**。

---

## 技术栈

**Backend**

- Python 3.11+ · FastAPI · SQLAlchemy (async) · PostgreSQL / VastBase（必填）
- LangChain · LangGraph · Ollama
- ChromaDB（本地向量库，默认）/ Milvus（可选）
- Uvicorn

**Frontend**

- Next.js 14 · React 18 · TypeScript
- Tailwind CSS · Radix UI · React Flow
- Zustand · Axios

---

## 项目结构

```
AI-Agent/
├── backend/
│   ├── app/
│   │   ├── api/          # REST API 路由
│   │   ├── core/         # 智能体、工作流、对话、工具、技能、数字员工调度
│   │   │   ├── auth/         # JWT、密码、用户数据范围、智能体 ACL、权限 Excel 导入
│   │   │   ├── chat/         # 推荐问题、会话清理、导出技能/知识库、对话沉淀（deposit）
│   │   │   ├── skills/       # 技能注入、在线技能库
│   │   │   ├── employees/    # 定时任务调度与执行
│   │   │   └── workflow/     # 工作流引擎、节点库、NL 生成
│   │   ├── db/           # 数据库模型与初始化
│   │   ├── knowledge/    # RAG 管道、向量存储、多库检索（retriever）
│   │   └── models_hub/   # LLM 路由与调用
│   └── smoke_test.py     # 端到端冒烟测试
├── frontend/
│   └── src/
│       ├── app/          # Next.js 页面
│       ├── components/   # UI 组件
│       └── lib/          # API 客户端、i18n
└── README.md
```

Screenshots: [`docs/screenshot.png`](docs/screenshot.png) (中文) · [`docs/screenshot-en.png`](docs/screenshot-en.png) (English)

---

## 环境要求

- **Python** 3.11+
- **Node.js** 20+
- **Ollama**（推荐，本地 LLM）：[https://ollama.com](https://ollama.com)
  - 默认模型：`qwen3.6:35b`
  - 默认嵌入模型：`nomic-embed-text`（`ollama pull nomic-embed-text`）
- 可选：Milvus、Redis、MinIO（不配置时使用本地 Chroma / 文件系统；**数据库须 PostgreSQL**）

---

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/oymclihui/AI-Agent.git
cd AI-Agent
```

### 2. 启动后端

```bash
cd backend

# 创建虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制示例文件后按需修改）
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux

# 启动 API 服务（Windows 也可在项目根目录执行 start_backend.ps1）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> 数字员工 Cron 调度依赖 `croniter`，已包含在 `requirements.txt`。若手动安装：`pip install croniter`。

后端启动后访问：

- 健康检查：http://localhost:8000/health
- API 文档：http://localhost:8000/docs

### 3. 启动前端

```bash
cd frontend
npm install

# 可选：自定义后端地址
copy .env.example .env.local   # Windows
# cp .env.example .env.local   # macOS / Linux

npm run dev
```

浏览器打开 **http://localhost:3000**（Windows 也可执行 `start_frontend.ps1` 或根目录 `start.ps1` 一键启动前后端）

运行冒烟测试：

```bash
cd backend
set SMOKE_BASE_URL=http://127.0.0.1:8001
set SMOKE_ADMIN_PASSWORD=your-admin-password
python smoke_test.py
python scripts/smoke_test_permission_import.py
python scripts/run_launch_preflight.py   # 上线前全量预检
```

全面集成测试（L0 基础设施 + L1 模块 API + L2 协作链路）：

```bash
cd backend
set AIAGNET_TEST_BASE=http://127.0.0.1:8001
set SMOKE_ADMIN_PASSWORD=your-admin-password
python integration_test.py
# 仅协作链路: python integration_test.py --level L2
# 跳过 LLM 重调用: set AIAGNET_SKIP_LLM=1 && python integration_test.py
```

预期：`smoke_test` 约 22 项；`smoke_test_permission_import` 7 项；`integration_test` 覆盖 Skills、数字员工、知识库、工作流等协作链。

---

## 配置说明

| 文件 | 说明 |
|------|------|
| `backend/.env.example` | 后端全部环境变量模板，复制为 `backend/.env` |
| `frontend/.env.example` | 前端 API 地址，复制为 `frontend/.env.local` |
| `backend/requirements.txt` | Python 依赖锁定列表 |

### 数据库（PostgreSQL / VastBase，必填）

业务库仅支持 **PostgreSQL** 或兼容协议 **VastBase**。本地开发可先启动 Docker 中的 PG：

```powershell
docker compose up -d postgres
```

**方式 A — 完整连接串（推荐远程服务器）**

在 `backend/.env` 中设置：

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
# 若服务端要求 SSL：
# DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME?ssl=require
```

**方式 B — 分项配置**

```env
DB_HOST=your.remote.server
DB_PORT=5432
DB_USER=aiagnet
DB_PASSWORD=your_password
DB_NAME=aiagnet
DB_SSL=prefer
```

**首次建库**

```powershell
cd backend
python scripts/provision_postgres.py
```

**从旧版 SQLite 迁移到 PostgreSQL**（历史数据）

```powershell
cd backend
python scripts/migrate_sqlite_to_postgres.py --dry-run
python scripts/migrate_sqlite_to_postgres.py
```

> 迁移脚本只复制 **关系型表**。**Chroma 向量索引** 与 **`uploads/` 文件** 需在本机保留或重新上传文档。

健康检查 `/health` 会返回 `database.backend`（`postgresql` / `vastbase`）与连接状态。

一键配置示例：

```bash
# 后端
cd backend && cp .env.example .env

# 前端
cd frontend && cp .env.example .env.local
```

常用项：

| 变量 | 说明 |
|------|------|
| `OLLAMA_BASE_URL` | 本地 Ollama 地址 |
| `DEFAULT_LLM_MODEL` | 默认对话模型 |
| `OPENAI_API_KEY` | 全局 OpenAI Key（用户未配置个人 Key 时使用） |
| `VECTOR_STORE_TYPE` | `chroma`（本地）或 `milvus`（远程） |
| `SECRET_KEY` | JWT 签名密钥，**生产环境务必修改**（≥32 字符） |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 登录 Token 有效期，默认 7 天 |
| `CONVERSATION_RETENTION_DAYS` | 对话自动保留天数，默认 30 |
| `DEFAULT_ADMIN_EMPLOYEE_NO` / `DEFAULT_ADMIN_PASSWORD` / `DEFAULT_ADMIN_EMAIL` | 首次启动默认管理员账号 |

> **注意**：请勿将 `.env` 提交到 Git。仓库已通过 `.gitignore` 排除敏感文件。

---

## API 概览

所有接口前缀：`/api/v1`

| 路径 | 功能 |
|------|------|
| `/auth` | 登录、注册、`/me` 当前用户、**个人模型 Key** CRUD |
| `/chat` | 对话、SessionContext（`GET/PATCH context`）、**对话 RAG**、推荐问题、智能沉淀、存为技能/知识库 |
| `/skills` | 技能 CRUD（**删除需管理员**）；`/skills/library/*` 在线技能库 |
| `/agents` | 智能体 CRUD、**scope 列表**、**分享设置**、**复制**、运行；`GET/PUT /{id}/sharing`、`GET /share-targets` |
| `/employees` | 数字员工 CRUD、**模板导入**、定时任务、手动执行、运行记录、调度状态 |
| `/dashboard` | 运营大屏概览、SSE 流式刷新 |
| `/workflows` | 工作流管理、执行、NL 生成、节点库、AI 配置助手 |
| `/knowledge` | 知识库与文档检索 |
| `/models` | 模型配置 CRUD、设默认、推理参数、可用模型列表 |
| `/tools` | 工具注册表 |
| `/orchestrator` | 多智能体编排 |

完整接口见 Swagger UI：http://localhost:8000/docs

---

## Docker

**Compose（初版，实验性）**

```bash
# 需本机 Ollama（默认 http://host.docker.internal:11434）
docker compose up -d
```

服务包括 PostgreSQL、Redis、Chroma、后端、前端、Nginx。生产使用前请修改 `.env` 中的密钥与连接串。

**仅前端镜像**

```bash
cd frontend
docker build -t aiagnet-frontend .
docker run -p 3000:3000 aiagnet-frontend
```

---

## Windows 交付包（自包含）

适用于 **Windows 10/11 演示机、单位内网**：目标机**不必**单独安装 Python 或 Node.js。

### 打包（开发机）

```powershell
cd E:\AIAGNET
.\scripts\package_win_release.ps1
```

脚本会：

1. 下载并缓存便携 **Python 3.12**、**Node 20**（`runtime/cache/`，仅打包机使用）
2. 复制到交付目录 `runtime/python`、`runtime/node`
3. 在交付目录内完成 `pip install -r backend/requirements.txt` 与 `npm ci` + `npm run build`
4. 输出 `AI-AGENT.bat`、`launch.ps1`、`install.ps1`、`win_runtime.ps1` 等

| 输出 | 说明 |
|------|------|
| `release\aiagnet-win-YYYYMMDD-HHmm\` | 解压即用目录 |
| `release\aiagnet-win-YYYYMMDD-HHmm.zip` | 压缩包（约 1GB+，含完整运行时与依赖） |

### 部署（目标机）

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| Python / Node | **不需要**（已内置 `runtime/`） |
| 数据库 | **PostgreSQL 或 VastBase**（在 `/setup` 配置） |

**步骤：**

1. **完整解压** zip（勿在压缩包内直接双击）
2. 双击 **`AI-AGENT.bat`**
3. 管理员查看 **`SETUP_TOKEN.admin.txt`**，访问 `http://localhost:3000/setup` 配置数据库
4. 重启后登录 `admin / admin123`，在「设置 → 组织」创建用户

**交付包目录结构（节选）：**

```
aiagnet-win-*/
├── AI-AGENT.bat          # 双击启动
├── launch.ps1            # 启动入口（环境检查）
├── install.ps1           # 首次配置（交付包内为轻量模式）
├── start_prod.ps1        # 生产模式启停
├── win_runtime.ps1       # 内置运行时路径解析
├── runtime/
│   ├── python/           # Python 3.12 + 后端依赖
│   └── node/             # Node 20
├── backend/              # 后端源码
└── frontend/
    ├── .next/            # 预构建前端
    └── node_modules/     # 前端依赖
```

**故障排查：** 若窗口一闪关闭，查看同目录 **`ai-agent-start.log`**。

更多说明：[docs/单位部署与首次登录.md](docs/单位部署与首次登录.md) · [docs/Windows交付说明.md](docs/Windows交付说明.md)

---

## 技能 · 知识 · 对话 · 沉淀整合

> **状态：P0 已上线（2026-06）；P1/P2 规划中**  
> 目标：一次选型、全链路一致 —— **对话里选的 = 运行时生效的 = 沉淀后绑定的 = 员工定时跑的**

### 已上线能力（P0）

| 能力 | 实现要点 |
|------|----------|
| 会话 `skills_config` | `Conversation` 表新增字段；启动时自动迁移 |
| SessionContext API | `GET/PATCH /chat/conversations/{id}/context` |
| 技能合并注入 | `merge_skill_bindings(conv, agent)` → `SkillInjector` |
| 多库 RAG | `collect_knowledge_base_ids` + `knowledge/retriever.py` |
| 沉淀互绑 | confirm 写入 Skill.knowledge_base_ids、回写 conv 技能与资料库 |
| 草案物化 | `materialize_skill_from_spec` / `materialize_knowledge_from_spec` |
| 前端联动 | 下拉变更 PATCH；切换会话恢复；沉淀后刷新上下文 |
| 管理员删除 | 技能 / 智能体删除需 `user.is_admin` |

### 设计分层

| 层级 | 模块 | 职责 |
|------|------|------|
| 事实层 | **Knowledge（资料库）** | 制度、数据、结论 —— 知道什么 |
| 方法层 | **Skills（技能）** | SOP、步骤、输出格式 —— 怎么做 |
| 角色层 | **Agents / Employees** | 谁来做、何时做 |
| 体验层 | **Chat SessionContext** | 对话页四个下拉统一为运行时上下文包 |

### 已修复的历史问题

| 原问题 | 现状态 |
|--------|--------|
| 对话技能下拉未入库 | ✅ 已 PATCH 到 `conv.skills_config` |
| 资料库只写一次 | ✅ 切换下拉实时 PATCH |
| 对话 RAG 未接线 | ✅ `MultiKnowledgeRetriever` 已接入 |
| 沉淀 Skill/KB 不互绑 | ✅ confirm 自动关联并回写会话 |
| 沉淀后上下文不一致 | ✅ Agent/Employee 与 conv 同步 |
| 非管理员可删技能/智能体 | ✅ 技能仍限管理员；智能体所有者可删自己的 |

### 核心概念：`SessionContext`（会话上下文包）

对话页 **智能体 · 技能 · 资料库 · 模型 · 连接器** 统一抽象为运行时上下文，贯穿 **对话 → 沉淀 → 发布**：

```typescript
SessionContext {
  agent_id?: string
  skills_config: SkillBinding[]      // [{ skill_id, always_load, priority }]
  knowledge_base_ids: string[]
  model_config_id?: string
  connector_id?: string
}
```

**运行时合并规则：**

```
effective_skills = dedupe( conv.skills_config ∪ agent.skills_config )
effective_kbs    = dedupe( conv.knowledge_base_ids ∪ skill.knowledge_base_ids[] )
```

- 会话级技能与智能体绑定技能**合并注入**（去重）
- Skill 上已有的 `knowledge_base_ids` **自动并入 RAG**，用户无需重复选资料库

### 数据模型（P0 已落地）

| 对象 | 字段 | 说明 |
|------|------|------|
| `Conversation` | `skills_config` | 会话级技能绑定，与 Agent 结构一致 |
| `Conversation` | `knowledge_base_ids` | 支持 PATCH 动态更新 |
| `Skill` | `knowledge_base_ids` | 沉淀 confirm 时自动回填 |

启动后端时 `init_db` 自动执行迁移（PostgreSQL / VastBase）。

#### Phase 1 — 沉淀包表（规划中）

```text
deposit_bundles
  id, owner_id, department_id
  source_type       -- conversation | desktop_demo | employee_run
  source_id
  status            -- draft | published | archived
  extracted_json    -- 一次 LLM 结构化输出
  published_refs    -- { skill_id, kb_id, doc_id, agent_id, employee_id }
  parent_id         -- 版本链
  created_at, published_at
```

Phase 0 草稿仍存 `conv.metadata.deposit_draft`；P1 将迁出至独立 `deposit_bundles` 表。

### 运行时链路（已实现）

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as 对话页
    participant API as chat API
    participant Inj as SkillInjector
    participant RAG as KB Search
    participant LLM

    U->>FE: 选 智能体 + 技能 + 资料库
    FE->>API: PATCH /conversations/{id}/context
    U->>FE: 发送消息
    FE->>API: POST /messages
    API->>API: merge skills + kbs
    API->>Inj: build_messages(effective_skills)
    API->>RAG: search(effective_kbs, query)
    Inj->>LLM: system SOP
    RAG->>LLM: system 事实引用
    LLM->>U: 流式回复
```

**`send_message` 改造要点：**

1. 合并 `conv.skills_config` 与 `agent.skills_config` → `SkillInjector.build_messages`
2. 合并 `conv.knowledge_base_ids` 与各 Skill 的 `knowledge_base_ids` → 构建 retriever
3. `DialogueManager(memory, knowledge_retriever=retriever)` 接入现有 `/knowledge/{id}/search` 能力

**前端行为（已实现）：**

| 行为 | 说明 |
|------|------|
| 选技能 / 资料库 / 智能体 | `PATCH /chat/conversations/{id}/context` |
| 切换会话 | 从 `ConversationResponse` 恢复全部下拉 |
| 新建会话 | `createConversation` 携带完整 SessionContext |
| 沉淀完成 | 自动刷新当前会话上下文 |

### 沉淀链路（已实现）

#### 统一抽取（一次 LLM）

`suggest-deposit` 输出单一 JSON，供预览与 confirm 共用；**confirm 不再二次调 LLM**：

```json
{
  "worth_deposit": true,
  "confidence": 0.85,
  "skill": {
    "display_name": "月度管报核对 SOP",
    "instructions_md": "## 适用场景\n...",
    "tools_required": ["calculator"]
  },
  "knowledge": {
    "kb_name": "管报核对-对话沉淀",
    "document_md": "## 摘要\n...",
    "citation_message_ids": ["msg-3", "msg-7"]
  },
  "agent": { "name": "...", "role": "...", "goal": "..." },
  "employee": { "name": "...", "tasks": [] }
}
```

#### Confirm 物化与互绑规则

1. 同时选 skill + knowledge → 自动写入 `skill.knowledge_base_ids = [kb_id]`
2. 新 KB **追加**到 `conv.knowledge_base_ids`（不覆盖用户已选）
3. 新 Skill **追加**到 `conv.skills_config`
4. 创建 Agent 时 `skills_config` = 新 Skill + 会话已有 Skill
5. 创建 Employee 时 KB / Skill 与 Agent 保持一致
6. 沉淀完成后用户继续对话 → **立刻生效**新 Skill + 新 KB

**方法 vs 事实边界：** 可检索引用的事实进 Knowledge；可逐步执行的流程进 Skill；Skill 通过 `knowledge_base_ids` 指向依据。

草案缺 `instructions_md` / `document_md` 时，`export.py` 中 LLM 兜底生成。

### API 清单

| 方法 | 路径 | 状态 |
|------|------|------|
| PATCH | `/chat/conversations/{id}/context` | ✅ P0 |
| GET | `/chat/conversations/{id}` | ✅ P0 |
| POST | `/chat/conversations/{id}/messages` | ✅ P0（技能合并 + RAG） |
| POST | `/chat/conversations/{id}/suggest-deposit` | ✅ |
| POST | `/chat/conversations/{id}/deposit/confirm` | ✅ P0（互绑 + 回写） |
| GET | `/deposits` | 🔲 P1 |
| GET | `/deposits/{id}/lineage` | 🔲 P1 |

### P0 验收（已通过）

- [x] 对话只选技能（不选智能体）也能注入 SOP
- [x] 选资料库后对话可返回 `rag_used: true`
- [x] 沉淀 skill + knowledge 后，继续对话自动用新 Skill + 新 KB
- [x] 新建 Agent / Employee 绑定与对话上下文一致

### 后续规划

#### P1 — 可运营

| # | 任务 |
|---|------|
| 1 | `deposit_bundles` 表，草稿迁出 `conversation.metadata` |
| 2 | `/deposits` 工作台：草稿 / 已发布 / 溯源 |
| 3 | 发布前 Markdown 编辑预览 |
| 4 | 相似 Skill / KB 去重提示 |
| 5 | 组织级沉淀：`pending_review` → 管理员批准 |

#### P2 — 与知识库增强对齐

| # | 任务 |
|---|------|
| 6 | Hybrid 检索 + Rerank（见 [知识库增强规划](docs/知识库增强规划.md)） |
| 7 | Skill 运行时只检索关联 KB（降噪） |
| 8 | 逐句溯源：SOP 步骤 ↔ 对话消息 ↔ KB chunk |
| 9 | 桌面录制 / 员工执行记录统一进 Deposit Hub |

详见 [docs/知识库增强规划.md](docs/知识库增强规划.md)。

### 刻意不做（避免过度工程）

| 不做 | 原因 |
|------|------|
| Skill 与 KB 合并成一种实体 | 方法 / 事实分层清晰，现有模型够用 |
| Phase 0 上 GraphRAG | 不阻塞主链路 |
| 每次发消息都 PATCH context | 仅下拉变更时 PATCH |
| 重写 SkillInjector | 扩展 `merge_skill_bindings()` 即可 |
| 沉淀时删除用户已选技能 | 默认追加，可选「仅保留新沉淀」 |

### 代码映射（P0 已改动文件）

| 模块 | 改动 |
|------|------|
| `backend/app/db/models.py` | `Conversation.skills_config` |
| `backend/app/db/init_db.py` | 自动迁移 `skills_config` 列 |
| `backend/app/schemas/chat.py` | `ConversationContextUpdate`；Response 含 skills |
| `backend/app/api/chat.py` | `_resolve_effective_context`；RAG retriever |
| `backend/app/core/chat/deposit.py` | confirm 互绑 + 回写 conv |
| `backend/app/core/chat/export.py` | `materialize_*_from_spec` 物化 |
| `backend/app/core/skills/injector.py` | `merge_skill_bindings()`、`collect_knowledge_base_ids()` |
| `backend/app/knowledge/retriever.py` | **新增** 多库联合检索 |
| `frontend/src/app/chat/page.tsx` | PATCH context；恢复下拉；沉淀后刷新 |
| `frontend/src/lib/api.ts` | `getConversation`、`updateContext` |
| `frontend/src/lib/permissions.ts` | `canDeleteAgentsOrSkills()` |

---

## 开发路线

以下规划已写入知识库 **「AI-AGENT 平台文档」**（启动后端时自动创建并嵌入 `platform-roadmap.md`），可在 **Knowledge** 页检索，例如：「数字员工 Phase 2 计划是什么？」

**技能 · 知识 · 对话 · 沉淀整合（见上一节）：**

- [x] P0：`SessionContext` — 会话 `skills_config` + `PATCH /context` + 对话技能/RAG 生效
- [x] P0：沉淀 confirm 互绑（Skill ↔ KB ↔ Conv ↔ Agent/Employee）+ 一次 LLM 抽取（confirm 复用 suggest 草案，缺正文时 LLM 兜底）
- [ ] P1：沉淀包表 + `/deposits` 工作台 + 发布前编辑 + 去重提示
- [ ] P2：Hybrid RAG + Skill 关联 KB 降噪 + 逐句溯源 + 多来源统一沉淀
- [x] 技能 / 智能体删除权限（技能管理员；智能体所有者 / 平台管理员）
- [x] 智能体可见性与分享 ACL（private / shared / org / platform、复制、重命名、scope 列表）

- [x] n8n 风格工作流节点库与设计器
- [x] 自然语言创建工作流 / 智能体
- [x] 技能模块与在线技能库导入（含 SkillHub.cn、data-qa-intent、技能 i18n）
- [x] 数字员工与 Cron 定时任务
- [x] 从模板创建数字员工（含数据分析类模板）
- [x] 运营大屏 `/screen` 与 Dashboard API
- [x] 远程部署脚本（Linux + systemd + Nginx）
- [x] 飞书 / 钉钉等 IM 机器人接入（Webhook 回调 + `/settings/integrations` 配置说明）
- [x] Chat 内图表 / KPI 结构化渲染（`data-qa-intent` 协议：`[kpi]` / `[chart]` / `[choices]`）
- [x] 定时任务支持工作流 / 多 Agent 编排执行（数字员工任务类型 `workflow` / `crew`）
- [x] SessionContext 整合 P0（对话技能/RAG/沉淀互绑）
- [x] 从对话「智能沉淀」与「保存为技能 / 知识库」
- [x] 用户登录与按用户数据隔离（个人 API Key、30 天会话清理）
- [x] 组织权限与用户管理 UI（部门树、角色赋权、新建用户、**Excel 批量导入** — `/settings/organization`）
- [x] Windows 自包含交付包（`package_win_release.ps1`：内置 Python/Node/依赖 + `AI-AGENT.bat`）
- [~] Docker Compose 一键部署（compose 文件已有，待完善）

---

## 许可证

本项目尚未指定开源许可证。如需商用或二次分发，请联系作者确认。

---

## 链接

- 仓库：[https://github.com/oymclihui/AI-Agent](https://github.com/oymclihui/AI-Agent)
- 英文说明：[README.en.md](README.en.md)
- 用户操作手册：[docs/用户操作手册.md](docs/用户操作手册.md)
- 技能 · 知识 · 沉淀整合：见上文 [技能 · 知识 · 对话 · 沉淀整合](#技能--知识--对话--沉淀整合)
- 知识库增强规划：[docs/知识库增强规划.md](docs/知识库增强规划.md)
- 单位部署指南：[docs/单位部署与首次登录.md](docs/单位部署与首次登录.md)
- Windows 交付说明：[docs/Windows交付说明.md](docs/Windows交付说明.md)
