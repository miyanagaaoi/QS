"""字典与主数据公共接口（PRD 7.5 / FR-MST-01~03）。

供「询价单新建/编辑」等页面拉取下拉选项：
- GET /units     启用的计量单位
- GET /taxes     启用的税率（含 is_default）
- GET /suppliers 供货商档案（默认只返回启用档案）

权限：require_internal（管理员 + 采购员）。字典的增改在 /api/admin/* 下。
所有接口成功统一 Envelope 包装，失败统一 {"code":..,"message":..}。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_internal
from ..models import Supplier, TaxDict, UnitDict, User
from ..schemas import Envelope, TaxOut, UnitOut

router = APIRouter()


class MetaSupplierOut(BaseModel):
    """供货商档案精简视图（选择受邀供货商用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: int
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


@router.get("/units", response_model=Envelope[list[UnitOut]], summary="启用中的计量单位")
def list_units(
    db: Session = Depends(get_db),
    _: User = Depends(require_internal),
):
    rows = db.scalars(
        select(UnitDict).where(UnitDict.status == 1).order_by(UnitDict.sort.asc(), UnitDict.id.asc())
    ).all()
    return Envelope(data=list(rows))


@router.get("/taxes", response_model=Envelope[list[TaxOut]], summary="启用中的税率")
def list_taxes(
    db: Session = Depends(get_db),
    _: User = Depends(require_internal),
):
    rows = db.scalars(
        select(TaxDict).where(TaxDict.status == 1).order_by(TaxDict.sort.asc(), TaxDict.id.asc())
    ).all()
    return Envelope(data=list(rows))


@router.get("/suppliers", response_model=Envelope[list[MetaSupplierOut]], summary="供货商档案列表")
def list_suppliers(
    include_disabled: bool = Query(False, description="是否包含已停用档案，默认仅返回启用档案"),
    db: Session = Depends(get_db),
    _: User = Depends(require_internal),
):
    stmt = select(Supplier)
    if not include_disabled:
        stmt = stmt.where(Supplier.status == 1)
    rows = db.scalars(stmt.order_by(Supplier.id.asc())).all()
    return Envelope(data=list(rows))
