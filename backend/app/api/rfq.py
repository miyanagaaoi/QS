"""询价单（我方）：列表 / CRUD / 发布 / 撤回 / 截止 / 进度 / 报价查看 / Excel 导入导出。

对应 PRD 5.1、7.2 与验收用例 TC-08 ~ TC-20、TC-31。

安全与可见性（PRD 3.3）：
- 全部接口仅我方人员可用；供货商调用一律 40300 并写 `security.forbidden` 告警（TC-31）；
- 采购员只能操作 `created_by = 自己` 的单据，管理员不限（3.3-4）；
- 已发布/已截止的单据禁止增删改明细（40900），需先「撤回为草稿」（FR-RFQ-12 / TC-17 / TC-19）。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import exporter, importer
from ..config import settings
from ..database import get_db
from ..deps import INTERNAL_ROLES, audit_forbidden, get_current_user, write_audit
from ..models import (
    QuoteHistory,
    QuoteLine,
    Rfq,
    RfqLine,
    RfqSupplier,
    Supplier,
    UnitDict,
    User,
    app_now,
)
from ..schemas import (
    AssigneeOut,
    RfqAppendSuppliers,
    ComparisonResult,
    Envelope,
    ImportConfirmRequest,
    ImportPreviewResult,
    PageData,
    PageMeta,
    RfqCreate,
    RfqDetail,
    RfqLineOut,
    RfqListItem,
    RfqUpdate,
)
from ..utils import (
    auto_close_if_due,
    fmt,
    generate_rfq_no,
    is_deadline_passed,
    page_offset,
    qty,
    to_app_tz,
)
from .report import build_comparison

router = APIRouter()


# --------------------------------------------------------------------------
# 公共辅助
# --------------------------------------------------------------------------
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


def require_internal_audited(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    """我方守卫：供货商访问我方接口时 40300 + 越权告警（TC-31）。"""
    if user.role not in INTERNAL_ROLES:
        raise audit_forbidden(
            db,
            request,
            user,
            resource=request.url.path,
            detail=f"账号 {user.username}（{user.role}）尝试访问我方接口 {request.url.path}",
        )
    return user


def _norm_dt(value: datetime | None) -> datetime | None:
    """统一为应用基准（北京时间）的 naive datetime（存储约定，见 models.app_now）。

    前端 <input type="datetime-local"> 可能带浏览器时区偏移，须先转换再落库，
    否则会出现"存 UTC / 比北京时间"的 8 小时错位。
    """
    return to_app_tz(value)


def _load_rfq(db: Session, request: Request, user: User, rfq_id: int) -> Rfq:
    """取单据并校验可见性，顺带做惰性自动截止（PRD 4.3）。"""
    rfq = db.get(Rfq, rfq_id)
    if rfq is None:
        raise _err(404, 40400, "询价单不存在")
    if user.role != "admin" and rfq.created_by != user.id:
        raise audit_forbidden(
            db,
            request,
            user,
            resource=f"rfq:{rfq_id}",
            detail=f"用户 {user.username} 尝试操作他人询价单（id={rfq_id}）",
        )
    if auto_close_if_due(db, rfq):
        db.commit()
    return rfq


def _load_draft(db: Session, request: Request, user: User, rfq_id: int) -> Rfq:
    rfq = _load_rfq(db, request, user, rfq_id)
    if rfq.status != "draft":
        raise _err(409, 40900, "已发布或已截止的询价单不可修改明细，请先撤回为草稿")
    return rfq


def _ordered_lines(db: Session, rfq_id: int) -> list[RfqLine]:
    return list(
        db.scalars(select(RfqLine).where(RfqLine.rfq_id == rfq_id).order_by(RfqLine.seq, RfqLine.id)).all()
    )


def _enabled_units(db: Session) -> set[str]:
    return {name for (name,) in db.execute(select(UnitDict.name).where(UnitDict.status == 1)).all()}


def _user_name(db: Session, user_id: int | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None:
        return None
    return user.real_name or user.username


def _assignee_out(assignment: RfqSupplier, supplier: Supplier) -> AssigneeOut:
    return AssigneeOut(
        supplier_id=assignment.supplier_id,
        supplier_name=supplier.name,
        contact_name=supplier.contact_name,
        contact_phone=supplier.contact_phone,
        status=assignment.status,
        line_count=assignment.line_count,
        quoted_line_count=assignment.quoted_line_count,
        last_saved_at=assignment.last_saved_at,
        submitted_at=assignment.submitted_at,
    )


def _assignment_rows(db: Session, rfq_id: int) -> list[tuple[RfqSupplier, Supplier]]:
    """只返回「已受邀」的分派（line_count > 0）。

    撤回为草稿后若取消勾选某家曾报价的供货商，为保证 quote_history 外键完整性
    会保留其分派记录，但 line_count 置 0，从而不再出现在受邀清单与报表中。
    """
    rows = db.execute(
        select(RfqSupplier, Supplier)
        .join(Supplier, Supplier.id == RfqSupplier.supplier_id)
        .where(RfqSupplier.rfq_id == rfq_id)
        .order_by(RfqSupplier.id)
    ).all()
    return [(a, s) for a, s in rows if a.line_count > 0]


def _rfq_detail(db: Session, rfq: Rfq) -> RfqDetail:
    lines = _ordered_lines(db, rfq.id)
    assignees = [_assignee_out(a, s) for a, s in _assignment_rows(db, rfq.id)]
    return RfqDetail(
        id=rfq.id,
        rfq_no=rfq.rfq_no,
        title=rfq.title,
        project=rfq.project,
        status=rfq.status,
        deadline=rfq.deadline,
        remark=rfq.remark,
        internal_remark=rfq.internal_remark,
        published_at=rfq.published_at,
        closed_at=rfq.closed_at,
        created_by=rfq.created_by,
        created_by_name=_user_name(db, rfq.created_by),
        created_at=rfq.created_at,
        lines=[RfqLineOut.model_validate(line) for line in lines],
        assignees=assignees,
    )


def _resolve_suppliers(db: Session, supplier_ids: list[int]) -> list[Supplier]:
    """去重并按传入顺序返回供货商档案；不存在则 40001。"""
    ordered: list[int] = []
    for sid in supplier_ids:
        if sid not in ordered:
            ordered.append(sid)
    if not ordered:
        return []
    found = {s.id: s for s in db.scalars(select(Supplier).where(Supplier.id.in_(ordered))).all()}
    missing = [sid for sid in ordered if sid not in found]
    if missing:
        raise _err(400, 40001, f"供货商不存在：{missing}")
    return [found[sid] for sid in ordered]


def _replace_lines(db: Session, rfq_id: int, lines: list[Any]) -> None:
    """草稿明细全量替换（发布后禁止调用）。

    草稿允许明细不完整（PRD FR-RFQ-09 / TC-09）：材料名称、单位、采购数量可为空，
    这里把空值统一落成空串/0，完整性由发布校验负责拦截（_collect_publish_errors）。
    """
    for existing in db.scalars(select(RfqLine).where(RfqLine.rfq_id == rfq_id)).all():
        db.delete(existing)
    db.flush()
    for index, line in enumerate(lines, start=1):
        db.add(
            RfqLine(
                rfq_id=rfq_id,
                seq=index,
                material_name=(line.material_name or "").strip(),
                spec=(line.spec or None),
                unit=(line.unit or "").strip(),
                project=(line.project or None),
                quantity=qty(line.quantity) or Decimal("0"),
                remark=(line.remark or None),
            )
        )
    db.flush()


def _reconcile_assignments(db: Session, rfq: Rfq, suppliers: list[Supplier]) -> None:
    """把分派记录对齐到勾选的供货商集合（草稿阶段）。

    约定：`line_count > 0` 表示该供货商当前受邀；模板约定一次询价单至少 1 行明细，
    因此草稿阶段即使明细为空也置 1，避免 0 行草稿无法表达「已勾选」。

    未被勾选的分派：无历史则物理删除；有历史（改价快照受 FK 约束，且 PRD 要求只追加）
    则置 line_count=0 隐藏，不再出现在受邀清单、供货商待报价列表与报表中。
    """
    wanted = {s.id for s in suppliers}
    existing = {
        a.supplier_id: a
        for a in db.scalars(select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id)).all()
    }
    total_lines = db.scalar(
        select(func.count()).select_from(RfqLine).where(RfqLine.rfq_id == rfq.id)
    ) or 0
    line_count = int(total_lines) or 1

    for supplier in suppliers:
        assignment = existing.get(supplier.id)
        if assignment is None:
            db.add(
                RfqSupplier(
                    rfq_id=rfq.id,
                    supplier_id=supplier.id,
                    status="pending",
                    line_count=line_count,
                )
            )
        else:
            assignment.line_count = line_count

    for supplier_id, assignment in existing.items():
        if supplier_id in wanted:
            continue
        has_history = db.scalar(
            select(func.count())
            .select_from(QuoteHistory)
            .where(QuoteHistory.rfq_supplier_id == assignment.id)
        )
        if has_history:
            assignment.line_count = 0
            assignment.status = "pending"
            assignment.quoted_line_count = 0
        else:
            db.delete(assignment)
    db.flush()


def _new_rfq_no(db: Session) -> str:
    for _ in range(20):
        no = generate_rfq_no(db)
        if not db.scalar(select(Rfq.id).where(Rfq.rfq_no == no)):
            return no
    return generate_rfq_no(db)


# --------------------------------------------------------------------------
# 列表
# --------------------------------------------------------------------------
@router.get("", response_model=Envelope[PageData[RfqListItem]], summary="询价单列表")
def list_rfqs(
    page: str | None = Query(None, description="页码，默认 1；空串视为未传"),
    page_size: str | None = Query(None, description="每页条数，默认 20，上限 200"),
    status: str | None = Query(None, description="draft/published/closed；空串视为全部"),
    keyword: str | None = Query(None, description="单号/名称/项目模糊匹配；空串视为不过滤"),
    date_from: str | None = Query(None, description="创建时间起（含）；空串视为未传"),
    date_to: str | None = Query(None, description="创建时间止（含）；空串视为未传"),
    only_mine: str | None = Query(None, description="管理员可切换「全部 / 我创建的」（true/false）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    page_no = _parse_page_param(page, 1, "page")
    page_limit = _parse_page_param(page_size, 20, "page_size", max_value=200)
    status_value = _blank_to_none(status)
    keyword_value = _blank_to_none(keyword)
    date_from_value = _parse_date_param(date_from, "date_from")
    date_to_value = _parse_date_param(date_to, "date_to")
    only_mine_value = _parse_bool_param(only_mine, False, "only_mine")

    stmt = select(Rfq)
    if user.role != "admin" or only_mine_value:
        stmt = stmt.where(Rfq.created_by == user.id)
    if status_value in ("draft", "published", "closed"):
        stmt = stmt.where(Rfq.status == status_value)
    if keyword_value:
        like = f"%{keyword_value}%"
        stmt = stmt.where(Rfq.rfq_no.like(like) | Rfq.title.like(like) | Rfq.project.like(like))
    if date_from_value:
        stmt = stmt.where(Rfq.created_at >= datetime.combine(date_from_value, time.min))
    if date_to_value:
        stmt = stmt.where(
            Rfq.created_at < datetime.combine(date_to_value + timedelta(days=1), time.min)
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    offset, limit = page_offset(page_no, page_limit)
    rfqs = list(db.scalars(stmt.order_by(Rfq.id.desc()).offset(offset).limit(limit)).all())

    closed_changed = False
    for rfq in rfqs:
        closed_changed = auto_close_if_due(db, rfq) or closed_changed
    if closed_changed:
        db.commit()

    ids = [rfq.id for rfq in rfqs]
    line_counts: dict[int, int] = {}
    assign_stats: dict[int, tuple[int, int, int]] = {}
    if ids:
        line_counts = dict(
            db.execute(
                select(RfqLine.rfq_id, func.count())
                .where(RfqLine.rfq_id.in_(ids))
                .group_by(RfqLine.rfq_id)
            ).all()
        )
        stats_rows = db.execute(
            select(
                RfqSupplier.rfq_id,
                func.count(),
                func.sum(case((RfqSupplier.status == "quoted", 1), else_=0)),
                func.sum(RfqSupplier.quoted_line_count),
            )
            .where(RfqSupplier.rfq_id.in_(ids), RfqSupplier.line_count > 0)
            .group_by(RfqSupplier.rfq_id)
        ).all()
        assign_stats = {
            row[0]: (int(row[1] or 0), int(row[2] or 0), int(row[3] or 0)) for row in stats_rows
        }

    creator_names = {
        uid: (_user_name(db, uid) or "")
        for uid in {rfq.created_by for rfq in rfqs}
    }

    items = []
    for rfq in rfqs:
        supplier_count, quoted_count, quoted_line_count = assign_stats.get(rfq.id, (0, 0, 0))
        items.append(
            RfqListItem(
                id=rfq.id,
                rfq_no=rfq.rfq_no,
                title=rfq.title,
                project=rfq.project,
                status=rfq.status,
                deadline=rfq.deadline,
                line_count=line_counts.get(rfq.id, 0),
                supplier_count=supplier_count,
                quoted_count=quoted_count,
                quoted_line_count=quoted_line_count,
                created_by_name=creator_names.get(rfq.created_by),
                created_at=rfq.created_at,
            )
        )
    return Envelope(data=PageData(items=items, meta=PageMeta(page=page_no, page_size=limit, total=total)))


# --------------------------------------------------------------------------
# Excel 导入
# --------------------------------------------------------------------------
@router.get("/import/template", summary="下载导入模板 .xlsx")
def import_template(
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    units = [
        name
        for (name,) in db.execute(
            select(UnitDict.name).where(UnitDict.status == 1).order_by(UnitDict.sort, UnitDict.id)
        ).all()
    ]
    content = exporter.build_import_template(units)
    filename = "询价明细导入模板.xlsx"
    return Response(
        content=content,
        media_type=exporter.EXPORT_MEDIA_TYPE,
        headers={"Content-Disposition": exporter.content_disposition(filename, "rfq_import_template.xlsx")},
    )


@router.post("/import/preview", response_model=Envelope[ImportPreviewResult], summary="Excel 预校验（不落库）")
async def import_preview(
    request: Request,
    rfq_id: str | None = Query(None, description="目标询价单（必填；空串按未填处理）"),
    file: UploadFile = File(..., description=".xlsx 或 .xls"),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq_id_value = _parse_int_param(rfq_id, "rfq_id", blank_message="请选择要导入明细的询价单")
    assert rfq_id_value is not None
    rfq = _load_draft(db, request, user, rfq_id_value)
    content = await file.read()
    if not content:
        raise _err(400, 40001, "上传文件为空")
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise _err(400, 40001, f"文件超过 {settings.max_upload_size_mb}MB 上限")
    try:
        result = importer.build_preview(
            db, file.filename or "", content, user_id=user.id, rfq_id=rfq.id
        )
    except importer.ImportValidationError as exc:
        raise _err(400, 40001, exc.message)

    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.import_preview",
        target_type="rfq",
        target_id=rfq.id,
        summary=(
            f"导入预校验 {file.filename}：共 {result.total_rows} 行，"
            f"有效 {result.valid_rows} 行，错误 {result.error_rows} 行"
        ),
    )
    db.commit()
    return Envelope(data=result)


@router.post("/import/confirm", response_model=Envelope[dict], summary="确认导入明细")
def import_confirm(
    payload: ImportConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    try:
        record = importer.take_token(payload.token, user.id)
    except importer.ImportValidationError as exc:
        raise _err(400, 40001, exc.message)

    rfq = _load_draft(db, request, user, record.rfq_id)
    keep, skipped, new_units = importer.split_rows(
        record, add_unknown_units=payload.add_unknown_units
    )
    if new_units:
        max_sort = db.scalar(select(func.max(UnitDict.sort))) or 0
        for offset, name in enumerate(new_units, start=1):
            db.add(UnitDict(name=name, sort=int(max_sort) + offset, status=1))
        db.flush()

    if payload.mode == "replace" and keep:
        # 全部行都被跳过时不做清空，避免误删已有明细
        db.execute(RfqLine.__table__.delete().where(RfqLine.rfq_id == rfq.id))
        db.flush()

    base_seq = db.scalar(select(func.max(RfqLine.seq)).where(RfqLine.rfq_id == rfq.id)) or 0
    for offset, row in enumerate(keep, start=1):
        item = row.to_payload()
        db.add(
            RfqLine(
                rfq_id=rfq.id,
                seq=int(base_seq) + offset,
                material_name=item["material_name"],
                spec=item["spec"],
                unit=item["unit"],
                project=item["project"],
                quantity=Decimal(item["quantity"]),
                remark=item["remark"],
            )
        )
    db.flush()

    total_lines = db.scalar(
        select(func.count()).select_from(RfqLine).where(RfqLine.rfq_id == rfq.id)
    ) or 0
    # 明细行数变化后同步「已勾选」分派的应填行数（line_count=0 表示已取消勾选，保持隐藏）
    for assignment in db.scalars(
        select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id)
    ).all():
        if assignment.line_count > 0:
            assignment.line_count = int(total_lines) or 1

    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.import",
        target_type="rfq",
        target_id=rfq.id,
        summary=(
            f"导入询价明细到 {rfq.rfq_no}：模式 {payload.mode}，写入 {len(keep)} 行，"
            f"跳过 {len(skipped)} 行，新增单位 {new_units or '无'}，当前共 {total_lines} 行"
        ),
    )
    db.commit()
    message = "ok"
    if not keep and skipped:
        message = f"{len(skipped)} 行因单位不在计量单位字典内被跳过，未导入任何明细"
    return Envelope(
        message=message,
        data={
            "rfq_id": rfq.id,
            "mode": payload.mode,
            "imported_rows": len(keep),
            "skipped_rows": len(skipped),
            "skipped_details": [
                {"row": r.row, "unit": r.unit, "material_name": r.material_name} for r in skipped
            ],
            "new_units": new_units,
            "total_lines": int(total_lines),
        },
    )


# --------------------------------------------------------------------------
# 新建 / 详情 / 编辑 / 删除
# --------------------------------------------------------------------------
@router.post("", response_model=Envelope[RfqDetail], summary="新建询价单草稿")
def create_rfq(
    payload: RfqCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    suppliers = _resolve_suppliers(db, payload.supplier_ids)

    rfq: Rfq | None = None
    for _ in range(5):
        candidate = Rfq(
            rfq_no=_new_rfq_no(db),
            title=payload.title.strip(),
            project=payload.project.strip(),
            deadline=_norm_dt(payload.deadline),
            status="draft",
            remark=payload.remark,
            internal_remark=payload.internal_remark,
            created_by=user.id,
        )
        try:
            db.add(candidate)
            db.flush()
            rfq = candidate
            break
        except IntegrityError:
            # 单号并发冲突：回滚后换号重试（PRD 6.3-1）
            db.rollback()
    if rfq is None:
        raise _err(500, 50000, "询价单号生成冲突，请重试")

    _replace_lines(db, rfq.id, payload.lines)
    _reconcile_assignments(db, rfq, suppliers)

    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.create",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"新建询价单草稿 {rfq.rfq_no}（{len(payload.lines)} 行 / {len(suppliers)} 家供货商）",
    )
    db.commit()
    db.refresh(rfq)
    return Envelope(data=_rfq_detail(db, rfq))


@router.get("/{rfq_id}", response_model=Envelope[RfqDetail], summary="询价单详情")
def get_rfq(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_rfq(db, request, user, rfq_id)
    return Envelope(data=_rfq_detail(db, rfq))


@router.put("/{rfq_id}", response_model=Envelope[RfqDetail], summary="编辑询价单草稿")
def update_rfq(
    rfq_id: int,
    payload: RfqUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_draft(db, request, user, rfq_id)
    suppliers = _resolve_suppliers(db, payload.supplier_ids)

    rfq.title = payload.title.strip()
    rfq.project = payload.project.strip()
    rfq.deadline = _norm_dt(payload.deadline)
    rfq.remark = payload.remark
    rfq.internal_remark = payload.internal_remark

    _replace_lines(db, rfq.id, payload.lines)
    _reconcile_assignments(db, rfq, suppliers)

    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.update",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"编辑询价单草稿 {rfq.rfq_no}（{len(payload.lines)} 行 / {len(suppliers)} 家供货商）",
    )
    db.commit()
    db.refresh(rfq)
    return Envelope(data=_rfq_detail(db, rfq))


@router.delete("/{rfq_id}", response_model=Envelope[None], summary="删除询价单草稿")
def delete_rfq(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_rfq(db, request, user, rfq_id)
    if rfq.status != "draft":
        # 已发布/已截止不可删除（FR-RFQ-06 / TC-19）
        raise _err(409, 40900, "已发布或已截止的询价单不可删除，只能截止")

    assignments = db.scalars(select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id)).all()
    history_count = 0
    if assignments:
        history_count = db.scalar(
            select(func.count())
            .select_from(QuoteHistory)
            .where(QuoteHistory.rfq_supplier_id.in_([a.id for a in assignments]))
        ) or 0
    if history_count:
        raise _err(409, 40900, "该单据存在历史报价快照（可追溯数据不可删除），请保留为草稿")

    rfq_no = rfq.rfq_no
    db.delete(rfq)
    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.delete",
        target_type="rfq",
        target_id=rfq_id,
        summary=f"删除询价单草稿 {rfq_no}",
    )
    db.commit()
    return Envelope(message="已删除")


# --------------------------------------------------------------------------
# 发布 / 撤回 / 截止 / 进度 / 报价
# --------------------------------------------------------------------------
def _collect_publish_errors(db: Session, rfq: Rfq, assignments: list[RfqSupplier]) -> list[str]:
    errors: list[str] = []
    if not (rfq.title or "").strip():
        errors.append("单据名称：必填")
    if not (rfq.project or "").strip():
        errors.append("项目：必填")
    if rfq.deadline is None:
        errors.append("报价截止时间：必填")
    elif is_deadline_passed(rfq.deadline):
        errors.append("报价截止时间：必须晚于当前时间")

    lines = _ordered_lines(db, rfq.id)
    if not lines:
        errors.append("明细：至少需要 1 行明细")

    units = _enabled_units(db)
    for line in lines:
        prefix = f"第{line.seq}行"
        if not (line.material_name or "").strip():
            errors.append(f"{prefix} 材料名称：必填")
        if not (line.unit or "").strip():
            errors.append(f"{prefix} 单位：必填")
        elif line.unit not in units:
            errors.append(f"{prefix} 单位：不在计量单位字典内（{line.unit}）")
        if line.quantity is None or Decimal(str(line.quantity)) <= 0:
            errors.append(f"{prefix} 采购数量：必须大于 0")

    if not assignments:
        errors.append("受邀供货商：请至少选择一家供货商")
    return errors


@router.post("/{rfq_id}/publish", response_model=Envelope[RfqDetail], summary="发布询价单并生成分派")
def publish_rfq(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_rfq(db, request, user, rfq_id)
    if rfq.status == "closed":
        raise _err(409, 40900, "该询价单已截止，不可再次发布")
    if rfq.status == "published":
        return Envelope(data=_rfq_detail(db, rfq))

    assignments = [
        a
        for a in db.scalars(select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id)).all()
        if a.line_count > 0
    ]
    errors = _collect_publish_errors(db, rfq, assignments)
    if errors:
        # 逐条列出错误（FR-RFQ-10 / TC-10 / TC-11）；全局异常处理器会输出 {code,message,data:null}
        raise _err(400, 40001, "发布校验未通过：\n" + "\n".join(errors))

    line_count = len(_ordered_lines(db, rfq.id))
    for assignment in assignments:
        assignment.line_count = line_count
        assignment.status = "pending"
        assignment.quoted_line_count = 0
        assignment.submitted_at = None
        assignment.first_saved_at = None
        assignment.last_saved_at = None

    rfq.status = "published"
    rfq.published_at = app_now()
    rfq.closed_at = None
    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.publish",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"发布询价单 {rfq.rfq_no}，生成 {len(assignments)} 份报价单（{line_count} 行明细）",
    )
    db.commit()
    db.refresh(rfq)
    return Envelope(data=_rfq_detail(db, rfq))


@router.post(
    "/{rfq_id}/append-suppliers",
    response_model=Envelope[RfqDetail],
    summary="已发布未截止的询价单：追加受邀供货商",
)
def append_suppliers(
    rfq_id: int,
    payload: RfqAppendSuppliers,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    """追加受邀供货商（需求变更 2026-10）。

    业务规则：
    - 仅「已发布且未截止」可追加；草稿请直接改受邀名单，已截止一律拒绝（40301/40900）；
    - 只能追加**尚未被分派**的供货商，已在名单里的会被明确拒绝；
    - 明细、已有分派与已有报价**不受任何影响**；
    - 新供货商立即可填报：分派记录 `line_count` 记为当前明细行数，报价行在首次保存时创建。
    """
    rfq = _load_rfq(db, request, user, rfq_id)

    if rfq.status == "draft":
        raise _err(409, 40900, "草稿状态请直接编辑受邀供货商，无需追加")
    if rfq.status == "closed" or is_deadline_passed(rfq.deadline):
        raise _err(403, 40301, "该询价单已截止，不可再追加供货商")

    lines = _ordered_lines(db, rfq.id)
    line_count = len(lines)
    if line_count == 0:
        raise _err(409, 40900, "该询价单没有明细行，无法追加供货商")

    existing = {
        a.supplier_id
        for a in db.scalars(select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id)).all()
        if a.line_count > 0
    }
    suppliers = _resolve_suppliers(db, payload.supplier_ids)

    added: list[Supplier] = []
    skipped: list[str] = []
    for supplier in suppliers:
        if supplier.id in existing:
            skipped.append(supplier.name)
            continue
        if supplier.status != 1:
            skipped.append(f"{supplier.name}（已停用）")
            continue
        # 复用可能存在的历史分派记录（撤回后重新发布等场景），避免唯一约束冲突
        assignment = db.scalar(
            select(RfqSupplier).where(
                RfqSupplier.rfq_id == rfq.id, RfqSupplier.supplier_id == supplier.id
            )
        )
        if assignment is None:
            assignment = RfqSupplier(rfq_id=rfq.id, supplier_id=supplier.id)
            db.add(assignment)
        assignment.line_count = line_count
        assignment.status = "pending"
        assignment.quoted_line_count = 0
        assignment.submitted_at = None
        added.append(supplier)

    if not added:
        detail = "；".join(skipped) if skipped else "没有可追加的供货商"
        raise _err(409, 40900, f"没有新增供货商：{detail}")

    db.flush()
    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.append_suppliers",
        target_type="rfq",
        target_id=rfq.id,
        summary=(
            f"询价单 {rfq.rfq_no} 追加 {len(added)} 家受邀供货商"
            f"（{('、'.join(s.name for s in added))}，{line_count} 行明细）"
            + (f"；跳过：{'、'.join(skipped)}" if skipped else "")
        ),
    )
    db.commit()
    db.refresh(rfq)
    return Envelope(
        data=_rfq_detail(db, rfq),
        message=f"已追加 {len(added)} 家供货商" + (f"；跳过 {len(skipped)} 家" if skipped else ""),
    )


@router.post("/{rfq_id}/withdraw", response_model=Envelope[RfqDetail], summary="撤回为草稿（作废已有报价）")
def withdraw_rfq(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_rfq(db, request, user, rfq_id)
    if rfq.status == "draft":
        return Envelope(data=_rfq_detail(db, rfq))
    if rfq.status != "published":
        raise _err(409, 40900, "仅已发布的询价单可撤回为草稿")

    assignments = list(db.scalars(select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id)).all())
    voided = 0
    for assignment in assignments:
        quote_lines = list(
            db.scalars(select(QuoteLine).where(QuoteLine.rfq_supplier_id == assignment.id)).all()
        )
        for line in quote_lines:
            if line.price_incl_tax is None and line.remark is None and line.moq is None:
                continue
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
                    snapshot=_quote_snapshot(line),
                    changed_fields=[],
                    action="withdraw",
                    operated_by=user.id,
                )
            )
            voided += 1
        for line in quote_lines:
            db.delete(line)
        assignment.status = "pending"
        assignment.quoted_line_count = 0
        assignment.submitted_at = None

    rfq.status = "draft"
    rfq.published_at = None
    rfq.closed_at = None
    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.withdraw",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"撤回询价单 {rfq.rfq_no} 为草稿，作废 {voided} 条报价（历史快照保留）",
    )
    db.commit()
    db.refresh(rfq)
    return Envelope(data=_rfq_detail(db, rfq))


@router.post("/{rfq_id}/close", response_model=Envelope[RfqDetail], summary="手动截止")
def close_rfq(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_rfq(db, request, user, rfq_id)
    if rfq.status == "draft":
        raise _err(409, 40900, "草稿状态的询价单无需截止，请先发布")
    if rfq.status == "closed":
        return Envelope(data=_rfq_detail(db, rfq))

    rfq.status = "closed"
    rfq.closed_at = app_now()
    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.close",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"手动截止询价单 {rfq.rfq_no}",
    )
    db.commit()
    db.refresh(rfq)
    return Envelope(data=_rfq_detail(db, rfq))


@router.get("/{rfq_id}/progress", response_model=Envelope[list[AssigneeOut]], summary="报价进度（含未报价清单）")
def rfq_progress(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_rfq(db, request, user, rfq_id)
    assignees = [_assignee_out(a, s) for a, s in _assignment_rows(db, rfq.id)]
    return Envelope(data=assignees)


@router.get("/{rfq_id}/quotes", response_model=Envelope[ComparisonResult], summary="各家报价明细（供货商 403）")
def rfq_quotes(
    rfq_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    rfq = _load_rfq(db, request, user, rfq_id)
    return Envelope(data=build_comparison(db, rfq))



# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
@router.get("/{rfq_id}/export", summary="导出询价单及报价结果 .xlsx")
def export_rfq(
    rfq_id: int,
    request: Request,
    include_quotes: str | None = Query(None, description="false = 仅导出我方询价明细；空串用默认值 true"),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal_audited),
):
    include_quotes_value = _parse_bool_param(include_quotes, True, "include_quotes")
    rfq = _load_rfq(db, request, user, rfq_id)
    lines = _ordered_lines(db, rfq.id)
    if len(lines) > settings.export_max_rows:
        raise _err(
            400,
            40001,
            f"本次导出 {len(lines)} 行，超过单次上限 {settings.export_max_rows} 行，请拆分单据",
        )

    result = build_comparison(db, rfq)
    progress = [
        {
            "supplier_name": s.name,
            "status": a.status,
            "quoted_line_count": a.quoted_line_count,
            "line_count": a.line_count,
            "last_saved_at": a.last_saved_at,
            "submitted_at": a.submitted_at,
        }
        for a, s in _assignment_rows(db, rfq.id)
    ]
    content = exporter.build_rfq_export(
        rfq_no=rfq.rfq_no,
        title=rfq.title,
        project=rfq.project,
        deadline=rfq.deadline,
        status=rfq.status,
        creator_name=_user_name(db, rfq.created_by),
        created_at=rfq.created_at,
        remark=rfq.remark,
        internal_remark=rfq.internal_remark,
        result=result,
        include_quotes=include_quotes_value,
        progress=progress,
    )
    filename = exporter.rfq_export_filename(rfq.rfq_no, rfq.project)
    write_audit(
        db,
        request=request,
        user=user,
        action="rfq.export",
        target_type="rfq",
        target_id=rfq.id,
        summary=f"导出询价单 {rfq.rfq_no}（{len(lines)} 行，{'含报价对比' if include_quotes_value else '仅明细'}）",
    )
    db.commit()
    return Response(
        content=content,
        media_type=exporter.EXPORT_MEDIA_TYPE,
        headers={"Content-Disposition": exporter.content_disposition(filename, "rfq_export.xlsx")},
    )


def _quote_snapshot(line: QuoteLine) -> dict[str, Any]:
    """报价行变更前快照（JSON 安全：金额/税率/数量转字符串）。"""
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
