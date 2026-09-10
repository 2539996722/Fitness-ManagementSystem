"""应用配置（基于 Pydantic Settings）。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from slowapi import Limiter
from slowapi.util import get_remote_address


class Settings(BaseSettings):
    """应用配置。所有值来自环境变量 / .env 文件。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用基础 ----------
    app_name: str = "FitHub API"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    tz: str = "Asia/Shanghai"

    # ---------- 数据库 ----------
    # 推荐方式：完整 DSN
    mysql_dsn: str = "mysql+aiomysql://fithub_user:fithub_pass@localhost:3306/fithub?charset=utf8mb4"

    # 拆分方式（如果不用 mysql_dsn）
    mysql_host: str | None = None
    mysql_port: int | None = None
    mysql_user: str | None = None
    mysql_password: str | None = None
    mysql_db: str | None = None

    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_echo: bool = False

    # ---------- JWT ----------
    jwt_secret: str = Field(
        default="change-me-to-a-secure-random-string-at-least-32-characters-long",
        min_length=32,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    refresh_token_expire_days: int = 7

    # ---------- 默认管理员 ----------
    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    # ---------- CORS ----------
    cors_origins: str = "http://localhost:8080,http://localhost:3000"
    cors_allow_credentials: bool = True

    # ---------- LLM ----------
    llm_api_base: str = "https://api.openai.com/v1"
    llm_api_key: str = "sk-placeholder"
    llm_model_chat: str = "gpt-4o-mini"
    llm_model_embed: str = "text-embedding-3-small"
    llm_timeout: int = 60
    llm_max_retries: int = 2

    # ---------- Chroma ----------
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "exercises_zh"
    # 默认关闭：需要 LLM 服务商提供 embed 模型才能用
    rag_enabled: bool = False

    # ---------- Milvus (向量库，存子块向量) ----------
    milvus_uri: str = "./data/milvus_lite.db"
    # 远程 Milvus 示例：milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "exercises_chunks"
    milvus_embed_dim: int = 1536
    milvus_top_k: int = 5

    # ---------- Redis（短期会话缓存）----------
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str | None = None
    redis_db: int = 0
    redis_max_connections: int = 20
    redis_session_cache_rounds: int = 5
    redis_session_ttl_seconds: int = 3600

    # ---------- 数据集 ----------
    exercises_data_dir: str = "./data/exercises-dataset-zh"

    # ---------- 限流 ----------
    rate_limit_per_minute: int = 60
    rate_limit_ai_per_user_per_day: int = 50
    rate_limit_ai_per_user_per_minute: int = 5

    # ---------- 文件上传 ----------
    upload_max_size_mb: int = 10
    upload_dir: str = "./data/uploads"

    # ---------- 安全 ----------
    bcrypt_rounds: int = 12

    # ============================================
    # 计算属性
    # ============================================

    @field_validator("mysql_dsn")
    @classmethod
    def ensure_charset(cls, v: str) -> str:
        """确保 DSN 包含 charset=utf8mb4。"""
        if "charset=" not in v:
            separator = "&" if "?" in v else "?"
            return f"{v}{separator}charset=utf8mb4"
        return v

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> "Settings":
        """生产模式下强校验：禁占位密钥 + 禁 DEBUG + 默认 admin 密码必须改。"""
        if self.app_env != "production":
            return self

        errors: list[str] = []

        # 1) JWT 密钥必须是真随机（不能再用 change-me 占位）
        if self.jwt_secret.startswith("change-me") or "change-me" in self.jwt_secret:
            errors.append(
                "JWT_SECRET 仍是占位符。生产环境必须用 `openssl rand -hex 32` 生成。"
            )

        # 2) DEBUG 必须关闭
        if self.debug:
            errors.append("DEBUG=true 在生产环境会泄露栈/SQL，必须改为 false。")

        # 3) 默认 admin 密码必须改
        if self.default_admin_password in {"admin123", "password", "123456", "admin"}:
            errors.append(
                f"DEFAULT_ADMIN_PASSWORD={self.default_admin_password!r} 仍是占位密码。"
                "生产前必须修改。"
            )

        if errors:
            msg = "🚨 生产模式启动失败（修复 .env 后重启）：\n  - " + "\n  - ".join(errors)
            logger.error(msg)
            raise RuntimeError(msg)

        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def chroma_path(self) -> Path:
        return Path(self.chroma_persist_dir)

    @property
    def milvus_path(self) -> Path:
        """Milvus Lite 嵌入式数据文件目录。"""
        return Path(self.milvus_uri).parent if not self.milvus_uri.startswith("http") else None

    @property
    def exercises_path(self) -> Path:
        return Path(self.exercises_data_dir)

    @property
    def limiter(self) -> Limiter:
        """全局限流器（按 IP 限流）。"""
        return Limiter(key_func=get_remote_address, default_limits=[f"{self.rate_limit_per_minute}/minute"])

    @property
    def ai_user_daily_limit(self) -> str:
        return f"{self.rate_limit_ai_per_user_per_day}/day"

    @property
    def ai_user_minute_limit(self) -> str:
        return f"{self.rate_limit_ai_per_user_per_minute}/minute"


@lru_cache
def get_settings() -> Settings:
    """获取配置单例。"""
    return Settings()


# 全局配置实例
settings = get_settings()