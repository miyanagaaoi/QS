"""设备管理接口（CH-014）：设备全生命周期台账。

| 资源 | 接口 |
|---|---|
| 字典 | `GET /meta` |
| 主台账 | `GET/POST /assets`、`GET/PUT/DELETE /assets/{id}` |
| 动态事件 | `GET/POST /events`、`PUT/DELETE /events/{id}` |
| 计量检定 | `GET/POST /meters`、`PUT/DELETE /meters/{id}` |
| 特种检验 | `GET/POST /specials`、`PUT/DELETE /specials/{id}` |
| 备件更换 | `GET/POST /spares`、`PUT/DELETE /spares/{id}` |
| 统计看板 | `GET /board` |
| 导入导出 | 见 `api/eq_io.py`（`/export`、`/import`） |

权限：`require_internal`（管理员 + 采购员）；供货商 403。
与采购报价、项目管理模块**完全独立**，不引用任何 rfq/pm 数据。
子台账通过 `asset_id` 强关联主台账：删除设备前必须先清掉子记录（返回 409 提示）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_internal, write_audit
from ..eq_models import (
    EQ_ACCEPT_RESULT,
    EQ_ASSET_STATUS,
    EQ_CHECK_TYPES,
    EQ_CHECK_WARN_DAYS,
    EQ_EVENT_TYPES,
    EQ_IMPORTANCE,
    EQ_METER_STATUS,
    EQ_OLD_PART_DISPOSAL,
    EQ_PART_ORIGIN,
    EQ_PLAN_WARN_DAYS,
    EQ_SPECIAL_STATUS,
    EQ_WARRANTY_WARN_DAYS,
    EqAsset,
    EqEvent,
    EqMeter,
    EqSpare,
    EqSpecial,
)
from ..eq_schemas import (
    EqAssetDetail,
    EqAssetIn,
    EqAssetOut,
    EqBoardOut,
    EqCountItem,
    EqEventIn,
    EqEventOut,
    EqMeterIn,
    EqMeterOut,
    EqSpareIn,
    EqSpareOut,
    EqSpecialIn,
    EqSpecialOut,
    EqWarnItem,
)
from ..models import User, app_now
from ..schemas import Envelope, PageData, PageMeta

router = APIRouter()


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _err(status: int, code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _dec(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # noqa: TRY003
        raise _err(400, 40001, f"{field}：请输入数字") from exc


def _str(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _fmt(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _check_range(start: date | None, end: date | None, label: str) -> None:
    """结束日期不能早于开始日期（质保期、检定/检验有效期、事件完成日期）。"""
    if start and end and end < start:
        raise _err(400, 40001, f"{label}：结束日期不能早于开始日期")


def _days_until(target: date | None, today: date) -> int | None:
    return (target - today).days if target else None


def _expire_status(days: int | None) -> str | None:
    if days is None:
        return None
    if days < 0:
        return "overdue"
    if days <= EQ_CHECK_WARN_DAYS:
        return "warn"
    return "ok"


def _warranty_status(days: int | None) -> str | None:
    """质保预警状态（模板：≤30 天橙、<0 红）。"""
    if days is None:
        return None
    if days < 0:
        return "overdue"
    if days <= EQ_WARRANTY_WARN_DAYS:
        return "warn"
    return "ok"


# --------------------------------------------------------------------------
# 输出构造
# --------------------------------------------------------------------------
def _asset_out(row: EqAsset, today: date, counts: dict[str, int] | None = None) -> EqAssetOut:
    data = EqAssetOut.model_validate(row)
    data.days_to_warranty = _days_until(row.warranty_end, today)
    if counts:
        data.event_count = counts.get("events", 0)
        data.meter_count = counts.get("meters", 0)
        data.special_count = counts.get("specials", 0)
        data.spare_count = counts.get("spares", 0)
    return data


def _event_out(row: EqEvent, today: date) -> EqEventOut:
    asset = row.asset
    days = _days_until(row.plan_date, today)
    return EqEventOut(
        id=row.id,
        asset_id=row.asset_id,
        asset_no=asset.asset_no if asset else None,
        asset_name=asset.name if asset else None,
        event_type=row.event_type,
        occur_date=row.occur_date,
        plan_date=row.plan_date,
        actual_date=row.actual_date,
        reporter=row.reporter,
        content=row.content,
        executor=row.executor,
        cert_no=row.cert_no,
        cost=_fmt(row.cost),
        accept_result=row.accept_result,
        acceptor=row.acceptor,
        accept_date=row.accept_date,
        attachment_path=row.attachment_path,
        corrective=row.corrective,
        remark=row.remark,
        created_at=row.created_at,
        days_to_plan=days,
        plan_overdue=bool(days is not None and days < 0 and row.actual_date is None),
    )


def _meter_out(row: EqMeter, today: date) -> EqMeterOut:
    asset = row.asset
    days = _days_until(row.valid_until, today)
    return EqMeterOut(
        id=row.id,
        asset_id=row.asset_id,
        asset_no=asset.asset_no if asset else None,
        asset_name=asset.name if asset else None,
        name=row.name,
        model=row.model,
        accuracy=row.accuracy,
        is_mandatory=row.is_mandatory,
        cycle_months=row.cycle_months,
        last_check_date=row.last_check_date,
        cert_no=row.cert_no,
        valid_until=row.valid_until,
        org=row.org,
        status=row.status,
        owner=row.owner,
        remark=row.remark,
        created_at=row.created_at,
        days_to_expire=days,
        expire_status=_expire_status(days),
    )


def _special_out(row: EqSpecial, today: date) -> EqSpecialOut:
    asset = row.asset
    days = _days_until(row.valid_until, today)
    return EqSpecialOut(
        id=row.id,
        asset_id=row.asset_id,
        asset_no=asset.asset_no if asset else None,
        asset_name=asset.name if asset else None,
        name=row.name,
        reg_no=row.reg_no,
        check_type=row.check_type,
        cycle_months=row.cycle_months,
        last_check_date=row.last_check_date,
        report_no=row.report_no,
        valid_until=row.valid_until,
        org=row.org,
        status=row.status,
        owner=row.owner,
        remark=row.remark,
        created_at=row.created_at,
        days_to_expire=days,
        expire_status=_expire_status(days),
    )


def _spare_out(row: EqSpare) -> EqSpareOut:
    asset = row.asset
    return EqSpareOut(
        id=row.id,
        asset_id=row.asset_id,
        asset_no=asset.asset_no if asset else None,
        asset_name=asset.name if asset else None,
        part_name=row.part_name,
        model=row.model,
        origin_type=row.origin_type,
        replace_date=row.replace_date,
        reason=row.reason,
        qty=_fmt(row.qty),
        unit_price=_fmt(row.unit_price),
        amount=_fmt(row.amount),
        supplier=row.supplier,
        old_disposal=row.old_disposal,
        executor=row.executor,
        remark=row.remark,
        created_at=row.created_at,
    )


# --------------------------------------------------------------------------
# 字典
# --------------------------------------------------------------------------
@router.get("/meta", summary="设备管理字典（下拉选项与预警阈值）")
def eq_meta(user: User = Depends(require_internal)):
    return Envelope(
        data={
            "importance": list(EQ_IMPORTANCE),
            "asset_status": list(EQ_ASSET_STATUS),
            "event_types": list(EQ_EVENT_TYPES),
            "accept_results": list(EQ_ACCEPT_RESULT),
            "meter_status": list(EQ_METER_STATUS),
            "check_types": list(EQ_CHECK_TYPES),
            "special_status": list(EQ_SPECIAL_STATUS),
            "part_origins": list(EQ_PART_ORIGIN),
            "old_part_disposals": list(EQ_OLD_PART_DISPOSAL),
            "warranty_warn_days": EQ_WARRANTY_WARN_DAYS,
            "check_warn_days": EQ_CHECK_WARN_DAYS,
            "plan_warn_days": EQ_PLAN_WARN_DAYS,
        }
    )


# --------------------------------------------------------------------------
# 主台账
# --------------------------------------------------------------------------
@router.get("/assets", summary="设备台账列表")
def list_assets(
    keyword: str | None = Query(None, description="台账编号/资产编号/名称/地点/责任人"),
    status: str | None = Query(None),
    category: str | None = Query(None),
    importance: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    today = app_now().date()
    stmt = select(EqAsset)
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                EqAsset.asset_no.like(like),
                EqAsset.finance_no.like(like),
                EqAsset.name.like(like),
                EqAsset.location.like(like),
                EqAsset.owner.like(like),
            )
        )
    if status:
        stmt = stmt.where(EqAsset.status == status)
    if category:
        stmt = stmt.where(EqAsset.category == category)
    if importance:
        stmt = stmt.where(EqAsset.importance == importance)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(EqAsset.asset_no).offset((page - 1) * page_size).limit(page_size)
    ).all()
    ids = [r.id for r in rows]
    counts: dict[int, dict[str, int]] = {i: {} for i in ids}
    if ids:
        for key, model in (
            ("events", EqEvent),
            ("meters", EqMeter),
            ("specials", EqSpecial),
            ("spares", EqSpare),
        ):
            for asset_id, cnt in db.execute(
                select(model.asset_id, func.count()).where(model.asset_id.in_(ids)).group_by(model.asset_id)
            ).all():
                counts.setdefault(asset_id, {})[key] = cnt
    items = [_asset_out(r, today, counts.get(r.id)) for r in rows]
    return Envelope(data=PageData(items=items, meta=PageMeta(page=page, page_size=page_size, total=total)))


@router.get("/assets/{asset_id}", response_model=None, summary="设备台账详情（含四类子记录）")
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    today = app_now().date()
    row = db.get(EqAsset, asset_id)
    if row is None:
        raise _err(404, 40400, "设备不存在")
    base = _asset_out(
        row,
        today,
        {
            "events": len(row.events),
            "meters": len(row.meters),
            "specials": len(row.specials),
            "spares": len(row.spares),
        },
    )
    detail = EqAssetDetail(
        **base.model_dump(),
        events=[_event_out(r, today) for r in sorted(row.events, key=lambda x: x.id, reverse=True)],
        meters=[_meter_out(r, today) for r in row.meters],
        specials=[_special_out(r, today) for r in row.specials],
        spares=[_spare_out(r) for r in sorted(row.spares, key=lambda x: x.id, reverse=True)],
    )
    return Envelope(data=detail)


def _apply_asset(row: EqAsset, payload: EqAssetIn) -> None:
    row.asset_no = payload.asset_no.strip()
    row.finance_no = _str(payload.finance_no)
    row.name = payload.name.strip()
    row.model = _str(payload.model)
    row.category = _str(payload.category)
    row.importance = _str(payload.importance)
    row.is_special = bool(payload.is_special)
    row.special_reg_no = _str(payload.special_reg_no)
    row.location = _str(payload.location)
    row.system_name = _str(payload.system_name)
    row.commission_date = payload.commission_date
    row.warranty_start = payload.warranty_start
    row.warranty_end = payload.warranty_end
    row.design_life_years = payload.design_life_years
    row.scrap_date = payload.scrap_date
    row.purchase_value = _dec(payload.purchase_value, "采购原值")
    row.supplier = _str(payload.supplier)
    row.status = payload.status or "在用"
    row.owner = _str(payload.owner)
    row.remark = _str(payload.remark)


@router.post("/assets", summary="新增设备")
def create_asset(
    payload: EqAssetIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    _check_range(payload.warranty_start, payload.warranty_end, "质保期")
    if db.scalar(select(func.count()).select_from(EqAsset).where(EqAsset.asset_no == payload.asset_no.strip())):
        raise _err(409, 40900, "台账编号已存在")
    if payload.is_special and not _str(payload.special_reg_no):
        raise _err(400, 40001, "特种设备必须填写特种设备登记号")
    row = EqAsset(created_by=user.id)
    _apply_asset(row, payload)
    db.add(row)
    db.flush()
    write_audit(
        db, request=request, user=user,
        action="eq.asset.create", target_type="eq_asset", target_id=row.id,
        summary=f"设备建档 {row.asset_no} {row.name}（状态={row.status}）",
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_asset_out(row, app_now().date()))


@router.put("/assets/{asset_id}", summary="修改设备")
def update_asset(
    asset_id: int,
    payload: EqAssetIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(EqAsset, asset_id)
    if row is None:
        raise _err(404, 40400, "设备不存在")
    _check_range(payload.warranty_start, payload.warranty_end, "质保期")
    dup = db.scalar(
        select(func.count())
        .select_from(EqAsset)
        .where(EqAsset.asset_no == payload.asset_no.strip(), EqAsset.id != asset_id)
    )
    if dup:
        raise _err(409, 40900, "台账编号已存在")
    if payload.is_special and not _str(payload.special_reg_no):
        raise _err(400, 40001, "特种设备必须填写特种设备登记号")
    old_status = row.status
    _apply_asset(row, payload)
    row.updated_at = app_now()
    write_audit(
        db, request=request, user=user,
        action="eq.asset.update", target_type="eq_asset", target_id=row.id,
        summary=f"修改设备 {row.asset_no} {row.name}"
        + (f"（状态 {old_status} → {row.status}）" if old_status != row.status else ""),
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_asset_out(row, app_now().date()))


@router.delete("/assets/{asset_id}", summary="删除设备（有子记录时禁止）")
def delete_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(EqAsset, asset_id)
    if row is None:
        raise _err(404, 40400, "设备不存在")
    children = {
        "动态事件": len(row.events),
        "计量检定": len(row.meters),
        "特种检验": len(row.specials),
        "备件更换": len(row.spares),
    }
    used = {k: v for k, v in children.items() if v}
    if used:
        detail = "、".join(f"{k} {v} 条" for k, v in used.items())
        raise _err(409, 40900, f"该设备还有子台账记录（{detail}），请先删除子记录再删设备")
    asset_no, name = row.asset_no, row.name
    db.delete(row)
    write_audit(
        db, request=request, user=user,
        action="eq.asset.delete", target_type="eq_asset", target_id=asset_id,
        summary=f"删除设备 {asset_no} {name}",
    )
    db.commit()
    return Envelope(data={"deleted": asset_id})


# --------------------------------------------------------------------------
# 子台账通用工具
# --------------------------------------------------------------------------
def _ensure_asset(db: Session, asset_id: int) -> EqAsset:
    asset = db.get(EqAsset, asset_id)
    if asset is None:
        raise _err(400, 40001, "所选设备不存在")
    return asset


def _child_counts(db: Session, model, asset_id: int | None, extra=None) -> int:
    stmt = select(func.count()).select_from(model)
    if asset_id:
        stmt = stmt.where(model.asset_id == asset_id)
    if extra is not None:
        stmt = stmt.where(extra)
    return db.scalar(stmt) or 0


# --------------------------------------------------------------------------
# 动态事件
# --------------------------------------------------------------------------
@router.get("/events", summary="设备动态事件列表")
def list_events(
    asset_id: int | None = Query(None),
    event_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    today = app_now().date()
    stmt = select(EqEvent)
    if asset_id:
        stmt = stmt.where(EqEvent.asset_id == asset_id)
    if event_type:
        stmt = stmt.where(EqEvent.event_type == event_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(EqEvent.occur_date.desc().nullslast(), EqEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Envelope(
        data=PageData(
            items=[_event_out(r, today) for r in rows],
            meta=PageMeta(page=page, page_size=page_size, total=total),
        )
    )


def _apply_event(row: EqEvent, payload: EqEventIn) -> None:
    _check_range(payload.occur_date, payload.actual_date, "事件实际完成")
    row.asset_id = payload.asset_id
    row.event_type = payload.event_type
    row.occur_date = payload.occur_date
    row.plan_date = payload.plan_date
    row.actual_date = payload.actual_date
    row.reporter = _str(payload.reporter)
    row.content = _str(payload.content)
    row.executor = _str(payload.executor)
    row.cert_no = _str(payload.cert_no)
    row.cost = _dec(payload.cost, "费用")
    row.accept_result = _str(payload.accept_result)
    row.acceptor = _str(payload.acceptor)
    row.accept_date = payload.accept_date
    row.attachment_path = _str(payload.attachment_path)
    row.corrective = _str(payload.corrective)
    row.remark = _str(payload.remark)


@router.post("/events", summary="新增动态事件")
def create_event(
    payload: EqEventIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    _ensure_asset(db, payload.asset_id)
    row = EqEvent()
    _apply_event(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_event_out(row, app_now().date()))


@router.put("/events/{item_id}", summary="修改动态事件")
def update_event(
    item_id: int,
    payload: EqEventIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(EqEvent, item_id)
    if row is None:
        raise _err(404, 40400, "事件不存在")
    _ensure_asset(db, payload.asset_id)
    _apply_event(row, payload)
    db.commit()
    db.refresh(row)
    return Envelope(data=_event_out(row, app_now().date()))


@router.delete("/events/{item_id}", summary="删除动态事件")
def delete_event(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_internal)):
    row = db.get(EqEvent, item_id)
    if row is None:
        raise _err(404, 40400, "事件不存在")
    db.delete(row)
    db.commit()
    return Envelope(data={"deleted": item_id})


# --------------------------------------------------------------------------
# 计量器具检定
# --------------------------------------------------------------------------
@router.get("/meters", summary="计量器具检定列表")
def list_meters(
    asset_id: int | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    today = app_now().date()
    stmt = select(EqMeter)
    if asset_id:
        stmt = stmt.where(EqMeter.asset_id == asset_id)
    if status:
        stmt = stmt.where(EqMeter.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(EqMeter.valid_until.asc().nullslast(), EqMeter.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Envelope(
        data=PageData(
            items=[_meter_out(r, today) for r in rows],
            meta=PageMeta(page=page, page_size=page_size, total=total),
        )
    )


def _apply_meter(row: EqMeter, payload: EqMeterIn) -> None:
    _check_range(payload.last_check_date, payload.valid_until, "检定有效期")
    row.asset_id = payload.asset_id
    row.name = payload.name.strip()
    row.model = _str(payload.model)
    row.accuracy = _str(payload.accuracy)
    row.is_mandatory = bool(payload.is_mandatory)
    row.cycle_months = payload.cycle_months
    row.last_check_date = payload.last_check_date
    row.cert_no = _str(payload.cert_no)
    row.valid_until = payload.valid_until
    row.org = _str(payload.org)
    row.status = payload.status or "在用"
    row.owner = _str(payload.owner)
    row.remark = _str(payload.remark)


@router.post("/meters", summary="新增计量器具检定记录")
def create_meter(
    payload: EqMeterIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    _ensure_asset(db, payload.asset_id)
    row = EqMeter()
    _apply_meter(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_meter_out(row, app_now().date()))


@router.put("/meters/{item_id}", summary="修改计量器具检定记录")
def update_meter(
    item_id: int,
    payload: EqMeterIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(EqMeter, item_id)
    if row is None:
        raise _err(404, 40400, "检定记录不存在")
    _ensure_asset(db, payload.asset_id)
    _apply_meter(row, payload)
    db.commit()
    db.refresh(row)
    return Envelope(data=_meter_out(row, app_now().date()))


@router.delete("/meters/{item_id}", summary="删除计量器具检定记录")
def delete_meter(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_internal)):
    row = db.get(EqMeter, item_id)
    if row is None:
        raise _err(404, 40400, "检定记录不存在")
    db.delete(row)
    db.commit()
    return Envelope(data={"deleted": item_id})


# --------------------------------------------------------------------------
# 特种设备定期检验
# --------------------------------------------------------------------------
@router.get("/specials", summary="特种设备检验列表")
def list_specials(
    asset_id: int | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    today = app_now().date()
    stmt = select(EqSpecial)
    if asset_id:
        stmt = stmt.where(EqSpecial.asset_id == asset_id)
    if status:
        stmt = stmt.where(EqSpecial.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(EqSpecial.valid_until.asc().nullslast(), EqSpecial.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Envelope(
        data=PageData(
            items=[_special_out(r, today) for r in rows],
            meta=PageMeta(page=page, page_size=page_size, total=total),
        )
    )


def _apply_special(row: EqSpecial, payload: EqSpecialIn) -> None:
    _check_range(payload.last_check_date, payload.valid_until, "检验有效期")
    row.asset_id = payload.asset_id
    row.name = _str(payload.name)
    row.reg_no = _str(payload.reg_no)
    row.check_type = payload.check_type
    row.cycle_months = payload.cycle_months
    row.last_check_date = payload.last_check_date
    row.report_no = _str(payload.report_no)
    row.valid_until = payload.valid_until
    row.org = _str(payload.org)
    row.status = payload.status or "在用"
    row.owner = _str(payload.owner)
    row.remark = _str(payload.remark)


@router.post("/specials", summary="新增特种设备检验记录")
def create_special(
    payload: EqSpecialIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    _ensure_asset(db, payload.asset_id)
    row = EqSpecial()
    _apply_special(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_special_out(row, app_now().date()))


@router.put("/specials/{item_id}", summary="修改特种设备检验记录")
def update_special(
    item_id: int,
    payload: EqSpecialIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(EqSpecial, item_id)
    if row is None:
        raise _err(404, 40400, "检验记录不存在")
    _ensure_asset(db, payload.asset_id)
    _apply_special(row, payload)
    db.commit()
    db.refresh(row)
    return Envelope(data=_special_out(row, app_now().date()))


@router.delete("/specials/{item_id}", summary="删除特种设备检验记录")
def delete_special(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_internal)):
    row = db.get(EqSpecial, item_id)
    if row is None:
        raise _err(404, 40400, "检验记录不存在")
    db.delete(row)
    db.commit()
    return Envelope(data={"deleted": item_id})


# --------------------------------------------------------------------------
# 备件更换
# --------------------------------------------------------------------------
@router.get("/spares", summary="备件更换列表")
def list_spares(
    asset_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    stmt = select(EqSpare)
    if asset_id:
        stmt = stmt.where(EqSpare.asset_id == asset_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(EqSpare.replace_date.desc().nullslast(), EqSpare.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Envelope(
        data=PageData(
            items=[_spare_out(r) for r in rows],
            meta=PageMeta(page=page, page_size=page_size, total=total),
        )
    )


def _apply_spare(row: EqSpare, payload: EqSpareIn) -> None:
    row.asset_id = payload.asset_id
    row.part_name = payload.part_name.strip()
    row.model = _str(payload.model)
    row.origin_type = _str(payload.origin_type)
    row.replace_date = payload.replace_date
    row.reason = _str(payload.reason)
    row.qty = _dec(payload.qty, "更换数量")
    row.unit_price = _dec(payload.unit_price, "单价")
    row.amount = _dec(payload.amount, "金额")
    if row.amount is None and row.qty is not None and row.unit_price is not None:
        row.amount = row.qty * row.unit_price
    row.supplier = _str(payload.supplier)
    row.old_disposal = _str(payload.old_disposal)
    row.executor = _str(payload.executor)
    row.remark = _str(payload.remark)


@router.post("/spares", summary="新增备件更换记录")
def create_spare(
    payload: EqSpareIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    _ensure_asset(db, payload.asset_id)
    row = EqSpare()
    _apply_spare(row, payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_spare_out(row))


@router.put("/spares/{item_id}", summary="修改备件更换记录")
def update_spare(
    item_id: int,
    payload: EqSpareIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(EqSpare, item_id)
    if row is None:
        raise _err(404, 40400, "备件记录不存在")
    _ensure_asset(db, payload.asset_id)
    _apply_spare(row, payload)
    db.commit()
    db.refresh(row)
    return Envelope(data=_spare_out(row))


@router.delete("/spares/{item_id}", summary="删除备件更换记录")
def delete_spare(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_internal)):
    row = db.get(EqSpare, item_id)
    if row is None:
        raise _err(404, 40400, "备件记录不存在")
    db.delete(row)
    db.commit()
    return Envelope(data={"deleted": item_id})


# --------------------------------------------------------------------------
# 统计看板
# --------------------------------------------------------------------------
@router.get("/board", summary="设备管理统计看板")
def eq_board(db: Session = Depends(get_db), user: User = Depends(require_internal)):
    today = app_now().date()
    total = db.scalar(select(func.count()).select_from(EqAsset)) or 0

    def _ratio(count: int) -> float:
        return round(count / total, 4) if total else 0.0

    status_rows = dict(
        db.execute(select(EqAsset.status, func.count()).group_by(EqAsset.status)).all()
    )
    by_status = [
        EqCountItem(label=s, count=status_rows.get(s, 0), ratio=_ratio(status_rows.get(s, 0)))
        for s in EQ_ASSET_STATUS
    ]
    importance_rows = dict(
        db.execute(select(EqAsset.importance, func.count()).group_by(EqAsset.importance)).all()
    )
    by_importance = [
        EqCountItem(
            label=f"{i} 类设备",
            count=importance_rows.get(i, 0),
            ratio=_ratio(importance_rows.get(i, 0)),
        )
        for i in EQ_IMPORTANCE
    ]

    assets = db.scalars(select(EqAsset)).all()
    warranty_warn = warranty_over = 0
    for a in assets:
        days = _days_until(a.warranty_end, today)
        st = _warranty_status(days)
        if st == "warn":
            warranty_warn += 1
        elif st == "overdue":
            warranty_over += 1

    meter_rows = db.scalars(select(EqMeter)).all()
    meter_warn = meter_over = 0
    for m in meter_rows:
        st = _expire_status(_days_until(m.valid_until, today))
        if st == "warn":
            meter_warn += 1
        elif st == "overdue":
            meter_over += 1

    special_rows = db.scalars(select(EqSpecial)).all()
    special_warn = special_over = 0
    for s in special_rows:
        st = _expire_status(_days_until(s.valid_until, today))
        if st == "warn":
            special_warn += 1
        elif st == "overdue":
            special_over += 1

    event_rows = db.scalars(select(EqEvent)).all()
    plan_overdue = 0
    for e in event_rows:
        days = _days_until(e.plan_date, today)
        if days is not None and days < 0 and e.actual_date is None:
            plan_overdue += 1
    this_year = app_now().year
    events_this_year = sum(1 for e in event_rows if e.occur_date and e.occur_date.year == this_year)

    event_type_rows = dict(
        db.execute(select(EqEvent.event_type, func.count()).group_by(EqEvent.event_type)).all()
    )
    event_total = len(event_rows)
    by_event_type = [
        EqCountItem(label=t, count=event_type_rows.get(t, 0), ratio=(
            round(event_type_rows.get(t, 0) / event_total, 4) if event_total else 0.0
        ))
        for t in EQ_EVENT_TYPES
    ]

    return Envelope(
        data=EqBoardOut(
            total=total,
            by_status=by_status,
            by_importance=by_importance,
            warnings=[
                EqWarnItem(label=f"质保 {EQ_WARRANTY_WARN_DAYS} 天内到期", count=warranty_warn, action="联系供应商履约"),
                EqWarnItem(label="质保已超期", count=warranty_over, action="转自费维保"),
                EqWarnItem(label=f"计量检定 {EQ_CHECK_WARN_DAYS} 天内到期", count=meter_warn, action="安排送检"),
                EqWarnItem(label="计量检定已超期", count=meter_over, action="立即停用送检"),
                EqWarnItem(label=f"特种设备检验 {EQ_CHECK_WARN_DAYS} 天内到期", count=special_warn, action="报检并准备资料"),
                EqWarnItem(label="特种设备检验已超期", count=special_over, action="停用整改、限期报检"),
                EqWarnItem(label="动态事件逾期未完成", count=plan_overdue, action="催办并说明原因"),
            ],
            event_total=event_total,
            by_event_type=by_event_type,
            events_this_year=events_this_year,
        )
    )
