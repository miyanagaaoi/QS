"""设备管理 · Excel 导入 / 导出（CH-014）。

- 导出：5 张台账各导一个 .xlsx，列顺序与模板一致；到期类列按模板规则**标色**
  （≤阈值 橙、已超期 红），方便直接上报。
- 导入：按模板列名读取（列顺序无关，按表头文字匹配）；逐行校验，
  返回 `total/created/failed/errors[]`，不因个别行失败中断整批。
- 子台账导入按「台账编号」关联主台账；找不到设备则该行失败并说明。
- 复用 `app.exporter` 的表头样式与中文文件名，观感与其它模块一致。
"""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_internal, write_audit
from ..eq_models import (
    EQ_CHECK_WARN_DAYS,
    EQ_WARRANTY_WARN_DAYS,
    EqAsset,
    EqEvent,
    EqMeter,
    EqSpare,
    EqSpecial,
)
from ..eq_schemas import EqImportError, EqImportResult
from ..exporter import (
    _FILL_HEAD,
    _dt,
    _today,
    _write_header,
    _write_row,
    content_disposition,
)
from ..models import User, app_now
from ..schemas import Envelope
from .equipment import _dec, _err, _str

router = APIRouter()

#: 导入文件大小上限（10MB）：xlsx 台账一般几百 KB，超过多为误传
MAX_IMPORT_BYTES = 10 * 1024 * 1024

FILL_WARN = PatternFill("solid", fgColor="FFE4B5")  # 橙：临期
FILL_OVER = PatternFill("solid", fgColor="FFC7CE")  # 红：超期


def _widths(ws, widths: tuple[int, ...]) -> None:
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _xlsx(wb: Workbook, filename: str, ascii_name: str) -> Response:
    buf = BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition(filename, ascii_name)},
    )


def _paint(ws, row_no: int, col: int, days: int | None) -> None:
    if days is None:
        return
    cell = ws.cell(row=row_no, column=col)
    if days < 0:
        cell.fill = FILL_OVER
    elif days <= EQ_CHECK_WARN_DAYS:
        cell.fill = FILL_WARN


def _paint_warranty(ws, row_no: int, col: int, days: int | None) -> None:
    if days is None:
        return
    cell = ws.cell(row=row_no, column=col)
    if days < 0:
        cell.fill = FILL_OVER
    elif days <= EQ_WARRANTY_WARN_DAYS:
        cell.fill = FILL_WARN


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
@router.get("/assets/export", summary="导出设备台账（xlsx，含预警标色）")
def export_assets(db: Session = Depends(get_db), user: User = Depends(require_internal)):
    today = app_now().date()
    rows = db.scalars(select(EqAsset).order_by(EqAsset.asset_no)).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "设备主台账"
    headers = [
        "台账编号", "资产编号", "设备名称", "规格型号", "设备类别", "重要等级",
        "是否特种设备", "特种设备登记号", "安装地点/站点", "所属系统", "投用日期",
        "质保起始日", "质保到期日", "距质保到期(天)", "设计使用年限(年)", "预计报废日期",
        "采购原值(元)", "供应商", "当前状态", "属地责任人", "备注",
    ]
    _write_header(ws, headers)
    for row in rows:
        days = (row.warranty_end - today).days if row.warranty_end else None
        row_no = _write_row(
            ws,
            [
                row.asset_no,
                row.finance_no or "",
                row.name,
                row.model or "",
                row.category or "",
                row.importance or "",
                "是" if row.is_special else "否",
                row.special_reg_no or "",
                row.location or "",
                row.system_name or "",
                row.commission_date.isoformat() if row.commission_date else "",
                row.warranty_start.isoformat() if row.warranty_start else "",
                row.warranty_end.isoformat() if row.warranty_end else "",
                days if days is not None else "",
                row.design_life_years if row.design_life_years is not None else "",
                row.scrap_date.isoformat() if row.scrap_date else "",
                float(row.purchase_value) if row.purchase_value is not None else "",
                row.supplier or "",
                row.status,
                row.owner or "",
                row.remark or "",
            ],
        )
        _paint_warranty(ws, row_no, 14, days)
    _widths(ws, (18, 16, 20, 20, 12, 8, 12, 18, 18, 12, 12, 12, 12, 14, 14, 12, 14, 20, 10, 12, 24))
    ws.freeze_panes = "A2"
    return _xlsx(
        wb,
        f"设备主台账_{_today().strftime('%Y%m%d')}.xlsx",
        f"eq-assets-{_today().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/events/export", summary="导出动态事件台账（xlsx）")
def export_events(
    asset_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    today = app_now().date()
    stmt = select(EqEvent)
    if asset_id:
        stmt = stmt.where(EqEvent.asset_id == asset_id)
    rows = db.scalars(stmt.order_by(EqEvent.id)).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "设备动态事件台账"
    headers = [
        "台账编号", "设备名称", "事件类型", "事件发生日期", "计划完成日期", "实际完成日期",
        "提报人", "事件简述内容", "执行单位/执行人", "相关证书/报告编号", "费用(元)",
        "验收结论", "验收人", "验收日期", "附件存储路径", "整改措施", "备注",
    ]
    _write_header(ws, headers)
    for row in rows:
        asset = row.asset
        days = (row.plan_date - today).days if row.plan_date else None
        row_no = _write_row(
            ws,
            [
                asset.asset_no if asset else "",
                asset.name if asset else "",
                row.event_type,
                row.occur_date.isoformat() if row.occur_date else "",
                row.plan_date.isoformat() if row.plan_date else "",
                row.actual_date.isoformat() if row.actual_date else "",
                row.reporter or "",
                row.content or "",
                row.executor or "",
                row.cert_no or "",
                float(row.cost) if row.cost is not None else "",
                row.accept_result or "",
                row.acceptor or "",
                row.accept_date.isoformat() if row.accept_date else "",
                row.attachment_path or "",
                row.corrective or "",
                row.remark or "",
            ],
        )
        if days is not None and row.actual_date is None:
            _paint(ws, row_no, 5, days)
    _widths(ws, (18, 18, 12, 12, 12, 12, 10, 40, 20, 18, 10, 10, 10, 12, 24, 24, 18))
    ws.freeze_panes = "A2"
    return _xlsx(
        wb,
        f"设备动态事件台账_{_today().strftime('%Y%m%d')}.xlsx",
        f"eq-events-{_today().strftime('%Y%m%d')}.xlsx",
    )


def _export_expiry(title: str, rows, headers: list[str], values_fn, days_col: int, prefix: str) -> Response:
    """计量/特种两张表结构一致，共用导出逻辑。"""
    today = app_now().date()
    wb = Workbook()
    ws = wb.active
    ws.title = title
    _write_header(ws, headers)
    for row in rows:
        values, days = values_fn(row, today)
        row_no = _write_row(ws, values)
        _paint(ws, row_no, days_col, days)
    _widths(ws, (18, 20, 16, 10, 12, 12, 18, 16, 12, 14, 12, 20, 10, 12, 20))
    ws.freeze_panes = "A2"
    return _xlsx(
        wb,
        f"{title}_{_today().strftime('%Y%m%d')}.xlsx",
        f"{prefix}-{_today().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/meters/export", summary="导出计量器具检定台账（xlsx）")
def export_meters(
    asset_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    stmt = select(EqMeter)
    if asset_id:
        stmt = stmt.where(EqMeter.asset_id == asset_id)
    rows = db.scalars(stmt.order_by(EqMeter.id)).all()
    headers = [
        "台账编号", "设备名称", "器具名称", "规格型号", "精度等级", "是否强检",
        "检定周期(月)", "上次检定日期", "证书编号", "有效期至", "距到期(天)",
        "检定机构", "状态", "责任人", "备注",
    ]

    def values_fn(row, today):
        asset = row.asset
        days = (row.valid_until - today).days if row.valid_until else None
        return (
            [
                asset.asset_no if asset else "",
                asset.name if asset else "",
                row.name,
                row.model or "",
                row.accuracy or "",
                "是" if row.is_mandatory else "否",
                row.cycle_months if row.cycle_months is not None else "",
                row.last_check_date.isoformat() if row.last_check_date else "",
                row.cert_no or "",
                row.valid_until.isoformat() if row.valid_until else "",
                days if days is not None else "",
                row.org or "",
                row.status,
                row.owner or "",
                row.remark or "",
            ],
            days,
        )

    return _export_expiry("计量器具检定台账", rows, headers, values_fn, 11, "eq-meters")


@router.get("/specials/export", summary="导出特种设备检验台账（xlsx）")
def export_specials(
    asset_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    stmt = select(EqSpecial)
    if asset_id:
        stmt = stmt.where(EqSpecial.asset_id == asset_id)
    rows = db.scalars(stmt.order_by(EqSpecial.id)).all()
    headers = [
        "台账编号", "设备名称", "注册编号", "检验类型", "检验周期(月)", "上次检验日期",
        "报告编号", "有效期至", "距到期(天)", "检验机构", "状态", "责任人", "备注",
    ]

    def values_fn(row, today):
        asset = row.asset
        days = (row.valid_until - today).days if row.valid_until else None
        return (
            [
                asset.asset_no if asset else "",
                asset.name if asset else "",
                row.reg_no or "",
                row.check_type,
                row.cycle_months if row.cycle_months is not None else "",
                row.last_check_date.isoformat() if row.last_check_date else "",
                row.report_no or "",
                row.valid_until.isoformat() if row.valid_until else "",
                days if days is not None else "",
                row.org or "",
                row.status,
                row.owner or "",
                row.remark or "",
            ],
            days,
        )

    return _export_expiry("特种设备定期检验台账", rows, headers, values_fn, 9, "eq-specials")


@router.get("/spares/export", summary="导出备件更换台账（xlsx）")
def export_spares(
    asset_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    stmt = select(EqSpare)
    if asset_id:
        stmt = stmt.where(EqSpare.asset_id == asset_id)
    rows = db.scalars(stmt.order_by(EqSpare.id)).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "备件更换明细台账"
    headers = [
        "台账编号", "设备名称", "备件名称", "规格型号", "原厂/替代件", "更换时间",
        "更换原因", "更换数量", "单价(元)", "金额(元)", "供应商", "换下旧件处置", "执行人", "备注",
    ]
    _write_header(ws, headers)
    for row in rows:
        asset = row.asset
        _write_row(
            ws,
            [
                asset.asset_no if asset else "",
                asset.name if asset else "",
                row.part_name,
                row.model or "",
                row.origin_type or "",
                row.replace_date.isoformat() if row.replace_date else "",
                row.reason or "",
                float(row.qty) if row.qty is not None else "",
                float(row.unit_price) if row.unit_price is not None else "",
                float(row.amount) if row.amount is not None else "",
                row.supplier or "",
                row.old_disposal or "",
                row.executor or "",
                row.remark or "",
            ],
        )
    _widths(ws, (18, 18, 18, 18, 12, 12, 28, 10, 10, 12, 20, 14, 10, 20))
    ws.freeze_panes = "A2"
    return _xlsx(
        wb,
        f"备件更换明细台账_{_today().strftime('%Y%m%d')}.xlsx",
        f"eq-spares-{_today().strftime('%Y%m%d')}.xlsx",
    )


# --------------------------------------------------------------------------
# 导入
# --------------------------------------------------------------------------
def _to_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10].replace("/", "-")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:  # noqa: TRY003
        raise _err(400, 40001, f"日期格式错误：{value}") from exc


def _to_bool(value) -> bool:
    return str(value).strip() in ("是", "Y", "y", "1", "True", "true")


def _read_sheet(file: UploadFile) -> tuple[list[str], list[list]]:
    raw = file.file.read()
    if not raw:
        raise _err(400, 40001, "请选择要导入的 Excel 文件")
    if len(raw) > MAX_IMPORT_BYTES:
        raise _err(400, 40001, f"文件过大（{len(raw) // 1024 // 1024}MB），请控制在 10MB 以内")
    try:
        wb = load_workbook(BytesIO(raw), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise _err(400, 40001, "无法读取文件，请上传 .xlsx 格式") from exc
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise _err(400, 40001, "文件为空")
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    return header, [list(r) for r in rows[1:] if any(c is not None and str(c).strip() for c in r)]


def _mapper(header: list[str], spec: dict[str, str]):
    """返回 dict(中文列名) → 列下标。spec: {字段键: 模板列名}"""
    index = {name: i for i, name in enumerate(header) if name}
    return {key: index.get(col) for key, col in spec.items()}


def _cell(row: list, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    value = row[idx]
    return value if value not in ("", None) else None


def _result(total: int, created: int, errors: list[EqImportError]) -> EqImportResult:
    return EqImportResult(total=total, created=created, failed=len(errors), errors=errors[:200])


ASSET_SPEC = {
    "asset_no": "台账编号",
    "finance_no": "资产编号",
    "name": "设备名称",
    "model": "规格型号",
    "category": "设备类别",
    "importance": "重要等级",
    "is_special": "是否特种设备",
    "special_reg_no": "特种设备登记号",
    "location": "安装地点/站点",
    "system_name": "所属系统",
    "commission_date": "投用日期",
    "warranty_start": "质保起始日",
    "warranty_end": "质保到期日",
    "design_life_years": "设计使用年限(年)",
    "scrap_date": "预计报废日期",
    "purchase_value": "采购原值(元)",
    "supplier": "供应商",
    "status": "当前状态",
    "owner": "属地责任人",
    "remark": "备注",
}


@router.post("/assets/import", summary="导入设备台账（xlsx）")
def import_assets(
    file: UploadFile = File(...),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    header, rows = _read_sheet(file)
    m = _mapper(header, ASSET_SPEC)
    if m.get("asset_no") is None or m.get("name") is None:
        raise _err(400, 40001, "表头缺少「台账编号」或「设备名称」列")
    errors: list[EqImportError] = []
    created = 0
    existing = {a.asset_no for a in db.scalars(select(EqAsset)).all()}
    for offset, row in enumerate(rows, start=2):
        try:
            asset_no = _str(_cell(row, m["asset_no"]))
            name = _str(_cell(row, m["name"]))
            if not asset_no or not name:
                raise _err(400, 40001, "台账编号与设备名称必填")
            if asset_no in existing:
                raise _err(409, 40900, "台账编号已存在")
            is_special = _to_bool(_cell(row, m.get("is_special")))
            reg_no = _str(_cell(row, m.get("special_reg_no")))
            if is_special and not reg_no:
                raise _err(400, 40001, "特种设备必须填写特种设备登记号")
            years = _cell(row, m.get("design_life_years"))
            row_obj = EqAsset(
                asset_no=asset_no,
                finance_no=_str(_cell(row, m.get("finance_no"))),
                name=name,
                model=_str(_cell(row, m.get("model"))),
                category=_str(_cell(row, m.get("category"))),
                importance=_str(_cell(row, m.get("importance"))),
                is_special=is_special,
                special_reg_no=reg_no,
                location=_str(_cell(row, m.get("location"))),
                system_name=_str(_cell(row, m.get("system_name"))),
                commission_date=_to_date(_cell(row, m.get("commission_date"))),
                warranty_start=_to_date(_cell(row, m.get("warranty_start"))),
                warranty_end=_to_date(_cell(row, m.get("warranty_end"))),
                design_life_years=int(years) if years is not None else None,
                scrap_date=_to_date(_cell(row, m.get("scrap_date"))),
                purchase_value=_dec(_cell(row, m.get("purchase_value")), "采购原值"),
                supplier=_str(_cell(row, m.get("supplier"))),
                status=_str(_cell(row, m.get("status"))) or "在用",
                owner=_str(_cell(row, m.get("owner"))),
                remark=_str(_cell(row, m.get("remark"))),
                created_by=user.id,
            )
            db.add(row_obj)
            db.commit()  # 逐行提交：坏行 rollback 时不会带走前面已成功的行
            existing.add(asset_no)
            created += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            detail = getattr(exc, "detail", None)
            reason = detail.get("message") if isinstance(detail, dict) else str(exc)
            errors.append(EqImportError(row=offset, reason=reason))
    db.commit()
    write_audit(
        db, request=request, user=user,
        action="eq.import.assets", target_type="eq_import",
        summary=f"导入设备主台账：成功 {created} 行 / 失败 {len(errors)} 行",
    )
    db.commit()
    return Envelope(data=_result(len(rows), created, errors))


def _asset_map(db: Session) -> dict[str, EqAsset]:
    return {a.asset_no: a for a in db.scalars(select(EqAsset)).all()}


def _resolve_asset(db: Session, amap: dict[str, EqAsset], row: list, idx: int | None) -> EqAsset:
    asset_no = _str(_cell(row, idx))
    if not asset_no:
        raise _err(400, 40001, "台账编号必填")
    asset = amap.get(asset_no)
    if asset is None:
        raise _err(400, 40001, f"台账编号「{asset_no}」在主台账中不存在，请先导入设备台账")
    return asset


EVENT_SPEC = {
    "asset_no": "台账编号",
    "event_type": "事件类型",
    "occur_date": "事件发生日期",
    "plan_date": "计划完成日期",
    "actual_date": "实际完成日期",
    "reporter": "提报人",
    "content": "事件简述内容",
    "executor": "执行单位/执行人",
    "cert_no": "相关证书/报告编号",
    "cost": "费用(元)",
    "accept_result": "验收结论",
    "acceptor": "验收人",
    "accept_date": "验收日期",
    "attachment_path": "附件存储路径",
    "corrective": "整改措施",
    "remark": "备注",
}


@router.post("/events/import", summary="导入动态事件台账（xlsx）")
def import_events(
    file: UploadFile = File(...),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    header, rows = _read_sheet(file)
    m = _mapper(header, EVENT_SPEC)
    if m.get("asset_no") is None or m.get("event_type") is None:
        raise _err(400, 40001, "表头缺少「台账编号」或「事件类型」列")
    amap = _asset_map(db)
    errors: list[EqImportError] = []
    created = 0
    for offset, row in enumerate(rows, start=2):
        try:
            asset = _resolve_asset(db, amap, row, m["asset_no"])
            event_type = _str(_cell(row, m["event_type"]))
            if not event_type:
                raise _err(400, 40001, "事件类型必填")
            db.add(
                EqEvent(
                    asset_id=asset.id,
                    event_type=event_type,
                    occur_date=_to_date(_cell(row, m.get("occur_date"))),
                    plan_date=_to_date(_cell(row, m.get("plan_date"))),
                    actual_date=_to_date(_cell(row, m.get("actual_date"))),
                    reporter=_str(_cell(row, m.get("reporter"))),
                    content=_str(_cell(row, m.get("content"))),
                    executor=_str(_cell(row, m.get("executor"))),
                    cert_no=_str(_cell(row, m.get("cert_no"))),
                    cost=_dec(_cell(row, m.get("cost")), "费用"),
                    accept_result=_str(_cell(row, m.get("accept_result"))),
                    acceptor=_str(_cell(row, m.get("acceptor"))),
                    accept_date=_to_date(_cell(row, m.get("accept_date"))),
                    attachment_path=_str(_cell(row, m.get("attachment_path"))),
                    corrective=_str(_cell(row, m.get("corrective"))),
                    remark=_str(_cell(row, m.get("remark"))),
                )
            )
            db.commit()  # 逐行提交：坏行 rollback 时不会带走前面已成功的行
            created += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            detail = getattr(exc, "detail", None)
            reason = detail.get("message") if isinstance(detail, dict) else str(exc)
            errors.append(EqImportError(row=offset, reason=reason))
    db.commit()
    write_audit(
        db, request=request, user=user,
        action="eq.import.events", target_type="eq_import",
        summary=f"导入动态事件台账：成功 {created} 行 / 失败 {len(errors)} 行",
    )
    db.commit()
    return Envelope(data=_result(len(rows), created, errors))


METER_SPEC = {
    "asset_no": "台账编号",
    "name": "器具名称",
    "model": "规格型号",
    "accuracy": "精度等级",
    "is_mandatory": "是否强检",
    "cycle_months": "检定周期(月)",
    "last_check_date": "上次检定日期",
    "cert_no": "证书编号",
    "valid_until": "有效期至",
    "org": "检定机构",
    "status": "状态",
    "owner": "责任人",
    "remark": "备注",
}


@router.post("/meters/import", summary="导入计量器具检定台账（xlsx）")
def import_meters(
    file: UploadFile = File(...),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    header, rows = _read_sheet(file)
    m = _mapper(header, METER_SPEC)
    if m.get("name") is None:
        raise _err(400, 40001, "表头缺少「器具名称」列")
    amap = _asset_map(db)
    errors: list[EqImportError] = []
    created = 0
    for offset, row in enumerate(rows, start=2):
        try:
            asset = _resolve_asset(db, amap, row, m.get("asset_no"))
            name = _str(_cell(row, m["name"]))
            if not name:
                raise _err(400, 40001, "器具名称必填")
            cycle = _cell(row, m.get("cycle_months"))
            db.add(
                EqMeter(
                    asset_id=asset.id,
                    name=name,
                    model=_str(_cell(row, m.get("model"))),
                    accuracy=_str(_cell(row, m.get("accuracy"))),
                    is_mandatory=_to_bool(_cell(row, m.get("is_mandatory"))),
                    cycle_months=int(cycle) if cycle is not None else None,
                    last_check_date=_to_date(_cell(row, m.get("last_check_date"))),
                    cert_no=_str(_cell(row, m.get("cert_no"))),
                    valid_until=_to_date(_cell(row, m.get("valid_until"))),
                    org=_str(_cell(row, m.get("org"))),
                    status=_str(_cell(row, m.get("status"))) or "在用",
                    owner=_str(_cell(row, m.get("owner"))),
                    remark=_str(_cell(row, m.get("remark"))),
                )
            )
            db.commit()  # 逐行提交：坏行 rollback 时不会带走前面已成功的行
            created += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            detail = getattr(exc, "detail", None)
            reason = detail.get("message") if isinstance(detail, dict) else str(exc)
            errors.append(EqImportError(row=offset, reason=reason))
    db.commit()
    write_audit(
        db, request=request, user=user,
        action="eq.import.meters", target_type="eq_import",
        summary=f"导入计量器具检定台账：成功 {created} 行 / 失败 {len(errors)} 行",
    )
    db.commit()
    return Envelope(data=_result(len(rows), created, errors))


SPECIAL_SPEC = {
    "asset_no": "台账编号",
    "name": "设备名称",
    "reg_no": "注册编号",
    "check_type": "检验类型",
    "cycle_months": "检验周期(月)",
    "last_check_date": "上次检验日期",
    "report_no": "报告编号",
    "valid_until": "有效期至",
    "org": "检验机构",
    "status": "状态",
    "owner": "责任人",
    "remark": "备注",
}


@router.post("/specials/import", summary="导入特种设备检验台账（xlsx）")
def import_specials(
    file: UploadFile = File(...),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    header, rows = _read_sheet(file)
    m = _mapper(header, SPECIAL_SPEC)
    if m.get("check_type") is None:
        raise _err(400, 40001, "表头缺少「检验类型」列")
    amap = _asset_map(db)
    errors: list[EqImportError] = []
    created = 0
    for offset, row in enumerate(rows, start=2):
        try:
            asset = _resolve_asset(db, amap, row, m.get("asset_no"))
            check_type = _str(_cell(row, m["check_type"]))
            if not check_type:
                raise _err(400, 40001, "检验类型必填")
            cycle = _cell(row, m.get("cycle_months"))
            db.add(
                EqSpecial(
                    asset_id=asset.id,
                    name=_str(_cell(row, m.get("name"))),
                    reg_no=_str(_cell(row, m.get("reg_no"))),
                    check_type=check_type,
                    cycle_months=int(cycle) if cycle is not None else None,
                    last_check_date=_to_date(_cell(row, m.get("last_check_date"))),
                    report_no=_str(_cell(row, m.get("report_no"))),
                    valid_until=_to_date(_cell(row, m.get("valid_until"))),
                    org=_str(_cell(row, m.get("org"))),
                    status=_str(_cell(row, m.get("status"))) or "在用",
                    owner=_str(_cell(row, m.get("owner"))),
                    remark=_str(_cell(row, m.get("remark"))),
                )
            )
            db.commit()  # 逐行提交：坏行 rollback 时不会带走前面已成功的行
            created += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            detail = getattr(exc, "detail", None)
            reason = detail.get("message") if isinstance(detail, dict) else str(exc)
            errors.append(EqImportError(row=offset, reason=reason))
    db.commit()
    write_audit(
        db, request=request, user=user,
        action="eq.import.specials", target_type="eq_import",
        summary=f"导入特种设备检验台账：成功 {created} 行 / 失败 {len(errors)} 行",
    )
    db.commit()
    return Envelope(data=_result(len(rows), created, errors))


SPARE_SPEC = {
    "asset_no": "台账编号",
    "part_name": "备件名称",
    "model": "规格型号",
    "origin_type": "原厂/替代件",
    "replace_date": "更换时间",
    "reason": "更换原因",
    "qty": "更换数量",
    "unit_price": "单价(元)",
    "amount": "金额(元)",
    "supplier": "供应商",
    "old_disposal": "换下旧件处置",
    "executor": "执行人",
    "remark": "备注",
}


@router.post("/spares/import", summary="导入备件更换台账（xlsx）")
def import_spares(
    file: UploadFile = File(...),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    header, rows = _read_sheet(file)
    m = _mapper(header, SPARE_SPEC)
    if m.get("part_name") is None:
        raise _err(400, 40001, "表头缺少「备件名称」列")
    amap = _asset_map(db)
    errors: list[EqImportError] = []
    created = 0
    for offset, row in enumerate(rows, start=2):
        try:
            asset = _resolve_asset(db, amap, row, m.get("asset_no"))
            part_name = _str(_cell(row, m["part_name"]))
            if not part_name:
                raise _err(400, 40001, "备件名称必填")
            qty = _dec(_cell(row, m.get("qty")), "更换数量")
            unit_price = _dec(_cell(row, m.get("unit_price")), "单价")
            amount = _dec(_cell(row, m.get("amount")), "金额")
            if amount is None and qty is not None and unit_price is not None:
                amount = qty * unit_price
            db.add(
                EqSpare(
                    asset_id=asset.id,
                    part_name=part_name,
                    model=_str(_cell(row, m.get("model"))),
                    origin_type=_str(_cell(row, m.get("origin_type"))),
                    replace_date=_to_date(_cell(row, m.get("replace_date"))),
                    reason=_str(_cell(row, m.get("reason"))),
                    qty=qty,
                    unit_price=unit_price,
                    amount=amount,
                    supplier=_str(_cell(row, m.get("supplier"))),
                    old_disposal=_str(_cell(row, m.get("old_disposal"))),
                    executor=_str(_cell(row, m.get("executor"))),
                    remark=_str(_cell(row, m.get("remark"))),
                )
            )
            db.commit()  # 逐行提交：坏行 rollback 时不会带走前面已成功的行
            created += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            detail = getattr(exc, "detail", None)
            reason = detail.get("message") if isinstance(detail, dict) else str(exc)
            errors.append(EqImportError(row=offset, reason=reason))
    db.commit()
    write_audit(
        db, request=request, user=user,
        action="eq.import.spares", target_type="eq_import",
        summary=f"导入备件更换台账：成功 {created} 行 / 失败 {len(errors)} 行",
    )
    db.commit()
    return Envelope(data=_result(len(rows), created, errors))


@router.get("/import-template", summary="下载导入模板（5 张表各一个 sheet）")
def download_template(user: User = Depends(require_internal)):
    """按导出格式提供空模板：只写表头，直接填数据即可导入。"""
    wb = Workbook()
    sheets = [
        (
            "设备主台账",
            [
                "台账编号", "资产编号", "设备名称", "规格型号", "设备类别", "重要等级",
                "是否特种设备", "特种设备登记号", "安装地点/站点", "所属系统", "投用日期",
                "质保起始日", "质保到期日", "设计使用年限(年)", "预计报废日期", "采购原值(元)",
                "供应商", "当前状态", "属地责任人", "备注",
            ],
        ),
        (
            "设备动态事件台账",
            [
                "台账编号", "事件类型", "事件发生日期", "计划完成日期", "实际完成日期", "提报人",
                "事件简述内容", "执行单位/执行人", "相关证书/报告编号", "费用(元)", "验收结论",
                "验收人", "验收日期", "附件存储路径", "整改措施", "备注",
            ],
        ),
        (
            "计量器具检定台账",
            [
                "台账编号", "器具名称", "规格型号", "精度等级", "是否强检", "检定周期(月)",
                "上次检定日期", "证书编号", "有效期至", "检定机构", "状态", "责任人", "备注",
            ],
        ),
        (
            "特种设备定期检验台账",
            [
                "台账编号", "设备名称", "注册编号", "检验类型", "检验周期(月)", "上次检验日期",
                "报告编号", "有效期至", "检验机构", "状态", "责任人", "备注",
            ],
        ),
        (
            "备件更换明细台账",
            [
                "台账编号", "备件名称", "规格型号", "原厂/替代件", "更换时间", "更换原因",
                "更换数量", "单价(元)", "金额(元)", "供应商", "换下旧件处置", "执行人", "备注",
            ],
        ),
    ]
    first = True
    for title, headers in sheets:
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        first = False
        _write_header(ws, headers)
        _widths(ws, tuple(20 for _ in headers))
        ws.freeze_panes = "A2"
    return _xlsx(
        wb,
        f"设备台账导入模板_{_today().strftime('%Y%m%d')}.xlsx",
        f"eq-import-template-{_today().strftime('%Y%m%d')}.xlsx",
    )
