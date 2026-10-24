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


# ===========================================================================
# 项目管理模块（CH-002）
#
# 与报价模块**完全独立**：不建立任何外键关联，也不共享 project 文本字段，
# 便于后期按需改造（例如把询价单挂到项目上）。数据以手工维护为主。
# ===========================================================================

#: 8 阶段标准工期模板（月）。来源：doc/工程项目全周期工期计划表 的「工期计划表」。
#: 建设工期合计 = 序号 1~7 = 24 个月；缺陷保修（质保）24 个月单列，不计入建设工期。
PM_STAGE_TEMPLATE: list[dict[str, object]] = [
    {"seq": 1, "name": "决策立项", "group_name": "决策阶段", "months": 2,
     "deliverables": "项目建议书、可研报告、立项批复/备案文件",
     "pm_role": "尚未介入（甲方主导）", "owner": "甲方"},
    {"seq": 2, "name": "勘察设计", "group_name": "准备阶段", "months": 3,
     "deliverables": "地质勘察、初步设计、施工图、审图合格书",
     "pm_role": "尚未介入（设计/甲方）", "owner": "设计单位"},
    {"seq": 3, "name": "招标签约", "group_name": "准备阶段", "months": 1.5,
     "deliverables": "招标文件、中标通知书、工程合同",
     "pm_role": "参与投标与合同谈判", "owner": "甲方/总包"},
    {"seq": 4, "name": "施工准备", "group_name": "准备阶段", "months": 1,
     "deliverables": "施工许可证、施组报审、项目管理目标责任书",
     "pm_role": "★ 正式进场履职", "owner": "施工方"},
    {"seq": 5, "name": "施工实施", "group_name": "实施阶段", "months": 14,
     "deliverables": "分部分项验收、隐蔽验收、变更签证记录",
     "pm_role": "★ 全周期第一责任人", "owner": "施工方"},
    {"seq": 6, "name": "调试试运行", "group_name": "实施阶段", "months": 1.5,
     "deliverables": "单机调试、联动调试报告、试运行记录",
     "pm_role": "★ 组织调试与整改", "owner": "施工方"},
    {"seq": 7, "name": "竣工验收", "group_name": "验收交付", "months": 1,
     "deliverables": "五方竣工验收报告、规划/消防/档案验收、备案表",
     "pm_role": "★ 组织验收与移交", "owner": "五方/甲方"},
    {"seq": 8, "name": "缺陷保修", "group_name": "验收交付", "months": 24,
     "deliverables": "保修书、缺陷维修记录、质保金结算单",
     "pm_role": "保修期内牵头处理", "owner": "施工方"},
]


class PmProject(Base):
    """工程项目（手工维护；与 rfq.project 文本无关）。"""

    __tablename__ = "pm_project"
    __table_args__ = (Index("ix_pm_project_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    code: Mapped[str | None] = mapped_column(String(40))
    current_stage: Mapped[str | None] = mapped_column(String(20))  # 手工维护的"实际阶段"
    start_date: Mapped[date | None] = mapped_column(Date)
    plan_end_date: Mapped[date | None] = mapped_column(Date)
    total_months: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    manager: Mapped[str | None] = mapped_column(String(50))
    # planning 未开工 / active 进行中 / done 已竣工 / paused 暂停
    status: Mapped[str] = mapped_column(String(12), default="active", nullable=False)
    remark: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=app_now, onupdate=app_now, nullable=False
    )

    stages: Mapped[list["PmStage"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="PmStage.seq"
    )


class PmStage(Base):
    """某项目的工期计划表一行（默认由 PM_STAGE_TEMPLATE 生成，可手工改）。"""

    __tablename__ = "pm_stage"
    __table_args__ = (Index("ix_pm_stage_project", "project_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("pm_project.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(20))
    months: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    start_month: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    end_month: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    deliverables: Mapped[str | None] = mapped_column(String(300))
    pm_role: Mapped[str | None] = mapped_column(String(60))
    owner: Mapped[str | None] = mapped_column(String(60))

    project: Mapped[PmProject] = relationship(back_populates="stages")


class PmProcess(Base):
    """施工实施步骤明细（CH-005：模板 + 项目副本）。

    `project_id` 为 NULL 表示**标准模板**（管理员维护，全公司一套）；
    非空表示某个项目的副本（新建项目时从模板复制，项目内可增删改，互不影响）。
    进度字段只对项目副本有意义（模板不跟踪进度）。
    """

    __tablename__ = "pm_process"
    __table_args__ = (
        Index("ix_pm_process_project", "project_id", "seq"),
        Index("ix_pm_process_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("pm_project.id"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    group_name: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    content: Mapped[str | None] = mapped_column(String(400))
    qc_point: Mapped[str | None] = mapped_column(String(300))
    predecessor: Mapped[str | None] = mapped_column(String(100))
    # —— 进度（仅项目副本使用）——
    # todo 未开始 / doing 进行中 / done 已完成 / paused 暂停
    status: Mapped[str] = mapped_column(String(12), default="todo", nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(50))  # 该工序负责人
    started_at: Mapped[datetime | None] = mapped_column(DateTime)  # 首次转"进行中"
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)  # 转"已完成"
    progress_remark: Mapped[str | None] = mapped_column(String(200))


class PmProcessLog(Base):
    """工序状态变更历史（CH-005）—— 追加写入，永不修改或删除。

    每次状态变更记一条（原状态 → 新状态 + 备注 + 操作人），
    对应 PRD `FR-PM-22`：用于追溯"谁在什么时候把哪道工序推进到哪一步"。
    """

    __tablename__ = "pm_process_log"
    __table_args__ = (Index("ix_pm_process_log_lookup", "process_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("pm_process.id"), nullable=False)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("pm_project.id"))
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str] = mapped_column(String(12), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(200))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    operator_name: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=app_now, nullable=False)


class PmCostPoint(Base):
    """预算决算管理点（CH-005：模板 + 项目副本；project_id 为 NULL 表示模板）。"""

    __tablename__ = "pm_cost_point"
    project_id: Mapped[int | None] = mapped_column(ForeignKey("pm_project.id"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)  # 预算编制/过程管控/竣工结算/财务决算/审计配合
    point: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str | None] = mapped_column(String(400))
    risk: Mapped[str | None] = mapped_column(String(300))
    owner: Mapped[str | None] = mapped_column(String(60))


class PmDocument(Base):
    """预算决算配套单据（CH-005：模板 + 项目副本；project_id 为 NULL 表示模板）。"""

    __tablename__ = "pm_document"
    project_id: Mapped[int | None] = mapped_column(ForeignKey("pm_project.id"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_point: Mapped[str | None] = mapped_column(String(60))  # 对应管理点
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    usage: Mapped[str | None] = mapped_column(String(200))
    required_fields: Mapped[str | None] = mapped_column(String(400))
    flow: Mapped[str | None] = mapped_column(String(200))
    archive: Mapped[str | None] = mapped_column(String(200))
