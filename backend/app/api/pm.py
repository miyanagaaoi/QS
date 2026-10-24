"""项目管理模块（CH-002）。

与「询价报价」完全独立：不读取也不引用任何 `rfq` 数据，未来如需打通
（例如把某张询价单挂到项目/阶段上）再单独评估。

设计取向（需求方明确）：**快速实现 + 手工维护关键数据 + 看板汇总关键指标**。
- 项目主数据手工维护；8 阶段工期计划表由标准模板一键生成，之后可逐行改。
- 施工工序 / 预算决算管理点 / 配套单据 是三张**全局参考表**（一套，可编辑），
  不跟项目绑定，避免为每个项目复制一份带来的维护负担。
- 进度不手工填：按 `开工日 → 计划竣工日` 的日期跨度实时计算（已过天数占比）。
  "当前阶段"由用户手工维护（现实会拖期，计划与实际分开表达）。

接口（前缀 /api/pm）：
    GET    /board                      看板汇总
    GET    /projects                   项目列表（含进度派生指标）
    POST   /projects                   新建项目（自动生成 8 阶段）
    GET    /projects/{id}              项目详情（含阶段表）
    PUT    /projects/{id}              更新项目
    DELETE /projects/{id}              删除项目（仅管理员）
    PUT    /projects/{id}/stages       批量保存阶段表
    POST   /projects/{id}/stages/reset 按标准模板重置阶段表
    GET    /processes                  施工工序
    PUT    /processes/{id}             修改单条工序
    GET    /cost-points                预算决算管理点
    PUT    /cost-points/{id}           修改单条管理点
    GET    /documents                  预算决算配套单据
    PUT    /documents/{id}             修改单张单据

权限：require_internal（管理员 + 采购员）；供货商一律 403；删除项目仅管理员。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin, require_internal, write_audit
from ..models import (
    PM_STAGE_TEMPLATE,
    PmCostPoint,
    PmDocument,
    PmProcess,
    PmProject,
    PmStage,
    User,
    app_now,
)
from ..schemas import (
    Envelope,
    PmBoard,
    PmBoardSummary,
    PmCostPointIn,
    PmCostPointOut,
    PmDocumentIn,
    PmDocumentOut,
    PmProcessIn,
    PmProcessOut,
    PmProjectDetail,
    PmProjectIn,
    PmProjectOut,
    PmStageDistribution,
    PmStageIn,
    PmStageOut,
)

router = APIRouter()

DUE_SOON_DAYS = 30


def _err(status: int, code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _dec(value: str | None, field: str) -> Decimal | None:
    """把前端传来的字符串数值转 Decimal；空串按未填处理。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # noqa: TRY003
        raise _err(400, 40001, f"{field}：请输入数字") from exc


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _progress(project: PmProject, today: date) -> dict[str, object]:
    """按日期跨度计算进度派生指标（前端不重复计算，保证口径唯一）。"""
    start = project.start_date
    end = project.plan_end_date
    total_days = (end - start).days if (start and end) else None
    if project.status == "done":
        progress = 100
    elif total_days and total_days > 0 and start:
        elapsed_raw = (today - start).days
        progress = max(0, min(100, round(elapsed_raw / total_days * 100)))
    else:
        progress = 0
    elapsed_days = (today - start).days if start else 0
    remaining_days = (end - today).days if end else None
    finished = project.status in ("done",)
    overdue = bool(end and remaining_days is not None and remaining_days < 0 and not finished)
    due_soon = bool(
        end and remaining_days is not None and 0 <= remaining_days <= DUE_SOON_DAYS and not finished
    )
    return {
        "progress": progress,
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
        "overdue": overdue,
        "due_soon": due_soon,
    }


def _project_out(project: PmProject, today: date, stage_count: int | None = None) -> PmProjectOut:
    return PmProjectOut(
        id=project.id,
        name=project.name,
        code=project.code,
        current_stage=project.current_stage,
        start_date=project.start_date,
        plan_end_date=project.plan_end_date,
        total_months=str(project.total_months) if project.total_months is not None else None,
        manager=project.manager,
        status=project.status,  # type: ignore[arg-type]
        remark=project.remark,
        created_at=project.created_at,
        updated_at=project.updated_at,
        stage_count=stage_count if stage_count is not None else len(project.stages),
        **_progress(project, today),
    )


def _stage_out(stage: PmStage) -> PmStageOut:
    def s(value):
        return str(value) if value is not None else None

    return PmStageOut(
        id=stage.id,
        seq=stage.seq,
        name=stage.name,
        group_name=stage.group_name,
        months=s(stage.months),
        start_month=s(stage.start_month),
        end_month=s(stage.end_month),
        deliverables=stage.deliverables,
        pm_role=stage.pm_role,
        owner=stage.owner,
    )


def _detail(project: PmProject, today: date) -> PmProjectDetail:
    base = _project_out(project, today).model_dump()
    return PmProjectDetail(**base, stages=[_stage_out(x) for x in project.stages])


def _apply_stage_template(db: Session, project: PmProject) -> None:
    """按标准 8 阶段模板重建阶段表（累计月数自动累加）。"""
    project.stages.clear()
    cursor = Decimal("0")
    for item in PM_STAGE_TEMPLATE:
        months = Decimal(str(item["months"]))
        db.add(
            PmStage(
                project_id=project.id,
                seq=int(item["seq"]),  # type: ignore[arg-type]
                name=str(item["name"]),
                group_name=str(item["group_name"]),
                months=months,
                start_month=cursor,
                end_month=cursor + months,
                deliverables=str(item["deliverables"]),
                pm_role=str(item["pm_role"]),
                owner=str(item["owner"]),
            )
        )
        cursor += months


def _load_project(db: Session, project_id: int) -> PmProject:
    project = db.get(PmProject, project_id)
    if project is None:
        raise _err(404, 40400, "项目不存在")
    return project


# --------------------------------------------------------------------------
# 看板
# --------------------------------------------------------------------------
@router.get("/board", response_model=Envelope[PmBoard], summary="项目管理看板汇总")
def board(
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    today = app_now().date()
    projects = list(db.scalars(select(PmProject).order_by(PmProject.id)).all())
    outs = [_project_out(p, today) for p in projects]

    summary = PmBoardSummary(total=len(outs))
    for item in outs:
        summary.__setattr__(item.status, getattr(summary, item.status) + 1)
        if item.overdue:
            summary.overdue += 1
        if item.due_soon:
            summary.due_soon += 1

    dist: dict[str, int] = {}
    for item in outs:
        key = item.current_stage or "未设置"
        dist[key] = dist.get(key, 0) + 1
    distribution = [
        PmStageDistribution(stage=k, count=v)
        for k, v in sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 近期关键节点：有竣工日期的按剩余天数升序（超期为负，排前面），取 5 个
    dated = [x for x in outs if x.remaining_days is not None and x.status != "done"]
    dated.sort(key=lambda x: x.remaining_days or 0)
    return Envelope(
        data=PmBoard(
            summary=summary,
            stage_distribution=distribution,
            projects=outs,
            upcoming=dated[:5],
        )
    )


# --------------------------------------------------------------------------
# 项目 CRUD
# --------------------------------------------------------------------------
@router.get("/projects", response_model=Envelope[list[PmProjectOut]], summary="项目列表")
def list_projects(
    keyword: str | None = Query(None, description="名称/编号/项目经理模糊匹配"),
    stage: str | None = Query(None, description="按当前阶段过滤"),
    status: str | None = Query(None, description="planning/active/done/paused"),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    stmt = select(PmProject).order_by(PmProject.id.desc())
    if keyword and keyword.strip():
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            PmProject.name.like(like) | PmProject.code.like(like) | PmProject.manager.like(like)
        )
    if stage and stage.strip():
        stmt = stmt.where(PmProject.current_stage == stage.strip())
    if status and status.strip():
        stmt = stmt.where(PmProject.status == status.strip())
    today = app_now().date()
    return Envelope(data=[_project_out(p, today) for p in db.scalars(stmt).all()])


@router.post("/projects", response_model=Envelope[PmProjectDetail], summary="新建项目")
def create_project(
    payload: PmProjectIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    _check_dates(payload.start_date, payload.plan_end_date)
    project = PmProject(
        name=payload.name.strip(),
        code=_str_or_none(payload.code),
        current_stage=_str_or_none(payload.current_stage),
        start_date=payload.start_date,
        plan_end_date=payload.plan_end_date,
        total_months=_dec(payload.total_months, "总工期(月)"),
        manager=_str_or_none(payload.manager),
        status=payload.status,
        remark=_str_or_none(payload.remark),
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    _apply_stage_template(db, project)
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.create",
        target_type="pm_project",
        target_id=project.id,
        summary=f"新建项目 {project.name}（自动生成 8 阶段工期计划表）",
    )
    db.commit()
    db.refresh(project)
    return Envelope(data=_detail(project, app_now().date()))


@router.get("/projects/{project_id}", response_model=Envelope[PmProjectDetail], summary="项目详情")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    return Envelope(data=_detail(_load_project(db, project_id), app_now().date()))


@router.put("/projects/{project_id}", response_model=Envelope[PmProjectDetail], summary="更新项目")
def update_project(
    project_id: int,
    payload: PmProjectIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    project = _load_project(db, project_id)
    _check_dates(payload.start_date, payload.plan_end_date)
    project.name = payload.name.strip()
    project.code = _str_or_none(payload.code)
    project.current_stage = _str_or_none(payload.current_stage)
    project.start_date = payload.start_date
    project.plan_end_date = payload.plan_end_date
    project.total_months = _dec(payload.total_months, "总工期(月)")
    project.manager = _str_or_none(payload.manager)
    project.status = payload.status
    project.remark = _str_or_none(payload.remark)
    project.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.update",
        target_type="pm_project",
        target_id=project.id,
        summary=f"修改项目 {project.name}（阶段={project.current_stage or '未设置'}，状态={project.status}）",
    )
    db.commit()
    db.refresh(project)
    return Envelope(data=_detail(project, app_now().date()))


@router.delete("/projects/{project_id}", response_model=Envelope[dict], summary="删除项目（仅管理员）")
def delete_project(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    project = _load_project(db, project_id)
    name = project.name
    db.delete(project)
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.delete",
        target_type="pm_project",
        target_id=project_id,
        summary=f"删除项目 {name}",
    )
    db.commit()
    return Envelope(data={"deleted": project_id})


@router.put(
    "/projects/{project_id}/stages",
    response_model=Envelope[PmProjectDetail],
    summary="批量保存阶段表",
)
def save_stages(
    project_id: int,
    payload: list[PmStageIn],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    project = _load_project(db, project_id)
    if not payload:
        raise _err(400, 40001, "阶段表不能为空")
    seqs = [row.seq for row in payload]
    if len(set(seqs)) != len(seqs):
        raise _err(400, 40001, "阶段序号重复")
    project.stages.clear()
    db.flush()
    for row in sorted(payload, key=lambda r: r.seq):
        db.add(
            PmStage(
                project_id=project.id,
                seq=row.seq,
                name=row.name.strip(),
                group_name=_str_or_none(row.group_name),
                months=_dec(row.months, f"第{row.seq}行工期"),
                start_month=_dec(row.start_month, f"第{row.seq}行开始月"),
                end_month=_dec(row.end_month, f"第{row.seq}行结束月"),
                deliverables=_str_or_none(row.deliverables),
                pm_role=_str_or_none(row.pm_role),
                owner=_str_or_none(row.owner),
            )
        )
    project.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.stages",
        target_type="pm_project",
        target_id=project.id,
        summary=f"更新项目 {project.name} 的工期计划表（{len(payload)} 行）",
    )
    db.commit()
    db.refresh(project)
    return Envelope(data=_detail(project, app_now().date()))


@router.post(
    "/projects/{project_id}/stages/reset",
    response_model=Envelope[PmProjectDetail],
    summary="按标准模板重置阶段表",
)
def reset_stages(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    project = _load_project(db, project_id)
    db.flush()
    _apply_stage_template(db, project)
    project.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.stages_reset",
        target_type="pm_project",
        target_id=project.id,
        summary=f"按标准模板重置项目 {project.name} 的工期计划表",
    )
    db.commit()
    db.refresh(project)
    return Envelope(data=_detail(project, app_now().date()))


# --------------------------------------------------------------------------
# 三张全局参考表（可编辑，不跟项目绑定）
# --------------------------------------------------------------------------
@router.get("/processes", response_model=Envelope[list[PmProcessOut]], summary="施工实施步骤明细")
def list_processes(db: Session = Depends(get_db), user: User = Depends(require_internal)):
    rows = db.scalars(select(PmProcess).order_by(PmProcess.seq)).all()
    return Envelope(
        data=[
            PmProcessOut(
                id=r.id, seq=r.seq, group_name=r.group_name, name=r.name,
                content=r.content, qc_point=r.qc_point, predecessor=r.predecessor,
            )
            for r in rows
        ]
    )


@router.put("/processes/{item_id}", response_model=Envelope[PmProcessOut], summary="修改工序")
def update_process(
    item_id: int,
    payload: PmProcessIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(PmProcess, item_id)
    if row is None:
        raise _err(404, 40400, "工序不存在")
    if payload.seq is not None:
        row.seq = payload.seq
    if payload.group_name is not None:
        row.group_name = payload.group_name.strip()
    if payload.name is not None:
        row.name = payload.name.strip()
    row.content = payload.content if payload.content is not None else row.content
    row.qc_point = payload.qc_point if payload.qc_point is not None else row.qc_point
    row.predecessor = payload.predecessor if payload.predecessor is not None else row.predecessor
    db.commit()
    db.refresh(row)
    return Envelope(
        data=PmProcessOut(
            id=row.id, seq=row.seq, group_name=row.group_name, name=row.name,
            content=row.content, qc_point=row.qc_point, predecessor=row.predecessor,
        )
    )


@router.get("/cost-points", response_model=Envelope[list[PmCostPointOut]], summary="预算决算管理点")
def list_cost_points(db: Session = Depends(get_db), user: User = Depends(require_internal)):
    rows = db.scalars(select(PmCostPoint).order_by(PmCostPoint.seq)).all()
    return Envelope(
        data=[
            PmCostPointOut(
                id=r.id, seq=r.seq, phase=r.phase, point=r.point,
                action=r.action, risk=r.risk, owner=r.owner,
            )
            for r in rows
        ]
    )


@router.put("/cost-points/{item_id}", response_model=Envelope[PmCostPointOut], summary="修改管理点")
def update_cost_point(
    item_id: int,
    payload: PmCostPointIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(PmCostPoint, item_id)
    if row is None:
        raise _err(404, 40400, "管理点不存在")
    if payload.seq is not None:
        row.seq = payload.seq
    if payload.phase is not None:
        row.phase = payload.phase.strip()
    if payload.point is not None:
        row.point = payload.point.strip()
    row.action = payload.action if payload.action is not None else row.action
    row.risk = payload.risk if payload.risk is not None else row.risk
    row.owner = payload.owner if payload.owner is not None else row.owner
    db.commit()
    db.refresh(row)
    return Envelope(
        data=PmCostPointOut(
            id=row.id, seq=row.seq, phase=row.phase, point=row.point,
            action=row.action, risk=row.risk, owner=row.owner,
        )
    )


@router.get("/documents", response_model=Envelope[list[PmDocumentOut]], summary="预算决算配套单据")
def list_documents(db: Session = Depends(get_db), user: User = Depends(require_internal)):
    rows = db.scalars(select(PmDocument).order_by(PmDocument.seq)).all()
    return Envelope(
        data=[
            PmDocumentOut(
                id=r.id, seq=r.seq, cost_point=r.cost_point, name=r.name, usage=r.usage,
                required_fields=r.required_fields, flow=r.flow, archive=r.archive,
            )
            for r in rows
        ]
    )


@router.put("/documents/{item_id}", response_model=Envelope[PmDocumentOut], summary="修改配套单据")
def update_document(
    item_id: int,
    payload: PmDocumentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(PmDocument, item_id)
    if row is None:
        raise _err(404, 40400, "单据不存在")
    if payload.seq is not None:
        row.seq = payload.seq
    if payload.name is not None:
        row.name = payload.name.strip()
    row.cost_point = payload.cost_point if payload.cost_point is not None else row.cost_point
    row.usage = payload.usage if payload.usage is not None else row.usage
    row.required_fields = (
        payload.required_fields if payload.required_fields is not None else row.required_fields
    )
    row.flow = payload.flow if payload.flow is not None else row.flow
    row.archive = payload.archive if payload.archive is not None else row.archive
    db.commit()
    db.refresh(row)
    return Envelope(
        data=PmDocumentOut(
            id=row.id, seq=row.seq, cost_point=row.cost_point, name=row.name,
            usage=row.usage, required_fields=row.required_fields,
            flow=row.flow, archive=row.archive,
        )
    )


def _check_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise _err(400, 40001, "计划竣工日期不能早于开工日期")
