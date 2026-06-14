from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import Optional, Self

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_PG_URL = (
    "postgresql+asyncpg://aiagnet:aiagnet123@127.0.0.1:5432/aiagnet"
)


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "AI-AGENT"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    SQL_ECHO: bool = False
    SECRET_KEY: str = "changeme-in-production-32chars!!"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    CONVERSATION_RETENTION_DAYS: int = 30
    # Employee template categories visible to non-admin users (comma-separated)
    EMPLOYEE_TEMPLATE_USER_CATEGORIES: str = "finance"
    DEFAULT_ADMIN_EMPLOYEE_NO: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    DEFAULT_ADMIN_EMAIL: str = "admin@local"
    # One-time first-run setup token (install.ps1 generates into SETUP_TOKEN.admin.txt)
    SETUP_TOKEN: str = ""

    # Database — PostgreSQL / VastBase only (SQLite is not supported)
    # Use DATABASE_URL directly, or set DB_HOST + credentials
    # DB_DRIVER: postgresql | vastbase | auto
    # VastBase (海量/Vastbase) uses PostgreSQL wire protocol — same URL shape as PG
    DATABASE_URL: str = _DEFAULT_PG_URL
    DB_DRIVER: str = "postgresql"
    DB_HOST: Optional[str] = None
    DB_PORT: int = 5432
    DB_USER: str = "aiagnet"
    DB_PASSWORD: str = ""
    DB_NAME: str = "aiagnet"
    DB_SSL: str = "prefer"  # disable | prefer | require
    DB_SCHEMA: str = "public"  # VastBase default schema (optional)

    @model_validator(mode="after")
    def _compose_database_url(self) -> Self:
        from app.database_url import build_database_url, DB_DRIVER_VASTBASE, is_sqlite_url

        if self.DB_HOST:
            driver_setting = (self.DB_DRIVER or "postgresql").strip().lower()
            if driver_setting == DB_DRIVER_VASTBASE:
                resolved = DB_DRIVER_VASTBASE
            elif driver_setting == "postgresql":
                resolved = "postgresql"
            else:
                resolved = "postgresql"

            object.__setattr__(
                self,
                "DATABASE_URL",
                build_database_url(
                    driver=resolved,
                    host=self.DB_HOST,
                    port=self.DB_PORT,
                    user=self.DB_USER,
                    password=self.DB_PASSWORD,
                    database=self.DB_NAME,
                    ssl=self.DB_SSL,
                    async_driver=True,
                ),
            )
            if driver_setting == "auto":
                object.__setattr__(self, "DB_DRIVER", resolved)

        if is_sqlite_url(self.DATABASE_URL):
            raise ValueError(
                "SQLite is not supported. Configure PostgreSQL via DATABASE_URL "
                "(postgresql+asyncpg://...) or DB_HOST + DB_USER + DB_PASSWORD + DB_NAME."
            )
        return self

    @property
    def resolved_db_driver(self) -> str:
        from app.database_url import resolve_db_driver

        return resolve_db_driver(self.DATABASE_URL, self.DB_DRIVER)

    @property
    def employee_template_user_categories(self) -> frozenset[str]:
        raw = (self.EMPLOYEE_TEMPLATE_USER_CATEGORIES or "finance").strip()
        if not raw:
            return frozenset()
        return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())

    # Redis — optional; leave empty to disable Celery/Redis features
    REDIS_URL: str = ""

    # ChromaDB — "local" uses embedded persistent client, no server needed
    CHROMA_MODE: str = "local"           # "local" | "server"
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8001
    CHROMA_LOCAL_PATH: str = "./chroma_data"

    # Vector store backend: "milvus" (remote) or "chroma" (local embedded)
    VECTOR_STORE_TYPE: str = "chroma"
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_TOKEN: Optional[str] = None
    MILVUS_DB: str = "default"

    # MinIO — optional; leave empty to use local filesystem uploads
    MINIO_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET_DOCUMENTS: str = "documents"
    MINIO_SECURE: bool = False

    # Local file uploads directory (used when MinIO is not configured)
    LOCAL_UPLOADS_DIR: str = "./uploads"

    # LLM Providers
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Speech-to-text (voice input) — Ollama Whisper by default
    STT_MODEL: str = "whisper"
    STT_TIMEOUT_SECONDS: int = 120
    OPENAI_STT_MODEL: str = "whisper-1"

    # Chat web search — domestic providers first (comma-separated)
    # Supported: bing_cn, baidu, ddg
    WEB_SEARCH_PROVIDERS: str = "bing_cn,baidu"
    WEB_SEARCH_TIMEOUT: float = 10.0

    # Default model settings (fallback when DB has no reachable model yet)
    DEFAULT_LLM_PROVIDER: str = "ollama"
    DEFAULT_LLM_MODEL: str = "qwen3.6:35b"
    DEFAULT_EMBEDDING_MODEL: str = "nomic-embed-text"
    # On startup, probe active models and set the first reachable one as default
    AUTO_PICK_DEFAULT_MODEL: bool = True
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_API_VERSION: str = "2024-02-01"

    # BYD EIS internal LLM gateway (OpenAI-compatible)
    BYD_DEEPSEEK_V4_FLASH_API_KEY: Optional[str] = None
    BYD_DEEPSEEK_V4_FLASH_BASE_URL: str = (
        "https://eisapi.byd.com/open-api/1.0/llm/v1/deepseek-v4-flash"
    )
    BYD_QWEN35_35B_API_KEY: Optional[str] = None
    BYD_QWEN35_35B_BASE_URL: str = (
        "https://eisapi.byd.com/open-api/1.0/llm/v1/qwen35-35b-a3b-fp8"
    )
    BYD_DEEPSEEK_REASONER_API_KEY: Optional[str] = None
    BYD_DEEPSEEK_REASONER_BASE_URL: str = (
        "https://eisapi.byd.com/open-api/1.0/llm/v1/ds-open-671b"
    )
    BYD_DEEPSEEK_32B_API_KEY: Optional[str] = None
    BYD_DEEPSEEK_32B_BASE_URL: str = (
        "https://eisapi.byd.com/open-api/1.0/llm/v1/deepseek/stream"
    )

    # BYD corporate KMS RAG (unit knowledge base)
    BYD_KMS_DEFAULT_URL: str = "https://kms-api.byd.com/open-api/1.0/llm/v1/rag-qa"
    BYD_KMS_API_KEY: Optional[str] = None
    BYD_KMS_TIMEOUT_SECONDS: int = 30

    # Desktop automation (OpenAdapt sidecar)
    DESKTOP_REQUIRE_CONFIRMATION: bool = True
    DESKTOP_OPENADAPT_DATA_DIR: str = "./desktop_openadapt_data"

    # Agent harness (tool policy, confirmation, boundaries)
    HARNESS_REQUIRE_TOOL_CONFIRMATION: bool = True
    HARNESS_LLM_TIMEOUT_SEC: int = 120
    HARNESS_MAX_ITERATIONS_CAP: int = 25

    # Public URL for password-reset links
    APP_PUBLIC_URL: str = "http://localhost:3000"
    PASSWORD_RESET_EXPIRE_MINUTES: int = 60

    # IM bots (Feishu / DingTalk)
    FEISHU_ENABLED: bool = False
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_VERIFICATION_TOKEN: str = ""
    FEISHU_ENCRYPT_KEY: str = ""
    DINGTALK_ENABLED: bool = False
    DINGTALK_APP_KEY: str = ""
    DINGTALK_APP_SECRET: str = ""
    DINGTALK_ROBOT_WEBHOOK: str = ""
    IM_BOT_USER_ID: str = ""

    # Platform SMTP (sends password-reset emails)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USE_SSL: bool = True
    SMTP_USE_TLS: bool = False
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_FROM_NAME: str = "AI-AGENT"

    # Default IMAP for user mailbox tool (BYD corporate mail)
    IMAP_HOST: str = "imap.byd.com"
    IMAP_PORT: int = 1993
    IMAP_USE_SSL: bool = True

    # CORS
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://localhost:80",
    ]

    class Config:
        env_file = str(_BACKEND_DIR / ".env")
        case_sensitive = True


settings = Settings()
