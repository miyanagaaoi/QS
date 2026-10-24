"""初始数据：默认管理员、单位/税率字典、可选的演示数据。

启动时自动执行（幂等）。
- 默认管理员密码：环境变量 XUNJIA_ADMIN_PASSWORD，未设置则生成随机密码并打印到日志
- 演示数据：环境变量 XUNJIA_SEED_DEMO=1 时创建供货商、账号、示例询价单（对齐 doc/示例.xls）
"""
from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import timedelta

from sqlalchemy import func, select

from .config import settings
from .database import SessionLocal
from .models import Rfq, RfqLine, RfqSupplier, Supplier, TaxDict, UnitDict, User, app_now
from .security import hash_password
from .utils import generate_rfq_no

logger = logging.getLogger("xunjia.seed")

DEFAULT_UNITS = ["个", "台", "套", "包", "支", "桶", "米", "千克", "件", "箱", "卷", "张"]
DEFAULT_TAXES = [
    ("0.1300", "13%", True),
    ("0.0900", "9%", False),
    ("0.0600", "6%", False),
    ("0.0300", "3%", False),
    ("0.0000", "0%", False),
]


def _random_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _ensure_admin(db) -> None:
    exists = db.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
    if exists:
        return
    pwd = settings.admin_password or _random_password()
    db.add(
        User(
            username=settings.default_admin_username,
            password_hash=hash_password(pwd),
            real_name="系统管理员",
            role="admin",
            status=1,
            # 初始管理员不要求强制改密。
            #
            # 原因（本项目真实教训）：管理员密码来自部署时配置的 XUNJIA_ADMIN_PASSWORD，
            # 若首登强制改密，任何用该密码登录的自动化流程（如验收脚本）都会把它改成别的值，
            # 导致后续用约定密码登录失败、多人反复排查。密码强度与"重置密码强制改密"
            # 两处安全兜底仍然生效（见 PRD 14.5）。
            must_change_password=False,
        )
    )
    logger.warning(
        "已创建默认管理员账号：%s / %s（未强制首登改密；如需强制请用账号管理的开关）",
        settings.default_admin_username,
        pwd,
    )


def _ensure_dicts(db) -> None:
    if not db.scalar(select(func.count()).select_from(UnitDict)):
        for i, name in enumerate(DEFAULT_UNITS, start=1):
            db.add(UnitDict(name=name, sort=i, status=1))
    if not db.scalar(select(func.count()).select_from(TaxDict)):
        for i, (rate, label, is_default) in enumerate(DEFAULT_TAXES, start=1):
            db.add(TaxDict(rate=rate, label=label, is_default=is_default, status=1, sort=i))


DEMO_SUPPLIERS = [
    # (名称, 联系人, 电话, 邮箱, 登录名)
    ("恒信文具", "张经理", "13800006621", "zhang@hengxin.example", "hengxin_wenju"),
    ("鑫达办公", "刘女士", "13900003308", "liu@xinda.example", "xinda_bg"),
    ("汇通商贸", "陈先生", "13700009912", "chen@huitong.example", "huitong_sm"),
    ("万隆物资", "赵经理", "13500004417", "zhao@wanlong.example", "wanlong_wz"),
    ("立诚供应链", "孙女士", "13600002233", "sun@licheng.example", "licheng_gyl"),
]

DEMO_LINES = [
    # 对齐 doc/示例.xls 的列语义：材料名称 / 规格型号 / 单位 / 项目 / 采购数量 / 备注
    ("订书机", "得力，小", "个", "办公用品", 40, None),
    ("A4 复印纸", "70g / 500张", "包", "办公用品", 200, None),
    ("签字笔", "0.5mm 黑色", "支", "办公用品", 500, "可替代品牌请在报价备注说明"),
    ("档案盒", "A4 / 55mm", "个", "办公用品", 120, None),
    ("白板笔", "可擦 黑色", "支", "办公用品", 300, None),
    ("文件夹", "A4 双强力", "个", "办公用品", 150, None),
    ("硒鼓", "适配 HP 88A", "个", "办公用品", 20, None),
    ("订书钉", "24/6 通用", "盒", "办公用品", 60, None),
]


def _ensure_demo(db) -> None:
    """创建演示数据（供货商 + 供货商账号 + 3 张不同状态的询价单）。"""
    if db.scalar(select(func.count()).select_from(Supplier)):
        return

    demo_pwd = settings.demo_password
    buyer_pwd = settings.buyer_password

    # 一位采购员
    buyer = User(
        username="wangcaigou",
        password_hash=hash_password(buyer_pwd),
        real_name="王采购",
        role="buyer",
        status=1,
        must_change_password=False,
    )
    db.add(buyer)

    suppliers: list[Supplier] = []
    for name, contact, phone, email, username in DEMO_SUPPLIERS:
        s = Supplier(name=name, contact_name=contact, contact_phone=phone, contact_email=email, status=1)
        db.add(s)
        db.flush()
        suppliers.append(s)
        db.add(
            User(
                username=username,
                password_hash=hash_password(demo_pwd),
                real_name=contact,
                role="supplier",
                supplier_id=s.id,
                status=1,
                must_change_password=False,
            )
        )

    db.flush()

    # 验收专用管理员：供 scripts/e2e_acceptance.py 使用。
    # 单独建号（而不是直接用 admin）是为了让端到端脚本里的"改密类用例"
    # 不会改动人工演示用的 admin 密码 —— 本项目曾因此反复互相干扰。
    if not db.scalar(select(func.count()).select_from(User).where(User.username == "e2e_admin")):
        db.add(
            User(
                username="e2e_admin",
                password_hash=hash_password("E2eAdmin2026"),
                real_name="验收专用管理员",
                role="admin",
                status=1,
                must_change_password=False,
            )
        )
        logger.warning("已创建验收专用管理员：e2e_admin / E2eAdmin2026（供 e2e 脚本使用，与 admin 隔离）")

    def build_rfq(title: str, project: str, status: str, deadline_offset_hours: int, n_suppliers: int) -> Rfq:
        rfq = Rfq(
            rfq_no=generate_rfq_no(db),
            title=title,
            project=project,
            # 草稿按业务惯例不带截止时间（PRD 5.1.2：截止时间在发布时必填），
            # 避免出现"草稿 + 已过期截止时间"这种自相矛盾的演示数据
            deadline=(None if status == "draft" else app_now() + timedelta(hours=deadline_offset_hours)),
            status=status,
            remark="报价含运费，付款方式月结 30 天",
            created_by=buyer.id,
            published_at=app_now() if status != "draft" else None,
            closed_at=app_now() if status == "closed" else None,
        )
        db.add(rfq)
        db.flush()
        for seq, (name, spec, unit, proj, q, remark) in enumerate(DEMO_LINES, start=1):
            db.add(
                RfqLine(
                    rfq_id=rfq.id,
                    seq=seq,
                    material_name=name,
                    spec=spec,
                    unit=unit,
                    project=proj,
                    quantity=q,
                    remark=remark,
                )
            )
        if status != "draft":
            for s in suppliers[:n_suppliers]:
                db.add(
                    RfqSupplier(
                        rfq_id=rfq.id,
                        supplier_id=s.id,
                        status="pending",
                        line_count=len(DEMO_LINES),
                    )
                )
        return rfq

    # deadline_offset_hours 相对当前时间：正数=未到截止（进行中），负数=已过期（已截止）
    build_rfq("办公用品-10月补货询价", "办公用品", "published", 52, 5)
    build_rfq("车间耗材-Q4备料询价", "生产耗材", "closed", -6, 3)
    build_rfq("劳保用品-询价", "劳保用品", "draft", 0, 0)

    logger.warning(
        "已创建演示数据：5 家供货商 / 采购员 %s(%s) / 供货商账号密码 %s（仅开发环境使用）",
        buyer.username,
        buyer_pwd,
        demo_pwd,
    )


def ensure_seed_data() -> None:
    db = SessionLocal()
    try:
        _ensure_admin(db)
        _ensure_dicts(db)
        if settings.seed_demo:
            _ensure_demo(db)
        # 项目管理模块的三张参考表（施工工序/预算决算管理点/配套单据）默认值
        from .pm_seed import ensure_pm_seed

        ensure_pm_seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
