"""后台调度：自动截止兜底扫描（PRD 4.3）。

PRD 4.3 要求：已发布且到达报价截止时间的询价单应自动置为「已截止」。
实现采用双保险：
1. **惰性触发**：任何读取/写入询价单的接口都会调用 utils.auto_close_if_due，
   保证用户看到的列表状态一定是正确的（这是主要路径）。
2. **定时兜底**（本模块）：后台任务每 auto_close_scan_seconds 秒扫描一次，
   确保长时间无人访问时状态也不会滞后（例如报表统计的口径、操作日志留痕）。

调度器故意保持极简：单进程 asyncio 任务 + 独立数据库会话，不引入 APScheduler
等额外依赖。SQLite 单进程部署下足够；若将来多 worker 部署，需要改为
数据库行锁或只在单一 worker 启用（见注释）。
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import Rfq
from ..utils import auto_close_if_due, is_deadline_passed

logger = logging.getLogger("xunjia.scheduler")


def scan_and_close_once() -> int:
    """扫描一批到期未截止的询价单并关闭，返回关闭数量。

    抽成独立函数便于测试（不需要起 asyncio 任务）。
    """
    closed = 0
    db = SessionLocal()
    try:
        candidates = db.scalars(
            select(Rfq).where(Rfq.status == "published", Rfq.deadline.is_not(None))
        ).all()
        for rfq in candidates:
            if is_deadline_passed(rfq.deadline) and auto_close_if_due(db, rfq):
                closed += 1
        if closed:
            db.commit()
            logger.info("自动截止扫描：关闭 %d 张到期询价单", closed)
    except Exception:  # pragma: no cover - 兜底任务不可影响主流程
        db.rollback()
        logger.exception("自动截止扫描失败")
    finally:
        db.close()
    return closed


async def auto_close_loop() -> None:
    """常驻后台循环。由 main.py 的 lifespan 启动与取消。"""
    interval = max(10, int(settings.auto_close_scan_seconds))
    logger.info("自动截止兜底扫描已启动，间隔 %ds", interval)
    try:
        while True:
            # 放到线程池执行，避免阻塞事件循环（SQLite 同步驱动）
            await asyncio.to_thread(scan_and_close_once)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:  # pragma: no cover - 正常关停
        logger.info("自动截止兜底扫描已停止")
        raise
