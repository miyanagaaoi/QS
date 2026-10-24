"""预算决算配套单据接口（CH-007）。

从 `api/pm.py` 拆出来，因为这组接口在 CH-007 后有明显独立逻辑：
审批节点推进 + 归档文件清单 + 勾选/批量勾选 + 操作历史。

## 数据结构（存在 pm_document 的 JSON 列里）
- `flow_nodes`: `["造价编制","财务复核","分管领导批准"]`（有序节点列表）
- `current_node`: 当前停在哪个节点（**只有项目副本**有值，模板不跟踪）
- `archive_files`: `[{"name","note","required","archived","archived_at","archived_by"}]`
- `archived_at` / `archived_by`: 该单据**全部**文件归档完成的时间与操作人

## 权限
- 读：`require_internal`；不传 `project_id` = 标准模板，仅管理员可读
- 改模板：仅管理员；节点/归档操作**只作用于项目副本**（模板行调用返回 409）
- 供货商：403
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_internal, write_audit
from ..models import PmDocument, PmDocumentLog, User, app_now
from ..schemas import (
    Envelope,
    PmArchiveFile,
    PmDocumentArchiveIn,
    PmDocumentBatchArchiveIn,
    PmDocumentFileIn,
    PmDocumentIn,
    PmDocumentLogOut,
    PmDocumentNodeIn,
    PmDocumentOut,
)
from .pm import _ensure_project_exists, _err, _guard_template, _str_or_none

router = APIRouter()


# --------------------------------------------------------------------------
# 输出与内部工具
# --------------------------------------------------------------------------
def document_out(row: PmDocument) -> PmDocumentOut:
    files = [PmArchiveFile(**f) for f in (row.archive_files or [])]
    total = len(files)
    done = sum(1 for f in files if f.archived)
    return PmDocumentOut(
        id=row.id,
        seq=row.seq,
        cost_point=row.cost_point,
        name=row.name,
        usage=row.usage,
        required_fields=row.required_fields,
        project_id=row.project_id,
        flow_nodes=list(row.flow_nodes or []),
        current_node=row.current_node,
        archive_files=files,
        archive_total=total,
        archive_done=done,
        archived=bool(total and done == total),
        archived_at=row.archived_at,
        archived_by=row.archived_by,
    )


def _load(db: Session, document_id: int) -> PmDocument:
    row = db.get(PmDocument, document_id)
    if row is None:
        raise _err(404, 40400, "单据不存在")
    return row


def _require_copy(row: PmDocument) -> None:
    if row.project_id is None:
        raise _err(409, 40900, "标准模板不跟踪节点与归档，请在具体项目下操作")


def _recompute_archived(row: PmDocument, user: User) -> None:
    """全部文件归档 → 记完成时间/人；否则清空。"""
    files = row.archive_files or []
    if files and all(f.get("archived") for f in files):
        if row.archived_at is None:
            row.archived_at = app_now()
            row.archived_by = user.real_name or user.username
    else:
        row.archived_at = None
        row.archived_by = None


def _log(
    db: Session,
    *,
    row: PmDocument,
    user: User,
    kind: str,
    from_value: str | None = None,
    to_value: str | None = None,
    remark: str | None = None,
) -> None:
    db.add(
        PmDocumentLog(
            document_id=row.id,
            project_id=row.project_id,
            kind=kind,
            from_value=from_value,
            to_value=to_value,
            remark=remark,
            operator_id=user.id,
            operator_name=user.real_name or user.username,
        )
    )


# --------------------------------------------------------------------------
# 列表 / 增 / 改 / 删
# --------------------------------------------------------------------------
@router.get("/documents", response_model=Envelope[list[PmDocumentOut]], summary="预算决算配套单据")
def list_documents(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    if project_id:
        _ensure_project_exists(db, project_id)
        db.commit()
        rows = db.scalars(
            select(PmDocument).where(PmDocument.project_id == project_id).order_by(PmDocument.seq)
        ).all()
    else:
        _guard_template(user)
        rows = db.scalars(
            select(PmDocument).where(PmDocument.project_id.is_(None)).order_by(PmDocument.seq)
        ).all()
    return Envelope(data=[document_out(r) for r in rows])


@router.post("/documents", response_model=Envelope[PmDocumentOut], summary="新增配套单据")
def create_document(
    payload: PmDocumentIn,
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
        select(func.max(PmDocument.seq)).where(
            PmDocument.project_id.is_(None) if template else PmDocument.project_id == project_id
        )
    )
    nodes = [n.strip() for n in (payload.flow_nodes or []) if n.strip()]
    files = [f.model_dump() for f in (payload.archive_files or [])]
    row = PmDocument(
        project_id=None if template else project_id,
        seq=int(payload.seq or (max_seq or 0) + 1),
        cost_point=_str_or_none(payload.cost_point),
        name=(payload.name or "新增单据").strip(),
        usage=_str_or_none(payload.usage),
        required_fields=_str_or_none(payload.required_fields),
        flow_nodes=nodes,
        current_node=None if template or not nodes else nodes[0],
        archive_files=files,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return Envelope(data=document_out(row))


@router.put("/documents/{item_id}", response_model=Envelope[PmDocumentOut], summary="修改配套单据")
def update_document(
    item_id: int,
    payload: PmDocumentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = _load(db, item_id)
    if row.project_id is None:
        _guard_template(user)
    if payload.seq is not None:
        row.seq = payload.seq
    if payload.name is not None:
        row.name = payload.name.strip()
    row.cost_point = payload.cost_point if payload.cost_point is not None else row.cost_point
    row.usage = payload.usage if payload.usage is not None else row.usage
    row.required_fields = (
        payload.required_fields if payload.required_fields is not None else row.required_fields
    )
    if payload.flow_nodes is not None:
        nodes = [n.strip() for n in payload.flow_nodes if n.strip()]
        row.flow_nodes = nodes
        # 当前节点被删/改名 → 落到第一步，避免悬空
        if row.current_node not in nodes:
            row.current_node = None if row.project_id is None else (nodes[0] if nodes else None)
    if payload.archive_files is not None:
        previous = {f["name"]: f for f in (row.archive_files or [])}
        merged: list[dict] = []
        for item in payload.archive_files:
            data = item.model_dump()
            prev = previous.get(data["name"])
            if prev and prev.get("archived"):
                # 编辑弹窗只维护"要求"，不负责勾选归档 → 保留已有归档状态
                data["archived"] = True
                data["archived_at"] = prev.get("archived_at")
                data["archived_by"] = prev.get("archived_by")
            merged.append(data)
        row.archive_files = merged
        _recompute_archived(row, user)
    db.commit()
    db.refresh(row)
    return Envelope(data=document_out(row))


@router.delete("/documents/{item_id}", response_model=Envelope[dict], summary="删除配套单据")
def delete_document(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = _load(db, item_id)
    if row.project_id is None:
        _guard_template(user)
    for log in db.scalars(
        select(PmDocumentLog).where(PmDocumentLog.document_id == item_id)
    ).all():
        db.delete(log)
    name, project_id = row.name, row.project_id
    db.delete(row)
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.document.delete",
        target_type="pm_document",
        target_id=item_id,
        summary=f"删除配套单据 {name}（项目 {project_id if project_id else '模板'}）",
    )
    db.commit()
    return Envelope(data={"deleted": item_id})


# --------------------------------------------------------------------------
# 审批节点推进 / 回退
# --------------------------------------------------------------------------
@router.post(
    "/documents/{item_id}/node",
    response_model=Envelope[PmDocumentOut],
    summary="推进/回退审批节点（写历史）",
)
def change_document_node(
    item_id: int,
    payload: PmDocumentNodeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = _load(db, item_id)
    _require_copy(row)
    nodes = list(row.flow_nodes or [])
    node = payload.node.strip()
    if node not in nodes:
        raise _err(400, 40001, "该节点不在审批流转中")
    if row.current_node == node:
        raise _err(400, 40001, "节点未发生变化")

    from_node = row.current_node
    row.current_node = node
    _log(db, row=row, user=user, kind="node", from_value=from_node, to_value=node)
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.document.node",
        target_type="pm_document",
        target_id=row.id,
        summary=f"单据 {row.name} 节点：{from_node or '未开始'} → {node}",
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=document_out(row))


# --------------------------------------------------------------------------
# 归档：单文件勾选 / 批量勾选 / 追加文件要求
# --------------------------------------------------------------------------
@router.post(
    "/documents/{item_id}/archive",
    response_model=Envelope[PmDocumentOut],
    summary="勾选/取消某个归档文件（写历史）",
)
def toggle_document_archive(
    item_id: int,
    payload: PmDocumentArchiveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = _load(db, item_id)
    _require_copy(row)
    files = [dict(f) for f in (row.archive_files or [])]
    target = next((f for f in files if f.get("name") == payload.file_name), None)
    if target is None:
        raise _err(404, 40400, "该归档文件不存在")
    if bool(target.get("archived")) == payload.archived:
        raise _err(400, 40001, "归档状态未发生变化")

    stamp = app_now().isoformat(timespec="seconds")
    operator = user.real_name or user.username
    target["archived"] = payload.archived
    target["archived_at"] = stamp if payload.archived else None
    target["archived_by"] = operator if payload.archived else None
    row.archive_files = files
    _recompute_archived(row, user)
    _log(
        db,
        row=row,
        user=user,
        kind="archive",
        to_value=payload.file_name,
        remark="归档" if payload.archived else "撤销归档",
    )
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.document.archive",
        target_type="pm_document",
        target_id=row.id,
        summary=f"单据 {row.name} 归档「{payload.file_name}」：{'已归档' if payload.archived else '撤销归档'}",
    )
    db.commit()
    db.refresh(row)
    return Envelope(data=document_out(row))


@router.post(
    "/documents/archive-batch",
    response_model=Envelope[dict],
    summary="多选批量归档 / 撤销归档",
)
def batch_archive_documents(
    payload: PmDocumentBatchArchiveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    """列表页多选：把选中单据的**全部归档文件**一次性勾上（或全部撤销）。"""
    updated = 0
    skipped: list[int] = []
    operator = user.real_name or user.username
    stamp = app_now().isoformat(timespec="seconds")
    for doc_id in payload.ids:
        row = db.get(PmDocument, doc_id)
        if row is None or row.project_id is None:
            skipped.append(doc_id)
            continue
        files = [dict(f) for f in (row.archive_files or [])]
        if not files:
            skipped.append(doc_id)
            continue
        for item in files:
            item["archived"] = payload.archived
            item["archived_at"] = stamp if payload.archived else None
            item["archived_by"] = operator if payload.archived else None
        row.archive_files = files
        _recompute_archived(row, user)
        _log(
            db,
            row=row,
            user=user,
            kind="archive",
            to_value=f"全部 {len(files)} 个文件",
            remark="批量归档" if payload.archived else "批量撤销归档",
        )
        updated += 1
    write_audit(
        db,
        request=request,
        user=user,
        action="pm.document.archive_batch",
        target_type="pm_document",
        summary=f"批量{'归档' if payload.archived else '撤销归档'} {updated} 张单据"
        + (f"，跳过 {len(skipped)} 张（无文件或模板）" if skipped else ""),
    )
    db.commit()
    return Envelope(data={"updated": updated, "skipped": skipped})


@router.post(
    "/documents/{item_id}/files",
    response_model=Envelope[PmDocumentOut],
    summary="追加一条需要归档的文件",
)
def add_document_file(
    item_id: int,
    payload: PmDocumentFileIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    row = _load(db, item_id)
    _require_copy(row)
    files = [dict(f) for f in (row.archive_files or [])]
    name = payload.name.strip()
    if any(f.get("name") == name for f in files):
        raise _err(400, 40001, "同名归档文件已存在")
    files.append(
        {
            "name": name,
            "note": _str_or_none(payload.note),
            "required": bool(payload.required),
            "archived": False,
            "archived_at": None,
            "archived_by": None,
        }
    )
    row.archive_files = files
    _recompute_archived(row, user)  # 追加了未归档文件 → 单据回到未完成
    db.commit()
    db.refresh(row)
    return Envelope(data=document_out(row))


@router.get(
    "/documents/{item_id}/logs",
    response_model=Envelope[list[PmDocumentLogOut]],
    summary="单据节点/归档操作历史",
)
def list_document_logs(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_internal),
):
    _load(db, item_id)
    rows = db.scalars(
        select(PmDocumentLog)
        .where(PmDocumentLog.document_id == item_id)
        .order_by(PmDocumentLog.id.desc())
    ).all()
    return Envelope(
        data=[
            PmDocumentLogOut(
                id=r.id,
                document_id=r.document_id,
                kind=r.kind,
                from_value=r.from_value,
                to_value=r.to_value,
                remark=r.remark,
                operator_name=r.operator_name,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )
