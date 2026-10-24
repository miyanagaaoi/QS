"""数据库会话与初始化。

SQLite 关键配置（PRD 9.5 风险应对）：
- 开启 WAL 模式，缓解 20 人同时在线时的 database is locked
- busy_timeout 兜底等待，避免瞬时并发直接报错
- 外键约束显式开启（SQLite 默认关闭）
"""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings


def _ensure_sqlite_dir(url: str) -> None:
    """确保 SQLite 文件所在目录存在，否则首次启动会失败。"""
    if not url.startswith("sqlite:///"):
        return
    path = url.replace("sqlite:///", "", 1)
    if path in ("", ":memory:"):
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)


# 数据库位置基于 backend/ 解析，避免受启动工作目录影响
_DB_URL = settings.resolved_database_url()
_ensure_sqlite_dir(_DB_URL)

connect_args: dict = {}
if settings.is_sqlite:
    # 多线程场景（uvicorn 默认线程池）需要放开线程检查
    connect_args = {"check_same_thread": False, "timeout": 15}

engine = create_engine(
    _DB_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
    """仅对 SQLite 生效的 PRAGMA 设置。"""
    if not settings.is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每请求一个会话，异常回滚，最终关闭。"""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """建表（原型阶段用 create_all；正式环境改用 Alembic 迁移）。"""
    from . import models  # noqa: F401  确保模型已注册到 metadata

    models.Base.metadata.create_all(bind=engine)
    _migrate_add_columns()
    os.makedirs(settings.resolved_upload_dir(), exist_ok=True)


def _migrate_add_columns() -> None:
    """轻量级列迁移：给已存在的表补新增列（create_all 只建新表，不改旧表）。

    CH-005 给 3 张参考表加了 `project_id`、给 pm_process 加了进度字段。
    这些列都可空/有默认值，因此用 `ALTER TABLE ... ADD COLUMN` 即可，幂等：
    先读 `PRAGMA table_info`（SQLite）判断列是否已存在，存在则跳过。
    仅对 SQLite 生效；换 PostgreSQL 时应改用 Alembic（README 已列为待办）。
    """
    from sqlalchemy import text

    additions: dict[str, list[tuple[str, str]]] = {
        "pm_process": [
            ("project_id", "INTEGER REFERENCES pm_project(id)"),
            ("status", "VARCHAR(12) NOT NULL DEFAULT 'todo'"),
            ("assignee", "VARCHAR(50)"),
            ("started_at", "DATETIME"),
            ("finished_at", "DATETIME"),
            ("progress_remark", "VARCHAR(200)"),
        ],
        "pm_process_log": [("kind", "VARCHAR(12) NOT NULL DEFAULT 'status'")],
        "pm_cost_point": [("project_id", "INTEGER REFERENCES pm_project(id)")],
        "pm_document": [("project_id", "INTEGER REFERENCES pm_project(id)")],
    }
    with engine.begin() as conn:
        for table, columns in additions.items():
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not rows:  # 表还不存在（首次建库时 create_all 已建好，理论上不会走到）
                continue
            existing = {row[1] for row in rows}
            for name, ddl in columns:
                if name in existing:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
