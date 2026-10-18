"""统计报表：视图 A 单张询价单比价、视图 B 汇总统计（PRD 5.3 / FR-RPT-01 ~ FR-RPT-07）。

性能约定（PRD 8. 性能：50 家 × 2000 行 P95 < 2s）：
- 比价与汇总均使用**一次性聚合查询**把全部 quote_line 取到内存再组装，不做 N+1；
- 金额全程 Decimal，输出统一 utils.fmt（两位小数纯数字字符串，¥ 由前端补），绝不使用 float；
- 比率字段（diff_rate / response_rate / saved_rate / coverage_rate）输出 `"xx.x%"` 百分数字符串，
  与设计稿 02-pages-buyer 的 `15.9%` / `83.3%` 展示一致（PRD FR-RPT-03）。

安全约定（PRD 3.3-2 / FR-RPT-07）：
- 供货商角色访问报表接口一律 40300，并写 security.forbidden 告警日志；
- 采购员只能看自己创建的单据，其余按越权留痕处理。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import exporter
from ..database import get_db
from ..deps import INTERNAL_ROLES, audit_forbidden, get_current_user, write_audit
from ..models import QuoteLine, Rfq, RfqLine, RfqSupplier, Supplier, User
from ..schemas import (
    ComparisonResult,
    ComparisonRow,
    ComparisonSupplier,
    Envelope,
    ProjectSummaryRow,
    SupplierSummaryRow,
    SummaryResult,
)
from ..utils import fmt, money

router = APIRouter()

EXPORT_MEDIA_TYPE = exporter.EXPORT_MEDIA_TYPE


def require_report_access(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """报表可见性守卫：供货商一律 403 并留痕（require_internal 不留痕，故单独实现）。"""
    if user.role not in INTERNAL_ROLES:
        raise audit_forbidden(
            db,
            request,
            user,
            resource=request.url.path,
            detail=f"账号 {user.username}（{user.role}）尝试访问报表接口 {request.url.path}",
        )
    return user


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": 40400, "message": message})


def _err(status_code: int, code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# --------------------------------------------------------------------------
# 数据隔离：非管理员只能看到/统计自己创建的询价单（PRD 3.3-4）
# --------------------------------------------------------------------------
def _owner_scope(user: User) -> int | None:
    """返回需要限定的创建人 ID；None 表示不限（管理员）。

    采购员之间必须互相看不到对方发出的询价，这是服务端强制的边界：
    前端隐藏菜单/按钮只是体验，不能作为隔离手段。
    """
    return None if user.role == "admin" else user.id


# --------------------------------------------------------------------------
# 查询参数容错（前端清空筛选条件时会把 "" 透传上来，必须按「未传」处理）
# --------------------------------------------------------------------------
def _blank_to_none(value: str | None) -> str | None:
    """把 '' / 纯空白 的查询参数视为未传。"""
    if value is None:
        return None
    text = value.strip()
    return text or None


def _parse_date_param(value: str | None, field: str) -> date | None:
    """'' -> None；合法日期字符串 -> date；非法 -> 40001（友好提示而非解析堆栈）。"""
    text = _blank_to_none(value)
    if text is None:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise _err(400, 40001, f"{field}：日期格式应为 YYYY-MM-DD")


def _parse_int_param(
    value: str | None, field: str, *, blank_message: str | None = None
) -> int | None:
    """'' -> None（或 blank_message 指定的 40001）；非法整数 -> 40001。"""
    text = _blank_to_none(value)
    if text is None:
        if blank_message:
            raise _err(400, 40001, blank_message)
        return None
    try:
        return int(text)
    except ValueError:
        raise _err(400, 40001, f"{field}：必须为整数")


def _parse_bool_param(value: str | None, default: bool, field: str) -> bool:
    """'' -> 默认值；1/0/true/false/yes/no/on/off 均可；非法 -> 40001。"""
    text = _blank_to_none(value)
    if text is None:
        return default
    lowered = text.lower()
    if lowered in ("1", "true", "yes", "y", "on"):
        return True
    if lowered in ("0", "false", "no", "n", "off"):
        return False
    raise _err(400, 40001, f"{field}：必须为 true/false")


def _parse_page_param(value: str | None, default: int, field: str, *, max_value: int | None = None) -> int:
    """'' -> 默认值；非法或越界 -> 40001（与原 Query(ge/le) 的语义保持一致）。"""
    text = _blank_to_none(value)
    if text is None:
        return default
    try:
        number = int(text)
    except ValueError:
        raise _err(400, 40001, f"{field}：必须为整数")
    if number < 1:
        raise _err(400, 40001, f"{field}：必须大于等于 1")
    if max_value is not None and number > max_value:
        raise _err(400, 40001, f"{field}：不能超过 {max_value}")
    return number


def _parse_supplier_ids(value: str | None) -> list[int] | None:
    """解析 `supplier_ids=1,2`；空串视为「全部」（返回 None），而不是 [0]。"""
    text = _blank_to_none(value)
    if text is None:
        return None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return None
    try:
        return [int(part) for part in parts]
    except ValueError:
        raise _err(400, 40001, "supplier_ids 必须为逗号分隔的整数")


def _ratio(numerator: Decimal, denominator: Decimal, places: int = 1) -> str | None:
    """比率 -> 百分数字符串（`"83.3%"`，一位小数，PRD FR-RPT-03 / 设计稿 02-pages-buyer）。

    `diff_rate` / `response_rate` / `saved_rate` / `coverage_rate` 统一走这里；分母为 0 返回 None。
    """
    if denominator is None or denominator <= 0:
        return None
    percent = (numerator * 100 / denominator).quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )
    return f"{percent}%"


def _check_rfq_visible(db: Session, request: Request, user: User, rfq_id: int) -> Rfq:
    rfq = db.get(Rfq, rfq_id)
    if rfq is None:
        raise _not_found("询价单不存在")
    if user.role != "admin" and rfq.created_by != user.id:
        raise audit_forbidden(
            db,
            request,
            user,
            resource=f"rfq:{rfq_id}",
            detail=f"用户 {user.username} 尝试查看他人询价单 {rfq.rfq_no} 的报表",
        )
    return rfq


# --------------------------------------------------------------------------
# 视图 A：单张询价单比价
# --------------------------------------------------------------------------
def build_comparison(db: Session, rfq: Rfq) -> ComparisonResult:
    """组装单张询价单的交叉比价结果（视图 A）。"""
    lines = db.scalars(
        select(RfqLine).where(RfqLine.rfq_id == rfq.id).order_by(RfqLine.seq, RfqLine.id)
    ).all()
    assignments = db.scalars(
        select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id).order_by(RfqSupplier.id)
    ).all()

    supplier_ids = [a.supplier_id for a in assignments]
    name_map: dict[int, str] = {}
    if supplier_ids:
        name_map = {
            sid: name
            for sid, name in db.execute(
                select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids))
            ).all()
        }

    # 一次查询取全部报价行（含税单价），内存组装，避免逐行查库
    price_map: dict[str, dict[int, Decimal]] = {}
    if supplier_ids:
        quote_rows = db.execute(
            select(QuoteLine.line_uid, RfqSupplier.supplier_id, QuoteLine.price_incl_tax)
            .join(RfqSupplier, RfqSupplier.id == QuoteLine.rfq_supplier_id)
            .where(RfqSupplier.rfq_id == rfq.id, QuoteLine.price_incl_tax.is_not(None))
        ).all()
        for line_uid, supplier_id, price in quote_rows:
            value = money(price)
            if value is None:
                continue
            price_map.setdefault(line_uid, {})[supplier_id] = value

    required_count = len(assignments)
    rows: list[ComparisonRow] = []
    total_best = Decimal("0")
    total_max = Decimal("0")

    for line in lines:
        line_prices = price_map.get(line.line_uid, {})
        quantity = Decimal(str(line.quantity))
        prices_out = {str(sid): fmt(price) or "0.00" for sid, price in line_prices.items()}

        best_supplier_id: int | None = None
        best_price: Decimal | None = None
        # 同价取先分派的供货商，保证结果稳定可复现
        for assignment in assignments:
            price = line_prices.get(assignment.supplier_id)
            if price is None:
                continue
            if best_price is None or price < best_price:
                best_price = price
                best_supplier_id = assignment.supplier_id

        values = list(line_prices.values())
        max_price = max(values) if values else None
        avg_price = money(sum(values) / len(values)) if values else None
        diff_rate = None
        if best_price is not None and max_price is not None:
            diff_rate = _ratio(max_price - best_price, best_price)

        if best_price is not None:
            total_best += best_price * quantity
        if max_price is not None:
            total_max += max_price * quantity

        rows.append(
            ComparisonRow(
                line_uid=line.line_uid,
                seq=line.seq,
                material_name=line.material_name,
                spec=line.spec,
                unit=line.unit,
                quantity=quantity,
                project=line.project or rfq.project,
                prices=prices_out,
                best_price=fmt(best_price),
                best_supplier_id=best_supplier_id,
                best_supplier_name=name_map.get(best_supplier_id) if best_supplier_id else None,
                max_price=fmt(max_price),
                avg_price=fmt(avg_price),
                diff_rate=diff_rate,
                quoted_count=len(line_prices),
                required_count=required_count,
            )
        )

    total_best = money(total_best) or Decimal("0.00")
    total_max = money(total_max) or Decimal("0.00")
    saved = money(total_max - total_best) or Decimal("0.00")

    return ComparisonResult(
        rfq_id=rfq.id,
        rfq_no=rfq.rfq_no,
        title=rfq.title,
        project=rfq.project,
        status=rfq.status,
        suppliers=[
            ComparisonSupplier(
                supplier_id=a.supplier_id,
                supplier_name=name_map.get(a.supplier_id, f"供货商#{a.supplier_id}"),
                status=a.status,
            )
            for a in assignments
        ],
        rows=rows,
        total_best_amount=fmt(total_best),
        total_max_amount=fmt(total_max),
        saved_amount=fmt(saved),
        saved_rate=_ratio(saved, total_max),
    )


@router.get("/rfq-comparison", response_model=Envelope[ComparisonResult], summary="视图 A：单张询价单比价")
def rfq_comparison(
    request: Request,
    rfq_id: str | None = Query(None, description="询价单 ID（必填；空串按未填处理）"),
    only_unquoted: str | None = Query(None, description="仅显示未报价供货商列（true/false）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_report_access),
):
    rfq_id_value = _parse_int_param(rfq_id, "rfq_id", blank_message="请选择询价单")
    assert rfq_id_value is not None
    only_unquoted_value = _parse_bool_param(only_unquoted, False, "only_unquoted")
    rfq = _check_rfq_visible(db, request, user, rfq_id_value)
    result = build_comparison(db, rfq)
    if only_unquoted_value:
        keep = {s.supplier_id for s in result.suppliers if s.status != "quoted"}
        result.suppliers = [s for s in result.suppliers if s.supplier_id in keep]
        for row in result.rows:
            row.prices = {k: v for k, v in row.prices.items() if int(k) in keep}
    return Envelope(data=result)


@router.get("/rfq-comparison/export", summary="导出视图 A 比价明细 .xlsx")
def rfq_comparison_export(
    request: Request,
    rfq_id: str | None = Query(None, description="询价单 ID（空串按未填处理）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_report_access),
):
    rfq_id_value = _parse_int_param(rfq_id, "rfq_id", blank_message="请选择询价单")
    assert rfq_id_value is not None
    rfq = _check_rfq_visible(db, request, user, rfq_id_value)
    result = build_comparison(db, rfq)
    content = exporter.build_comparison_export(result)
    filename = exporter.comparison_export_filename(rfq.rfq_no, rfq.project)
    write_audit(
        db,
        request=request,
        user=user,
        action="report.export",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"导出比价明细：{rfq.rfq_no}（{len(result.rows)} 行）",
    )
    db.commit()
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPE,
        headers={"Content-Disposition": exporter.content_disposition(filename, "rfq_comparison.xlsx")},
    )


# --------------------------------------------------------------------------
# 视图 B：汇总统计
# --------------------------------------------------------------------------
def _resolve_range(
    date_from: date | None, date_to: date | None
) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(date_from, time.min) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min) if date_to else None
    return start, end


def build_summary(
    db: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    project: str | None = None,
    supplier_ids: list[int] | None = None,
    rfq_id: int | None = None,
    status: str | None = None,
    only_unquoted: bool = False,
    owner_id: int | None = None,
) -> SummaryResult:
    """组装视图 B 汇总统计（按报价截止时间筛选，PRD 5.3.1）。

    owner_id 不为空时只统计该创建人的单据 —— 供非管理员（采购员）做数据隔离：
    采购员只能看到自己发出的询价，管理员传 None 表示不限（PRD 3.3-4）。
    """
    start, end = _resolve_range(date_from, date_to)

    rfq_stmt = select(Rfq.id, Rfq.project, Rfq.deadline)
    if owner_id is not None:
        rfq_stmt = rfq_stmt.where(Rfq.created_by == owner_id)
    if rfq_id:
        rfq_stmt = rfq_stmt.where(Rfq.id == rfq_id)
    if start is not None:
        rfq_stmt = rfq_stmt.where(Rfq.deadline.is_not(None), Rfq.deadline >= start)
    if end is not None:
        rfq_stmt = rfq_stmt.where(Rfq.deadline.is_not(None), Rfq.deadline < end)
    if project:
        rfq_stmt = rfq_stmt.where(Rfq.project.like(f"%{project}%"))
    if status:
        rfq_stmt = rfq_stmt.where(Rfq.status == status)
    if supplier_ids:
        rfq_stmt = rfq_stmt.where(
            Rfq.id.in_(
                select(RfqSupplier.rfq_id).where(RfqSupplier.supplier_id.in_(supplier_ids))
            )
        )

    rfq_rows = db.execute(rfq_stmt).all()
    rfq_ids = [row[0] for row in rfq_rows]

    result = SummaryResult(
        date_from=date_from.isoformat() if date_from else None,
        date_to=date_to.isoformat() if date_to else None,
    )
    if not rfq_ids:
        return result

    line_rows = db.execute(
        select(RfqLine.line_uid, RfqLine.rfq_id, RfqLine.quantity, RfqLine.project).where(
            RfqLine.rfq_id.in_(rfq_ids)
        )
    ).all()
    assignment_rows = db.execute(
        select(RfqSupplier.supplier_id, RfqSupplier.rfq_id, RfqSupplier.status).where(
            RfqSupplier.rfq_id.in_(rfq_ids)
        )
    ).all()

    quote_stmt = (
        select(
            RfqSupplier.supplier_id,
            QuoteLine.line_uid,
            QuoteLine.price_incl_tax,
            QuoteLine.moq,
            QuoteLine.lead_time_days,
        )
        .join(RfqSupplier, RfqSupplier.id == QuoteLine.rfq_supplier_id)
        .where(
            RfqSupplier.rfq_id.in_(rfq_ids),
            QuoteLine.price_incl_tax.is_not(None),
        )
    )
    if supplier_ids:
        quote_stmt = quote_stmt.where(RfqSupplier.supplier_id.in_(supplier_ids))
    quote_rows = db.execute(quote_stmt).all()

    qty_by_uid: dict[str, Decimal] = {row[0]: Decimal(str(row[2])) for row in line_rows}

    # 每行最低价（跨供货商），用于最优总金额
    best_by_uid: dict[str, Decimal] = {}
    supplier_amount: dict[int, Decimal] = {}
    supplier_lead: dict[int, list[int]] = {}
    supplier_moq: dict[int, list[Decimal]] = {}
    for supplier_id, line_uid, price, moq, lead_time in quote_rows:
        value = money(price)
        if value is None:
            continue
        if line_uid not in best_by_uid or value < best_by_uid[line_uid]:
            best_by_uid[line_uid] = value
        quantity = qty_by_uid.get(line_uid, Decimal("0"))
        supplier_amount[supplier_id] = supplier_amount.get(supplier_id, Decimal("0")) + value * quantity
        if lead_time is not None:
            supplier_lead.setdefault(supplier_id, []).append(int(lead_time))
        if moq is not None:
            supplier_moq.setdefault(supplier_id, []).append(Decimal(str(moq)))

    result.rfq_count = len(rfq_ids)
    result.line_count = len(line_rows)
    result.invited_assignments = len(assignment_rows)
    result.quoted_assignments = sum(1 for row in assignment_rows if row[2] == "quoted")
    result.response_rate = _ratio(
        Decimal(result.quoted_assignments), Decimal(result.invited_assignments)
    )
    result.best_amount = fmt(
        money(sum((price * qty_by_uid.get(uid, Decimal("0")) for uid, price in best_by_uid.items()), Decimal("0")))
    )

    # 按供货商汇总
    invited: dict[int, int] = {}
    quoted: dict[int, int] = {}
    for supplier_id, _rfq_id, assign_status in assignment_rows:
        invited[supplier_id] = invited.get(supplier_id, 0) + 1
        if assign_status == "quoted":
            quoted[supplier_id] = quoted.get(supplier_id, 0) + 1
    if supplier_ids:
        for sid in supplier_ids:
            invited.setdefault(sid, 0)

    names: dict[int, str] = {}
    if invited:
        names = {
            sid: name
            for sid, name in db.execute(
                select(Supplier.id, Supplier.name).where(Supplier.id.in_(list(invited)))
            ).all()
        }

    for supplier_id in sorted(invited, key=lambda s: (-invited[s], s)):
        invited_count = invited[supplier_id]
        quoted_count = quoted.get(supplier_id, 0)
        if only_unquoted and quoted_count:
            continue
        lead_list = supplier_lead.get(supplier_id, [])
        moq_list = supplier_moq.get(supplier_id, [])
        result.by_supplier.append(
            SupplierSummaryRow(
                supplier_id=supplier_id,
                supplier_name=names.get(supplier_id, f"供货商#{supplier_id}"),
                invited_count=invited_count,
                quoted_count=quoted_count,
                response_rate=_ratio(Decimal(quoted_count), Decimal(invited_count)),
                amount=fmt(money(supplier_amount.get(supplier_id, Decimal("0")))),
                avg_lead_time=(
                    format((Decimal(sum(lead_list)) / Decimal(len(lead_list))).quantize(Decimal("0.1")), "f")
                    if lead_list
                    else None
                ),
                avg_moq=(
                    fmt(sum(moq_list) / Decimal(len(moq_list)), 3) if moq_list else None
                ),
            )
        )

    # 按项目汇总（以询价单表头项目为口径，保证「询价单数 / 明细行数」一致）
    project_lines: dict[str, list[str]] = {}
    rfq_project_map = {row[0]: (row[1] or "未分类") for row in rfq_rows}
    for line_uid, line_rfq_id, _qty, _line_project in line_rows:
        key = rfq_project_map.get(line_rfq_id, "未分类")
        project_lines.setdefault(key, []).append(line_uid)

    project_rfq_count: dict[str, int] = {}
    for proj in rfq_project_map.values():
        project_rfq_count[proj] = project_rfq_count.get(proj, 0) + 1

    project_assign: dict[str, list[int]] = {}
    for _sid, rid, assign_status in assignment_rows:
        key = rfq_project_map.get(rid, "未分类")
        stats = project_assign.setdefault(key, [0, 0])
        stats[0] += 1
        if assign_status == "quoted":
            stats[1] += 1

    for proj in sorted(project_lines):
        uids = project_lines[proj]
        stats = project_assign.get(proj, [0, 0])
        best_amount = sum(
            (best_by_uid[uid] * qty_by_uid.get(uid, Decimal("0")) for uid in uids if uid in best_by_uid),
            Decimal("0"),
        )
        result.by_project.append(
            ProjectSummaryRow(
                project=proj,
                rfq_count=project_rfq_count.get(proj, 0),
                line_count=len(uids),
                coverage_rate=_ratio(Decimal(stats[1]), Decimal(stats[0])),
                best_amount=fmt(money(best_amount)),
            )
        )

    return result


@router.get("/summary", response_model=Envelope[SummaryResult], summary="视图 B：报价单汇总统计")
def summary(
    date_from: str | None = Query(None, description="按报价截止时间起（含）；空串视为未传"),
    date_to: str | None = Query(None, description="按报价截止时间止（含）；空串视为未传"),
    project: str | None = Query(None, description="项目模糊匹配"),
    supplier_ids: str | None = Query(None, description="供货商 ID，逗号分隔；空串视为全部"),
    rfq_id: str | None = Query(None, description="询价单 ID；空串视为全部"),
    status: str | None = Query(None, description="draft/published/closed"),
    only_unquoted: str | None = Query(None, description="仅统计未报价供货商（true/false）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_report_access),
):
    result = build_summary(
        db,
        date_from=_parse_date_param(date_from, "date_from"),
        date_to=_parse_date_param(date_to, "date_to"),
        project=_blank_to_none(project),
        supplier_ids=_parse_supplier_ids(supplier_ids),
        rfq_id=_parse_int_param(rfq_id, "rfq_id"),
        status=_blank_to_none(status),
        only_unquoted=_parse_bool_param(only_unquoted, False, "only_unquoted"),
        # 数据隔离：非管理员只能统计自己创建的询价单
        owner_id=_owner_scope(user),
    )
    return Envelope(data=result)


@router.get("/summary/export", summary="导出视图 B 汇总统计 .xlsx")
def summary_export(
    request: Request,
    date_from: str | None = Query(None, description="空串视为未传"),
    date_to: str | None = Query(None, description="空串视为未传"),
    project: str | None = Query(None),
    supplier_ids: str | None = Query(None),
    rfq_id: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_report_access),
):
    result = build_summary(
        db,
        date_from=_parse_date_param(date_from, "date_from"),
        date_to=_parse_date_param(date_to, "date_to"),
        project=_blank_to_none(project),
        supplier_ids=_parse_supplier_ids(supplier_ids),
        rfq_id=_parse_int_param(rfq_id, "rfq_id"),
        status=_blank_to_none(status),
        # 导出与页面口径必须一致，否则会出现"页面看不到、导出的 Excel 里却有"
        owner_id=_owner_scope(user),
    )
    content = exporter.build_summary_export(result)
    filename = exporter.summary_export_filename()
    write_audit(
        db,
        request=request,
        user=user,
        action="report.export",
        target_type="report",
        target_id="summary",
        summary=(
            f"导出汇总统计：询价单 {result.rfq_count} 张 / 明细 {result.line_count} 行"
            f" / 受邀 {result.invited_assignments} 家次"
        ),
    )
    db.commit()
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPE,
        headers={"Content-Disposition": exporter.content_disposition(filename, "summary.xlsx")},
    )
