"""SQLAlchemy 数据模型。

对应 PRD 第 6 章「数据模型」。字段与约束严格按 PRD 落地：
- 金额/数量一律 DECIMAL，禁止 float（PRD 6.3-4）
- 明细行使用内部 UUID line_uid 定位，不依赖「名称+规格」匹配（PRD 2. 明细行标识）
- 改价历史 quote_history 只追加，永不更新或删除（PRD 6.2 / 8. 可追溯）
- 时间统一以 UTC 存储，接口层返回带时区 ISO8601（PRD 6.3-5）
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

# 应用统一时区：北京时间（UTC+8）。与 utils.APP_TZ 保持同一数值；
# 这里独立定义是为了 models 不反向依赖 utils（避免循环导入）。
APP_TZ = timezone(timedelta(hours=8))
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def app_now() -> datetime:
    """应用统一时间基准：**北京时间（UTC+8）的 naive datetime**。

    为什么用本地时间而不是 UTC：
    本系统是**内网单时区**部署（PRD 12.1 Q1：本期固定人民币/单时区），
    管理员在界面里输入的「报价截止时间」直接就是北京时间（Pydantic 解析为 naive）。
    若把存储基准定为 UTC，则 18:00 会被当作 UTC 18:00（实际北京时间次日 02:00），
    导致截止时间比用户意图晚 8 小时 —— 这是实测确认过的缺陷。

    统一为北京时间后：
    - 输入即所见：界面填 18:00，到点即截止；
    - 输出即所见：接口返回的时间字符串可直接展示，无需前端做时区换算；
    - `is_deadline_passed` / `remaining_seconds` 与之同基准比较，语义一致。

    工程约束：业务代码中**禁止直接使用** `datetime.now()` / `date.today()` /
    `astimezone(timezone.utc)`，一律改用 `app_now()` 与 `utils.to_app_tz()`。
    唯一例外是 `security.py` 中 JWT 的 `exp/iat`（协议标准要求 UTC）。
    该约束由 `scripts/e2e_acceptance.py` 的时间口径门禁自动检查。

    实现说明：这里**显式使用 UTC+8 偏移**而不是 `datetime.now()`，因此即使容器
    未安装 tzdata 或 `TZ` 环境变量失效（常见于精简基础镜像），时间口径也不会偏移。

    若将来要支持多时区，应改为带 tzinfo 的 UTC 存储 + 接口层显式时区标注。
    """
    return datetime.now(APP_TZ).replace(tzinfo=None)


def new_line_uid() -> str:
    """明细行的内部 UUID，不展示给用户（PRD 2. 明细行标识）。"""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# 字典与主数据
# --------------------------------------------------------------------------
class UnitDict(Base):
    """计量单位字典（PRD 6.2 unit_dict / FR-MST-01）。"""

    __tablename__ = "unit_dict"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)  # 1启用 0停用
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)


class TaxDict(Base):
    """税率字典（PRD 6.2 tax_dict / FR-MST-02）。"""

    __tablename__ = "tax_dict"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)  # 0.1300
    label: Mapped[str] = mapped_column(String(20), nullable=False)  # "13%"
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Supplier(Base):
    """供货商档案（PRD 6.2 supplier / FR-MST-03）。"""

    __tablename__ = "supplier"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    credit_code: Mapped[str | None] = mapped_column(String(30))
    contact_name: Mapped[str | None] = mapped_column(String(50))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    contact_email: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(200))
    remark: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=app_now, onupdate=app_now, nullable=False
    )

    users: Mapped[list["User"]] = relationship(back_populates="supplier")


class User(Base):
    """账号表（PRD 6.2 user）。

    role: admin 管理员 / buyer 采购员 / supplier 供货商
    供货商角色必须绑定 supplier_id（在业务层校验）。
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str | None] = mapped_column(String(50))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("supplier.id"))
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=app_now, onupdate=app_now, nullable=False
    )

    supplier: Mapped[Supplier | None] = relationship(back_populates="users")


# --------------------------------------------------------------------------
# 询价单
# --------------------------------------------------------------------------
class Rfq(Base):
    """询价单表头（PRD 6.2 rfq）。

    status: draft 草稿 / published 已发布 / closed 已截止
    rfq_no 规则 RFQ{YYYYMMDD}{4位流水}
    """

    __tablename__ = "rfq"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rfq_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    project: Mapped[str] = mapped_column(String(100), nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime)  # 草稿允许为空
    status: Mapped[str] = mapped_column(String(12), default="draft", nullable=False, index=True)
    remark: Mapped[str | None] = mapped_column(String(500))  # 对供货商可见
    internal_remark: Mapped[str | None] = mapped_column(String(500))  # 仅我方可见
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=app_now, onupdate=app_now, nullable=False
    )

    lines: Mapped[list["RfqLine"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan", order_by="RfqLine.seq"
    )
    assignments: Mapped[list["RfqSupplier"]] = relationship(
        back_populates="rfq", cascade="all, delete-orphan"
    )


class RfqLine(Base):
    """询价明细行（PRD 6.2 rfq_line）。发布后视为冻结副本，禁止增删改。"""

    __tablename__ = "rfq_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_uid: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=new_line_uid
    )
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfq.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    material_name: Mapped[str] = mapped_column(String(100), nullable=False)
    spec: Mapped[str | None] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    project: Mapped[str | None] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)

    rfq: Mapped[Rfq] = relationship(back_populates="lines")


class RfqSupplier(Base):
    """分派记录：一条 = 某供货商在某询价单上的报价单（PRD 6.2 rfq_supplier）。

    (rfq_id, supplier_id) 唯一 —— 一家供货商一份报价单（PRD 2. 单据模型）。
    status 由填写完整度自动计算：pending / partial / quoted
    """

    __tablename__ = "rfq_supplier"
    __table_args__ = (UniqueConstraint("rfq_id", "supplier_id", name="uq_rfq_supplier"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfq.id"), nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quoted_line_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_saved_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_saved_at: Mapped[datetime | None] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)

    rfq: Mapped[Rfq] = relationship(back_populates="assignments")
    supplier: Mapped[Supplier] = relationship()
    quote_lines: Mapped[list["QuoteLine"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class QuoteLine(Base):
    """报价明细行（PRD 6.2 quote_line）。一行 = 某供货商对某条询价明细的报价。"""

    __tablename__ = "quote_line"
    __table_args__ = (
        UniqueConstraint("rfq_supplier_id", "line_uid", name="uq_quote_line"),
        # PRD 9.5 建议索引：比价报表按 (rfq_supplier_id, line_uid) 取数
        Index("ix_quote_line_assignment_line", "rfq_supplier_id", "line_uid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rfq_supplier_id: Mapped[int] = mapped_column(
        ForeignKey("rfq_supplier.id"), nullable=False, index=True
    )
    line_uid: Mapped[str] = mapped_column(String(36), nullable=False)
    price_incl_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    tax_included: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    price_excl_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    moq: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    arrival_date: Mapped[date | None] = mapped_column(Date)
    remark: Mapped[str | None] = mapped_column(String(200))
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=app_now, onupdate=app_now, nullable=False
    )

    assignment: Mapped[RfqSupplier] = relationship(back_populates="quote_lines")


class QuoteHistory(Base):
    """改价历史（PRD 6.2 quote_history）—— 追加写入，永不更新或删除。"""

    __tablename__ = "quote_history"
    __table_args__ = (
        Index("ix_quote_history_lookup", "rfq_supplier_id", "line_uid", "version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rfq_supplier_id: Mapped[int] = mapped_column(ForeignKey("rfq_supplier.id"), nullable=False)
    line_uid: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)  # 变更前快照
    changed_fields: Mapped[list[str] | None] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(12), nullable=False)  # save / submit
    operated_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)


class AuditLog(Base):
    """操作日志（PRD 6.2 audit_log）—— 只读，任何角色不可删除。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created", "created_at"),
        Index("ix_audit_log_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operator_id: Mapped[int | None] = mapped_column(Integer)  # 系统动作为 NULL
    operator_name: Mapped[str | None] = mapped_column(String(50))  # 冗余快照
    role: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(String(500))
    client_ip: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False, index=True)
