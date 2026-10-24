"""Pydantic 模型（接口契约）。

约定（PRD 7.6）：
- 统一响应体 {"code": 0, "message": "ok", "data": ...}
- 金额与数量序列化为字符串，避免前端浮点误差（后端计算一律 Decimal）
- 时间以 **北京时间（UTC+8）的 naive ISO8601 字符串**返回（如 "2026-10-15T18:00:00"），
  可直接展示，前端不做时区换算；口径与实现约定见 PRD 6.3-5 与 models.app_now 的说明
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

T = TypeVar("T")

# 角色与状态字面量
Role = Literal["admin", "buyer", "supplier"]
RfqStatus = Literal["draft", "published", "closed"]
AssignStatus = Literal["pending", "partial", "quoted"]


# --------------------------------------------------------------------------
# 统一响应
# --------------------------------------------------------------------------
class Envelope(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


class PageMeta(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0


class PageData(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    meta: PageMeta = Field(default_factory=PageMeta)


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json", check_fields=False)
    def _ser(self, value: Any) -> Any:  # pragma: no cover - 兜底序列化
        return value


def _decimal_to_str(v: Decimal | None) -> str | None:
    """金额/数量统一两位或三位小数字符串输出，避免 JS 浮点误差。"""
    if v is None:
        return None
    return format(v, "f")


# --------------------------------------------------------------------------
# 认证
# --------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=100)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=100)
    new_password: str = Field(min_length=8, max_length=20)

    @field_validator("new_password")
    @classmethod
    def _check_strength(cls, v: str) -> str:
        """PRD FR-ACC-13：8~20 位，至少含字母与数字。"""
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("新密码需至少包含字母与数字")
        return v


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    real_name: str | None = None
    role: str
    supplier_id: int | None = None
    supplier_name: str | None = None
    must_change_password: bool = False


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserBrief


# --------------------------------------------------------------------------
# 账号管理
# --------------------------------------------------------------------------
class InternalUserCreate(BaseModel):
    username: str = Field(min_length=4, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    real_name: str | None = Field(default=None, max_length=50)
    role: Literal["admin", "buyer"]
    initial_password: str = Field(min_length=8, max_length=20)
    # 是否要求该账号首次登录修改密码。
    # 需求变更（2026-10）：**默认关闭**（原 FR-ACC-13 为强制改密，现改为可按账号开关）。
    must_change_password: bool = False

    @field_validator("initial_password")
    @classmethod
    def _check_strength(cls, v: str) -> str:
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("初始密码需至少包含字母与数字")
        return v


class InternalUserUpdate(BaseModel):
    real_name: str | None = Field(default=None, max_length=50)
    role: Literal["admin", "buyer"] | None = None


class SupplierAccountCreate(BaseModel):
    supplier_id: int | None = None
    supplier_name: str | None = Field(default=None, max_length=100)
    # 档案字段（supplier_id 为空时用于新建档案）
    credit_code: str | None = Field(default=None, max_length=30)
    contact_name: str | None = Field(default=None, max_length=50)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    username: str = Field(min_length=4, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    initial_password: str = Field(min_length=8, max_length=20)
    # 是否要求首次登录修改密码，**默认关闭**（需求变更 2026-10）
    must_change_password: bool = False


class UserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    real_name: str | None = None
    role: str
    status: int
    supplier_id: int | None = None
    supplier_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=20)


# --------------------------------------------------------------------------
# 供货商档案 / 字典
# --------------------------------------------------------------------------
class SupplierBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    credit_code: str | None = Field(default=None, max_length=30)
    contact_name: str | None = Field(default=None, max_length=50)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    remark: str | None = Field(default=None, max_length=500)


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    credit_code: str | None = Field(default=None, max_length=30)
    contact_name: str | None = Field(default=None, max_length=50)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=200)
    remark: str | None = Field(default=None, max_length=500)


class SupplierOut(SupplierBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: int
    account_bound: bool = False
    account_username: str | None = None
    created_at: datetime | None = None


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    sort: int
    status: int


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    sort: int = 0


class TaxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rate: Decimal
    label: str
    is_default: bool
    status: int
    sort: int = 0

    @field_serializer("rate")
    def _ser_rate(self, v: Decimal) -> str:
        return _decimal_to_str(v) or "0"


class TaxIn(BaseModel):
    rate: Decimal = Field(ge=0, le=1)
    label: str = Field(min_length=1, max_length=20)
    is_default: bool = False
    sort: int = 0


# --------------------------------------------------------------------------
# 询价单
# --------------------------------------------------------------------------
class RfqLineIn(BaseModel):
    """询价明细行入参。

    注意必填策略（PRD FR-RFQ-09 / TC-09）：
    - **草稿允许明细不完整**（材料名称/单位/采购数量可留空），只做长度与数量正数校验，
      真正落库时为空值存空串/NULL；这样用户能边想边存草稿。
    - "明细必填齐全"由**发布校验**统一拦截（api/rfq.py::_collect_publish_errors
      会逐条给出「第N行 字段：原因」），前端在发布前也会先自检一遍。
    """

    seq: int | None = None
    line_uid: str | None = None  # 编辑已有行时携带，避免"名称+规格"匹配错行
    material_name: str | None = Field(default=None, max_length=100)
    spec: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    project: str | None = Field(default=None, max_length=100)
    quantity: Decimal | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=200)


class RfqLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    line_uid: str
    seq: int
    material_name: str
    spec: str | None = None
    unit: str
    project: str | None = None
    quantity: Decimal
    remark: str | None = None

    @field_serializer("quantity")
    def _ser_qty(self, v: Decimal) -> str:
        return _decimal_to_str(v) or "0"


class RfqCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    project: str = Field(min_length=1, max_length=100)
    deadline: datetime | None = None
    remark: str | None = Field(default=None, max_length=500)
    internal_remark: str | None = Field(default=None, max_length=500)
    supplier_ids: list[int] = Field(default_factory=list)
    lines: list[RfqLineIn] = Field(default_factory=list)


class RfqUpdate(RfqCreate):
    pass


class RfqAppendSuppliers(BaseModel):
    """已发布且未截止的询价单：追加受邀供货商（需求变更 2026-10）。

    规则：只能追加**尚未被分派**的供货商；明细与已有分派/报价不受影响。
    被追加的供货商立即可在手机端填报（看到全部明细，自己报价列为空）。
    """

    supplier_ids: list[int] = Field(min_length=1)


class AssigneeOut(BaseModel):
    supplier_id: int
    supplier_name: str
    contact_name: str | None = None
    contact_phone: str | None = None
    status: AssignStatus = "pending"
    line_count: int = 0
    quoted_line_count: int = 0
    last_saved_at: datetime | None = None
    submitted_at: datetime | None = None


class RfqListItem(BaseModel):
    id: int
    rfq_no: str
    title: str
    project: str
    status: RfqStatus
    deadline: datetime | None = None
    line_count: int = 0
    supplier_count: int = 0
    quoted_count: int = 0
    quoted_line_count: int = 0
    created_by_name: str | None = None
    created_at: datetime | None = None


class RfqDetail(BaseModel):
    id: int
    rfq_no: str
    title: str
    project: str
    status: RfqStatus
    deadline: datetime | None = None
    remark: str | None = None
    internal_remark: str | None = None
    published_at: datetime | None = None
    closed_at: datetime | None = None
    created_by: int
    created_by_name: str | None = None
    created_at: datetime | None = None
    lines: list[RfqLineOut] = Field(default_factory=list)
    assignees: list[AssigneeOut] = Field(default_factory=list)


class RfqProgressItem(AssigneeOut):
    pass


# --------------------------------------------------------------------------
# 导入
# --------------------------------------------------------------------------
class ImportErrorItem(BaseModel):
    row: int
    column: str | None = None
    value: str | None = None
    reason: str


class ImportPreviewLine(BaseModel):
    seq: int
    material_name: str
    spec: str | None = None
    unit: str
    project: str | None = None
    quantity: str


class ImportPreviewResult(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    preview: list[ImportPreviewLine] = Field(default_factory=list)
    errors: list[ImportErrorItem] = Field(default_factory=list)
    unknown_units: list[str] = Field(default_factory=list)
    token: str | None = None  # 预校验通过后用于确认导入


class ImportConfirmRequest(BaseModel):
    token: str
    mode: Literal["append", "replace"] = "append"
    add_unknown_units: bool = False


# --------------------------------------------------------------------------
# 供货商报价
# --------------------------------------------------------------------------
class QuoteLineIn(BaseModel):
    line_uid: str
    price_incl_tax: Decimal | None = Field(default=None, ge=0, le=Decimal("9999999.99"))
    tax_included: bool = True
    tax_rate: Decimal | None = Field(default=None, ge=0, le=1)
    moq: Decimal | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    arrival_date: date | None = None
    remark: str | None = Field(default=None, max_length=200)
    attachments: list[dict[str, Any]] | None = None


class QuoteSaveRequest(BaseModel):
    lines: list[QuoteLineIn] = Field(default_factory=list)
    submit: bool = False
    # 乐观锁：客户端回传打开页面时的 assignment.updated_at，服务端比对（PRD 8. 并发）
    expected_updated_at: datetime | None = None


class QuoteLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    line_uid: str
    price_incl_tax: Decimal | None = None
    tax_included: bool = True
    tax_rate: Decimal | None = None
    price_excl_tax: Decimal | None = None
    moq: Decimal | None = None
    lead_time_days: int | None = None
    arrival_date: date | None = None
    remark: str | None = None
    attachments: list[dict[str, Any]] | None = None

    @field_serializer("price_incl_tax", "price_excl_tax")
    def _ser_price(self, v: Decimal | None) -> str | None:
        return _decimal_to_str(v)

    @field_serializer("tax_rate")
    def _ser_tax(self, v: Decimal | None) -> str | None:
        return _decimal_to_str(v)

    @field_serializer("moq")
    def _ser_moq(self, v: Decimal | None) -> str | None:
        return _decimal_to_str(v)


class SupplierRfqListItem(BaseModel):
    """供货商待报价列表项（PRD FR-SUP-02 / FR-RWD-16）。

    注意：绝不包含他方报价、最低价等任何信息（PRD FR-SUP-05）。
    """

    rfq_id: int
    rfq_no: str
    title: str
    project: str
    deadline: datetime | None = None
    remaining_seconds: int | None = None
    status: RfqStatus
    my_status: AssignStatus
    line_count: int = 0
    quoted_line_count: int = 0
    last_saved_at: datetime | None = None
    submitted_at: datetime | None = None


class SupplierRfqDetail(BaseModel):
    rfq_id: int
    rfq_no: str
    title: str
    project: str
    remark: str | None = None  # 我方备注（对供货商可见）
    deadline: datetime | None = None
    remaining_seconds: int | None = None
    status: RfqStatus
    my_status: AssignStatus
    readonly: bool = False
    line_count: int = 0
    quoted_line_count: int = 0
    submitted_at: datetime | None = None
    updated_at: datetime | None = None
    lines: list["SupplierRfqLineOut"] = Field(default_factory=list)


class SupplierRfqLineOut(BaseModel):
    line_uid: str
    seq: int
    material_name: str
    spec: str | None = None
    unit: str
    quantity: Decimal
    # 供货商可见的范围仅限自己公司的报价
    quote: QuoteLineOut | None = None

    @field_serializer("quantity")
    def _ser_qty(self, v: Decimal) -> str:
        return _decimal_to_str(v) or "0"


class QuoteHistoryItem(BaseModel):
    line_uid: str
    version: int
    action: str
    changed_fields: list[str] | None = None
    snapshot: dict[str, Any] | None = None
    operated_by_name: str | None = None
    created_at: datetime


# --------------------------------------------------------------------------
# 报表
# --------------------------------------------------------------------------
class ComparisonRow(BaseModel):
    line_uid: str
    seq: int
    material_name: str
    spec: str | None = None
    unit: str
    quantity: Decimal
    project: str | None = None
    # supplier_id -> 含税单价字符串；未报价不出现该键
    prices: dict[str, str] = Field(default_factory=dict)
    best_price: str | None = None
    best_supplier_id: int | None = None
    best_supplier_name: str | None = None
    max_price: str | None = None
    avg_price: str | None = None
    diff_rate: str | None = None  # (最高-最低)/最低
    quoted_count: int = 0
    required_count: int = 0

    @field_serializer("quantity")
    def _ser_qty(self, v: Decimal) -> str:
        return _decimal_to_str(v) or "0"


class ComparisonSupplier(BaseModel):
    supplier_id: int
    supplier_name: str
    status: AssignStatus


class ComparisonResult(BaseModel):
    rfq_id: int
    rfq_no: str
    title: str
    project: str
    status: RfqStatus
    suppliers: list[ComparisonSupplier] = Field(default_factory=list)
    rows: list[ComparisonRow] = Field(default_factory=list)
    total_best_amount: str | None = None
    total_max_amount: str | None = None
    saved_amount: str | None = None
    saved_rate: str | None = None


class SupplierSummaryRow(BaseModel):
    supplier_id: int
    supplier_name: str
    invited_count: int = 0
    quoted_count: int = 0
    response_rate: str | None = None
    amount: str | None = None
    avg_lead_time: str | None = None
    avg_moq: str | None = None


class ProjectSummaryRow(BaseModel):
    project: str
    rfq_count: int = 0
    line_count: int = 0
    coverage_rate: str | None = None
    best_amount: str | None = None


class SummaryResult(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    rfq_count: int = 0
    line_count: int = 0
    invited_assignments: int = 0
    quoted_assignments: int = 0
    response_rate: str | None = None
    best_amount: str | None = None
    by_supplier: list[SupplierSummaryRow] = Field(default_factory=list)
    by_project: list[ProjectSummaryRow] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 操作日志
# --------------------------------------------------------------------------
class AuditLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    operator_name: str | None = None
    role: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    summary: str | None = None
    client_ip: str | None = None
    created_at: datetime


SupplierRfqDetail.model_rebuild()


# --------------------------------------------------------------------------
# 项目管理模块（CH-002）— 与报价模块无任何字段/外键关联
# --------------------------------------------------------------------------
PmProjectStatus = Literal["planning", "active", "done", "paused"]


class PmStageIn(BaseModel):
    seq: int = Field(ge=1, le=99)
    name: str = Field(min_length=1, max_length=30)
    group_name: str | None = Field(default=None, max_length=20)
    months: str | None = None
    start_month: str | None = None
    end_month: str | None = None
    deliverables: str | None = Field(default=None, max_length=300)
    pm_role: str | None = Field(default=None, max_length=60)
    owner: str | None = Field(default=None, max_length=60)


class PmStageOut(PmStageIn):
    id: int


class PmProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=40)
    current_stage: str | None = Field(default=None, max_length=20)
    start_date: date | None = None
    plan_end_date: date | None = None
    total_months: str | None = None
    manager: str | None = Field(default=None, max_length=50)
    status: PmProjectStatus = "active"
    remark: str | None = Field(default=None, max_length=300)


class PmProjectOut(PmProjectIn):
    id: int
    created_at: datetime
    updated_at: datetime
    # 看板派生指标（按日期计算，只读）
    progress: int = 0            # 0~100，已过天数 / 计划跨度
    elapsed_days: int = 0
    remaining_days: int | None = None
    overdue: bool = False        # 已过计划竣工且未标记竣工
    due_soon: bool = False       # 30 天内到期且未竣工
    stage_count: int = 0
    # 施工工序完成情况（CH-005，看板展示「工序 x/y 完成」）
    process_done: int = 0
    process_total: int = 0


class PmProjectDetail(PmProjectOut):
    stages: list[PmStageOut] = Field(default_factory=list)


class PmBoardSummary(BaseModel):
    total: int = 0
    active: int = 0
    planning: int = 0
    done: int = 0
    paused: int = 0
    overdue: int = 0
    due_soon: int = 0


class PmStageDistribution(BaseModel):
    stage: str
    count: int


class PmBoard(BaseModel):
    summary: PmBoardSummary
    stage_distribution: list[PmStageDistribution] = Field(default_factory=list)
    projects: list[PmProjectOut] = Field(default_factory=list)
    # 近期关键节点：计划竣工日最近的若干项目（含已超期）
    upcoming: list[PmProjectOut] = Field(default_factory=list)


PmProcessStatus = Literal["todo", "doing", "done", "paused"]


class PmProcessIn(BaseModel):
    seq: int | None = None
    group_name: str | None = Field(default=None, max_length=20)
    name: str | None = Field(default=None, max_length=60)
    content: str | None = Field(default=None, max_length=400)
    qc_point: str | None = Field(default=None, max_length=300)
    predecessor: str | None = Field(default=None, max_length=100)
    # 进度字段（模板行不使用）
    assignee: str | None = Field(default=None, max_length=50)
    progress_remark: str | None = Field(default=None, max_length=200)


class PmProcessOut(PmProcessIn):
    id: int
    seq: int
    group_name: str
    name: str
    project_id: int | None = None   # None = 标准模板
    status: PmProcessStatus = "todo"
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PmProcessStatusIn(BaseModel):
    """工序状态变更：目标状态 + 一句备注（PRD FR-PM-21）。"""

    status: PmProcessStatus
    remark: str | None = Field(default=None, max_length=200)


class PmProgressIn(BaseModel):
    """进行中工序的进度更新（CH-006 / FR-PM-27）：只填一句当前进度说明。"""

    remark: str = Field(min_length=1, max_length=200)


class PmProcessLogOut(BaseModel):
    id: int
    process_id: int
    kind: str = "status"   # status=状态变更；progress=进度更新
    from_status: str | None = None
    to_status: str
    remark: str | None = None
    operator_name: str | None = None
    created_at: datetime


class PmProcessCreate(PmProcessIn):
    """在项目副本里新增一行工序（模板行不属于任何项目）。"""

    name: str = Field(min_length=1, max_length=60)
    group_name: str = Field(min_length=1, max_length=20)


class PmCostPointIn(BaseModel):
    seq: int | None = None
    phase: str | None = Field(default=None, max_length=20)
    point: str | None = Field(default=None, max_length=60)
    action: str | None = Field(default=None, max_length=400)
    risk: str | None = Field(default=None, max_length=300)
    owner: str | None = Field(default=None, max_length=60)


class PmCostPointOut(PmCostPointIn):
    id: int
    seq: int
    phase: str
    point: str
    project_id: int | None = None   # None = 标准模板


class PmDocumentIn(BaseModel):
    seq: int | None = None
    cost_point: str | None = Field(default=None, max_length=60)
    name: str | None = Field(default=None, max_length=60)
    usage: str | None = Field(default=None, max_length=200)
    required_fields: str | None = Field(default=None, max_length=400)
    flow: str | None = Field(default=None, max_length=200)
    archive: str | None = Field(default=None, max_length=200)


class PmDocumentOut(PmDocumentIn):
    id: int
    seq: int
    name: str
    project_id: int | None = None   # None = 标准模板
