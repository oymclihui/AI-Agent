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
| **Agents** | 创建与管理智能体，支持角色、目标、工具绑定、**技能绑定**与自然语言生成 |
| **Skills** | 可复用 SOP / 方法论沉淀（对齐 Cursor `SKILL.md`），在线技能库（约 1123 模板）、**中英双语展示**、运行时注入 |
| **Digital Employees** | **数字员工**：岗位化绑定智能体，Cron / 间隔定时任务；**从模板一键创建**（含 11 个 bundled 岗位模板） |
| **Operations Screen** | 运营大屏 **`/screen`**：KPI、员工状态、任务趋势；Dashboard API + SSE 实时刷新 |
| **Workflows** | n8n 风格可视化设计器（675+ 节点库）、**自然语言生成工作流**、节点 AI 配置助手 |
| **Chat** | 多轮对话、流式输出、**附件上传与推荐问题**、会话删除、**存为技能 / 知识库** |
| **Knowledge** | 文档上传、向量检索（RAG）；平台路线图文档自动种子与 **content_sha256 再索引** |
| **Model Hub** | 模型配置 **增删改查**、设默认、**推理参数**（temperature / top_p / max_tokens 等）、OpenAI 兼容 Base URL |
| **用户与权限** | 工号 / 邮箱登录、JWT、**按用户隔离**数据、**个人模型 API Key** |
| **Tools** | 内置计算器、HTTP 请求、网页搜索、日期时间等工具 |
| **Orchestrator** | 多智能体协同编排（CrewAI 风格 sequential 流程） |

前端支持 **中 / 英** 双语界面。

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
- **远程 Linux 部署脚本**：`backend/scripts/remote_deploy.py` 等（systemd + Nginx）
- 根目录 **`docker-compose.yml`** 初版（PG / Redis / Chroma / 前后端 / Nginx）；Ollama 需宿主机，一键流程待完善

### Model Hub 增强

- **完整 CRUD**：在 **`/models`** 页面或 API 创建 / 编辑 / 删除模型配置，支持设为默认
- **推理参数**：temperature、top_p、top_k、max_tokens、frequency_penalty、presence_penalty、stop、seed、timeout 等（写入 `config.inference`）
- **OpenAI 兼容接口**：provider 选 `openai`，填写 **Base URL** 即可对接内部网关或第三方 OpenAI 兼容服务
- 启动种子仅补全缺失模型，**用户修改不会被覆盖**

### 对话（Chat）增强

- **附件上传**：支持文档类附件；上传后 LLM 自动生成 **3 条推荐问题**，点击即可填入输入框
- **会话管理**：单条删除、**清空全部**；超过 **30 天**（可配置 `CONVERSATION_RETENTION_DAYS`）的会话自动清理
- **沉淀导出**：当前会话可 **存为技能**（AI 提炼 SOP）或 **存入知识库**（写入 Markdown 文档并索引）

### 用户登录与数据隔离

- **登录**：工号或邮箱 + 密码；首次启动自动创建默认管理员（工号 `admin`，密码 `admin123`，可在 `.env` 覆盖）
- **JWT 鉴权**：除 `/login`、`/register`、`/health` 外，API 与前端页面需登录后访问
- **按用户隔离**：智能体、技能、工作流、知识库、对话、数字员工等带 `owner_id`，各用户仅见/改自己的数据
- **共享模板**：历史种子数据中 `owner_id` 为空的项目为平台模板，全员可见、普通用户不可编辑
- **个人模型 Key**：在 **设置** 页配置各 provider 的 API Key / Base URL，调用 LLM 时优先于全局 `.env` 密钥

> 详细操作步骤见 **[用户操作手册](docs/用户操作手册.md)**。

---

## 技术栈

**Backend**

- Python 3.11+ · FastAPI · SQLAlchemy (async) · SQLite（默认）/ PostgreSQL（可配置）
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
│   │   │   ├── auth/         # JWT、密码、用户数据范围
│   │   │   ├── chat/         # 推荐问题、会话清理、导出技能/知识库
│   │   │   ├── skills/       # 技能注入、在线技能库
│   │   │   ├── employees/    # 定时任务调度与执行
│   │   │   └── workflow/     # 工作流引擎、节点库、NL 生成
│   │   ├── db/           # 数据库模型与初始化
│   │   ├── knowledge/    # RAG 管道与向量存储
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
- 可选：Milvus、Redis、MinIO（不配置时使用本地 SQLite / Chroma / 文件系统）

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
python smoke_test.py
```

全面集成测试（L0 基础设施 + L1 模块 API + L2 协作链路）：

```bash
cd backend
python integration_test.py
# 仅协作链路: python integration_test.py --level L2
# 跳过 LLM 重调用: set AIAGNET_SKIP_LLM=1 && python integration_test.py
```

预期：`smoke_test` 约 14 项；`integration_test` 覆盖 Skills、数字员工、知识库 content、工作流 NL 等模块协作链。

---

## 配置说明

| 文件 | 说明 |
|------|------|
| `backend/.env.example` | 后端全部环境变量模板，复制为 `backend/.env` |
| `frontend/.env.example` | 前端 API 地址，复制为 `frontend/.env.local` |
| `backend/requirements.txt` | Python 依赖锁定列表 |

### 数据库（SQLite / PostgreSQL）

默认使用本地 **SQLite**（`backend/aiagnet.db`），无需额外服务。生产或远程部署可切换到 **PostgreSQL**：

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

**从 SQLite 迁移到 PostgreSQL**

```powershell
cd backend
pip install -r requirements.txt

# 1. 在 .env 中配置目标 PostgreSQL（见上）
# 2. 预览源库行数
python scripts/migrate_sqlite_to_postgres.py --dry-run

# 3. 创建表结构并复制数据（目标已有数据时加 --clear）
python scripts/migrate_sqlite_to_postgres.py

# 4. 重启后端
cd .. ; .\start_backend.ps1
```

> 迁移脚本只复制 **关系型表**（Agents、Workflows、Knowledge 元数据等）。**Chroma 向量索引** 与 **`uploads/` 文件** 需在本机保留或重新上传文档。

健康检查 `/health` 会返回 `database.backend`（`sqlite` / `postgresql`）与连接状态。

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
| `/agents` | 智能体 CRUD、运行、技能绑定 |
| `/skills` | 技能 CRUD；`/skills/library/*` 在线技能库浏览与导入 |
| `/employees` | 数字员工 CRUD、**模板导入**、定时任务、手动执行、运行记录、调度状态 |
| `/dashboard` | 运营大屏概览、SSE 流式刷新 |
| `/workflows` | 工作流管理、执行、NL 生成、节点库、AI 配置助手 |
| `/chat` | 对话、**推荐问题**、会话删除、**存为技能 / 知识库** |
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

## 开发路线

以下规划已写入知识库 **「AI-AGENT 平台文档」**（启动后端时自动创建并嵌入 `platform-roadmap.md`），可在 **Knowledge** 页检索，例如：「数字员工 Phase 2 计划是什么？」

- [x] n8n 风格工作流节点库与设计器
- [x] 自然语言创建工作流 / 智能体
- [x] 技能模块与在线技能库导入（含 SkillHub.cn、data-qa-intent、技能 i18n）
- [x] 数字员工与 Cron 定时任务
- [x] 从模板创建数字员工（含数据分析类模板）
- [x] 运营大屏 `/screen` 与 Dashboard API
- [x] 远程部署脚本（Linux + systemd + Nginx）
- [ ] 飞书 / 钉钉等 IM 机器人接入
- [ ] Chat 内图表 / KPI 结构化渲染（`data-qa-intent` 协议已定义，前端未渲染）
- [ ] 定时任务支持工作流 / 多 Agent 编排执行
- [x] 从对话「保存为技能 / 知识库」
- [x] 用户登录与按用户数据隔离（个人 API Key、30 天会话清理）
- [ ] 完整多租户 / 管理员用户管理 UI
- [~] Docker Compose 一键部署（compose 文件已有，待完善）

---

## 许可证

本项目尚未指定开源许可证。如需商用或二次分发，请联系作者确认。

---

## 链接

- 仓库：[https://github.com/oymclihui/AI-Agent](https://github.com/oymclihui/AI-Agent)
- 英文说明：[README.en.md](README.en.md)
- 用户操作手册：[docs/用户操作手册.md](docs/用户操作手册.md)
