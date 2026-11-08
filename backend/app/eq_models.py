"""设备管理 · 设备全生命周期管理台账（CH-014）。

依据：`设备全生命周期管理台账模板_11-4(1).xlsx`（6 张业务表 + 统计看板）。

- 落 5 张表：主台账 + 动态事件 + 计量检定 + 特种设备检验 + 备件更换；
  统计看板不建表，由接口实时汇总。
- 子表通过 `asset_id` 外键**强关联**主台账（需求方 2026-11-08 确认：
  必须先选设备，不允许孤立台账编号）。
- 下拉字典全部取自模板内置的数据验证（`EQ_*` 常量），不自行增删。
- 主台账为**精简字段**（需求方确认）：去掉出厂编号/日期、制造/安装单位与日期、
  主要技术参数、采购合同号、图纸资料路径，保留建档/运行/状态/质保/报废相关字段。
- 与「采购报价」「项目管理」两个模块**无任何关联**。

本模块单独成文件（而不是追加进 `models.py`），是为了避免大文件追加带来的
编辑风险；建表注册由 `database.init_db()` 里 `import eq_models` 完成。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .models import Base, app_now

# ---------------------------------------------------------------------------
# 下拉字典（全部取自模板的数据验证，顺序与模板一致）
# ---------------------------------------------------------------------------
EQ_IMPORTANCE = ("A", "B", "C")
EQ_ASSET_STATUS = (
    "在用",
    "备用",
    "维修中",
    "待修",
    "封存",
    "闲置",
    "调拨中",
    "待报废",
    "已报废",
)
EQ_EVENT_TYPES = (
    "日常巡检",
    "定期维保",
    "润滑保养",
    "计量检定",
    "特种设备检验",
    "故障维修",
    "备件更换",
    "技术改造",
    "内部调拨",
    "封存启封",
    "报废处置",
)
EQ_ACCEPT_RESULT = ("合格", "不合格", "待复验", "—")
EQ_METER_STATUS = ("在用", "停用", "送检中", "已报废")
EQ_CHECK_TYPES = ("内部检验", "外部检验", "水压试验", "年度检查", "全面检验")
EQ_SPECIAL_STATUS = ("在用", "停用", "整改中", "已注销")
EQ_PART_ORIGIN = ("原厂件", "替代件")
EQ_OLD_PART_DISPOSAL = ("返修", "报废", "留存", "退回供应商")

#: 预警阈值（模板「四、自动预警规则」）
EQ_WARRANTY_WARN_DAYS = 30  # 质保 ≤30 天标橙
EQ_CHECK_WARN_DAYS = 15  # 检定/检验 ≤15 天标橙
EQ_PLAN_WARN_DAYS = 15  # 计划事项 ≤+15 天标橙


class EqAsset(Base):
    """设备主台账（一台设备一行）。"""

    __tablename__ = "eq_asset"
    __table_args__ = (
        Index("ix_eq_asset_status", "status"),
        Index("ix_eq_asset_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_no: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    finance_no: Mapped[str | None] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(30))
    importance: Mapped[str | None] = mapped_column(String(2))
    is_special: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    special_reg_no: Mapped[str | None] = mapped_column(String(60))
    location: Mapped[str | None] = mapped_column(String(80))
    system_name: Mapped[str | None] = mapped_column(String(40))
    commission_date: Mapped[date | None] = mapped_column(Date)
    warranty_start: Mapped[date | None] = mapped_column(Date)
    warranty_end: Mapped[date | None] = mapped_column(Date)
    design_life_years: Mapped[int | None] = mapped_column(Integer)
    scrap_date: Mapped[date | None] = mapped_column(Date)
    purchase_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    supplier: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="在用", nullable=False)
    owner: Mapped[str | None] = mapped_column(String(50))
    remark: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=app_now, onupdate=app_now, nullable=False
    )

    events: Mapped[list["EqEvent"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    meters: Mapped[list["EqMeter"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    specials: Mapped[list["EqSpecial"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    spares: Mapped[list["EqSpare"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class EqEvent(Base):
    """设备动态事件流水台账（一条事件一行）。"""

    __tablename__ = "eq_event"
    __table_args__ = (Index("ix_eq_event_asset", "asset_id", "occur_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("eq_asset.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    occur_date: Mapped[date | None] = mapped_column(Date)
    plan_date: Mapped[date | None] = mapped_column(Date)
    actual_date: Mapped[date | None] = mapped_column(Date)
    reporter: Mapped[str | None] = mapped_column(String(50))
    content: Mapped[str | None] = mapped_column(String(500))
    executor: Mapped[str | None] = mapped_column(String(100))
    cert_no: Mapped[str | None] = mapped_column(String(60))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    accept_result: Mapped[str | None] = mapped_column(String(12))
    acceptor: Mapped[str | None] = mapped_column(String(50))
    accept_date: Mapped[date | None] = mapped_column(Date)
    attachment_path: Mapped[str | None] = mapped_column(String(200))
    corrective: Mapped[str | None] = mapped_column(String(300))
    remark: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)

    asset: Mapped[EqAsset] = relationship(back_populates="events")


class EqMeter(Base):
    """计量器具检定校准台账。"""

    __tablename__ = "eq_meter"
    __table_args__ = (Index("ix_eq_meter_asset", "asset_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("eq_asset.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    accuracy: Mapped[str | None] = mapped_column(String(30))
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cycle_months: Mapped[int | None] = mapped_column(Integer)
    last_check_date: Mapped[date | None] = mapped_column(Date)
    cert_no: Mapped[str | None] = mapped_column(String(60))
    valid_until: Mapped[date | None] = mapped_column(Date)
    org: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="在用", nullable=False)
    owner: Mapped[str | None] = mapped_column(String(50))
    remark: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)

    asset: Mapped[EqAsset] = relationship(back_populates="meters")


class EqSpecial(Base):
    """特种设备定期检验台账。"""

    __tablename__ = "eq_special"
    __table_args__ = (Index("ix_eq_special_asset", "asset_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("eq_asset.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(80))
    reg_no: Mapped[str | None] = mapped_column(String(60))
    check_type: Mapped[str] = mapped_column(String(20), nullable=False)
    cycle_months: Mapped[int | None] = mapped_column(Integer)
    last_check_date: Mapped[date | None] = mapped_column(Date)
    report_no: Mapped[str | None] = mapped_column(String(60))
    valid_until: Mapped[date | None] = mapped_column(Date)
    org: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(12), default="在用", nullable=False)
    owner: Mapped[str | None] = mapped_column(String(50))
    remark: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)

    asset: Mapped[EqAsset] = relationship(back_populates="specials")


class EqSpare(Base):
    """备件更换明细台账。"""

    __tablename__ = "eq_spare"
    __table_args__ = (Index("ix_eq_spare_asset", "asset_id", "replace_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("eq_asset.id"), nullable=False)
    part_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    origin_type: Mapped[str | None] = mapped_column(String(12))
    replace_date: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(300))
    qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    supplier: Mapped[str | None] = mapped_column(String(80))
    old_disposal: Mapped[str | None] = mapped_column(String(20))
    executor: Mapped[str | None] = mapped_column(String(50))
    remark: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)

    asset: Mapped[EqAsset] = relationship(back_populates="spares")
