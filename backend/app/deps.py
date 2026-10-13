"""FastAPI 依赖：鉴权、角色守卫、审计日志辅助。

安全设计（对应 PRD 3.3 关键可见性约束）：
1. 供货商身份只来自 JWT 中的 supplier_id，接口一律不接受前端传入的 supplier_id；
2. 角色守卫在后端强制，前端菜单隐藏只是体验优化（PRD 3.3-1）；
3. must_change_password 为真时，除改密接口外一律 40101（PRD 7.1）。
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditLog, User, app_now
from .security import decode_access_token, password_fingerprint

bearer_scheme = HTTPBearer(auto_error=False)

# 角色常量
ROLE_ADMIN = "admin"
ROLE_BUYER = "buyer"
ROLE_SUPPLIER = "supplier"
INTERNAL_ROLES = (ROLE_ADMIN, ROLE_BUYER)

# 允许在强制改密状态下访问的路径。
# 注意：只放行"改密所必需"的三个接口。/auth/me 必须在拦截范围内 ——
# 否则未改密的账号可以正常调用业务接口，形成越权（对应 PRD TC-02 / 错误码 40101）。
_PASSWORD_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/change-password",
    "/api/auth/logout",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def _unauthorized(code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": code, "message": message})


def _forbidden(code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": code, "message": message})


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer token 并返回当前用户。"""
    if credentials is None or not credentials.credentials:
        raise _unauthorized(40100, "未登录或登录已过期")

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise _unauthorized(40100, "登录已过期，请重新登录")

    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized(40100, "登录凭证无效")

    user = db.get(User, int(user_id))
    if user is None:
        raise _unauthorized(40100, "账号不存在")
    if user.status != 1:
        # 停用账号：已登录会话立即失效（FR-ACC-04）
        raise _unauthorized(40100, "账号已停用，请联系管理员")

    # 密码指纹校验：管理员重置密码或用户自行改密后，旧 token 立即失效。
    # 这样"重置密码"才真正切断既有会话（PRD FR-ACC-05 / FR-ACC-12）。
    token_pwd = payload.get("pwd")
    if token_pwd != password_fingerprint(user.password_hash):
        raise _unauthorized(40100, "登录已失效（密码已变更），请重新登录")

    # 强制改密拦截（放行白名单路径）
    path = request.url.path
    if user.must_change_password and path not in _PASSWORD_EXEMPT_PATHS:
        raise _unauthorized(40101, "首次登录需先修改密码")

    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    """角色守卫工厂。用法：Depends(require_roles("admin"))。"""

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise _forbidden(40300, "无权访问该功能")
        return user

    return _guard


def require_internal(user: User = Depends(get_current_user)) -> User:
    """我方人员（管理员或采购员）。"""
    if user.role not in INTERNAL_ROLES:
        raise _forbidden(40300, "无权访问该功能")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """仅管理员（账号管理、字典维护、日志）。"""
    if user.role != ROLE_ADMIN:
        raise _forbidden(40300, "仅管理员可执行该操作")
    return user


def require_supplier(user: User = Depends(get_current_user)) -> User:
    """仅供货商，且必须绑定供货商档案。

    返回的用户对象其 supplier_id 来自服务端数据库，
    调用方应使用 current_user.supplier_id，禁止使用请求参数中的 supplier_id。
    """
    if user.role != ROLE_SUPPLIER:
        raise _forbidden(40300, "该接口仅供供货商使用")
    if user.supplier_id is None:
        raise _forbidden(40300, "当前账号未绑定供货商档案，请联系采购方")
    return user


def client_ip(request: Request) -> str | None:
    """取客户端 IP，优先 X-Forwarded-For（nginx 反代场景）。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def audit_forbidden(
    db: Session,
    request: Request,
    user: User | None,
    *,
    resource: str,
    detail: str | None = None,
) -> HTTPException:
    """记录一条越权告警日志并返回 403 异常（PRD 3.3 / TC-31 / TC-34）。

    供货商尝试访问他方报价或报表接口时必须留痕，便于事后追溯。
    """
    write_audit(
        db,
        request=request,
        user=user,
        action="security.forbidden",
        target_type="resource",
        target_id=resource,
        summary=detail or f"越权访问被拒绝：{resource}",
    )
    db.commit()
    return _forbidden(40300, "无权访问该数据")


def write_audit(
    db: Session,
    *,
    request: Request | None = None,
    user: User | None = None,
    action: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    summary: str | None = None,
) -> AuditLog:
    """写一条操作日志（PRD 6.2 audit_log / FR-LOG-01）。

    注意：调用方需保证它与会话在同一事务内提交。
    系统自动动作（如自动截止）传 user=None，operator_name 记为 system。
    """
    log = AuditLog(
        operator_id=user.id if user else None,
        operator_name=user.real_name or user.username if user else "system",
        role=user.role if user else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        summary=summary,
        client_ip=client_ip(request) if request else None,
        created_at=app_now(),
    )
    db.add(log)
    return log
