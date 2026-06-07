# AIAGNET

**Unified AI Agent Platform** — multi-agent orchestration, visual workflows, RAG knowledge bases, and model management in one place.

[![Repository](https://img.shields.io/badge/GitHub-AI--Agent-blue)](https://github.com/oymclihui/AI-Agent)

**Languages:** [中文](README.md) · **English**

<p align="center">
  <img src="docs/screenshot-en.png" alt="AIAGNET Dashboard (English UI)" width="900" />
</p>

---

## Features

| Module | Description |
|--------|-------------|
| **Agents** | Create and manage agents with roles, goals, tool bindings, and NL generation |
| **Workflows** | Visual flow designer with Agent / Condition / LLM nodes |
| **Chat** | Multi-turn dialogue, streaming output, session memory |
| **Knowledge** | Document upload and vector search (RAG) with Ollama embeddings |
| **Model Hub** | Unified LLM config for OpenAI, Anthropic, Ollama, and more |
| **Tools** | Built-in calculator, HTTP, web search, datetime tools |
| **Orchestrator** | Multi-agent collaboration (CrewAI-style sequential flows) |

The frontend supports **Chinese / English** UI.

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
│   │   ├── core/         # Agents, workflows, dialogue, tools
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
| `/agents` | Agent CRUD & execution |
| `/workflows` | Workflow management & execution |
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

- [ ] More workflow node types (HTTP, Code, LLM, etc.)
- [ ] User authentication & multi-tenancy
- [ ] Docker Compose one-click deployment

---

## License

No open-source license has been assigned yet. Contact the author before commercial use or redistribution.

---

## Links

- Repository: [https://github.com/oymclihui/AI-Agent](https://github.com/oymclihui/AI-Agent)
- Chinese README: [README.md](README.md)
