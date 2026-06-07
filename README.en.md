# AI-AGENT

**Unified AI Agent Platform** — multi-agent orchestration, visual workflows, skill playbooks, digital employees with scheduled tasks, RAG, and model management.

[![Repository](https://img.shields.io/badge/GitHub-AI--Agent-blue)](https://github.com/oymclihui/AI-Agent)

**Languages:** [中文](README.md) · **English**

<p align="center">
  <img src="docs/screenshot-en.png" alt="AI-AGENT Dashboard (English UI)" width="900" />
</p>

---

## Features

| Module | Description |
|--------|-------------|
| **Agents** | Create and manage agents with roles, goals, tools, **skill bindings**, and NL generation |
| **Skills** | Reusable SOPs (Cursor `SKILL.md`-compatible), online library import, runtime injection |
| **Digital Employees** | Role-based agents with **multiple Cron / interval scheduled tasks** and automatic Agent runs |
| **Workflows** | n8n-style designer (675+ nodes), **NL workflow generation**, AI node config assistant |
| **Chat** | Multi-turn dialogue, streaming, memory (skills injected when an agent is bound) |
| **Knowledge** | Document upload and vector search (RAG) with Ollama embeddings |
| **Model Hub** | Unified LLM config for OpenAI, Anthropic, Ollama, and more |
| **Tools** | Built-in calculator, HTTP, web search, datetime tools |
| **Orchestrator** | Multi-agent collaboration (CrewAI-style sequential flows) |

The frontend supports **Chinese / English** UI.

---

## Recent Additions

### Skills

- Create and edit skills in-platform (Markdown instructions, description, publish status)
- **Online skill library**: browse and import from [Anthropic official skills](https://github.com/anthropics/skills) and [Agent Skills Hub](https://github.com/agent-skills-hub/agent-skills-hub) (810+ templates)
- Bind skills when creating or editing agents; SOPs are injected during chat and agent task runs
- Separation: Knowledge = facts; Skills = how to work

### Digital Employees

- Wrap an agent as a “role”: name, title, bound agent, timezone
- Each employee can have **multiple scheduled tasks** (Cron or fixed interval)
- Current task type: **Agent prompt tasks** (`task_config.prompt`)
- Background scheduler polls every 30s; supports **run now** and **run history**
- Sample seed on startup: employee “小研” with a weekday 9:00 briefing task

### Workflow Enhancements

- Create workflows via **natural language** or manual form; opens designer after NL generation
- Node catalog generated from the official n8n repo (**675+ nodes**)
- Designer: collapsible palette, drag/add nodes, AI-assisted node configuration

### Branding

- Product name unified as **AI-AGENT** (UI, API docs, `APP_NAME` config)

---

## Tech Stack

**Backend**

- Python 3.11+ · FastAPI · SQLAlchemy (async) · SQLite (default)
- LangChain · LangGraph · Ollama
- ChromaDB (local, default) / Milvus (optional)
- Uvicorn

**Frontend**

- Next.js 14 · React 18 · TypeScript
- Tailwind CSS · Radix UI · React Flow
- Zustand · Axios

---

## Project Structure

```
AI-Agent/
├── backend/
│   ├── app/
│   │   ├── api/          # REST API routes
│   │   ├── core/         # Agents, workflows, dialogue, tools, skills, employee scheduler
│   │   │   ├── skills/       # Skill injection & online library
│   │   │   ├── employees/    # Scheduled task runner & scheduler
│   │   │   └── workflow/     # Engine, node catalog, NL generator
│   │   ├── db/           # Database models & seed data
│   │   ├── knowledge/    # RAG pipeline & vector store
│   │   └── models_hub/   # LLM routing & invocation
│   └── smoke_test.py     # End-to-end smoke test
├── frontend/
│   └── src/
│       ├── app/          # Next.js pages
│       ├── components/   # UI components
│       └── lib/          # API client, i18n
├── docs/                 # Screenshots
├── README.md             # Chinese documentation
└── README.en.md          # English documentation (this file)
```

---

## Requirements

- **Python** 3.11+
- **Node.js** 20+
- **Ollama** (recommended for local LLM): [https://ollama.com](https://ollama.com)
  - Default model: `qwen3.6:35b`
  - Default embedding: `nomic-embed-text` (`ollama pull nomic-embed-text`)
- Optional: Milvus, Redis, MinIO (SQLite / Chroma / local filesystem used when not configured)

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/oymclihui/AI-Agent.git
cd AI-Agent
```

### 2. Start the backend

```bash
cd backend

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

> Digital employee Cron scheduling requires `croniter` (listed in `requirements.txt`).

Once running:

- Health check: http://localhost:8000/health
- API docs: http://localhost:8000/docs

### 3. Start the frontend

```bash
cd frontend
npm install

copy .env.example .env.local   # Windows
# cp .env.example .env.local   # macOS / Linux

npm run dev
```

Open **http://localhost:3000** in your browser. Switch language via the sidebar toggle (中文 / English).

### 4. Run smoke tests

With the backend running:

```bash
cd backend
python smoke_test.py
```

Expected: `14 passed, 0 failed` (requires Ollama with the configured models).

---

## Configuration

| File | Purpose |
|------|---------|
| `backend/.env.example` | Backend env template → copy to `backend/.env` |
| `frontend/.env.example` | Frontend API URL → copy to `frontend/.env.local` |
| `backend/requirements.txt` | Pinned Python dependencies |

Quick setup:

```bash
cd backend && cp .env.example .env
cd frontend && cp .env.example .env.local
```

Key variables: `OLLAMA_BASE_URL`, `DEFAULT_LLM_MODEL`, `OPENAI_API_KEY`, `VECTOR_STORE_TYPE` (`chroma` / `milvus`).

> **Note:** Never commit `.env` files. They are excluded via `.gitignore`.

---

## API Overview

All endpoints are under `/api/v1`:

| Path | Purpose |
|------|---------|
| `/agents` | Agent CRUD, execution, skill bindings |
| `/skills` | Skill CRUD; `/skills/library/*` online catalog browse & import |
| `/employees` | Digital employees, scheduled tasks, manual run, run history, scheduler status |
| `/workflows` | Workflow CRUD, execution, NL generate, node catalog, AI config assistant |
| `/chat` | Conversations & messaging |
| `/knowledge` | Knowledge bases & document search |
| `/models` | Model configs & available models |
| `/tools` | Tool registry |
| `/orchestrator` | Multi-agent orchestration |

Full reference: http://localhost:8000/docs

---

## Docker (frontend)

```bash
cd frontend
docker build -t aiagnet-frontend .
docker run -p 3000:3000 aiagnet-frontend
```

---

## Roadmap

Future plans are stored in the seeded knowledge base **「AI-AGENT 平台文档」** (auto-created on backend startup from `platform-roadmap.md`). Search it on the **Knowledge** page, e.g. “What is Digital Employees Phase 2?”

- [x] n8n-style workflow node catalog & designer
- [x] Natural-language workflow / agent creation
- [x] Skills module & online skill library import
- [x] Digital employees with Cron scheduled tasks
- [ ] Scheduled tasks for workflows & crew orchestration
- [ ] “Save as skill” from chat / execution history
- [ ] User authentication & multi-tenancy
- [ ] Docker Compose one-click deployment

---

## License

No open-source license has been assigned yet. Contact the author before commercial use or redistribution.

---

## Links

- Repository: [https://github.com/oymclihui/AI-Agent](https://github.com/oymclihui/AI-Agent)
- Chinese README: [README.md](README.md)
