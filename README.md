# AIAGNET

**统一 AI 智能体平台** — 融合多智能体编排、可视化工作流、RAG 知识库与模型管理。

[![Repository](https://img.shields.io/badge/GitHub-AI--Agent-blue)](https://github.com/oymclihui/AI-Agent)

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **Agents** | 创建与管理智能体，支持角色、目标、工具绑定与自然语言生成 |
| **Workflows** | 可视化流程设计器，支持 Agent / 条件 / LLM 等节点编排与执行 |
| **Chat** | 多轮对话、流式输出、会话记忆 |
| **Knowledge** | 文档上传、向量检索（RAG），支持 Ollama 嵌入模型 |
| **Model Hub** | 统一管理 OpenAI、Anthropic、Ollama 等 LLM 配置 |
| **Tools** | 内置计算器、HTTP 请求、网页搜索、日期时间等工具 |
| **Orchestrator** | 多智能体协同编排（CrewAI 风格 sequential 流程） |

前端支持 **中 / 英** 双语界面。

---

## 技术栈

**Backend**

- Python 3.11+ · FastAPI · SQLAlchemy (async) · SQLite（默认）
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
│   │   ├── core/         # 智能体、工作流、对话、工具核心逻辑
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

# 启动 API 服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

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

浏览器打开 **http://localhost:3000**

### 4. 运行冒烟测试

确保后端已启动，然后：

```bash
cd backend
python smoke_test.py
```

预期输出：`14 passed, 0 failed`（需 Ollama 可用且已拉取相应模型）。

---

## 配置说明

| 文件 | 说明 |
|------|------|
| `backend/.env.example` | 后端全部环境变量模板，复制为 `backend/.env` |
| `frontend/.env.example` | 前端 API 地址，复制为 `frontend/.env.local` |
| `backend/requirements.txt` | Python 依赖锁定列表 |

一键配置示例：

```bash
# 后端
cd backend && cp .env.example .env

# 前端
cd frontend && cp .env.example .env.local
```

常用项：`OLLAMA_BASE_URL`、`DEFAULT_LLM_MODEL`、`OPENAI_API_KEY`、`VECTOR_STORE_TYPE`（`chroma` / `milvus`）。

> **注意**：请勿将 `.env` 提交到 Git。仓库已通过 `.gitignore` 排除敏感文件。

---

## API 概览

所有接口前缀：`/api/v1`

| 路径 | 功能 |
|------|------|
| `/agents` | 智能体 CRUD 与运行 |
| `/workflows` | 工作流管理与执行 |
| `/chat` | 对话与会话 |
| `/knowledge` | 知识库与文档检索 |
| `/models` | 模型配置与可用模型列表 |
| `/tools` | 工具注册表 |
| `/orchestrator` | 多智能体编排 |

完整接口见 Swagger UI：http://localhost:8000/docs

---

## Docker（前端）

```bash
cd frontend
docker build -t aiagnet-frontend .
docker run -p 3000:3000 aiagnet-frontend
```

---

## 开发路线

- [ ] 工作流设计器更多节点类型（HTTP、Code、LLM 等）
- [ ] 用户认证与多租户
- [ ] Docker Compose 一键部署

---

## 许可证

本项目尚未指定开源许可证。如需商用或二次分发，请联系作者确认。

---

## 链接

- 仓库：[https://github.com/oymclihui/AI-Agent](https://github.com/oymclihui/AI-Agent)
