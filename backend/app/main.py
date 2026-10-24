"""FastAPI 应用入口。

路由前缀在此处统一约定（各模块实现方只需创建 router，不用关心前缀）：

| 模块文件                    | 前缀                        |
|-----------------------------|-----------------------------|
| app/api/auth.py             | /api/auth                   |
| app/api/admin.py            | /api/admin                  |
| app/api/rfq.py              | /api/rfqs                   |
| app/api/supplier.py         | /api/supplier               |
| app/api/report.py           | /api/reports                |
| app/api/meta.py             | /api/meta                   |

每个模块必须导出名为 `router` 的 APIRouter。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .database import init_db

logger = logging.getLogger("xunjia")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建表、确保初始数据，并启动自动截止兜底扫描（PRD 4.3）。"""
    init_db()
    try:
        from .seed import ensure_seed_data

        ensure_seed_data()
    except Exception:  # pragma: no cover - 种子失败不应阻断启动
        logger.exception("种子数据初始化失败（不影响启动）")

    # 自动截止兜底：惰性触发之外的定时保险（PRD 4.3）
    scheduler_task: asyncio.Task | None = None
    try:
        from .services.scheduler import auto_close_loop

        scheduler_task = asyncio.create_task(auto_close_loop())
    except Exception:  # pragma: no cover
        logger.exception("自动截止调度启动失败（惰性截止仍然生效）")

    logger.info(
        "%s 启动完成 | 环境=%s | 数据库=%s",
        settings.app_name,
        "dev" if settings.debug else "prod",
        settings.resolved_database_url(),
    )
    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task


app = FastAPI(
    title=settings.app_name,
    description="小型询价报价系统 API。需求见 doc/PRD-询价报价系统.md。",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

# 内网部署，前端与 API 同源由 nginx 托管；开发期 Vite 端口需要跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# 统一异常响应：所有错误都返回 {"code": ..., "message": ...}
# --------------------------------------------------------------------------
# HTTP 状态码 → 业务码兜底映射。
# 业务代码抛出的 HTTPException 会带 detail={"code":...}，此处只处理框架自己抛出的
# 情况（未匹配路由、方法不允许等）。若直接透传 HTTP 状态码，会出现 PRD 7.6 错误码表里
# 不存在的码（例如不存在的路径返回 405 / code=405），前端无法按表处理。
_HTTP_STATUS_FALLBACK = {
    400: 40001,  # 参数/请求格式错误
    401: 40100,  # 未登录
    403: 40300,  # 无权限
    404: 40400,  # 资源不存在
    405: 40400,  # 方法不允许：对调用方而言等价于"该接口不存在"
    409: 40900,  # 业务冲突
    422: 40001,  # 语义校验失败（FastAPI 默认）
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        code = int(detail["code"])
        message = str(detail.get("message", ""))
    else:
        # 框架抛出的原始 HTTP 异常：映射到 PRD 7.6 的业务码
        code = _HTTP_STATUS_FALLBACK.get(exc.status_code, exc.status_code)
        message = str(detail) if detail else f"请求失败（HTTP {exc.status_code}）"
        if exc.status_code == 404:
            message = "接口或资源不存在"
        elif exc.status_code == 405:
            message = "该接口不支持此请求方法"
    return JSONResponse(status_code=exc.status_code, content={"code": code, "message": message, "data": None})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验失败统一为 40001，并给出首个字段的可读提示（PRD 7.6）。"""
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "path"))
    message = f"{loc}：{first.get('msg', '参数校验失败')}" if loc else "参数校验失败"
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"code": 40001, "message": message, "data": {"errors": [
            {"loc": ".".join(str(x) for x in e.get("loc", [])), "msg": e.get("msg")} for e in errors
        ]}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": 50000, "message": "服务端异常，请稍后重试或联系管理员", "data": None},
    )


@app.get("/api/health", tags=["system"], summary="健康检查")
def health():
    return {"code": 0, "message": "ok", "data": {"status": "up", "version": app.version}}


# --------------------------------------------------------------------------
# 路由注册（模块可能尚在开发中，缺失时给出警告而不阻断启动，便于并行开发）
# --------------------------------------------------------------------------
def _include(module: str, prefix: str, tag: str) -> None:
    try:
        mod = __import__(f"app.api.{module}", fromlist=["router"])
    except ModuleNotFoundError as exc:
        logger.warning("路由模块 app.api.%s 未就绪，跳过注册（%s）", module, exc)
        return
    app.include_router(mod.router, prefix=prefix, tags=[tag])


_include("auth", "/api/auth", "认证")
_include("meta", "/api/meta", "字典与主数据")
_include("admin", "/api/admin", "系统管理")
_include("rfq", "/api/rfqs", "询价单")
_include("supplier", "/api/supplier", "供货商报价")
_include("report", "/api/reports", "统计报表")
_include("pm", "/api/pm", "项目管理")

# --------------------------------------------------------------------------
# 前端静态资源（生产由 nginx 托管；若前端已构建则一并由后端提供，便于单容器/单端口演示）
# --------------------------------------------------------------------------
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    # 带内容哈希的静态资源
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA history 模式回退：非 API 前缀的未知路径一律返回 index.html。

        这样 /purchase/rfq、/system/account 等前端路由直接输入或刷新都能正常打开
        （nginx 部署时由 try_files 承担同样职责，见 frontend/nginx.conf）。

        注意：**/api 前缀必须排除**，否则未知接口会被回退成 HTML，
        前端拿到 200 + HTML 会误判为"接口成功"，比 404 更难排查。
        """
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404, content={"code": 40400, "message": "接口不存在", "data": None}
            )
        # 根目录下的真实静态文件（favicon.svg / manifest.json / apple-touch-icon.png）
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(_dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")

    logger.info("已挂载前端静态资源目录: %s（含 SPA history 回退）", _dist)
