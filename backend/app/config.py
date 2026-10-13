"""应用配置。

所有可变项通过环境变量注入（PRD 8. 安全：JWT 密钥从环境变量注入）。
.env 文件路径基于本文件定位，因此无论从哪个工作目录启动都能正确加载。

环境变量命名（去掉 XUNJIA_ 前缀后即为字段名）：
    XUNJIA_SECRET_KEY / XUNJIA_DATABASE_URL / XUNJIA_DEBUG
    XUNJIA_ADMIN_PASSWORD / XUNJIA_BUYER_PASSWORD / XUNJIA_DEMO_PASSWORD / XUNJIA_SEED_DEMO
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（config.py 位于 backend/app/config.py）
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="XUNJIA_",
        extra="ignore",
    )

    # --- 基础 ---
    app_name: str = "询价报价系统"
    debug: bool = False

    # --- 数据库 ---
    # SQLite 默认落在 backend/data/xunjia.db；切 PostgreSQL 只需改此项
    database_url: str = "sqlite:///./data/xunjia.db"

    # --- 认证 ---
    # 生产必须通过环境变量覆盖：export XUNJIA_SECRET_KEY=$(openssl rand -hex 32)
    secret_key: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 8 * 60  # 内网放宽至 8 小时（PRD 7.1）

    # --- 上传 ---
    upload_dir: str = "./data/uploads"
    max_upload_size_mb: int = 10

    # --- 业务 ---
    import_max_rows: int = 2000  # 单次导入上限（FR-IMP-06）
    export_max_rows: int = 5000  # 单次导出上限（FR-EXP-05）
    auto_close_scan_seconds: int = 60  # 自动截止兜底扫描间隔（PRD 4.3）

    # --- 初始账号 ---
    default_admin_username: str = "admin"
    admin_password: str | None = None  # 为空则启动时生成随机密码并打印
    buyer_password: str = "buyer123"
    demo_password: str = "supplier123"
    seed_demo: bool = False

    # --- 测试 ---
    # 测试环境下调低 bcrypt 轮数以加速用例执行（生产保持 12）
    bcrypt_rounds: int = 12

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def allowed_upload_ext(self) -> tuple[str, ...]:
        return (".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".docx")

    def resolved_database_url(self) -> str:
        """相对 SQLite 路径解析为基于 backend/ 的绝对路径，避免受工作目录影响。"""
        url = self.database_url
        if not url.startswith("sqlite:///"):
            return url
        raw = url.replace("sqlite:///", "", 1)
        if raw in ("", ":memory:") or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
            return url
        return f"sqlite:///{(BACKEND_DIR / raw).as_posix()}"

    def resolved_upload_dir(self) -> str:
        p = Path(self.upload_dir)
        return str(p if p.is_absolute() else (BACKEND_DIR / p))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
