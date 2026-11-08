"""设备管理模块的接口契约（CH-014）。

约定与全站一致：
- 统一响应 `{code, message, data}`（由 `api/equipment.py` 用 `Envelope` 包装）
- **金额一律序列化为字符串**（避免前端浮点误差，后端计算用 Decimal）
- 日期为 `YYYY-MM-DD`；时间戳为北京时间 naive ISO
- 「距到期(天)」不存库，由接口实时计算后返回（`days_to_warranty` / `days_to_expire` / `days_to_plan`）
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ---------------------------------------------------------------------------
# 主台账
# ---------------------------------------------------------------------------
class EqAssetIn(BaseModel):
    asset_no: str = Field(min_length=1, max_length=40, description="台账编号，唯一")
    finance_no: str | None = Field(default=None, max_length=40, description="资产编号")
    name: str = Field(min_length=1, max_length=80, description="设备名称")
    model: str | None = Field(default=None, max_length=80)
    category: str | None = Field(default=None, max_length=30)
    importance: str | None = Field(default=None, max_length=2, description="A/B/C")
    is_special: bool = False
    special_reg_no: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=80)
    system_name: str | None = Field(default=None, max_length=40)
    commission_date: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    design_life_years: int | None = Field(default=None, ge=0, le=200)
    scrap_date: date | None = None
    purchase_value: str | None = Field(default=None, description="采购原值(元)，字符串")
    supplier: str | None = Field(default=None, max_length=80)
    status: str = Field(default="在用", max_length=12)
    owner: str | None = Field(default=None, max_length=50)
    remark: str | None = Field(default=None, max_length=300)


class EqAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_no: str
    finance_no: str | None = None
    name: str
    model: str | None = None
    category: str | None = None
    importance: str | None = None
    is_special: bool = False
    special_reg_no: str | None = None
    location: str | None = None
    system_name: str | None = None
    commission_date: date | None = None
    warranty_start: date | None = None
    warranty_end: date | None = None
    design_life_years: int | None = None
    scrap_date: date | None = None
    purchase_value: Decimal | None = None
    supplier: str | None = None
    status: str
    owner: str | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime
    # 派生：距质保到期天数（负数为已超期）
    days_to_warranty: int | None = None
    # 派生：子台账条数（详情用）
    event_count: int = 0
    meter_count: int = 0
    special_count: int = 0
    spare_count: int = 0

    @field_serializer("purchase_value")
    def _ser_purchase(self, value: Decimal | None, _info: Any) -> str | None:
        """金额按全站口径序列化为字符串。"""
        return str(value) if value is not None else None


class EqAssetDetail(EqAssetOut):
    events: list["EqEventOut"] = Field(default_factory=list)
    meters: list["EqMeterOut"] = Field(default_factory=list)
    specials: list["EqSpecialOut"] = Field(default_factory=list)
    spares: list["EqSpareOut"] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 动态事件
# ---------------------------------------------------------------------------
class EqEventIn(BaseModel):
    asset_id: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=20)
    occur_date: date | None = None
    plan_date: date | None = None
    actual_date: date | None = None
    reporter: str | None = Field(default=None, max_length=50)
    content: str | None = Field(default=None, max_length=500)
    executor: str | None = Field(default=None, max_length=100)
    cert_no: str | None = Field(default=None, max_length=60)
    cost: str | None = None
    accept_result: str | None = Field(default=None, max_length=12)
    acceptor: str | None = Field(default=None, max_length=50)
    accept_date: date | None = None
    attachment_path: str | None = Field(default=None, max_length=200)
    corrective: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=200)


class EqEventOut(BaseModel):
    id: int
    asset_id: int
    asset_no: str | None = None
    asset_name: str | None = None
    event_type: str
    occur_date: date | None = None
    plan_date: date | None = None
    actual_date: date | None = None
    reporter: str | None = None
    content: str | None = None
    executor: str | None = None
    cert_no: str | None = None
    cost: str | None = None
    accept_result: str | None = None
    acceptor: str | None = None
    accept_date: date | None = None
    attachment_path: str | None = None
    corrective: str | None = None
    remark: str | None = None
    created_at: datetime
    # 派生：距计划完成天数（负数=逾期），未填计划日期则为 None
    days_to_plan: int | None = None
    plan_overdue: bool = False


# ---------------------------------------------------------------------------
# 计量器具检定
# ---------------------------------------------------------------------------
class EqMeterIn(BaseModel):
    asset_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    accuracy: str | None = Field(default=None, max_length=30)
    is_mandatory: bool = True
    cycle_months: int | None = Field(default=None, ge=0, le=120)
    last_check_date: date | None = None
    cert_no: str | None = Field(default=None, max_length=60)
    valid_until: date | None = None
    org: str | None = Field(default=None, max_length=80)
    status: str = Field(default="在用", max_length=12)
    owner: str | None = Field(default=None, max_length=50)
    remark: str | None = Field(default=None, max_length=200)


class EqMeterOut(BaseModel):
    id: int
    asset_id: int
    asset_no: str | None = None
    asset_name: str | None = None
    name: str
    model: str | None = None
    accuracy: str | None = None
    is_mandatory: bool = True
    cycle_months: int | None = None
    last_check_date: date | None = None
    cert_no: str | None = None
    valid_until: date | None = None
    org: str | None = None
    status: str
    owner: str | None = None
    remark: str | None = None
    created_at: datetime
    days_to_expire: int | None = None
    expire_status: str | None = None  # ok / warn / overdue


# ---------------------------------------------------------------------------
# 特种设备检验
# ---------------------------------------------------------------------------
class EqSpecialIn(BaseModel):
    asset_id: int = Field(ge=1)
    name: str | None = Field(default=None, max_length=80)
    reg_no: str | None = Field(default=None, max_length=60)
    check_type: str = Field(min_length=1, max_length=20)
    cycle_months: int | None = Field(default=None, ge=0, le=120)
    last_check_date: date | None = None
    report_no: str | None = Field(default=None, max_length=60)
    valid_until: date | None = None
    org: str | None = Field(default=None, max_length=80)
    status: str = Field(default="在用", max_length=12)
    owner: str | None = Field(default=None, max_length=50)
    remark: str | None = Field(default=None, max_length=200)


class EqSpecialOut(BaseModel):
    id: int
    asset_id: int
    asset_no: str | None = None
    asset_name: str | None = None
    name: str | None = None
    reg_no: str | None = None
    check_type: str
    cycle_months: int | None = None
    last_check_date: date | None = None
    report_no: str | None = None
    valid_until: date | None = None
    org: str | None = None
    status: str
    owner: str | None = None
    remark: str | None = None
    created_at: datetime
    days_to_expire: int | None = None
    expire_status: str | None = None


# ---------------------------------------------------------------------------
# 备件更换
# ---------------------------------------------------------------------------
class EqSpareIn(BaseModel):
    asset_id: int = Field(ge=1)
    part_name: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    origin_type: str | None = Field(default=None, max_length=12)
    replace_date: date | None = None
    reason: str | None = Field(default=None, max_length=300)
    qty: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    supplier: str | None = Field(default=None, max_length=80)
    old_disposal: str | None = Field(default=None, max_length=20)
    executor: str | None = Field(default=None, max_length=50)
    remark: str | None = Field(default=None, max_length=200)


class EqSpareOut(BaseModel):
    id: int
    asset_id: int
    asset_no: str | None = None
    asset_name: str | None = None
    part_name: str
    model: str | None = None
    origin_type: str | None = None
    replace_date: date | None = None
    reason: str | None = None
    qty: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    supplier: str | None = None
    old_disposal: str | None = None
    executor: str | None = None
    remark: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# 统计看板
# ---------------------------------------------------------------------------
class EqCountItem(BaseModel):
    label: str
    count: int
    ratio: float = 0.0


class EqWarnItem(BaseModel):
    label: str
    count: int
    action: str = ""


class EqBoardOut(BaseModel):
    total: int = 0
    by_status: list[EqCountItem] = Field(default_factory=list)
    by_importance: list[EqCountItem] = Field(default_factory=list)
    warnings: list[EqWarnItem] = Field(default_factory=list)
    event_total: int = 0
    by_event_type: list[EqCountItem] = Field(default_factory=list)
    events_this_year: int = 0


# ---------------------------------------------------------------------------
# 导入结果
# ---------------------------------------------------------------------------
class EqImportError(BaseModel):
    row: int
    reason: str


class EqImportResult(BaseModel):
    total: int = 0
    created: int = 0
    failed: int = 0
    errors: list[EqImportError] = Field(default_factory=list)


# 解决前向引用（EqAssetDetail 引用了下面定义的 Out 类）
EqAssetDetail.model_rebuild()
