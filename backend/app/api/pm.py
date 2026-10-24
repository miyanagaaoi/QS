"""项目管理模块（CH-002 + CH-005）。

与「询价报价」完全独立：不读取也不引用任何 `rfq` 数据。

## 数据模型（CH-005 起）
三张参考表（施工工序 / 预算决算管理点 / 配套单据）都带 `project_id`：
- `project_id IS NULL` → **标准模板**，全公司一套，仅管理员维护；
- `project_id = X` → **项目 X 的副本**，新建项目时从模板复制，项目内可增删改，
  与模板、其它项目互不影响。

## 工序进度（CH-005）
项目副本的工序带四态状态（todo/doing/done/paused），允许并行的多个 doing；
每次状态变更写一条 `pm_process_log`（追加、不可改不可删）。

接口（前缀 /api/pm）：
    GET    /board                       看板（含各项目工序完成数）
    GET    /projects                    项目列表
    POST   /projects                    新建项目（自动生成 8 阶段 + 复制三张参考表副本）
    GET    /projects/{id}               项目详情（含阶段表）
    PUT    /projects/{id}               更新项目
    DELETE /projects/{id}               删除项目（仅管理员，级联删副本）
    PUT    /projects/{id}/stages        批量保存阶段表
    POST   /projects/{id}/stages/reset  按标准模板重置阶段表
    POST   /projects/{id}/copies/reset  按模板重置三张参考表副本

    GET    /processes?project_id=       工序（不传 project_id = 模板，仅管理员）
    POST   /processes?project_id=       新增一行
    PUT    /processes/{id}              修改一行
    DELETE /processes/{id}              删除一行（模板行仅管理员）
    POST   /processes/{id}/status       状态变更（写历史）
    GET    /processes/{id}/logs         状态变更历史
    GET/POST/PUT/DELETE /cost-points    预算决算管理点（同样支持 project_id）
    GET/POST/PUT/DELETE /documents      预算决算配套单据（同样支持 project_id）

权限：项目相关 require_internal（管理员 + 采购员）；**模板维护仅管理员**；供货商 403。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin, require_internal, write_audit
from ..models import (
    PM_STAGE_TEMPLATE,
    PmCostPoint,
    PmDocument,
    PmDocumentLog,
    PmProcess,
    PmProcessLog,
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
    PmProcessCreate,
    PmProcessIn,
    PmProcessLogOut,
    PmProcessOut,
    PmProcessStatusIn,
    PmProgressIn,
    PmProjectDetail,
    PmProjectIn,
    PmProjectOut,
    PmStageDistribution,
    PmStageIn,
    PmStageOut,
)

router = APIRouter()

DUE_SOON_DAYS = 30
PROCESS_STATUSES = ("todo", "doing", "done", "paused")


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------
def _err(status: int, code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _dec(value: str | None, field: str) -> Decimal | None:
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


def _fmt(value) -> str | None:
    return str(value) if value is not None else None


# --------------------------------------------------------------------------
# 项目派生指标
# --------------------------------------------------------------------------
def _progress(project: PmProject, today: date) -> dict[str, object]:
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
    finished = project.status == "done"
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


def _project_out(
    project: PmProject,
    today: date,
    process_counts: dict[int, tuple[int, int]] | None = None,
) -> PmProjectOut:
    done, total = (process_counts or {}).get(project.id, (0, 0))
    return PmProjectOut(
        id=project.id,
        name=project.name,
        code=project.code,
        current_stage=project.current_stage,
        start_date=project.start_date,
        plan_end_date=project.plan_end_date,
        total_months=_fmt(project.total_months),
        manager=project.manager,
        status=project.status,  # type: ignore[arg-type]
        remark=project.remark,
        created_at=project.created_at,
        updated_at=project.updated_at,
        stage_count=len(project.stages),
        process_done=done,
        process_total=total,
        **_progress(project, today),
    )


def _process_counts(db: Session) -> dict[int, tuple[int, int]]:
    """各项目工序完成情况 {project_id: (done, total)}。"""
    rows = db.execute(
        select(PmProcess.project_id, PmProcess.status, func.count())
        .where(PmProcess.project_id.is_not(None))
        .group_by(PmProcess.project_id, PmProcess.status)
    ).all()
    counts: dict[int, tuple[int, int]] = {}
    for project_id, status, count in rows:
        done, total = counts.get(project_id, (0, 0))
        total += count
        if status == "done":
            done += count
        counts[project_id] = (done, total)
    return counts


def _stage_out(stage: PmStage) -> PmStageOut:
    return PmStageOut(
        id=stage.id,
        seq=stage.seq,
        name=stage.name,
        group_name=stage.group_name,
        months=_fmt(stage.months),
        start_month=_fmt(stage.start_month),
        end_month=_fmt(stage.end_month),
        deliverables=stage.deliverables,
        pm_role=stage.pm_role,
        owner=stage.owner,
    )


def _detail(project: PmProject, today: date, counts=None) -> PmProjectDetail:
    base = _project_out(project, today, counts).model_dump()
    return PmProjectDetail(**base, stages=[_stage_out(x) for x in project.stages])


def _load_project(db: Session, project_id: int) -> PmProject:
    project = db.get(PmProject, project_id)
    if project is None:
        raise _err(404, 40400, "项目不存在")
    return project


# --------------------------------------------------------------------------
# 模板 → 项目副本
# --------------------------------------------------------------------------
def _copy_process_row(tpl: PmProcess, project_id: int) -> PmProcess:
    return PmProcess(
        project_id=project_id,
        seq=tpl.seq,
        group_name=tpl.group_name,
        name=tpl.name,
        content=tpl.content,
        qc_point=tpl.qc_point,
        predecessor=tpl.predecessor,
        status="todo",
    )


def _copy_cost_point_row(tpl: PmCostPoint, project_id: int) -> PmCostPoint:
    return PmCostPoint(
        project_id=project_id,
        seq=tpl.seq,
        phase=tpl.phase,
        point=tpl.point,
        action=tpl.action,
        risk=tpl.risk,
        owner=tpl.owner,
    )


def _copy_document_row(tpl: PmDocument, project_id: int) -> PmDocument:
    """复制单据到项目：节点与文件清单继承模板；归档状态清零、当前节点回到第一步。"""
    nodes = list(tpl.flow_nodes or [])
    files = [
        {**f, "archived": False, "archived_at": None, "archived_by": None}
        for f in (tpl.archive_files or [])
    ]
    return PmDocument(
        project_id=project_id,
        seq=tpl.seq,
        cost_point=tpl.cost_point,
        name=tpl.name,
        usage=tpl.usage,
        required_fields=tpl.required_fields,
        flow=tpl.flow,
        archive=tpl.archive,
        flow_nodes=nodes,
        current_node=nodes[0] if nodes else None,
        archive_files=files,
    )


def _copy_reference_tables(db: Session, project: PmProject, *, only_missing: bool = True) -> None:
    """把三张参考表的模板行复制一份给该项目。

    only_missing=True（默认）：只补该项目**还没有任何副本行**的表，不覆盖项目内修改；
    only_missing=False：先清空该项目副本再复制（"从模板重置"）。
    """
    specs = (
        (PmProcess, _copy_process_row),
        (PmCostPoint, _copy_cost_point_row),
        (PmDocument, _copy_document_row),
    )
    for model, builder in specs:
        existing = db.scalar(
            select(func.count()).select_from(model).where(model.project_id == project.id)
        )
        if existing and only_missing:
            continue
        if existing:
            rows = db.scalars(select(model).where(model.project_id == project.id)).all()
            if model is PmProcess:
                # 先删工序变更历史，否则外键约束会拦下工序行的删除
                ids = [row.id for row in rows]
                if ids:
                    for log in db.scalars(
                        select(PmProcessLog).where(PmProcessLog.process_id.in_(ids))
                    ).all():
                        db.delete(log)
                    db.flush()
            if model is PmDocument:
                ids = [row.id for row in rows]
                if ids:
                    for log in db.scalars(
                        select(PmDocumentLog).where(PmDocumentLog.document_id.in_(ids))
                    ).all():
                        db.delete(log)
                    db.flush()
            for row in rows:
                db.delete(row)
            db.flush()
        templates = db.scalars(
            select(model).where(model.project_id.is_(None)).order_by(model.seq)
        ).all()
        for tpl in templates:
            db.add(builder(tpl, project.id))


def ensure_all_project_copies(db: Session) -> int:
    """为还没有副本的项目补齐副本（幂等，不覆盖已有）。返回补齐的项目数。"""
    fixed = 0
    for project in db.scalars(select(PmProject)).all():
        has_copy = db.scalar(
            select(func.count()).select_from(PmProcess).where(PmProcess.project_id == project.id)
        )
        if has_copy:
            continue
        _copy_reference_tables(db, project, only_missing=True)
        fixed += 1
    return fixed


def _apply_stage_template(db: Session, project: PmProject) -> None:
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


# --------------------------------------------------------------------------
# 看板 / 项目
# --------------------------------------------------------------------------
@router.get("/board", response_model=Envelope[PmBoard], summary="项目管理看板汇总")
def board(db: Session = Depends(get_db), user: User = Depends(require_internal)):
    if ensure_all_project_copies(db):
        db.commit()
    today = app_now().date()
    projects = list(db.scalars(select(PmProject).order_by(PmProject.id)).all())
    counts = _process_counts(db)
    outs = [_project_out(p, today, counts) for p in projects]

    summary = PmBoardSummary(total=len(outs))
    for item in outs:
        setattr(summary, item.status, getattr(summary, item.status) + 1)
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


@router.get("/projects", response_model=Envelope[list[PmProjectOut]], summary="项目列表")
def list_projects(
    keyword: str | None = Query(None),
    stage: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    if ensure_all_project_copies(db):
        db.commit()
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
    counts = _process_counts(db)
    return Envelope(data=[_project_out(p, today, counts) for p in db.scalars(stmt).all()])


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
    _copy_reference_tables(db, project, only_missing=True)  # CH-005
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.create",
        target_type="pm_project",
        target_id=project.id,
        summary=f"新建项目 {project.name}（自动生成 8 阶段并复制参考表副本）",
    )
    db.commit()
    db.refresh(project)
    return Envelope(data=_detail(project, app_now().date(), _process_counts(db)))


@router.get("/projects/{project_id}", response_model=Envelope[PmProjectDetail], summary="项目详情")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    project = _load_project(db, project_id)
    _copy_reference_tables(db, project, only_missing=True)
    db.commit()
    db.refresh(project)
    return Envelope(data=_detail(project, app_now().date(), _process_counts(db)))


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
    return Envelope(data=_detail(project, app_now().date(), _process_counts(db)))


@router.delete("/projects/{project_id}", response_model=Envelope[dict], summary="删除项目（仅管理员）")
def delete_project(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    project = _load_project(db, project_id)
    name = project.name
    # 先删工序变更历史，再删副本行（外键方向：log → process）
    for log in db.scalars(select(PmProcessLog).where(PmProcessLog.project_id == project_id)).all():
        db.delete(log)
    for log in db.scalars(
        select(PmDocumentLog).where(PmDocumentLog.project_id == project_id)
    ).all():
        db.delete(log)
    db.flush()
    for model in (PmProcess, PmCostPoint, PmDocument):
        for row in db.scalars(select(model).where(model.project_id == project_id)).all():
            db.delete(row)
    db.flush()
    db.delete(project)
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.delete",
        target_type="pm_project",
        target_id=project_id,
        summary=f"删除项目 {name}（含参考表副本）",
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
    return Envelope(data=_detail(project, app_now().date(), _process_counts(db)))


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
    return Envelope(data=_detail(project, app_now().date(), _process_counts(db)))


@router.post(
    "/projects/{project_id}/copies/reset",
    response_model=Envelope[dict],
    summary="按模板重置该项目的三张参考表副本",
)
def reset_copies(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    project = _load_project(db, project_id)
    _copy_reference_tables(db, project, only_missing=False)
    project.updated_at = app_now()
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.project.copies_reset",
        target_type="pm_project",
        target_id=project.id,
        summary=f"按模板重置项目 {project.name} 的参考表副本（工序/管理点/单据）",
    )
    db.commit()
    return Envelope(
        data={"project_id": project_id, "reset": ["processes", "cost_points", "documents"]}
    )


# --------------------------------------------------------------------------
# 参考表通用：模板（project_id 为空）与项目副本
# --------------------------------------------------------------------------
def _guard_template(user: User) -> None:
    """模板只有管理员能改（CH-005 / FR-PM-16）。"""
    if user.role != "admin":
        raise _err(403, 40300, "标准模板仅管理员可维护")


def _ensure_project_exists(db: Session, project_id: int) -> PmProject:
    project = _load_project(db, project_id)
    _copy_reference_tables(db, project, only_missing=True)
    return project


def _process_out(row: PmProcess) -> PmProcessOut:
    return PmProcessOut(
        id=row.id,
        seq=row.seq,
        group_name=row.group_name,
        name=row.name,
        content=row.content,
        qc_point=row.qc_point,
        predecessor=row.predecessor,
        assignee=row.assignee,
        progress_remark=row.progress_remark,
        project_id=row.project_id,
        status=row.status,  # type: ignore[arg-type]
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _cost_point_out(row: PmCostPoint) -> PmCostPointOut:
    return PmCostPointOut(
        id=row.id,
        seq=row.seq,
        phase=row.phase,
        point=row.point,
        action=row.action,
        risk=row.risk,
        owner=row.owner,
        project_id=row.project_id,
    )


def _document_out(row: PmDocument) -> PmDocumentOut:
    return PmDocumentOut(
        id=row.id,
        seq=row.seq,
        cost_point=row.cost_point,
        name=row.name,
        usage=row.usage,
        required_fields=row.required_fields,
        flow=row.flow,
        archive=row.archive,
        project_id=row.project_id,
    )


# ---------- 施工工序 ----------
@router.get("/processes", response_model=Envelope[list[PmProcessOut]], summary="施工实施步骤明细")
def list_processes(
    project_id: int | None = Query(None, description="项目 ID；不传=标准模板（仅管理员）"),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    if project_id:
        _ensure_project_exists(db, project_id)
        db.commit()
        rows = db.scalars(
            select(PmProcess).where(PmProcess.project_id == project_id).order_by(PmProcess.seq)
        ).all()
    else:
        _guard_template(user)
        rows = db.scalars(
            select(PmProcess).where(PmProcess.project_id.is_(None)).order_by(PmProcess.seq)
        ).all()
    return Envelope(data=[_process_out(r) for r in rows])


@router.post("/processes", response_model=Envelope[PmProcessOut], summary="新增一行工序")
def create_process(
    payload: PmProcessCreate,
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    if not project_id:
        _guard_template(user)
        template = True
    else:
        _ensure_project_exists(db, project_id)
        template = False
    max_seq = db.scalar(
        select(func.max(PmProcess.seq)).where(
            PmProcess.project_id.is_(None) if template else PmProcess.project_id == project_id
        )
    )
    row = PmProcess(
        project_id=None if template else project_id,
        seq=int(payload.seq or (max_seq or 0) + 1),
        group_name=payload.group_name.strip(),
        name=payload.name.strip(),
        content=_str_or_none(payload.content),
        qc_point=_str_or_none(payload.qc_point),
        predecessor=_str_or_none(payload.predecessor),
        assignee=_str_or_none(payload.assignee),
        progress_remark=_str_or_none(payload.progress_remark),
        status="todo",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_process_out(row))


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
    if row.project_id is None:
        _guard_template(user)
    if payload.seq is not None:
        row.seq = payload.seq
    if payload.group_name is not None:
        row.group_name = payload.group_name.strip()
    if payload.name is not None:
        row.name = payload.name.strip()
    row.content = payload.content if payload.content is not None else row.content
    row.qc_point = payload.qc_point if payload.qc_point is not None else row.qc_point
    row.predecessor = payload.predecessor if payload.predecessor is not None else row.predecessor
    row.assignee = payload.assignee if payload.assignee is not None else row.assignee
    row.progress_remark = (
        payload.progress_remark if payload.progress_remark is not None else row.progress_remark
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_process_out(row))


@router.delete("/processes/{item_id}", response_model=Envelope[dict], summary="删除工序")
def delete_process(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(PmProcess, item_id)
    if row is None:
        raise _err(404, 40400, "工序不存在")
    if row.project_id is None:
        _guard_template(user)
    for log in db.scalars(select(PmProcessLog).where(PmProcessLog.process_id == item_id)).all():
        db.delete(log)
    name, project_id = row.name, row.project_id
    db.delete(row)
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.process.delete",
        target_type="pm_process",
        target_id=item_id,
        summary=f"删除工序 {name}（项目 {project_id if project_id else '模板'}）",
    )
    db.commit()
    return Envelope(data={"deleted": item_id})


@router.post(
    "/processes/{item_id}/status",
    response_model=Envelope[PmProcessOut],
    summary="变更工序状态（写变更历史）",
)
def change_process_status(
    item_id: int,
    payload: PmProcessStatusIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(PmProcess, item_id)
    if row is None:
        raise _err(404, 40400, "工序不存在")
    if row.project_id is None:
        raise _err(409, 40900, "标准模板不跟踪进度，请在具体项目下操作")
    if payload.status not in PROCESS_STATUSES:
        raise _err(400, 40001, f"未知状态：{payload.status}")
    if row.status == payload.status:
        raise _err(400, 40001, "状态未发生变化")

    now = app_now()
    from_status = row.status
    row.status = payload.status
    if payload.status == "doing" and row.started_at is None:
        row.started_at = now
    if payload.status == "done":
        if row.started_at is None:
            row.started_at = now
        row.finished_at = now
    if payload.status in ("todo", "paused") and from_status == "done":
        row.finished_at = None
    if payload.remark is not None:
        row.progress_remark = payload.remark

    db.add(
        PmProcessLog(
            process_id=row.id,
            project_id=row.project_id,
            kind="status",
            from_status=from_status,
            to_status=payload.status,
            remark=_str_or_none(payload.remark),
            operator_id=user.id,
            operator_name=user.real_name or user.username,
        )
    )
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.process.status",
        target_type="pm_process",
        target_id=row.id,
        summary=f"工序 {row.name}：{from_status} → {payload.status}（项目 {row.project_id}）",
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_process_out(row))


@router.get(
    "/processes/{item_id}/logs",
    response_model=Envelope[list[PmProcessLogOut]],
    summary="工序状态变更历史",
)
def list_process_logs(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(PmProcess, item_id)
    if row is None:
        raise _err(404, 40400, "工序不存在")
    rows = db.scalars(
        select(PmProcessLog)
        .where(PmProcessLog.process_id == item_id)
        .order_by(PmProcessLog.id.desc())
    ).all()
    return Envelope(
        data=[
            PmProcessLogOut(
                id=r.id,
                process_id=r.process_id,
                kind=r.kind,
                from_status=r.from_status,
                to_status=r.to_status,
                remark=r.remark,
                operator_name=r.operator_name,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


@router.post(
    "/processes/{item_id}/progress",
    response_model=Envelope[PmProcessOut],
    summary="更新进行中工序的当前进度（写一条进度历史）",
)
def update_process_progress(
    item_id: int,
    payload: PmProgressIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    """CH-006：只有"进行中"的工序才允许提交进度更新。

    - 不改状态、不改实际开始/完成时间，只把最新进度写回工序备注；
    - 追加一条 `kind='progress'` 的历史（from_status == to_status == doing），
      这样"谁在什么时候报告了什么进展"可完整追溯。
    """
    row = db.get(PmProcess, item_id)
    if row is None:
        raise _err(404, 40400, "工序不存在")
    if row.project_id is None:
        raise _err(409, 40900, "标准模板不跟踪进度，请在具体项目下操作")
    if row.status != "doing":
        raise _err(409, 40900, "只有「进行中」的工序可以更新进度")

    remark = payload.remark.strip()
    if not remark:
        raise _err(400, 40001, "请填写本次进度说明")

    row.progress_remark = remark
    db.add(
        PmProcessLog(
            process_id=row.id,
            project_id=row.project_id,
            kind="progress",
            from_status=row.status,
            to_status=row.status,
            remark=remark,
            operator_id=user.id,
            operator_name=user.real_name or user.username,
        )
    )
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.process.progress",
        target_type="pm_process",
        target_id=row.id,
        summary=f"更新工序进度 {row.name}（项目 {row.project_id}）：{remark[:60]}",
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=_process_out(row))


# ---------- 预算决算管理点 ----------
@router.get("/cost-points", response_model=Envelope[list[PmCostPointOut]], summary="预算决算管理点")
def list_cost_points(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    if project_id:
        _ensure_project_exists(db, project_id)
        db.commit()
        rows = db.scalars(
            select(PmCostPoint)
            .where(PmCostPoint.project_id == project_id)
            .order_by(PmCostPoint.seq)
        ).all()
    else:
        _guard_template(user)
        rows = db.scalars(
            select(PmCostPoint).where(PmCostPoint.project_id.is_(None)).order_by(PmCostPoint.seq)
        ).all()
    return Envelope(data=[_cost_point_out(r) for r in rows])


@router.post("/cost-points", response_model=Envelope[PmCostPointOut], summary="新增管理点")
def create_cost_point(
    payload: PmCostPointIn,
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    if not project_id:
        _guard_template(user)
        template = True
    else:
        _ensure_project_exists(db, project_id)
        template = False
    max_seq = db.scalar(
        select(func.max(PmCostPoint.seq)).where(
            PmCostPoint.project_id.is_(None) if template else PmCostPoint.project_id == project_id
        )
    )
    row = PmCostPoint(
        project_id=None if template else project_id,
        seq=int(payload.seq or (max_seq or 0) + 1),
        phase=(payload.phase or "其他").strip(),
        point=(payload.point or "新增管理点").strip(),
        action=_str_or_none(payload.action),
        risk=_str_or_none(payload.risk),
        owner=_str_or_none(payload.owner),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=_cost_point_out(row))


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
    if row.project_id is None:
        _guard_template(user)
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
    return Envelope(data=_cost_point_out(row))


@router.delete("/cost-points/{item_id}", response_model=Envelope[dict], summary="删除管理点")
def delete_cost_point(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = db.get(PmCostPoint, item_id)
    if row is None:
        raise _err(404, 40400, "管理点不存在")
    if row.project_id is None:
        _guard_template(user)
    point, project_id = row.point, row.project_id
    db.delete(row)
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.cost_point.delete",
        target_type="pm_cost_point",
        target_id=item_id,
        summary=f"删除管理点 {point}（项目 {project_id if project_id else '模板'}）",
    )
    db.commit()
    return Envelope(data={"deleted": item_id})


def _check_dates(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise _err(400, 40001, "计划竣工日期不能早于开工日期")
