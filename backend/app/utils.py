"""通用工具：单号生成、金额计算、报价状态计算、时间处理。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Rfq, RfqSupplier, app_now

# 应用统一时区：北京时间（内网单时区部署，见 models.app_now 说明）
APP_TZ = timezone(timedelta(hours=8))

TWO = Decimal("0.01")
THREE = Decimal("0.001")


def money(value: Decimal | float | int | str | None) -> Decimal | None:
    """金额四舍五入到 2 位小数，一律用 Decimal（PRD 6.3-4）。"""
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def qty(value: Decimal | float | int | str | None) -> Decimal | None:
    """数量四舍五入到 3 位小数。"""
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(THREE, rounding=ROUND_HALF_UP)


def fmt(value: Decimal | None, places: int = 2) -> str | None:
    """Decimal -> 固定小数位字符串（接口输出用，避免 JS 浮点误差）。"""
    if value is None:
        return None
    return format(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")


def calc_price_excl_tax(price_incl_tax: Decimal | None, tax_included: bool, tax_rate: Decimal | None) -> Decimal | None:
    """不含税单价 = 含税单价 / (1 + 税率)。

    未含税（tax_included=False）时，填的即不含税价，直接返回原值（PRD 5.2.2）。
    """
    if price_incl_tax is None:
        return None
    if not tax_included:
        return money(price_incl_tax)
    rate = tax_rate or Decimal("0")
    if rate <= 0:
        return money(price_incl_tax)
    return money(price_incl_tax / (Decimal("1") + rate))


def generate_rfq_no(db: Session, today: date | None = None) -> str:
    """生成询价单号 RFQ{YYYYMMDD}{4位流水}（PRD 6.2 rfq_no / 6.3-1）。

    并发安全：唯一索引 + 冲突重试在调用侧处理；此处按当日最大流水 +1。
    """
    day = today or app_now().strftime("%Y%m%d")
    day = day if isinstance(day, str) else day.strftime("%Y%m%d")
    prefix = f"RFQ{day}"
    latest = db.scalar(
        select(func.max(Rfq.rfq_no)).where(Rfq.rfq_no.like(f"{prefix}%"))
    )
    seq = 1
    if latest:
        try:
            seq = int(latest[len(prefix):]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:04d}"


def refresh_assignment_status(db: Session, assignment: RfqSupplier, *, submitted: bool = False) -> RfqSupplier:
    """按填写完整度重算分派状态：pending / partial / quoted（PRD 4.2）。

    规则：
    - 已提交（submitted=True）或全部行已填价 -> quoted
    - 有任意一行填价 -> partial
    - 否则 pending
    """
    from .models import QuoteLine

    total = db.scalar(
        select(func.count()).select_from(QuoteLine).where(QuoteLine.rfq_supplier_id == assignment.id)
    ) or 0
    filled = db.scalar(
        select(func.count())
        .select_from(QuoteLine)
        .where(QuoteLine.rfq_supplier_id == assignment.id, QuoteLine.price_incl_tax.is_not(None))
    ) or 0
    assignment.quoted_line_count = int(filled)
    if assignment.line_count and assignment.line_count != total:
        # 分派行数与报价行数不一致时以实际报价行为准（防止数据漂移）
        assignment.line_count = int(total)

    if submitted or (total > 0 and filled >= total):
        assignment.status = "quoted"
        if submitted and assignment.submitted_at is None:
            assignment.submitted_at = app_now()
    elif filled > 0:
        assignment.status = "partial"
    else:
        assignment.status = "pending"
    return assignment


def to_app_tz(value: datetime | None) -> datetime | None:
    """把带时区的时间转成应用基准（北京时间）的 naive datetime。

    应用统一使用北京时间（见 models.app_now 的说明）。前端的 <input type="datetime-local">
    可能带上浏览器时区（如 +08:00），必须先转成北京时间再去掉 tzinfo，
    否则会出现"存的是 UTC，比的是北京时间"的错位。
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(APP_TZ).replace(tzinfo=None)
    return value


def is_deadline_passed(deadline: datetime | None, now: datetime | None = None) -> bool:
    """截止时间是否已过。存储与比较统一使用北京时间（models.app_now）。"""
    if deadline is None:
        return False
    now = now or app_now()
    deadline = to_app_tz(deadline)
    return deadline <= now


def remaining_seconds(deadline: datetime | None, now: datetime | None = None) -> int | None:
    """剩余秒数；无截止时间为 None，已过为 0。"""
    if deadline is None:
        return None
    now = now or app_now()
    deadline = to_app_tz(deadline)
    delta = (deadline - now).total_seconds()
    return max(0, int(delta))


def auto_close_if_due(db: Session, rfq: Rfq) -> bool:
    """惰性自动截止（PRD 4.3）：已发布且到期则置为 closed 并写日志。"""
    if rfq.status != "published" or not is_deadline_passed(rfq.deadline):
        return False
    from .deps import write_audit

    rfq.status = "closed"
    rfq.closed_at = app_now()
    write_audit(
        db,
        user=None,
        action="rfq.auto_close",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"询价单 {rfq.rfq_no} 到达截止时间，系统自动置为已截止",
    )
    return True


def page_offset(page: int, page_size: int) -> tuple[int, int]:
    """返回 (offset, limit)，并约束分页边界。"""
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    return (page - 1) * page_size, page_size
