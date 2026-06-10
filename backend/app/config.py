from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import Optional, Self


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "AI-AGENT"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    SQL_ECHO: bool = False
    SECRET_KEY: str = "changeme-in-production-32chars!!"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    CONVERSATION_RETENTION_DAYS: int = 30
    DEFAULT_ADMIN_EMPLOYEE_NO: str = "admin"
    DEFAULT_ADMIN_PASSWORD: str = "admin123"
    DEFAULT_ADMIN_EMAIL: str = "admin@local"

    # Database — use DATABASE_URL directly, or set DB_HOST + credentials for PostgreSQL
    DATABASE_URL: str = "sqlite+aiosqlite:///./aiagnet.db"
    DB_HOST: Optional[str] = None
    DB_PORT: int = 5432
    DB_USER: str = "aiagnet"
    DB_PASSWORD: str = ""
    DB_NAME: str = "aiagnet"
    DB_SSL: str = "prefer"  # disable | prefer | require

    @model_validator(mode="after")
    def _compose_database_url(self) -> Self:
        if self.DB_HOST:
            from app.database_url import build_database_url

            object.__setattr__(
                self,
                "DATABASE_URL",
                build_database_url(
                    driver="postgresql",
                    host=self.DB_HOST,
                    port=self.DB_PORT,
                    user=self.DB_USER,
                    password=self.DB_PASSWORD,
                    database=self.DB_NAME,
                    ssl=self.DB_SSL,
                    async_driver=True,
                ),
            )
        return self

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

    # Default model settings (Ollama-first when no OpenAI key)
    DEFAULT_LLM_PROVIDER: str = "ollama"
    DEFAULT_LLM_MODEL: str = "qwen3.6:35b"
    DEFAULT_EMBEDDING_MODEL: str = "nomic-embed-text"
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

    # Public URL for password-reset links
    APP_PUBLIC_URL: str = "http://localhost:3000"
    PASSWORD_RESET_EXPIRE_MINUTES: int = 60

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
        env_file = ".env"
        case_sensitive = True


settings = Settings()
