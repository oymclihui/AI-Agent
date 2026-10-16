# AGENTS.md

## Cursor Cloud specific instructions

This is the **AI-AGENT** platform: a FastAPI backend + Next.js frontend + PostgreSQL. The
dependency-refresh update script (venv + `pip install` + `npm install`) already runs on VM
startup. The notes below cover the non-obvious things needed to actually *run* the stack.

### Services

| Service | Dir | Port | Start command (dev) |
| --- | --- | --- | --- |
| PostgreSQL 16 | system | 5432 | `sudo pg_ctlcluster 16 main start` |
| Backend (FastAPI) | `backend/` | 8000 | `backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` |
| Frontend (Next.js 14) | `frontend/` | 3000 | `BACKEND_URL=http://127.0.0.1:8000 npm run dev` |

Standard scripts live in `frontend/package.json` (`dev`/`build`/`lint`/`start`) and the root
Windows `.ps1` / `docker-compose*.yml` files (not used in this Linux cloud env).

### Startup order & gotchas

- **PostgreSQL is mandatory and must be started first** — SQLite is explicitly rejected in
  `backend/app/config.py`. It does **not** auto-start on a fresh pod boot; run the
  `pg_ctlcluster` command above. The `aiagnet` role/db (`aiagnet` / `aiagnet123`) already
  exist in the data dir. If missing, recreate with:
  `sudo -u postgres psql -c "CREATE ROLE aiagnet LOGIN PASSWORD 'aiagnet123';" -c "CREATE DATABASE aiagnet OWNER aiagnet;"`
- **Backend config**: `backend/.env` (git-ignored) is created from `backend/.env.example`; its
  default `DATABASE_URL` (`postgresql+asyncpg://aiagnet:aiagnet123@127.0.0.1:5432/aiagnet`)
  matches the local DB. If `backend/.env` is ever missing, run `cp backend/.env.example backend/.env`.
- On first startup the backend auto-creates all tables and seeds template agents/workflows/
  skills plus the default admin. This can take ~10–20s; watch for `Application startup complete`.
- **Frontend must know where the backend is**: set `BACKEND_URL=http://127.0.0.1:8000`. The
  Next.js server proxies `/api/v1/*` to the backend via `frontend/src/app/api/v1/[...path]/route.ts`.
- **Default admin login**: employee no `admin` / password `admin123`.
- **Creating an agent** requires three non-empty fields: 名称 (name), 角色 (role) and
  目标 (goal). Omitting 目标 yields a silent `422` in the UI.

### LLM is not configured in this environment (expected)

No Ollama server or LLM API key is present, so any feature that calls a model **will fail**
with connection errors — this is expected, not a broken environment. Affected flows: chat,
agent *run*, workflow *execute*, orchestrator run, and knowledge document upload (needs
embeddings). All non-LLM CRUD (auth, agents/knowledge/workflows CRUD, tools, models config)
works fully. To enable AI features, set an LLM provider in `backend/.env` (e.g. `OPENAI_API_KEY`,
BYD `BYD_*_API_KEY`, or point `OLLAMA_BASE_URL` at a running Ollama).

### Lint / test

- Frontend lint: `npm run lint` (in `frontend/`) is **interactive on first run** because no
  ESLint config is committed — it prompts to pick a config and cannot run non-interactively
  until an `.eslintrc*` exists.
- Backend has no formal test framework; use the live-server smoke test:
  `backend/.venv/bin/python backend/smoke_test.py` (backend must be running). LLM-dependent
  checks in it will fail for the reason above; the rest should pass.

### Optional services (not required for dev)

Redis, MinIO, ChromaDB server, Milvus, Celery worker, and Nginx are all optional. The backend
degrades gracefully: `REDIS_URL` empty disables Celery, empty `MINIO_ENDPOINT` uses local-FS
uploads (`backend/uploads`), and ChromaDB runs embedded (`CHROMA_MODE=local`).
