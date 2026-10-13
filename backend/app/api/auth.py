"""认证接口：登录、登出、改密、当前用户（PRD 7.1）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, write_audit
from ..models import User, app_now
from ..schemas import ChangePasswordRequest, Envelope, LoginRequest, LoginResponse, UserBrief
from ..security import create_access_token, hash_password, verify_password

router = APIRouter()


def _brief(user: User) -> UserBrief:
    return UserBrief(
        id=user.id,
        username=user.username,
        real_name=user.real_name,
        role=user.role,
        supplier_id=user.supplier_id,
        supplier_name=user.supplier.name if user.supplier else None,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=Envelope[LoginResponse], summary="登录")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """用户名+密码登录，返回 JWT。

    失败时不区分"账号不存在"与"密码错误"（PRD TC-01），并记录一条失败日志。
    """
    user = db.scalar(select(User).where(User.username == payload.username))
    ok = bool(user) and verify_password(payload.password, user.password_hash)

    if not ok:
        write_audit(
            db,
            request=request,
            user=None,
            action="auth.login_failed",
            target_type="user",
            target_id=payload.username,
            summary=f"登录失败：账号 {payload.username}",
        )
        db.commit()
        raise HTTPException(status_code=401, detail={"code": 40100, "message": "用户名或密码错误"})

    assert user is not None
    if user.status != 1:
        write_audit(
            db,
            request=request,
            user=user,
            action="auth.login_failed",
            target_type="user",
            target_id=user.id,
            summary=f"登录失败：账号 {user.username} 已停用",
        )
        db.commit()
        raise HTTPException(status_code=401, detail={"code": 40100, "message": "账号已停用，请联系管理员"})

    user.last_login_at = app_now()
    write_audit(
        db,
        request=request,
        user=user,
        action="auth.login",
        target_type="user",
        target_id=user.id,
        summary="登录成功",
    )
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        supplier_id=user.supplier_id,
        password_hash=user.password_hash,
    )
    return Envelope(data=LoginResponse(token=token, user=_brief(user)))


@router.post("/logout", response_model=Envelope[None], summary="退出登录")
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """JWT 无状态，登出仅记录日志；前端清除本地 token。"""
    write_audit(
        db, request=request, user=user, action="auth.logout", target_type="user", target_id=user.id, summary="退出登录"
    )
    db.commit()
    return Envelope(message="已退出登录")


@router.get("/me", response_model=Envelope[UserBrief], summary="当前用户信息")
def me(user: User = Depends(get_current_user)):
    return Envelope(data=_brief(user))


@router.post("/change-password", response_model=Envelope[None], summary="修改自己的密码")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改密码；首次登录强制改密后 must_change_password 置否（FR-ACC-13）。"""
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "原密码不正确"})
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=400, detail={"code": 40001, "message": "新密码不能与原密码相同"})

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.updated_at = app_now()
    write_audit(
        db, request=request, user=user, action="auth.change_password", target_type="user", target_id=user.id, summary="修改密码"
    )
    db.commit()
    return Envelope(message="密码修改成功")
