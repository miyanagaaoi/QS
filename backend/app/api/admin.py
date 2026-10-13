"""系统管理接口：我方账号、供货商账号（含批量导入）、供货商档案、字典、操作日志。

对应 PRD 5.4（页面 3 系统管理）与 FR-ACC-01~14 / FR-MST-01~04 / FR-LOG-01~04。

统一约定：
- 前缀 /api/admin，全部接口 require_admin（PRD 7.5）
- 成功统一 schemas.Envelope 包装；失败 HTTPException(detail={"code":..,"message":..})
  40001 参数校验失败 / 40400 资源不存在 / 40900 业务冲突
- 所有写操作调用 deps.write_audit 留痕（FR-LOG-01）
- 账号不可删除（FR-ACC-07）；操作日志只读，本模块**不提供任何 DELETE 路由**（FR-LOG-04）

已知限制（部署相关）：
- 批量导入的预校验结果（token -> 行数据）保存在**进程内存** `_IMPORT_TOKENS` 中，TTL 30 分钟、确认后即失效。
  当前 uvicorn 单 worker 部署下没有问题；若将来改为多 worker / 多实例部署，
  「上传预校验」与「确认导入」可能落到不同进程，必须把该缓存迁移到 Redis 或数据库表。
"""
from __future__ import annotations

import io
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, NamedTuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_admin, write_audit
from ..models import AuditLog, RfqLine, Supplier, TaxDict, UnitDict, User, app_now
from ..schemas import (
    AuditLogItem,
    Envelope,
    ImportErrorItem,
    InternalUserCreate,
    InternalUserUpdate,
    PageData,
    PageMeta,
    ResetPasswordRequest,
    SupplierAccountCreate,
    SupplierCreate,
    SupplierOut,
    SupplierUpdate,
    TaxIn,
    TaxOut,
    UnitIn,
    UnitOut,
    UserListItem,
)
from ..security import hash_password
from ..utils import page_offset, to_app_tz

router = APIRouter()

ROLE_ADMIN = "admin"
ROLE_BUYER = "buyer"
ROLE_SUPPLIER = "supplier"
INTERNAL_ROLES = (ROLE_ADMIN, ROLE_BUYER)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,20}$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
MOBILE_RE = re.compile(r"^1[3-9]\d{9}$")
LANDLINE_RE = re.compile(r"^0\d{2,3}-?\d{7,8}(-\d{1,6})?$")

# 批量导入预校验结果暂存（不落库）：token -> {created_at, rows, filename, operator_id}
_IMPORT_TTL_SECONDS = 30 * 60
_IMPORT_TOKENS: dict[str, dict[str, Any]] = {}

# 模板列定义（PRD FR-ACC-10）
TEMPLATE_HEADERS = ["供货商名称", "联系人", "联系电话", "邮箱", "地址", "登录账号", "初始密码"]
# 表头别名 -> 内部字段，容忍手工调整过的模板
HEADER_ALIASES: dict[str, str] = {
    "供货商名称": "supplier_name",
    "供应商名称": "supplier_name",
    "供货商": "supplier_name",
    "联系人": "contact_name",
    "联系电话": "contact_phone",
    "手机号": "contact_phone",
    "电话": "contact_phone",
    "邮箱": "contact_email",
    "电子邮箱": "contact_email",
    "e-mail": "contact_email",
    "email": "contact_email",
    "地址": "address",
    "登录账号": "username",
    "登录名": "username",
    "账号": "username",
    "初始密码": "initial_password",
    "密码": "initial_password",
}
REQUIRED_FIELDS = ("supplier_name", "contact_name", "contact_phone", "username", "initial_password")
FIELD_LABELS = {
    "supplier_name": "供货商名称",
    "contact_name": "联系人",
    "contact_phone": "联系电话",
    "contact_email": "邮箱",
    "address": "地址",
    "username": "登录账号",
    "initial_password": "初始密码",
}


# --------------------------------------------------------------------------
# 通用小工具
# --------------------------------------------------------------------------
def _err(http_status: int, code: int, message: str) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


def _conflict(message: str) -> HTTPException:
    return _err(409, 40900, message)


def _not_found(message: str = "资源不存在") -> HTTPException:
    return _err(404, 40400, message)


def _bad_request(message: str) -> HTTPException:
    return _err(400, 40001, message)


def _check_password_strength(pwd: str) -> None:
    """PRD FR-ACC-13：8~20 位，至少含字母与数字。"""
    if not (8 <= len(pwd) <= 20) or not any(c.isalpha() for c in pwd) or not any(c.isdigit() for c in pwd):
        raise _bad_request("密码需 8~20 位且至少包含字母与数字")


def _check_username(username: str) -> None:
    """PRD FR-ACC-02：4~20 位字母数字下划线。"""
    if not USERNAME_RE.match(username or ""):
        raise _bad_request("用户名需为 4~20 位字母、数字或下划线")


def _commit_or_conflict(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflict(message)


def _user_item(u: User) -> UserListItem:
    """我方/供货商账号列表统一视图（带档案联系信息快照）。"""
    s = u.supplier
    return UserListItem(
        id=u.id,
        username=u.username,
        real_name=u.real_name,
        role=u.role,
        status=u.status,
        supplier_id=u.supplier_id,
        supplier_name=s.name if s else None,
        contact_name=s.contact_name if s else None,
        contact_phone=s.contact_phone if s else None,
        contact_email=s.contact_email if s else None,
        must_change_password=u.must_change_password,
        last_login_at=u.last_login_at,
        created_at=u.created_at,
    )


def _enabled_admin_count(db: Session, exclude_id: int | None = None) -> int:
    """当前启用的管理员数量（可排除某个账号）。"""
    stmt = select(func.count()).select_from(User).where(User.role == ROLE_ADMIN, User.status == 1)
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return int(db.scalar(stmt) or 0)


def _guard_last_admin(
    db: Session,
    request: Request,
    operator: User,
    target: User,
    *,
    action: str,
    reason: str,
) -> None:
    """FR-ACC-06：停用/降级最后一个启用的管理员时拒绝，并留痕。"""
    if target.role != ROLE_ADMIN or target.status != 1:
        return
    if _enabled_admin_count(db, exclude_id=target.id) > 0:
        return
    write_audit(
        db,
        request=request,
        user=operator,
        action=action,
        target_type="user",
        target_id=target.id,
        summary=f"拒绝操作：{reason}（{target.username} 是最后一个启用的管理员）",
    )
    db.commit()
    raise _conflict(f"系统至少需保留一个启用的管理员账号，无法{reason}")


def _get_internal_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None or u.role not in INTERNAL_ROLES:
        raise _not_found("账号不存在")
    return u


def _get_supplier_account(db: Session, account_id: int) -> User:
    u = db.get(User, account_id)
    if u is None or u.role != ROLE_SUPPLIER:
        raise _not_found("供货商账号不存在")
    return u


# --------------------------------------------------------------------------
# A. 我方账号（FR-ACC-01~07）
# --------------------------------------------------------------------------
@router.get("/users", response_model=Envelope[PageData[UserListItem]], summary="我方账号列表")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, description="用户名或姓名模糊匹配"),
    role: Literal["admin", "buyer"] | None = Query(None),
    status: int | None = Query(None, ge=0, le=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    conds = [User.role.in_(INTERNAL_ROLES)]
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        conds.append(or_(User.username.like(kw), User.real_name.like(kw)))
    if role:
        conds.append(User.role == role)
    if status is not None:
        conds.append(User.status == status)

    total = int(db.scalar(select(func.count()).select_from(User).where(*conds)) or 0)
    offset, limit = page_offset(page, page_size)
    rows = db.scalars(
        select(User).where(*conds).order_by(User.id.asc()).offset(offset).limit(limit)
    ).all()
    return Envelope(
        data=PageData(
            items=[_user_item(u) for u in rows],
            meta=PageMeta(page=max(1, page), page_size=limit, total=total),
        )
    )


@router.post("/users", response_model=Envelope[UserListItem], summary="新建我方账号")
def create_user(
    payload: InternalUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-02：用户名唯一，初始密码强度校验。

    是否要求首次登录改密由请求参数 `must_change_password` 控制（需求变更 2026-10：**默认关闭**）。
    """
    username = payload.username.strip()
    _check_username(username)
    _check_password_strength(payload.initial_password)
    if db.scalar(select(User.id).where(User.username == username)):
        raise _conflict(f"用户名 {username} 已存在")

    user = User(
        username=username,
        password_hash=hash_password(payload.initial_password),
        real_name=(payload.real_name or "").strip() or None,
        role=payload.role,
        status=1,
        must_change_password=bool(payload.must_change_password),
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        request=request,
        user=admin,
        action="user.create",
        target_type="user",
        target_id=user.id,
        summary=(
            f"新建{'管理员' if user.role == ROLE_ADMIN else '采购员'}账号 {user.username}"
            + ("（要求首次登录改密）" if user.must_change_password else "")
        ),
    )
    _commit_or_conflict(db, f"用户名 {username} 已存在")
    db.refresh(user)
    return Envelope(message="账号创建成功", data=_user_item(user))


@router.put("/users/{user_id}", response_model=Envelope[UserListItem], summary="编辑我方账号（用户名不可改）")
def update_user(
    user_id: int,
    payload: InternalUserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-03：仅姓名、角色可改；把最后一个管理员降级为采购员同样拦截（FR-ACC-06）。"""
    user = _get_internal_user(db, user_id)
    data = payload.model_dump(exclude_unset=True)

    changes: list[str] = []
    if "real_name" in data:
        new_name = (data["real_name"] or "").strip() or None
        if new_name != user.real_name:
            changes.append(f"姓名 {user.real_name or '空'} → {new_name or '空'}")
            user.real_name = new_name
    if data.get("role") and data["role"] != user.role:
        if user.role == ROLE_ADMIN and data["role"] == ROLE_BUYER:
            _guard_last_admin(
                db, request, admin, user, action="user.update", reason="将最后一个启用的管理员降级为其他角色"
            )
        changes.append(f"角色 {user.role} → {data['role']}")
        user.role = data["role"]

    if not changes:
        return Envelope(message="无变更", data=_user_item(user))

    user.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=admin,
        action="user.update",
        target_type="user",
        target_id=user.id,
        summary=f"编辑账号 {user.username}：{'；'.join(changes)}",
    )
    _commit_or_conflict(db, "保存失败，请检查角色或姓名是否合法")
    db.refresh(user)
    return Envelope(message="保存成功", data=_user_item(user))


@router.post("/users/{user_id}/toggle-status", response_model=Envelope[UserListItem], summary="启用/停用我方账号")
def toggle_user_status(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-04/06：停用后已登录会话立即失效；禁止停用最后一个启用的管理员。"""
    user = _get_internal_user(db, user_id)
    if user.status == 1:
        _guard_last_admin(db, request, admin, user, action="user.toggle_status", reason="停用最后一个启用的管理员")
        user.status = 0
        action_word = "停用"
    else:
        user.status = 1
        action_word = "启用"

    user.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=admin,
        action="user.toggle_status",
        target_type="user",
        target_id=user.id,
        summary=f"{action_word}账号 {user.username}",
    )
    _commit_or_conflict(db, "状态更新失败")
    db.refresh(user)
    return Envelope(message=f"账号已{action_word}", data=_user_item(user))


@router.post(
    "/users/{user_id}/reset-password",
    response_model=Envelope[UserListItem],
    summary="重置我方账号密码",
)
def reset_user_password(
    user_id: int,
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-05：重置后 must_change_password=True，下次登录强制改密。

    说明：JWT 无状态，但 get_current_user 会对 must_change_password 的账号
    在非改密接口上返回 40101，因此重置后既有会话在业务接口上立即失效。
    """
    user = _get_internal_user(db, user_id)
    _check_password_strength(payload.new_password)
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = True
    user.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=admin,
        action="user.reset_password",
        target_type="user",
        target_id=user.id,
        summary=f"重置账号 {user.username} 的密码，已要求下次登录强制修改",
    )
    _commit_or_conflict(db, "密码重置失败")
    db.refresh(user)
    return Envelope(message="密码已重置，该账号下次登录需修改密码", data=_user_item(user))


# --------------------------------------------------------------------------
# D. 供货商档案（FR-MST-03/04）—— 放在字典前，供账号绑定使用
# --------------------------------------------------------------------------
def _supplier_out(s: Supplier, account_username: str | None) -> SupplierOut:
    return SupplierOut(
        id=s.id,
        name=s.name,
        credit_code=s.credit_code,
        contact_name=s.contact_name,
        contact_phone=s.contact_phone,
        contact_email=s.contact_email,
        address=s.address,
        remark=s.remark,
        status=s.status,
        account_bound=account_username is not None,
        account_username=account_username,
        created_at=s.created_at,
    )


@router.get("/suppliers", response_model=Envelope[PageData[SupplierOut]], summary="供货商档案列表")
def list_suppliers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, description="名称/联系人/电话模糊匹配"),
    status: int | None = Query(None, ge=0, le=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    conds = []
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        conds.append(
            or_(
                Supplier.name.like(kw),
                Supplier.contact_name.like(kw),
                Supplier.contact_phone.like(kw),
            )
        )
    if status is not None:
        conds.append(Supplier.status == status)

    total = int(db.scalar(select(func.count()).select_from(Supplier).where(*conds)) or 0)
    offset, limit = page_offset(page, page_size)
    rows = db.execute(
        select(Supplier, User.username)
        .outerjoin(User, and_(User.supplier_id == Supplier.id, User.role == ROLE_SUPPLIER))
        .where(*conds)
        .order_by(Supplier.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return Envelope(
        data=PageData(
            items=[_supplier_out(s, username) for s, username in rows],
            meta=PageMeta(page=max(1, page), page_size=limit, total=total),
        )
    )


@router.post("/suppliers", response_model=Envelope[SupplierOut], summary="新建供货商档案")
def create_supplier(
    payload: SupplierCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    name = payload.name.strip()
    if db.scalar(select(Supplier.id).where(Supplier.name == name)):
        raise _conflict(f"供货商档案「{name}」已存在")
    supplier = Supplier(
        name=name,
        credit_code=payload.credit_code,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        address=payload.address,
        remark=payload.remark,
        status=1,
    )
    db.add(supplier)
    db.flush()
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier.create",
        target_type="supplier",
        target_id=supplier.id,
        summary=f"新建供货商档案 {supplier.name}",
    )
    _commit_or_conflict(db, f"供货商档案「{name}」已存在")
    db.refresh(supplier)
    return Envelope(message="档案创建成功", data=_supplier_out(supplier, None))


@router.put("/suppliers/{supplier_id}", response_model=Envelope[SupplierOut], summary="编辑供货商档案")
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise _not_found("供货商档案不存在")

    data = payload.model_dump(exclude_unset=True)
    changes: list[str] = []
    if "name" in data and data["name"] is not None:
        new_name = data["name"].strip()
        if not new_name:
            raise _bad_request("供货商名称不能为空")
        if new_name != supplier.name:
            if db.scalar(select(Supplier.id).where(Supplier.name == new_name, Supplier.id != supplier.id)):
                raise _conflict(f"供货商档案「{new_name}」已存在")
            changes.append(f"名称 {supplier.name} → {new_name}")
            supplier.name = new_name
    for field in ("credit_code", "contact_name", "contact_phone", "contact_email", "address", "remark"):
        if field in data and data[field] != getattr(supplier, field):
            changes.append(field)
            setattr(supplier, field, data[field])

    if not changes:
        bound = db.scalar(select(User.username).where(User.supplier_id == supplier.id, User.role == ROLE_SUPPLIER))
        return Envelope(message="无变更", data=_supplier_out(supplier, bound))

    supplier.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier.update",
        target_type="supplier",
        target_id=supplier.id,
        summary=f"编辑供货商档案 {supplier.name}（{', '.join(changes)}）",
    )
    _commit_or_conflict(db, "保存失败，供货商名称可能已存在")
    db.refresh(supplier)
    bound = db.scalar(select(User.username).where(User.supplier_id == supplier.id, User.role == ROLE_SUPPLIER))
    return Envelope(message="保存成功", data=_supplier_out(supplier, bound))


@router.post("/suppliers/{supplier_id}/toggle-status", response_model=Envelope[SupplierOut], summary="启用/停用供货商档案")
def toggle_supplier_status(
    supplier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-MST-04：档案停用后其账号不可登录（同步停用绑定账号）；启用档案不自动启用账号。"""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise _not_found("供货商档案不存在")

    accounts = db.scalars(
        select(User).where(User.supplier_id == supplier.id, User.role == ROLE_SUPPLIER)
    ).all()

    if supplier.status == 1:
        supplier.status = 0
        action_word = "停用"
        disabled = 0
        for acc in accounts:
            if acc.status != 0:
                acc.status = 0
                acc.updated_at = app_now()
                disabled += 1
        extra = f"，同步停用 {disabled} 个绑定账号" if disabled else ""
    else:
        supplier.status = 1
        action_word = "启用"
        extra = "（绑定账号需单独启用）" if any(a.status == 0 for a in accounts) else ""

    supplier.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier.toggle_status",
        target_type="supplier",
        target_id=supplier.id,
        summary=f"{action_word}供货商档案 {supplier.name}{extra}",
    )
    _commit_or_conflict(db, "状态更新失败")
    db.refresh(supplier)
    bound = db.scalar(select(User.username).where(User.supplier_id == supplier.id, User.role == ROLE_SUPPLIER))
    return Envelope(message=f"档案已{action_word}{extra}", data=_supplier_out(supplier, bound))


# --------------------------------------------------------------------------
# B. 供货商账号（FR-ACC-08/09、FR-ACC-14 清单导出）
# --------------------------------------------------------------------------
def _supplier_account_conds(
    keyword: str | None, status: int | None, login_state: str | None
) -> list:
    """供货商账号列表与导出共用的筛选条件，保证两者口径一致。"""
    conds = [User.role == ROLE_SUPPLIER]
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        conds.append(
            or_(
                User.username.like(kw),
                User.real_name.like(kw),
                Supplier.name.like(kw),
                Supplier.contact_name.like(kw),
                Supplier.contact_phone.like(kw),
            )
        )
    if status is not None:
        conds.append(User.status == status)
    if login_state == "never":
        conds.append(User.last_login_at.is_(None))
    elif login_state == "logged":
        conds.append(User.last_login_at.is_not(None))
    return conds


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def _xlsx_attachment(ascii_stem: str, chinese_name: str) -> str:
    """附件文件名：同时给出 ASCII 回退名与 RFC 5987 的 UTF-8 中文名。"""
    # 用应用基准（北京时间）取"今天"，避免宿主时区导致跨日偏差
    today = app_now().strftime("%Y%m%d")
    ascii_name = f"{ascii_stem}_{today}.xlsx"
    utf8_name = quote(f"{chinese_name}_{today}.xlsx")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"


@router.get(
    "/supplier-accounts",
    response_model=Envelope[PageData[UserListItem]],
    summary="供货商账号列表",
)
def list_supplier_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, description="登录账号/供货商名称/联系人模糊匹配"),
    status: int | None = Query(None, ge=0, le=1),
    login_state: Literal["never", "logged"] | None = Query(
        None, description="never=未首次登录（last_login_at 为空）；logged=已登录过"
    ),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    conds = _supplier_account_conds(keyword, status, login_state)
    base = select(User).outerjoin(Supplier, User.supplier_id == Supplier.id).where(*conds)
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    offset, limit = page_offset(page, page_size)
    rows = (
        db.scalars(base.order_by(User.id.desc()).offset(offset).limit(limit))
        .unique()
        .all()
    )
    return Envelope(
        data=PageData(
            items=[_user_item(u) for u in rows],
            meta=PageMeta(page=max(1, page), page_size=limit, total=total),
        )
    )


@router.get("/supplier-accounts/export", summary="导出供货商账号清单（xlsx，不含密码）")
def export_supplier_accounts(
    request: Request,
    keyword: str | None = Query(None, description="登录账号/供货商名称/联系人模糊匹配"),
    status: int | None = Query(None, ge=0, le=1),
    login_state: Literal["never", "logged"] | None = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-14：导出供货商账号清单。

    安全红线：只查询并写出上表业务字段，**绝不查询/输出 password_hash 或明文密码**；
    查询列表里不含 User 实体，避免任何密码字段意外流入导出文件。
    """
    conds = _supplier_account_conds(keyword, status, login_state)
    rows = db.execute(
        select(
            Supplier.name,
            Supplier.contact_name,
            Supplier.contact_phone,
            Supplier.contact_email,
            Supplier.address,
            User.username,
            User.status,
            User.last_login_at,
            User.created_at,
        )
        .select_from(User)
        .outerjoin(Supplier, User.supplier_id == Supplier.id)
        .where(*conds)
        .order_by(User.id.asc())
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "供货商账号"
    ws.append(["供货商名称", "联系人", "联系电话", "邮箱", "地址", "登录账号", "状态", "最后登录时间", "创建时间"])
    for name, contact, phone, email, address, username, st, last_login, created in rows:
        ws.append(
            [
                name or "",
                contact or "",
                phone or "",
                email or "",
                address or "",
                username,
                "启用" if st == 1 else "停用",
                _fmt_dt(last_login),
                _fmt_dt(created),
            ]
        )
    for idx, width in enumerate([22, 12, 16, 26, 24, 18, 8, 20, 20], start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier_account.export",
        target_type="user",
        summary=(
            f"导出供货商账号清单 {len(rows)} 条（不含密码）"
            f"｜筛选：keyword={keyword or '-'} status={status if status is not None else '-'} "
            f"login_state={login_state or '-'}"
        ),
    )
    db.commit()

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": _xlsx_attachment("supplier_accounts", "供货商账号清单"),
            "Cache-Control": "no-store",
        },
    )


def _create_supplier_account(
    db: Session,
    *,
    supplier: Supplier | None,
    supplier_name: str | None,
    payload: SupplierAccountCreate,
    create_supplier: bool = True,
) -> tuple[User, bool]:
    """按 supplier_id 绑定已有档案，或按 supplier_name 复用/新建档案后绑定（FR-ACC-09 一对一）。

    返回 (账号, 是否新建档案)。
    """
    created_supplier = False
    if supplier is None:
        name = (supplier_name or "").strip()
        if not name:
            raise _bad_request("请选择供货商档案或填写供货商名称")
        supplier = db.scalar(select(Supplier).where(Supplier.name == name))
        if supplier is None:
            if not create_supplier:
                raise _bad_request(f"供货商档案「{name}」不存在")
            supplier = Supplier(
                name=name,
                credit_code=payload.credit_code,
                contact_name=payload.contact_name,
                contact_phone=payload.contact_phone,
                contact_email=payload.contact_email,
                address=payload.address,
                status=1,
            )
            db.add(supplier)
            db.flush()
            created_supplier = True

    existing = db.scalar(
        select(User).where(User.supplier_id == supplier.id, User.role == ROLE_SUPPLIER)
    )
    if existing is not None:
        raise _conflict(f"供货商档案「{supplier.name}」已绑定账号 {existing.username}（账号与档案一对一）")

    account = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.initial_password),
        real_name=payload.contact_name or supplier.contact_name,
        role=ROLE_SUPPLIER,
        supplier_id=supplier.id,
        status=1,
        # 需求变更 2026-10：是否要求首次登录改密改为按账号控制，默认关闭
        must_change_password=bool(payload.must_change_password),
    )
    db.add(account)
    db.flush()
    return account, created_supplier


@router.post(
    "/supplier-accounts",
    response_model=Envelope[UserListItem],
    summary="新建供货商账号（绑定已有档案或新建档案）",
)
def create_supplier_account(
    payload: SupplierAccountCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    _check_username(payload.username.strip())
    _check_password_strength(payload.initial_password)
    if db.scalar(select(User.id).where(User.username == payload.username.strip())):
        raise _conflict(f"用户名 {payload.username.strip()} 已存在")

    supplier = db.get(Supplier, payload.supplier_id) if payload.supplier_id else None
    if payload.supplier_id and supplier is None:
        raise _not_found("供货商档案不存在")

    account, created_supplier = _create_supplier_account(
        db, supplier=supplier, supplier_name=payload.supplier_name, payload=payload
    )
    summary = f"新建供货商账号 {account.username}，绑定档案 {account.supplier.name}"
    if created_supplier:
        summary += "（同时新建档案）"
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier_account.create",
        target_type="user",
        target_id=account.id,
        summary=summary,
    )
    _commit_or_conflict(db, "创建失败：用户名或供货商档案已存在")
    db.refresh(account)
    return Envelope(message="供货商账号创建成功", data=_user_item(account))


@router.post(
    "/supplier-accounts/{account_id}/toggle-status",
    response_model=Envelope[UserListItem],
    summary="启用/停用供货商账号",
)
def toggle_supplier_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    account = _get_supplier_account(db, account_id)
    if account.status == 1:
        account.status = 0
        action_word = "停用"
    else:
        account.status = 1
        action_word = "启用"
    account.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier_account.toggle_status",
        target_type="user",
        target_id=account.id,
        summary=f"{action_word}供货商账号 {account.username}",
    )
    _commit_or_conflict(db, "状态更新失败")
    db.refresh(account)
    return Envelope(message=f"账号已{action_word}", data=_user_item(account))


@router.post(
    "/supplier-accounts/{account_id}/reset-password",
    response_model=Envelope[UserListItem],
    summary="重置供货商账号密码",
)
def reset_supplier_account_password(
    account_id: int,
    payload: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    account = _get_supplier_account(db, account_id)
    _check_password_strength(payload.new_password)
    account.password_hash = hash_password(payload.new_password)
    account.must_change_password = True
    account.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier_account.reset_password",
        target_type="user",
        target_id=account.id,
        summary=f"重置供货商账号 {account.username} 的密码，已要求下次登录强制修改",
    )
    _commit_or_conflict(db, "密码重置失败")
    db.refresh(account)
    return Envelope(message="密码已重置，该账号下次登录需修改密码", data=_user_item(account))


# --------------------------------------------------------------------------
# C. 批量导入（FR-ACC-10~13）—— 先预校验不落库，确认后再落库
# --------------------------------------------------------------------------
class SupplierImportPreview(BaseModel):
    total: int
    valid: int
    invalid: int
    errors: list[ImportErrorItem] = Field(default_factory=list)
    token: str


class SupplierImportConfirmIn(BaseModel):
    token: str


class SupplierImportResult(BaseModel):
    success: int
    failed: int
    errors: list[ImportErrorItem] = Field(default_factory=list)


def _purge_import_tokens() -> None:
    deadline = time.time() - _IMPORT_TTL_SECONDS
    for key in [k for k, v in _IMPORT_TOKENS.items() if v["created_at"] < deadline]:
        _IMPORT_TOKENS.pop(key, None)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


@router.get("/supplier-accounts/import-template", summary="下载供货商账号批量导入模板（xlsx）")
def supplier_account_import_template(_: User = Depends(require_admin)):
    """FR-ACC-10：模板列 = 供货商名称/联系人/联系电话/邮箱/地址/登录账号/初始密码，附「填写说明」Sheet。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "供货商账号"
    ws.append(TEMPLATE_HEADERS)
    for idx in range(1, len(TEMPLATE_HEADERS) + 1):
        ws.column_dimensions[chr(64 + idx)].width = 18

    notes = wb.create_sheet("填写说明")
    notes.append(["列名", "是否必填", "填写说明"])
    notes.append(["供货商名称", "必填", "已存在的档案名将直接复用；不存在则自动新建档案"])
    notes.append(["联系人", "必填", "2~50 个字"])
    notes.append(["联系电话", "必填", "手机号 11 位（如 13800000000）或座机（如 010-88886666）"])
    notes.append(["邮箱", "选填", "如 zhang@example.com；填写了就必须是合法邮箱格式"])
    notes.append(["地址", "选填", "不超过 200 字"])
    notes.append(["登录账号", "必填", "唯一，4~20 位字母、数字或下划线，不能与系统内已有账号重复"])
    notes.append(["初始密码", "必填", "8~20 位，至少包含字母与数字；导入后首次登录强制修改密码"])
    notes.append([])
    notes.append(["注意事项", "", "1) 请勿修改表头名称，可调整列顺序；2) 单次最多导入 2000 行"])
    notes.append(["", "", "3) 同一文件内供货商名称与登录账号不可重复；4) 上传后先预校验，确认无误再落库"])
    notes.append(["示例行", "", "恒信文具 / 张三 / 13800000000 / zhang@example.com / XX路1号 / hengxin_wz / Abc12345"])
    for col, width in (("A", 14), ("B", 10), ("C", 80)):
        notes.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="supplier_account_import_template.xlsx"',
            "Cache-Control": "no-store",
        },
    )


class ParsedImport(NamedTuple):
    """xlsx 解析结果（导入预校验与错误报告导出共用的中间结构）。"""

    matrix: list[list[Any]]
    header_index: int
    col_map: dict[str, int]
    data_rows: list[list[Any]]


async def _read_upload_xlsx(file: UploadFile) -> tuple[str, bytes]:
    """上传文件的扩展名/大小/非空校验并读入内存。"""
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        raise _bad_request("仅支持 .xlsx 格式的模板文件（.xls 请另存为 .xlsx）")

    raw = await file.read()
    if not raw:
        raise _bad_request("上传文件为空")
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise _bad_request(f"文件超过 {settings.max_upload_size_mb}MB 限制")
    return filename, raw


def _parse_import_workbook(raw: bytes) -> ParsedImport:
    """解析 xlsx、定位表头（第一行非空行）、按列名（含别名）建立字段映射。"""
    try:
        wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
    except Exception:
        raise _bad_request("文件解析失败，请确认上传的是有效的 .xlsx 文件")

    try:
        ws = wb["供货商账号"] if "供货商账号" in wb.sheetnames else wb.worksheets[0]
        matrix = [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    if not matrix:
        raise _bad_request("文件无有效内容")

    header_index = -1
    for i, row in enumerate(matrix):
        if any(_cell_text(c) for c in row):
            header_index = i
            break
    if header_index < 0:
        raise _bad_request("文件无有效内容")

    headers = [_cell_text(c).lower() for c in matrix[header_index]]
    col_map: dict[str, int] = {}
    for idx, text in enumerate(headers):
        field = HEADER_ALIASES.get(text)
        if field and field not in col_map:
            col_map[field] = idx
    missing_headers = [FIELD_LABELS[f] for f in REQUIRED_FIELDS if f not in col_map]
    if missing_headers:
        raise _bad_request(f"模板表头缺少列：{'、'.join(missing_headers)}；请使用「下载导入模板」生成的模板")

    data_rows = [r for r in matrix[header_index + 1:] if any(_cell_text(c) for c in r)]
    if not data_rows:
        raise _bad_request("模板中没有可导入的数据行")
    if len(data_rows) > settings.import_max_rows:
        raise _bad_request(f"单次导入最多 {settings.import_max_rows} 行，当前 {len(data_rows)} 行，请分批导入")

    return ParsedImport(matrix=matrix, header_index=header_index, col_map=col_map, data_rows=data_rows)


def _validate_import_rows(db: Session, parsed: ParsedImport) -> list[dict[str, Any]]:
    """逐行校验（导入预校验与错误报告导出**共用同一套规则**，避免口径漂移）。

    返回每个数据行一个 dict：{row, 各行值, supplier_exists, errors: [ImportErrorItem]}。
    """
    def cell(row: list[Any], field: str) -> str:
        idx = parsed.col_map.get(field)
        if idx is None or idx >= len(row):
            return ""
        return _cell_text(row[idx])

    existing_usernames = {u.lower() for (u,) in db.execute(select(User.username)).all() if u}
    bound_supplier_names = {
        name
        for (name,) in db.execute(
            select(Supplier.name).join(
                User, and_(User.supplier_id == Supplier.id, User.role == ROLE_SUPPLIER)
            )
        ).all()
        if name
    }
    known_supplier_names = {name for (name,) in db.execute(select(Supplier.name)).all() if name}

    seen_usernames: dict[str, int] = {}
    seen_suppliers: dict[str, int] = {}
    results: list[dict[str, Any]] = []

    for offset, raw_row in enumerate(parsed.data_rows):
        # Excel 中的实际行号（表头为第 1 行，数据从第 2 行开始）
        row_no = parsed.header_index + 2 + offset
        values = {field: cell(raw_row, field) for field in FIELD_LABELS}
        row_errors: list[ImportErrorItem] = []

        def add_error(field: str, value: str, reason: str) -> None:
            row_errors.append(
                ImportErrorItem(
                    row=row_no, column=FIELD_LABELS.get(field, field), value=value or None, reason=reason
                )
            )

        for field in REQUIRED_FIELDS:
            if not values[field]:
                add_error(field, values[field], f"{FIELD_LABELS[field]}为必填项，不能为空")

        username = values["username"]
        password = values["initial_password"]
        email = values["contact_email"]
        phone = values["contact_phone"]
        supplier_name = values["supplier_name"]

        if username:
            if not USERNAME_RE.match(username):
                add_error("username", username, "登录账号需为 4~20 位字母、数字或下划线")
            elif username.lower() in existing_usernames:
                add_error("username", username, "登录账号已存在于系统中")
            elif username.lower() in seen_usernames:
                add_error(
                    "username",
                    username,
                    f"登录账号在文件内重复（与第 {seen_usernames[username.lower()]} 行相同）",
                )
            else:
                seen_usernames[username.lower()] = row_no

        if password and (
            not (8 <= len(password) <= 20)
            or not any(c.isalpha() for c in password)
            or not any(c.isdigit() for c in password)
        ):
            add_error("initial_password", password, "初始密码需 8~20 位且至少包含字母与数字")

        if phone and not (MOBILE_RE.match(phone) or LANDLINE_RE.match(phone)):
            add_error("contact_phone", phone, "联系电话格式不正确（手机号 11 位或座机如 010-88886666）")

        if email and not EMAIL_RE.match(email):
            add_error("contact_email", email, "邮箱格式不正确")

        if supplier_name:
            key = supplier_name.strip()
            if key in seen_suppliers:
                add_error(
                    "supplier_name",
                    supplier_name,
                    f"供货商名称在文件内重复（与第 {seen_suppliers[key]} 行相同），请合并为一行",
                )
            else:
                seen_suppliers[key] = row_no
            if key in bound_supplier_names:
                add_error("supplier_name", supplier_name, "该供货商档案已绑定账号，一个档案只能绑定一个账号")

        results.append(
            {
                "row": row_no,
                "supplier_name": supplier_name.strip(),
                "contact_name": values["contact_name"],
                "contact_phone": phone,
                "contact_email": email or None,
                "address": values["address"] or None,
                "username": username,
                "initial_password": password,
                "supplier_exists": supplier_name.strip() in known_supplier_names,
                "errors": row_errors,
            }
        )

    return results


@router.post(
    "/supplier-accounts/import",
    response_model=Envelope[SupplierImportPreview],
    summary="批量导入预校验（不落库）",
)
async def import_supplier_accounts(
    request: Request,
    file: UploadFile = File(..., description="按模板填写的 .xlsx 文件"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-10~12：逐行校验，返回精确到行的 errors 与确认用 token，**不写库**。"""
    filename, raw = await _read_upload_xlsx(file)
    parsed = _parse_import_workbook(raw)
    rows = _validate_import_rows(db, parsed)
    total = len(parsed.data_rows)
    valid_rows = [r for r in rows if not r["errors"]]
    errors = [e for r in rows for e in r["errors"]]

    _purge_import_tokens()
    token = secrets.token_urlsafe(24)
    _IMPORT_TOKENS[token] = {
        "created_at": time.time(),
        "rows": valid_rows,
        "filename": filename,
        "operator_id": admin.id,
    }

    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier_account.import_preview",
        target_type="import",
        target_id=token[:16],
        summary=(
            f"预校验供货商账号导入文件 {filename}：共 {total} 行，"
            f"通过 {len(valid_rows)} 行，错误 {len(errors)} 处（未落库）"
        ),
    )
    db.commit()

    return Envelope(
        message="预校验完成，请确认后导入",
        data=SupplierImportPreview(
            total=total,
            valid=len(valid_rows),
            invalid=total - len(valid_rows),
            errors=errors,
            token=token,
        ),
    )


@router.post(
    "/supplier-accounts/import/confirm",
    response_model=Envelope[SupplierImportResult],
    summary="确认落库批量导入的供货商账号",
)
def confirm_supplier_accounts_import(
    payload: SupplierImportConfirmIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-12：按 token 落库，逐行返回失败原因；供货商名称不存在时自动创建档案。"""
    record = _IMPORT_TOKENS.pop(payload.token, None)
    if record is None:
        raise _bad_request("导入凭证无效或已使用，请重新上传文件预校验")
    if time.time() - record["created_at"] > _IMPORT_TTL_SECONDS:
        raise _bad_request("导入凭证已过期（有效期 30 分钟），请重新上传文件预校验")

    success = 0
    errors: list[ImportErrorItem] = []
    for row in record["rows"]:
        row_no = int(row["row"])
        try:
            with db.begin_nested():
                if db.scalar(select(User.id).where(func.lower(User.username) == row["username"].lower())):
                    raise ValueError(f"登录账号 {row['username']} 已存在")
                supplier = db.scalar(select(Supplier).where(Supplier.name == row["supplier_name"]))
                if supplier is None:
                    supplier = Supplier(
                        name=row["supplier_name"],
                        contact_name=row["contact_name"],
                        contact_phone=row["contact_phone"],
                        contact_email=row["contact_email"],
                        address=row["address"],
                        status=1,
                    )
                    db.add(supplier)
                    db.flush()
                bound = db.scalar(
                    select(User.username).where(
                        User.supplier_id == supplier.id, User.role == ROLE_SUPPLIER
                    )
                )
                if bound:
                    raise ValueError(f"供货商档案「{supplier.name}」已绑定账号 {bound}")
                db.add(
                    User(
                        username=row["username"],
                        password_hash=hash_password(row["initial_password"]),
                        real_name=row["contact_name"],
                        role=ROLE_SUPPLIER,
                        supplier_id=supplier.id,
                        status=1,
                        # 需求变更 2026-10：批量导入同样默认不强制改密；
                        # 如需强制，请导入后在账号列表里逐个开启（或走单个新建的开关）
                        must_change_password=False,
                    )
                )
                db.flush()
            success += 1
        except Exception as exc:  # noqa: BLE001 - 逐行容错，失败原因回传前端
            reason = str(exc) or exc.__class__.__name__
            errors.append(ImportErrorItem(row=row_no, column=None, value=row["username"], reason=reason))

    failed = len(record["rows"]) - success
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier_account.import",
        target_type="import",
        target_id=record.get("filename"),
        summary=(
            f"确认导入供货商账号（文件 {record.get('filename')}）：成功 {success} 条，失败 {failed} 条"
        ),
    )
    db.commit()
    return Envelope(
        message=f"导入完成：成功 {success} 条，失败 {failed} 条",
        data=SupplierImportResult(success=success, failed=failed, errors=errors),
    )


@router.post(
    "/supplier-accounts/import/error-report",
    summary="导出批量导入失败明细（xlsx，不落库、不签发 token）",
)
async def export_import_error_report(
    request: Request,
    file: UploadFile = File(..., description="按模板填写的 .xlsx 文件"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-ACC-12：对上传文件做与导入完全相同的行级校验，仅导出失败明细。

    - 不落库、不签发 token（与 /import 的区别）；
    - 全部行合法时返回只有表头的 xlsx，并在 audit summary 中说明"无错误行"。
    """
    filename, raw = await _read_upload_xlsx(file)
    parsed = _parse_import_workbook(raw)
    rows = _validate_import_rows(db, parsed)
    failures = [(row, err) for row in rows for err in row["errors"]]

    wb = Workbook()
    ws = wb.active
    ws.title = "导入错误明细"
    ws.append(["Excel 行号", "供货商名称", "登录账号", "失败原因"])
    for row, err in failures:
        reason = f"[{err.column}] {err.reason}" if err.column else err.reason
        ws.append([err.row, row["supplier_name"], row["username"], reason])
    for idx, width in enumerate([12, 24, 20, 60], start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    summary = (
        f"导出供货商账号导入错误报告 {filename}：共 {len(parsed.data_rows)} 行，错误 {len(failures)} 处（未落库）"
        if failures
        else f"导出供货商账号导入错误报告 {filename}：共 {len(parsed.data_rows)} 行，无错误行（未落库）"
    )
    write_audit(
        db,
        request=request,
        user=admin,
        action="supplier_account.import_error_report",
        target_type="import",
        target_id=filename,
        summary=summary,
    )
    db.commit()

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": _xlsx_attachment(
                "supplier_import_error_report", "供货商账号导入错误报告"
            ),
            "Cache-Control": "no-store",
        },
    )


# --------------------------------------------------------------------------
# E. 字典：计量单位（FR-MST-01）
# --------------------------------------------------------------------------
class AdminUnitOut(UnitOut):
    referenced_count: int = 0


class AdminUnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=20)
    sort: int | None = None
    status: int | None = Field(default=None, ge=0, le=1)


def _unit_reference_map(db: Session) -> dict[str, int]:
    rows = db.execute(select(RfqLine.unit, func.count()).group_by(RfqLine.unit)).all()
    return {name: int(cnt) for name, cnt in rows if name}


@router.get("/units", response_model=Envelope[list[AdminUnitOut]], summary="计量单位字典列表")
def list_units(
    keyword: str | None = Query(None),
    status: int | None = Query(None, ge=0, le=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    conds = []
    if keyword and keyword.strip():
        conds.append(UnitDict.name.like(f"%{keyword.strip()}%"))
    if status is not None:
        conds.append(UnitDict.status == status)
    rows = db.scalars(
        select(UnitDict).where(*conds).order_by(UnitDict.sort.asc(), UnitDict.id.asc())
    ).all()
    ref_map = _unit_reference_map(db)
    return Envelope(
        data=[
            AdminUnitOut(
                id=u.id,
                name=u.name,
                sort=u.sort,
                status=u.status,
                referenced_count=ref_map.get(u.name, 0),
            )
            for u in rows
        ]
    )


@router.post("/units", response_model=Envelope[AdminUnitOut], summary="新增计量单位")
def create_unit(
    payload: UnitIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    name = payload.name.strip()
    if db.scalar(select(UnitDict.id).where(UnitDict.name == name)):
        raise _conflict(f"计量单位「{name}」已存在")
    unit = UnitDict(name=name, sort=payload.sort, status=1)
    db.add(unit)
    db.flush()
    write_audit(
        db,
        request=request,
        user=admin,
        action="unit.create",
        target_type="unit_dict",
        target_id=unit.id,
        summary=f"新增计量单位 {unit.name}",
    )
    _commit_or_conflict(db, f"计量单位「{name}」已存在")
    db.refresh(unit)
    return Envelope(message="新增成功", data=AdminUnitOut(id=unit.id, name=unit.name, sort=unit.sort, status=unit.status))


@router.put("/units/{unit_id}", response_model=Envelope[AdminUnitOut], summary="编辑/停用计量单位")
def update_unit(
    unit_id: int,
    payload: AdminUnitUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-MST-01：被引用后不可删除，仅可停用；本模块不提供删除接口。"""
    unit = db.get(UnitDict, unit_id)
    if unit is None:
        raise _not_found("计量单位不存在")

    data = payload.model_dump(exclude_unset=True)
    changes: list[str] = []
    if data.get("name") is not None:
        new_name = data["name"].strip()
        if new_name != unit.name:
            if db.scalar(select(UnitDict.id).where(UnitDict.name == new_name, UnitDict.id != unit.id)):
                raise _conflict(f"计量单位「{new_name}」已存在")
            changes.append(f"名称 {unit.name} → {new_name}")
            unit.name = new_name
    if data.get("sort") is not None and data["sort"] != unit.sort:
        changes.append(f"排序 {unit.sort} → {data['sort']}")
        unit.sort = data["sort"]
    if data.get("status") is not None and data["status"] != unit.status:
        changes.append("启用" if data["status"] == 1 else "停用")
        unit.status = data["status"]

    if not changes:
        ref = _unit_reference_map(db).get(unit.name, 0)
        return Envelope(
            message="无变更",
            data=AdminUnitOut(id=unit.id, name=unit.name, sort=unit.sort, status=unit.status, referenced_count=ref),
        )

    write_audit(
        db,
        request=request,
        user=admin,
        action="unit.update",
        target_type="unit_dict",
        target_id=unit.id,
        summary=f"编辑计量单位 {unit.name}（{'；'.join(changes)}）",
    )
    _commit_or_conflict(db, "保存失败，计量单位名称可能已存在")
    db.refresh(unit)
    ref = _unit_reference_map(db).get(unit.name, 0)
    return Envelope(
        message="保存成功",
        data=AdminUnitOut(id=unit.id, name=unit.name, sort=unit.sort, status=unit.status, referenced_count=ref),
    )


# --------------------------------------------------------------------------
# E. 字典：税率（FR-MST-02，默认税率唯一）
# --------------------------------------------------------------------------
class AdminTaxUpdate(BaseModel):
    rate: Decimal | None = Field(default=None, ge=0, le=1)
    label: str | None = Field(default=None, min_length=1, max_length=20)
    is_default: bool | None = None
    sort: int | None = None
    status: int | None = Field(default=None, ge=0, le=1)


def _clear_default_taxes(db: Session, keep_id: int | None = None) -> None:
    stmt = select(TaxDict).where(TaxDict.is_default.is_(True))
    if keep_id is not None:
        stmt = stmt.where(TaxDict.id != keep_id)
    for row in db.scalars(stmt).all():
        row.is_default = False


@router.get("/taxes", response_model=Envelope[list[TaxOut]], summary="税率字典列表")
def list_taxes(
    status: int | None = Query(None, ge=0, le=1),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    stmt = select(TaxDict)
    if status is not None:
        stmt = stmt.where(TaxDict.status == status)
    rows = db.scalars(stmt.order_by(TaxDict.sort.asc(), TaxDict.id.asc())).all()
    return Envelope(data=list(rows))


@router.post("/taxes", response_model=Envelope[TaxOut], summary="新增税率")
def create_tax(
    payload: TaxIn,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-MST-02：默认税率全局唯一，设置新默认时清除旧的默认项。"""
    if db.scalar(select(TaxDict.id).where(TaxDict.rate == payload.rate)):
        raise _conflict(f"税率 {payload.rate} 已存在")

    has_default = bool(db.scalar(select(func.count()).select_from(TaxDict).where(TaxDict.is_default.is_(True))))
    make_default = payload.is_default or not has_default
    if make_default:
        _clear_default_taxes(db)

    tax = TaxDict(
        rate=payload.rate,
        label=payload.label.strip(),
        is_default=make_default,
        status=1,
        sort=payload.sort,
    )
    db.add(tax)
    db.flush()
    write_audit(
        db,
        request=request,
        user=admin,
        action="tax.create",
        target_type="tax_dict",
        target_id=tax.id,
        summary=f"新增税率 {tax.label}（{tax.rate}）{'，设为默认' if make_default else ''}",
    )
    _commit_or_conflict(db, f"税率 {payload.rate} 已存在")
    db.refresh(tax)
    return Envelope(message="新增成功", data=tax)


@router.put("/taxes/{tax_id}", response_model=Envelope[TaxOut], summary="编辑/停用税率")
def update_tax(
    tax_id: int,
    payload: AdminTaxUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    tax = db.get(TaxDict, tax_id)
    if tax is None:
        raise _not_found("税率不存在")

    data = payload.model_dump(exclude_unset=True)
    if data.get("status") == 0 and tax.is_default:
        raise _conflict("默认税率不可停用，请先把其他税率设为默认")
    if data.get("is_default") is True and data.get("status") == 0:
        raise _conflict("设为默认的税率必须处于启用状态")
    if data.get("is_default") is False and tax.is_default:
        raise _conflict("默认税率不可直接取消，请将其他税率设为默认")

    changes: list[str] = []
    if data.get("rate") is not None and data["rate"] != tax.rate:
        if db.scalar(select(TaxDict.id).where(TaxDict.rate == data["rate"], TaxDict.id != tax.id)):
            raise _conflict(f"税率 {data['rate']} 已存在")
        changes.append(f"税率 {tax.rate} → {data['rate']}")
        tax.rate = data["rate"]
    if data.get("label") is not None and data["label"].strip() != tax.label:
        changes.append(f"显示名 {tax.label} → {data['label'].strip()}")
        tax.label = data["label"].strip()
    if data.get("sort") is not None and data["sort"] != tax.sort:
        changes.append(f"排序 {tax.sort} → {data['sort']}")
        tax.sort = data["sort"]
    if data.get("status") is not None and data["status"] != tax.status:
        changes.append("启用" if data["status"] == 1 else "停用")
        tax.status = data["status"]
    if data.get("is_default") is True and not tax.is_default:
        _clear_default_taxes(db, keep_id=tax.id)
        tax.is_default = True
        changes.append("设为默认税率（已清除原默认项）")

    if not changes:
        return Envelope(message="无变更", data=tax)

    write_audit(
        db,
        request=request,
        user=admin,
        action="tax.update",
        target_type="tax_dict",
        target_id=tax.id,
        summary=f"编辑税率 {tax.label}（{'；'.join(changes)}）",
    )
    _commit_or_conflict(db, "保存失败，税率可能已存在")
    db.refresh(tax)
    return Envelope(message="保存成功", data=tax)


# --------------------------------------------------------------------------
# F. 操作日志（FR-LOG-01~04，只读）
# --------------------------------------------------------------------------
def _parse_time(value: str, *, end: bool) -> datetime:
    text = (value or "").strip()
    if not text:
        raise _bad_request("时间参数不能为空")
    try:
        if len(text) == 10:
            dt = datetime.strptime(text, "%Y-%m-%d")
            if end:
                return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _bad_request(f"时间格式不正确：{value}（应为 YYYY-MM-DD 或 ISO8601）")
    if dt.tzinfo is not None:
        # 统一到应用基准（北京时间）后再比较：审计日志 created_at 由 deps.write_audit
        # 按北京时间写入，这里若转成 UTC 会让带时区入参的筛选结果偏移 8 小时。
        dt = to_app_tz(dt)
    return dt


@router.get("/audit-logs", response_model=Envelope[PageData[AuditLogItem]], summary="操作日志查询（只读）")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    date_from: str | None = Query(None, description="YYYY-MM-DD 或 ISO8601，含当天"),
    date_to: str | None = Query(None, description="YYYY-MM-DD 或 ISO8601，含当天"),
    operator: str | None = Query(None, description="操作人姓名（模糊）或用户 ID"),
    action: str | None = Query(None, description="动作类型，支持前缀模糊（如 user.）"),
    target_type: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """FR-LOG-03：按时间、操作人、动作类型筛选；FR-LOG-04：只读，无删除接口。"""
    conds = []
    if date_from:
        conds.append(AuditLog.created_at >= _parse_time(date_from, end=False))
    if date_to:
        conds.append(AuditLog.created_at <= _parse_time(date_to, end=True))
    if operator and operator.strip():
        text = operator.strip()
        # 日志里的 operator_name 是姓名快照，这里同时支持按用户名/姓名/ID 过滤
        matched: list = [AuditLog.operator_name.like(f"%{text}%")]
        if text.isdigit():
            matched.append(AuditLog.operator_id == int(text))
        user_ids = [
            uid
            for (uid,) in db.execute(
                select(User.id).where(or_(User.username.like(f"%{text}%"), User.real_name.like(f"%{text}%")))
            ).all()
        ]
        if user_ids:
            matched.append(AuditLog.operator_id.in_(user_ids))
        conds.append(or_(*matched))
    if action and action.strip():
        conds.append(AuditLog.action.like(f"{action.strip()}%"))
    if target_type and target_type.strip():
        conds.append(AuditLog.target_type == target_type.strip())

    total = int(db.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0)
    offset, limit = page_offset(page, page_size)
    rows = db.scalars(
        select(AuditLog)
        .where(*conds)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return Envelope(
        data=PageData(
            items=[AuditLogItem.model_validate(r) for r in rows],
            meta=PageMeta(page=max(1, page), page_size=limit, total=total),
        )
    )


@router.get("/audit-logs/actions", response_model=Envelope[list[str]], summary="日志动作类型列表（筛选下拉用）")
def list_audit_actions(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    actions = [a for (a,) in db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action)).all() if a]
    return Envelope(data=actions)
