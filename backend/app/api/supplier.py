"""供货商报价：待报价列表、填报页数据、保存/提交（改价历史 + 状态重算）、历史、附件。

对应 PRD 5.2、7.3 与验收用例 TC-21 ~ TC-35。

安全红线（PRD 3.3-1 / 7.3）：
- 一律使用 `current_user.supplier_id`（来自 JWT + 数据库），**任何接口都不接受前端传入 supplier_id**；
- 未分派给本公司的单据、他方报价一律 40300 并写 `security.forbidden` 告警（TC-31 / TC-34）；
- 草稿单据对供货商完全不可见（404）。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import audit_forbidden, get_current_user, require_supplier, write_audit
from ..models import QuoteHistory, QuoteLine, Rfq, RfqLine, RfqSupplier, TaxDict, User, app_now
from ..schemas import (
    Envelope,
    PageData,
    PageMeta,
    QuoteHistoryItem,
    QuoteLineOut,
    QuoteSaveRequest,
    SupplierRfqDetail,
    SupplierRfqLineOut,
    SupplierRfqListItem,
)
from ..utils import (
    calc_price_excl_tax,
    fmt,
    is_deadline_passed,
    money,
    page_offset,
    qty,
    refresh_assignment_status,
    remaining_seconds,
    to_app_tz,
)

router = APIRouter()

# 参与改价历史比对的字段（PRD 6.2 quote_history.changed_fields）
HISTORY_FIELDS = (
    "price_incl_tax",
    "tax_included",
    "tax_rate",
    "price_excl_tax",
    "moq",
    "lead_time_days",
    "arrival_date",
    "remark",
    "attachments",
)


def _err(status_code: int, code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# --------------------------------------------------------------------------
# 查询参数容错（前端清空筛选条件时会把 "" 透传上来，必须按「未传」处理）
# --------------------------------------------------------------------------
def _blank_to_none(value: str | None) -> str | None:
    """把 '' / 纯空白 的查询参数视为未传。"""
    if value is None:
        return None
    text = value.strip()
    return text or None


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


def _norm_dt(value: datetime | None) -> datetime | None:
    """统一为应用基准（北京时间）的 naive datetime（见 models.app_now）。"""
    return to_app_tz(value)


def _ordered_lines(db: Session, rfq_id: int) -> list[RfqLine]:
    return list(
        db.scalars(select(RfqLine).where(RfqLine.rfq_id == rfq_id).order_by(RfqLine.seq, RfqLine.id)).all()
    )


def _quote_snapshot(line: QuoteLine) -> dict[str, Any]:
    """报价行快照（JSON 安全：Decimal/日期转字符串）。"""
    return {
        "price_incl_tax": fmt(line.price_incl_tax),
        "tax_included": bool(line.tax_included),
        "tax_rate": fmt(line.tax_rate, 4),
        "price_excl_tax": fmt(line.price_excl_tax),
        "moq": fmt(line.moq, 3),
        "lead_time_days": line.lead_time_days,
        "arrival_date": line.arrival_date.isoformat() if line.arrival_date else None,
        "remark": line.remark,
        "attachments": line.attachments,
    }


def _default_tax_rate(db: Session) -> Decimal | None:
    rate = db.scalar(
        select(TaxDict.rate).where(TaxDict.is_default.is_(True), TaxDict.status == 1).order_by(TaxDict.sort)
    )
    return Decimal(str(rate)) if rate is not None else None


def _load_assignment(
    db: Session, request: Request, user: User, rfq_id: int
) -> tuple[Rfq, RfqSupplier]:
    """按 current_user.supplier_id 取分派；草稿 404，未分派 403 + 留痕。"""
    rfq = db.get(Rfq, rfq_id)
    if rfq is None or rfq.status == "draft":
        # 草稿对供货商完全不可见（PRD 3.3-3）
        raise _err(404, 40400, "询价单不存在")
    assignment = db.scalar(
        select(RfqSupplier).where(
            RfqSupplier.rfq_id == rfq_id,
            RfqSupplier.supplier_id == user.supplier_id,
        )
    )
    if assignment is None or assignment.line_count <= 0:
        raise audit_forbidden(
            db,
            request,
            user,
            resource=f"rfq:{rfq_id}",
            detail=f"供货商 {user.supplier_id} 尝试访问未分派给本公司的询价单 {rfq.rfq_no}",
        )
    return rfq, assignment


def _detail(db: Session, rfq: Rfq, assignment: RfqSupplier) -> SupplierRfqDetail:
    """组装备供货商填报页数据（只含本公司报价，无任何他方信息）。"""
    quotes = {
        q.line_uid: q
        for q in db.scalars(
            select(QuoteLine).where(QuoteLine.rfq_supplier_id == assignment.id)
        ).all()
    }
    items = []
    for line in _ordered_lines(db, rfq.id):
        quote = quotes.get(line.line_uid)
        items.append(
            SupplierRfqLineOut(
                line_uid=line.line_uid,
                seq=line.seq,
                material_name=line.material_name,
                spec=line.spec,
                unit=line.unit,
                quantity=Decimal(str(line.quantity)),
                quote=QuoteLineOut.model_validate(quote) if quote is not None else None,
            )
        )
    readonly = rfq.status == "closed" or is_deadline_passed(rfq.deadline)
    return SupplierRfqDetail(
        rfq_id=rfq.id,
        rfq_no=rfq.rfq_no,
        title=rfq.title,
        project=rfq.project,
        remark=rfq.remark,
        deadline=rfq.deadline,
        remaining_seconds=remaining_seconds(rfq.deadline),
        status=rfq.status,
        my_status=assignment.status,
        readonly=readonly,
        line_count=assignment.line_count,
        quoted_line_count=assignment.quoted_line_count,
        submitted_at=assignment.submitted_at,
        updated_at=assignment.last_saved_at,
        lines=items,
    )


# --------------------------------------------------------------------------
# 待报价列表
# --------------------------------------------------------------------------
@router.get("/rfqs", response_model=Envelope[PageData[SupplierRfqListItem]], summary="待报价列表（仅本公司）")
def list_my_rfqs(
    page: str | None = Query(None, description="页码，默认 1；空串视为未传"),
    page_size: str | None = Query(None, description="每页条数，默认 20，上限 200"),
    my_status: str | None = Query(None, description="pending/partial/quoted；空串视为全部"),
    keyword: str | None = Query(None, description="单号/名称/项目模糊匹配；空串视为不过滤"),
    only_open: str | None = Query(None, description="仅未截止的单据（true/false）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_supplier),
):
    page_no = _parse_page_param(page, 1, "page")
    page_limit = _parse_page_param(page_size, 20, "page_size", max_value=200)
    my_status_value = _blank_to_none(my_status)
    keyword_value = _blank_to_none(keyword)
    only_open_value = _parse_bool_param(only_open, False, "only_open")

    stmt = (
        select(RfqSupplier, Rfq)
        .join(Rfq, Rfq.id == RfqSupplier.rfq_id)
        .where(
            RfqSupplier.supplier_id == user.supplier_id,  # 只信任服务端身份
            RfqSupplier.line_count > 0,
            Rfq.status.in_(("published", "closed")),
        )
    )
    if my_status_value in ("pending", "partial", "quoted"):
        stmt = stmt.where(RfqSupplier.status == my_status_value)
    if keyword_value:
        like = f"%{keyword_value}%"
        stmt = stmt.where(Rfq.rfq_no.like(like) | Rfq.title.like(like) | Rfq.project.like(like))
    if only_open_value:
        stmt = stmt.where(Rfq.status == "published")

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    offset, limit = page_offset(page_no, page_limit)
    rows = db.execute(
        stmt.order_by(Rfq.deadline.asc(), Rfq.id.desc()).offset(offset).limit(limit)
    ).all()

    items = [
        SupplierRfqListItem(
            rfq_id=rfq.id,
            rfq_no=rfq.rfq_no,
            title=rfq.title,
            project=rfq.project,
            deadline=rfq.deadline,
            remaining_seconds=remaining_seconds(rfq.deadline),
            status=rfq.status,
            my_status=assignment.status,
            line_count=assignment.line_count,
            quoted_line_count=assignment.quoted_line_count,
            last_saved_at=assignment.last_saved_at,
            submitted_at=assignment.submitted_at,
        )
        for assignment, rfq in rows
    ]
    return Envelope(data=PageData(items=items, meta=PageMeta(page=page_no, page_size=limit, total=total)))


@router.get("/rfqs/{rfq_id}", response_model=Envelope[SupplierRfqDetail], summary="填报页数据")
def get_my_rfq(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_supplier),
):
    rfq, assignment = _load_assignment(db, request, user, rfq_id)
    if rfq.status == "published" and is_deadline_passed(rfq.deadline):
        # 惰性自动截止，保证供货商看到的状态与锁定一致（PRD 4.3）
        from ..utils import auto_close_if_due

        if auto_close_if_due(db, rfq):
            db.commit()
    return Envelope(data=_detail(db, rfq, assignment))


# --------------------------------------------------------------------------
# 保存 / 提交报价
# --------------------------------------------------------------------------
@router.put("/rfqs/{rfq_id}/quotes", response_model=Envelope[SupplierRfqDetail], summary="保存/提交报价")
def save_quotes(
    rfq_id: int,
    payload: QuoteSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_supplier),
):
    rfq, assignment = _load_assignment(db, request, user, rfq_id)

    # 截止后锁定（PRD FR-SUP-11 / TC-30）
    if rfq.status == "closed" or is_deadline_passed(rfq.deadline):
        raise _err(403, 40301, "报价已截止，无法修改")

    # 乐观锁：比对打开填报页时的 assignment.last_saved_at（PRD 8. 并发 / TC-33）
    if payload.expected_updated_at is not None and assignment.last_saved_at is not None:
        expected = _norm_dt(payload.expected_updated_at)
        stored = assignment.last_saved_at
        if expected is None or expected.replace(microsecond=0) != stored.replace(microsecond=0):
            raise _err(409, 40900, "该报价单已被其他会话修改，请刷新后重试")

    lines = _ordered_lines(db, rfq.id)
    by_uid = {line.line_uid: line for line in lines}
    unknown = [item.line_uid for item in payload.lines if item.line_uid not in by_uid]
    if unknown:
        raise _err(400, 40001, f"明细行不存在或不属于本询价单：{unknown}")

    # 物化全部报价行：total 与 line_count 对齐，状态才能按"填写完整度"正确计算
    existing = {
        q.line_uid: q
        for q in db.scalars(select(QuoteLine).where(QuoteLine.rfq_supplier_id == assignment.id)).all()
    }
    default_rate = _default_tax_rate(db)
    for line in lines:
        if line.line_uid in existing:
            continue
        created = QuoteLine(
            rfq_supplier_id=assignment.id,
            line_uid=line.line_uid,
            price_incl_tax=None,
            tax_included=True,
            tax_rate=default_rate,
            updated_by=user.id,
        )
        db.add(created)
        existing[line.line_uid] = created
    db.flush()

    # 校验：不含税单价必须给出税率（PRD 5.2.2 / TC-28）
    errors: list[str] = []
    for item in payload.lines:
        if item.price_incl_tax is not None and not item.tax_included and item.tax_rate is None:
            errors.append(f"第{by_uid[item.line_uid].seq}行 税率：含税开关为「否」时必须填写税率")
    if errors:
        raise _err(400, 40001, "；".join(errors))

    # 提交前校验：所有明细行都必须含税单价（TC-26）
    if payload.submit:
        payload_map = {item.line_uid: item for item in payload.lines}
        missing: list[int] = []
        for line in lines:
            item = payload_map.get(line.line_uid)
            current = existing[line.line_uid]
            price = item.price_incl_tax if item is not None else current.price_incl_tax
            if price is None:
                missing.append(line.seq)
        if missing:
            detail = "；".join(f"第{seq}行 含税单价未填写" for seq in missing)
            raise _err(400, 40001, f"提交失败：{detail}")

    action = "submit" if payload.submit else "save"
    history_written = 0
    for item in payload.lines:
        line = by_uid[item.line_uid]
        quote = existing[line.line_uid]
        before = _quote_snapshot(quote)

        quote.price_incl_tax = money(item.price_incl_tax)
        quote.tax_included = bool(item.tax_included)
        if item.tax_included:
            quote.tax_rate = (
                item.tax_rate
                if item.tax_rate is not None
                else (quote.tax_rate if quote.tax_rate is not None else default_rate)
            )
        else:
            quote.tax_rate = item.tax_rate
        if quote.tax_rate is not None:
            quote.tax_rate = Decimal(str(quote.tax_rate)).quantize(Decimal("0.0001"))
        quote.price_excl_tax = calc_price_excl_tax(
            quote.price_incl_tax, quote.tax_included, quote.tax_rate
        )
        quote.moq = qty(item.moq) if item.moq is not None else None
        quote.lead_time_days = item.lead_time_days
        quote.arrival_date = item.arrival_date
        quote.remark = item.remark
        quote.attachments = item.attachments
        quote.updated_by = user.id
        db.flush()

        after = _quote_snapshot(quote)
        changed = [name for name in HISTORY_FIELDS if before.get(name) != after.get(name)]
        if not changed:
            continue
        # 版本号按 (rfq_supplier, line_uid) 自增，只追加（PRD 6.2 / TC-23 / TC-24）
        version = (
            db.scalar(
                select(func.max(QuoteHistory.version)).where(
                    QuoteHistory.rfq_supplier_id == assignment.id,
                    QuoteHistory.line_uid == line.line_uid,
                )
            )
            or 0
        ) + 1
        db.add(
            QuoteHistory(
                rfq_supplier_id=assignment.id,
                line_uid=line.line_uid,
                version=version,
                snapshot=before,
                changed_fields=changed,
                action=action,
                operated_by=user.id,
            )
        )
        history_written += 1

    now = app_now()
    if assignment.first_saved_at is None:
        assignment.first_saved_at = now
    assignment.last_saved_at = now
    if payload.submit:
        assignment.submitted_at = assignment.submitted_at or now
    db.flush()
    refresh_assignment_status(db, assignment, submitted=payload.submit)

    rfq.updated_at = now
    write_audit(
        db,
        request=request,
        user=user,
        action="quote.submit" if payload.submit else "quote.save",
        target_type="rfq",
        target_id=rfq.id,
        summary=(
            f"{'提交' if payload.submit else '保存'}报价 {rfq.rfq_no}："
            f"{len(payload.lines)} 行入参，{history_written} 条改价历史，"
            f"状态 {assignment.status}（{assignment.quoted_line_count}/{assignment.line_count}）"
        ),
    )
    db.commit()
    db.refresh(assignment)
    return Envelope(data=_detail(db, rfq, assignment))


@router.post(
    "/rfqs/{rfq_id}/submit",
    response_model=Envelope[SupplierRfqDetail],
    summary="提交报价（PRD 7.3 别名，等价于 PUT /quotes?submit=true）",
)
def submit_quotes(
    rfq_id: int,
    payload: QuoteSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_supplier),
):
    """PRD 7.3 单列的「提交报价」入口；内部复用保存逻辑并强制 submit=True。"""
    payload.submit = True
    return save_quotes(rfq_id=rfq_id, payload=payload, request=request, db=db, user=user)


# --------------------------------------------------------------------------
# 历史报价与改价记录
# --------------------------------------------------------------------------

@router.get("/quotes/history", response_model=Envelope[PageData[QuoteHistoryItem]], summary="本公司历史报价与改价记录")
def my_quote_history(
    page: str | None = Query(None, description="页码，默认 1；空串视为未传"),
    page_size: str | None = Query(None, description="每页条数，默认 50，上限 200"),
    rfq_id: str | None = Query(None, description="询价单 ID；空串视为全部"),
    line_uid: str | None = Query(None, description="明细行 UUID；空串视为全部"),
    db: Session = Depends(get_db),
    user: User = Depends(require_supplier),
):
    page_no = _parse_page_param(page, 1, "page")
    page_limit = _parse_page_param(page_size, 50, "page_size", max_value=200)
    rfq_id_value = _parse_int_param(rfq_id, "rfq_id")
    line_uid_value = _blank_to_none(line_uid)

    stmt = (
        select(QuoteHistory, User)
        .outerjoin(User, User.id == QuoteHistory.operated_by)
        .join(RfqSupplier, RfqSupplier.id == QuoteHistory.rfq_supplier_id)
        .where(RfqSupplier.supplier_id == user.supplier_id)
    )
    if rfq_id_value is not None:
        stmt = stmt.where(RfqSupplier.rfq_id == rfq_id_value)
    if line_uid_value:
        stmt = stmt.where(QuoteHistory.line_uid == line_uid_value)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    offset, limit = page_offset(page_no, page_limit)
    rows = db.execute(
        stmt.order_by(QuoteHistory.created_at.desc(), QuoteHistory.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    items = [
        QuoteHistoryItem(
            line_uid=history.line_uid,
            version=history.version,
            action=history.action,
            changed_fields=history.changed_fields,
            snapshot=history.snapshot,
            operated_by_name=(operator.real_name or operator.username) if operator else "system",
            created_at=history.created_at,
        )
        for history, operator in rows
    ]
    return Envelope(data=PageData(items=items, meta=PageMeta(page=page_no, page_size=limit, total=total)))


# --------------------------------------------------------------------------
# 附件（PRD 5.2.2 行附件 / TC-35）
# --------------------------------------------------------------------------
_FILENAME_SAFE = re.compile(r"[^0-9A-Za-z._\u4e00-\u9fff-]+")


@router.post("/attachments", response_model=Envelope[dict], summary="上传行附件")
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_supplier),
):
    original = Path(file.filename or "").name
    ext = Path(original).suffix.lower()
    if ext not in settings.allowed_upload_ext:
        raise _err(400, 40001, f"不支持的文件类型（允许：{'、'.join(settings.allowed_upload_ext)}）")
    content = await file.read()
    if not content:
        raise _err(400, 40001, "上传文件为空")
    limit = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > limit:
        raise _err(400, 40001, f"文件超过 {settings.max_upload_size_mb}MB 上限")

    safe_name = _FILENAME_SAFE.sub("_", original)[:80] or f"attachment{ext}"
    stored_name = f"{uuid.uuid4().hex[:12]}_s{user.supplier_id}_{safe_name}"
    upload_dir = Path(settings.resolved_upload_dir())
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / stored_name
    target.write_bytes(content)

    write_audit(
        db,
        request=request,
        user=user,
        action="attachment.upload",
        target_type="attachment",
        target_id=stored_name,
        summary=f"上传附件 {original}（{len(content)} 字节）",
    )
    db.commit()
    return Envelope(
        data={
            "filename": stored_name,
            "original_name": original,
            "size": len(content),
            "url": f"/api/supplier/attachments/{stored_name}",
        }
    )


@router.get("/attachments/{filename}", summary="下载附件")
def download_attachment(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """我方人员可下载全部附件；供货商只能下载自己上传的附件（PRD 3.3-5）。"""
    name = Path(filename).name
    if name != filename or name in ("", ".", ".."):
        raise _err(400, 40001, "文件名非法")

    upload_dir = Path(settings.resolved_upload_dir()).resolve()
    target = (upload_dir / name).resolve()
    if upload_dir not in target.parents:
        raise _err(403, 40300, "无权访问该文件")
    if not target.is_file():
        raise _err(404, 40400, "附件不存在")

    if user.role == "supplier":
        match = re.search(r"_s(\d+)_", name)
        if match and int(match.group(1)) != (user.supplier_id or -1):
            raise audit_forbidden(
                db,
                request,
                user,
                resource=f"attachment:{name}",
                detail=f"供货商 {user.supplier_id} 尝试下载他方附件 {name}",
            )
    return FileResponse(path=str(target), filename=name)
