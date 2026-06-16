"""Shared defaults for Windows Docker desktop delivery (org DB pre-configured)."""
from __future__ import annotations

import secrets
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / ".env.desktop.org"


def _load_config() -> dict[str, str]:
    defaults = {
        "DB_HOST": "10.9.240.114",
        "DB_PORT": "5432",
        "DB_USER": "root",
        "DB_PASSWORD": "",
        "DB_NAME": "fian",
        "DB_SCHEMA": "aiagent",
        "DB_DRIVER": "postgresql",
        "DB_SSL": "prefer",
        "HTTP_PORT": "3000",
        "USE_BUNDLED_POSTGRES": "false",
    }
    if not _CONFIG_PATH.is_file():
        return defaults
    for line in _CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        defaults[key.strip()] = val.strip()
    return defaults


_CFG = _load_config()
HTTP_PORT = int(_CFG.get("HTTP_PORT", "3000"))
USE_BUNDLED_POSTGRES = _CFG.get("USE_BUNDLED_POSTGRES", "false").lower() in ("1", "true", "yes")
DB_HOST = _CFG["DB_HOST"]
DB_PORT = _CFG["DB_PORT"]
DB_USER = _CFG["DB_USER"]
DB_PASSWORD = _CFG["DB_PASSWORD"]
DB_NAME = _CFG["DB_NAME"]
DB_SCHEMA = _CFG.get("DB_SCHEMA", "aiagent")
DB_DRIVER = _CFG["DB_DRIVER"]
DB_SSL = _CFG["DB_SSL"]


def build_env_text(*, setup_token: str | None = None, secret_key: str | None = None) -> str:
    token = setup_token or secrets.token_hex(16)
    sk = secret_key or secrets.token_hex(16)
    public_url = f"http://127.0.0.1:{HTTP_PORT}"
    origins = (
        f'["http://127.0.0.1:{HTTP_PORT}","http://localhost:{HTTP_PORT}",'
        f'"http://127.0.0.1","http://localhost"]'
    )
    return f"""HTTP_PORT={HTTP_PORT}
SECRET_KEY={sk}

APP_PUBLIC_URL={public_url}
ALLOWED_ORIGINS={origins}
NEXT_PUBLIC_WS_URL=ws://127.0.0.1:{HTTP_PORT}/ws

DB_DRIVER={DB_DRIVER}
DB_HOST={DB_HOST}
DB_PORT={DB_PORT}
DB_USER={DB_USER}
DB_PASSWORD={DB_PASSWORD}
DB_NAME={DB_NAME}
DB_SCHEMA={DB_SCHEMA}
DB_SSL={DB_SSL}

SETUP_TOKEN={token}

VECTOR_STORE_TYPE=chroma
OLLAMA_BASE_URL=http://host.docker.internal:11434
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL=qwen3.6:35b
DEFAULT_EMBEDDING_MODEL=nomic-embed-text
AUTO_PICK_DEFAULT_MODEL=true

WEB_SEARCH_PROVIDERS=bing_cn,baidu
WEB_SEARCH_TIMEOUT=10

BYD_DEEPSEEK_V4_FLASH_API_KEY=
BYD_QWEN35_35B_API_KEY=
"""


def build_backend_env_text(*, setup_token: str | None = None, secret_key: str | None = None) -> str:
    """Native Windows package: backend/.env — local FE/BE, shared org DB."""
    token = setup_token or secrets.token_hex(16)
    sk = secret_key or secrets.token_hex(16)
    return f"""APP_NAME=AI-AGENT
DEBUG=false
SQL_ECHO=false
SECRET_KEY={sk}
ACCESS_TOKEN_EXPIRE_MINUTES=10080

DEFAULT_ADMIN_EMPLOYEE_NO=admin
DEFAULT_ADMIN_PASSWORD=admin123
DEFAULT_ADMIN_EMAIL=admin@local
SETUP_TOKEN={token}
CONVERSATION_RETENTION_DAYS=30

DB_DRIVER={DB_DRIVER}
DB_HOST={DB_HOST}
DB_PORT={DB_PORT}
DB_USER={DB_USER}
DB_PASSWORD={DB_PASSWORD}
DB_NAME={DB_NAME}
DB_SCHEMA={DB_SCHEMA}
DB_SSL={DB_SSL}

VECTOR_STORE_TYPE=chroma
CHROMA_MODE=local
CHROMA_LOCAL_PATH=./chroma_data

OLLAMA_BASE_URL=http://127.0.0.1:11434
DEFAULT_LLM_PROVIDER=ollama
DEFAULT_LLM_MODEL=qwen3.6:35b
DEFAULT_EMBEDDING_MODEL=nomic-embed-text
AUTO_PICK_DEFAULT_MODEL=true

WEB_SEARCH_PROVIDERS=bing_cn,baidu
WEB_SEARCH_TIMEOUT=10

BYD_DEEPSEEK_V4_FLASH_API_KEY=
BYD_QWEN35_35B_API_KEY=
"""


def user_readme() -> str:
    public_url = f"http://127.0.0.1:{HTTP_PORT}"
    return f"""AI-AGENT 单位部署说明（每人本地一台服务器）
====================================

架构:
  - 每台办公电脑本地运行前端 + 后端（本机 {public_url}）
  - 共用中心数据库 {DB_HOST}:{DB_PORT}/{DB_NAME}  schema={DB_SCHEMA}
  - 向量库 Chroma 在本机（每人独立，不上传中心库）

首次使用:
  1. 双击 AI-AGENT.bat 或 AI-AGENT-Docker.bat / Setup EXE
  2. 浏览器打开 {public_url}
  3. 若库中尚无账号，管理员用 SETUP_TOKEN.admin.txt 完成初始化

登录: 工号自注册或管理员创建；模型 Key 在「模型中心」自行填写
"""


def admin_readme(setup_token: str) -> str:
    public_url = f"http://127.0.0.1:{HTTP_PORT}"
    return f"""AI-AGENT 管理员说明
====================
数据库: {DB_HOST}:{DB_PORT}/{DB_NAME}  schema={DB_SCHEMA}  (用户 {DB_USER})

用户访问:
  {public_url}

首次初始化（若数据库尚无账号）:
  {public_url}/setup?token={setup_token}

默认管理员（初始化后）:
  admin / admin123

日常启动: 双击 AI-AGENT-Docker.bat
"""


def compose_up_args() -> list[str]:
    if USE_BUNDLED_POSTGRES:
        return ["--profile", "bundled-db", "up", "-d"]
    return ["up", "-d"]


def required_image_tars() -> list[str]:
    base = ["backend.tar", "frontend.tar", "chromadb.tar", "nginx.tar"]
    if USE_BUNDLED_POSTGRES:
        base.append("postgres.tar")
    return base
