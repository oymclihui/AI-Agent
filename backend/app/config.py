from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "AIAGNET"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    SQL_ECHO: bool = False
    SECRET_KEY: str = "changeme-in-production-32chars!!"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database — defaults to local SQLite (no PostgreSQL needed)
    DATABASE_URL: str = "sqlite+aiosqlite:///./aiagnet.db"

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

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:80"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
