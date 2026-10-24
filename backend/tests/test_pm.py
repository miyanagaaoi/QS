"""项目管理模块（CH-002）回归用例。

覆盖：
- 三张全局参考表默认数据（15 工序 / 14 管理点 / 12 单据）与单条编辑
- 项目新建自动生成 8 阶段标准工期，累计月数正确（建设期 24 / 含质保 48）
- 进度派生指标按日期计算（progress / remaining_days / overdue / due_soon）
- 阶段表批量保存、模板重置、序号重复与日期非法时的 400
- 看板汇总计数
- 权限：供货商 403；删除项目仅管理员

与报价模块**零关联**：本文件不涉及 rfq 任何数据，反过来也验证了模块独立性。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from .conftest import auth


def _create(client, token: str, **over) -> dict:
    today = date.today()
    payload = {
        "name": "PM 测试项目",
        "code": "PM-T-001",
        "current_stage": "施工实施",
        "start_date": (today - timedelta(days=100)).isoformat(),
        "plan_end_date": (today + timedelta(days=265)).isoformat(),
        "total_months": "24",
        "manager": "张三",
        "status": "active",
        "remark": "pytest",
    }
    payload.update(over)
    resp = client.post("/api/pm/projects", json=payload, headers=auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


# ---------------------------------------------------------------------------
# 全局参考表
# ---------------------------------------------------------------------------
def test_reference_tables_seeded(client, admin_token):
    for path, expected in (
        ("/api/pm/processes", 15),
        ("/api/pm/cost-points", 14),
        ("/api/pm/documents", 12),
    ):
        resp = client.get(path, headers=auth(admin_token))
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]
        assert len(items) == expected, f"{path} 条数应为 {expected}，实际 {len(items)}"


def test_reference_item_editable(client, admin_token):
    resp = client.get("/api/pm/processes", headers=auth(admin_token))
    first = resp.json()["data"][0]
    new_qc = first["qc_point"] + "（已复核）"
    upd = client.put(
        f"/api/pm/processes/{first['id']}", json={"qc_point": new_qc}, headers=auth(admin_token)
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["data"]["qc_point"] == new_qc
    # 只改指定字段，其它字段保留
    assert upd.json()["data"]["name"] == first["name"]


# ---------------------------------------------------------------------------
# 项目 + 8 阶段
# ---------------------------------------------------------------------------
def test_create_project_generates_eight_stages_with_cumulative_months(client, admin_token):
    project = _create(client, admin_token, name="阶段模板验证项目")
    stages = project["stages"]
    assert len(stages) == 8
    assert [s["name"] for s in stages][0] == "决策立项"
    assert [s["name"] for s in stages][-1] == "缺陷保修"

    # 累计月数：0→2→5→6.5→7.5→21.5→23→24→48（与 doc 工作簿示例一致）
    starts = [float(s["start_month"]) for s in stages]
    ends = [float(s["end_month"]) for s in stages]
    assert starts[0] == 0 and ends[0] == 2
    assert starts[1] == 2 and ends[1] == 5
    assert abs(ends[3] - 7.5) < 1e-6
    assert abs(ends[6] - 24) < 1e-6      # 建设工期合计（不含质保）
    assert abs(ends[7] - 48) < 1e-6      # 含 24 个月质保
    # 相邻行首尾相接
    for prev, cur in zip(ends, starts[1:]):
        assert abs(prev - cur) < 1e-6


def test_progress_derived_from_dates(client, admin_token):
    today = date.today()
    project = _create(
        client,
        admin_token,
        name="进度计算项目",
        start_date=(today - timedelta(days=50)).isoformat(),
        plan_end_date=(today + timedelta(days=50)).isoformat(),
        status="active",
    )
    assert project["progress"] == 50, project["progress"]
    assert project["remaining_days"] == 50
    assert project["overdue"] is False
    assert project["due_soon"] is False

    # 超期（计划竣工已过、未标记竣工）
    overdue = _create(
        client,
        admin_token,
        name="超期项目",
        start_date=(today - timedelta(days=30)).isoformat(),
        plan_end_date=(today - timedelta(days=5)).isoformat(),
        status="active",
    )
    assert overdue["overdue"] is True
    assert overdue["remaining_days"] == -5
    assert overdue["progress"] == 100  # 进度封顶 100

    # 30 天内到期
    soon = _create(
        client,
        admin_token,
        name="临期项目",
        start_date=(today - timedelta(days=20)).isoformat(),
        plan_end_date=(today + timedelta(days=10)).isoformat(),
        status="active",
    )
    assert soon["due_soon"] is True

    # 已竣工不受超期影响
    done = _create(
        client,
        admin_token,
        name="已竣工项目",
        start_date=(today - timedelta(days=60)).isoformat(),
        plan_end_date=(today - timedelta(days=10)).isoformat(),
        status="done",
    )
    assert done["overdue"] is False
    assert done["progress"] == 100


def test_reject_end_before_start(client, admin_token):
    today = date.today()
    resp = client.post(
        "/api/pm/projects",
        json={
            "name": "日期非法项目",
            "start_date": today.isoformat(),
            "plan_end_date": (today - timedelta(days=1)).isoformat(),
            "status": "active",
        },
        headers=auth(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == 40001


# ---------------------------------------------------------------------------
# 阶段表保存 / 重置
# ---------------------------------------------------------------------------
def test_save_stages_and_reset_template(client, admin_token):
    project = _create(client, admin_token, name="阶段保存项目")
    pid = project["id"]
    stages = project["stages"]
    stages[4]["months"] = "16"
    stages[4]["deliverables"] = "延长 2 个月"
    resp = client.put(f"/api/pm/projects/{pid}/stages", json=stages, headers=auth(admin_token))
    assert resp.status_code == 200, resp.text
    saved = resp.json()["data"]["stages"]
    assert saved[4]["months"] == "16.0" or float(saved[4]["months"]) == 16
    assert saved[4]["deliverables"] == "延长 2 个月"

    reset = client.post(f"/api/pm/projects/{pid}/stages/reset", headers=auth(admin_token))
    assert reset.status_code == 200, reset.text
    back = reset.json()["data"]["stages"]
    assert float(back[4]["months"]) == 14
    assert back[4]["deliverables"].startswith("分部分项验收")


def test_save_stages_rejects_duplicate_seq(client, admin_token):
    project = _create(client, admin_token, name="序号重复项目")
    pid = project["id"]
    stages = project["stages"]
    stages[1]["seq"] = stages[0]["seq"]
    resp = client.put(f"/api/pm/projects/{pid}/stages", json=stages, headers=auth(admin_token))
    assert resp.status_code == 400, resp.text
    assert "序号重复" in resp.json()["message"]


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------
def test_board_summary_counts(client, admin_token, buyer_token):
    before = client.get("/api/pm/board", headers=auth(buyer_token)).json()["data"]["summary"]
    today = date.today()
    _create(
        client,
        admin_token,
        name="看板进行中",
        start_date=(today - timedelta(days=10)).isoformat(),
        plan_end_date=(today + timedelta(days=100)).isoformat(),
        status="active",
    )
    _create(
        client,
        admin_token,
        name="看板已竣工",
        start_date=(today - timedelta(days=100)).isoformat(),
        plan_end_date=(today - timedelta(days=10)).isoformat(),
        status="done",
    )
    after = client.get("/api/pm/board", headers=auth(admin_token)).json()["data"]
    summary = after["summary"]
    assert summary["total"] >= before["total"] + 2
    assert summary["active"] >= before["active"] + 1
    assert summary["done"] >= before["done"] + 1
    assert isinstance(after["stage_distribution"], list)
    assert isinstance(after["upcoming"], list)


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def test_supplier_cannot_access_pm(client, supplier_token):
    for method, path in (
        ("get", "/api/pm/board"),
        ("get", "/api/pm/projects"),
        ("get", "/api/pm/processes"),
    ):
        resp = getattr(client, method)(path, headers=auth(supplier_token))
        assert resp.status_code == 403, f"{path} 应 403，实际 {resp.status_code}"
        assert resp.json()["code"] == 40300


def test_only_admin_can_delete_project(client, admin_token, buyer_token):
    project = _create(client, admin_token, name="删除权限项目")
    pid = project["id"]
    denied = client.delete(f"/api/pm/projects/{pid}", headers=auth(buyer_token))
    assert denied.status_code == 403, denied.text
    assert denied.json()["code"] == 40300

    ok = client.delete(f"/api/pm/projects/{pid}", headers=auth(admin_token))
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/pm/projects/{pid}", headers=auth(admin_token)).status_code == 404


# ===========================================================================
# CH-005：模板 + 项目副本、工序进度与变更历史
# ===========================================================================
def _copies_of(client, project_id: int, token: str) -> dict[str, list]:
    out = {}
    for key, path in (
        ("processes", "/api/pm/processes"),
        ("cost_points", "/api/pm/cost-points"),
        ("documents", "/api/pm/documents"),
    ):
        resp = client.get(f"{path}?project_id={project_id}", headers=auth(token))
        assert resp.status_code == 200, resp.text
        out[key] = resp.json()["data"]
    return out


def test_template_listing_admin_only(client, admin_token, buyer_token):
    admin_rows = client.get("/api/pm/processes", headers=auth(admin_token)).json()["data"]
    assert len(admin_rows) == 15
    assert all(row["project_id"] is None for row in admin_rows)

    denied = client.get("/api/pm/processes", headers=auth(buyer_token))
    assert denied.status_code == 403
    assert denied.json()["code"] == 40300


def test_new_project_copies_reference_tables(client, admin_token):
    project = _create(client, admin_token, name="副本复制项目")
    copies = _copies_of(client, project["id"], admin_token)
    assert len(copies["processes"]) == 15
    assert len(copies["cost_points"]) == 14
    assert len(copies["documents"]) == 12
    # 副本行都归属该项目，且初始状态为未开始
    assert all(row["project_id"] == project["id"] for row in copies["processes"])
    assert all(row["status"] == "todo" for row in copies["processes"])


def test_copy_edits_do_not_pollute_template(client, admin_token):
    project = _create(client, admin_token, name="副本隔离项目")
    copies = _copies_of(client, project["id"], admin_token)["processes"]
    target = copies[0]
    resp = client.put(
        f"/api/pm/processes/{target['id']}",
        json={"name": "副本改名", "qc_point": "副本质控点"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["name"] == "副本改名"

    templates = client.get("/api/pm/processes", headers=auth(admin_token)).json()["data"]
    same_seq = next(row for row in templates if row["seq"] == target["seq"])
    assert same_seq["name"] != "副本改名"
    assert same_seq["project_id"] is None


def test_process_status_flow_writes_history(client, admin_token, buyer_token):
    project = _create(client, admin_token, name="状态流转项目")
    row = _copies_of(client, project["id"], buyer_token)["processes"][0]

    doing = client.post(
        f"/api/pm/processes/{row['id']}/status",
        json={"status": "doing", "remark": "现场开工"},
        headers=auth(buyer_token),
    )
    assert doing.status_code == 200, doing.text
    body = doing.json()["data"]
    assert body["status"] == "doing"
    assert body["started_at"] is not None
    assert body["finished_at"] is None
    assert body["progress_remark"] == "现场开工"

    done = client.post(
        f"/api/pm/processes/{row['id']}/status",
        json={"status": "done"},
        headers=auth(buyer_token),
    )
    assert done.status_code == 200
    assert done.json()["data"]["finished_at"] is not None

    logs = client.get(f"/api/pm/processes/{row['id']}/logs", headers=auth(admin_token)).json()["data"]
    assert len(logs) == 2
    # 倒序：最新在前
    assert logs[0]["from_status"] == "doing" and logs[0]["to_status"] == "done"
    assert logs[1]["from_status"] == "todo" and logs[1]["to_status"] == "doing"
    assert logs[0]["operator_name"]  # 有操作人

    # 同状态再改 → 400，且不写历史
    again = client.post(
        f"/api/pm/processes/{row['id']}/status",
        json={"status": "done"},
        headers=auth(buyer_token),
    )
    assert again.status_code == 400
    assert len(client.get(f"/api/pm/processes/{row['id']}/logs", headers=auth(admin_token)).json()["data"]) == 2


def test_template_row_rejects_status_change(client, admin_token):
    template = client.get("/api/pm/processes", headers=auth(admin_token)).json()["data"][0]
    resp = client.post(
        f"/api/pm/processes/{template['id']}/status",
        json={"status": "done"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


def test_add_and_delete_copy_row(client, admin_token):
    project = _create(client, admin_token, name="增删行项目")
    pid = project["id"]
    created = client.post(
        f"/api/pm/processes?project_id={pid}",
        json={"name": "临时工序", "group_name": "试验检验"},
        headers=auth(admin_token),
    )
    assert created.status_code == 200, created.text
    new_row = created.json()["data"]
    assert new_row["project_id"] == pid
    assert new_row["status"] == "todo"
    assert len(_copies_of(client, pid, admin_token)["processes"]) == 16

    deleted = client.delete(f"/api/pm/processes/{new_row['id']}", headers=auth(admin_token))
    assert deleted.status_code == 200
    assert len(_copies_of(client, pid, admin_token)["processes"]) == 15
    # 模板行数不受影响
    assert len(client.get("/api/pm/processes", headers=auth(admin_token)).json()["data"]) == 15


def test_reset_copies_restores_template_state(client, admin_token):
    project = _create(client, admin_token, name="重置副本项目")
    pid = project["id"]
    row = _copies_of(client, pid, admin_token)["processes"][0]
    client.post(
        f"/api/pm/processes/{row['id']}/status", json={"status": "done"}, headers=auth(admin_token)
    )
    client.put(
        f"/api/pm/processes/{row['id']}", json={"name": "被改过的名字"}, headers=auth(admin_token)
    )

    reset = client.post(f"/api/pm/projects/{pid}/copies/reset", headers=auth(admin_token))
    assert reset.status_code == 200, reset.text
    after = _copies_of(client, pid, admin_token)
    assert len(after["processes"]) == 15
    assert after["processes"][0]["status"] == "todo"
    assert after["processes"][0]["name"] != "被改过的名字"


def test_board_reports_process_progress(client, admin_token):
    project = _create(client, admin_token, name="看板工序数项目")
    pid = project["id"]
    rows = _copies_of(client, pid, admin_token)["processes"]
    for row in rows[:3]:
        client.post(
            f"/api/pm/processes/{row['id']}/status", json={"status": "done"}, headers=auth(admin_token)
        )
    board = client.get("/api/pm/board", headers=auth(admin_token)).json()["data"]
    item = next(p for p in board["projects"] if p["id"] == pid)
    assert item["process_done"] == 3
    assert item["process_total"] == 15


def test_delete_project_cleans_copies_and_logs(client, admin_token):
    project = _create(client, admin_token, name="删除级联项目")
    pid = project["id"]
    row = _copies_of(client, pid, admin_token)["processes"][0]
    client.post(
        f"/api/pm/processes/{row['id']}/status", json={"status": "doing"}, headers=auth(admin_token)
    )
    assert client.delete(f"/api/pm/projects/{pid}", headers=auth(admin_token)).status_code == 200
    # 项目没了，副本接口应 404
    assert client.get(f"/api/pm/processes?project_id={pid}", headers=auth(admin_token)).status_code == 404
    # 模板仍然是 15 条
    assert len(client.get("/api/pm/processes", headers=auth(admin_token)).json()["data"]) == 15


def test_progress_update_only_when_doing(client, admin_token, buyer_token):
    project = _create(client, admin_token, name="进度更新项目")
    row = _copies_of(client, project["id"], buyer_token)["processes"][0]

    # 未开始 → 拒绝
    rejected = client.post(
        f"/api/pm/processes/{row['id']}/progress",
        json={"remark": "还没开始就报进度"},
        headers=auth(buyer_token),
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == 40900

    # 转为进行中后可以更新
    client.post(
        f"/api/pm/processes/{row['id']}/status",
        json={"status": "doing"},
        headers=auth(buyer_token),
    )
    updated = client.post(
        f"/api/pm/processes/{row['id']}/progress",
        json={"remark": "土方开挖完成 40%"},
        headers=auth(buyer_token),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()["data"]
    assert body["status"] == "doing"           # 状态不变
    assert body["progress_remark"] == "土方开挖完成 40%"

    # 纯空格备注 → 400
    blank = client.post(
        f"/api/pm/processes/{row['id']}/progress",
        json={"remark": "   "},
        headers=auth(buyer_token),
    )
    assert blank.status_code == 400
    assert blank.json()["code"] == 40001


def test_progress_update_writes_history_entry(client, admin_token):
    project = _create(client, admin_token, name="进度历史项目")
    row = _copies_of(client, project["id"], admin_token)["processes"][0]
    client.post(
        f"/api/pm/processes/{row['id']}/status", json={"status": "doing"}, headers=auth(admin_token)
    )
    client.post(
        f"/api/pm/processes/{row['id']}/progress",
        json={"remark": "第一段管道焊接完成"},
        headers=auth(admin_token),
    )
    logs = client.get(f"/api/pm/processes/{row['id']}/logs", headers=auth(admin_token)).json()["data"]
    assert len(logs) == 2
    assert logs[0]["kind"] == "progress"
    assert logs[0]["from_status"] == "doing" and logs[0]["to_status"] == "doing"
    assert logs[0]["remark"] == "第一段管道焊接完成"
    assert logs[1]["kind"] == "status"


def test_template_rejects_progress_update(client, admin_token):
    template = client.get("/api/pm/processes", headers=auth(admin_token)).json()["data"][0]
    resp = client.post(
        f"/api/pm/processes/{template['id']}/progress",
        json={"remark": "模板不跟踪进度"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40900


# ===========================================================================
# CH-007：审批节点列表 + 归档文件清单 + 批量归档
# ===========================================================================
def _first_doc(client, project_id: int | None, token: str) -> dict:
    path = "/api/pm/documents" if project_id is None else f"/api/pm/documents?project_id={project_id}"
    return client.get(path, headers=auth(token)).json()["data"][0]


def test_document_template_has_nodes_and_files(client, admin_token):
    doc = _first_doc(client, None, admin_token)
    assert doc["flow_nodes"], "模板应有审批节点"
    assert all(isinstance(n, str) and n.strip() for n in doc["flow_nodes"])
    assert doc["current_node"] is None, "标准模板不跟踪当前节点"
    assert doc["archive_total"] >= 1
    assert doc["archive_files"][0]["archived"] is False


def test_document_node_advance_and_history(client, admin_token, buyer_token):
    project = _create(client, admin_token, name="单据节点项目")
    doc = _first_doc(client, project["id"], buyer_token)
    nodes = doc["flow_nodes"]
    assert len(nodes) >= 2
    assert doc["current_node"] == nodes[0], "新项目应从第一个节点开始"

    resp = client.post(
        f"/api/pm/documents/{doc['id']}/node", json={"node": nodes[1]}, headers=auth(buyer_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["current_node"] == nodes[1]

    again = client.post(
        f"/api/pm/documents/{doc['id']}/node", json={"node": nodes[1]}, headers=auth(buyer_token)
    )
    assert again.status_code == 400

    bad = client.post(
        f"/api/pm/documents/{doc['id']}/node", json={"node": "不存在的节点"}, headers=auth(buyer_token)
    )
    assert bad.status_code == 400

    logs = client.get(
        f"/api/pm/documents/{doc['id']}/logs", headers=auth(admin_token)
    ).json()["data"]
    assert logs[0]["kind"] == "node"
    assert logs[0]["from_value"] == nodes[0] and logs[0]["to_value"] == nodes[1]


def test_document_template_rejects_node_and_archive(client, admin_token):
    doc = _first_doc(client, None, admin_token)
    node_resp = client.post(
        f"/api/pm/documents/{doc['id']}/node",
        json={"node": doc["flow_nodes"][0]},
        headers=auth(admin_token),
    )
    assert node_resp.status_code == 409
    archive_resp = client.post(
        f"/api/pm/documents/{doc['id']}/archive",
        json={"file_name": doc["archive_files"][0]["name"], "archived": True},
        headers=auth(admin_token),
    )
    assert archive_resp.status_code == 409


def test_document_archive_toggle_and_completion(client, admin_token):
    project = _create(client, admin_token, name="单据归档项目")
    doc = _first_doc(client, project["id"], admin_token)
    files = doc["archive_files"]

    first = client.post(
        f"/api/pm/documents/{doc['id']}/archive",
        json={"file_name": files[0]["name"], "archived": True},
        headers=auth(admin_token),
    )
    assert first.status_code == 200
    body = first.json()["data"]
    assert body["archive_done"] == 1
    assert body["archive_files"][0]["archived_at"]

    dup = client.post(
        f"/api/pm/documents/{doc['id']}/archive",
        json={"file_name": files[0]["name"], "archived": True},
        headers=auth(admin_token),
    )
    assert dup.status_code == 400

    added = client.post(
        f"/api/pm/documents/{doc['id']}/files",
        json={"name": "监理验收意见单", "note": "需监理签认"},
        headers=auth(admin_token),
    )
    assert added.status_code == 200
    assert added.json()["data"]["archived"] is False
    assert added.json()["data"]["archive_total"] == len(files) + 1

    dup_file = client.post(
        f"/api/pm/documents/{doc['id']}/files",
        json={"name": "监理验收意见单"},
        headers=auth(admin_token),
    )
    assert dup_file.status_code == 400

    undo = client.post(
        f"/api/pm/documents/{doc['id']}/archive",
        json={"file_name": files[0]["name"], "archived": False},
        headers=auth(admin_token),
    )
    assert undo.status_code == 200
    assert undo.json()["data"]["archive_done"] == 0


def test_document_batch_archive(client, admin_token):
    project = _create(client, admin_token, name="批量归档项目")
    docs = client.get(
        f"/api/pm/documents?project_id={project['id']}", headers=auth(admin_token)
    ).json()["data"]
    ids = [d["id"] for d in docs[:3]]
    template_id = _first_doc(client, None, admin_token)["id"]

    resp = client.post(
        "/api/pm/documents/archive-batch",
        json={"ids": ids + [template_id], "archived": True},
        headers=auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["updated"] == 3
    assert template_id in body["skipped"], "模板行应被跳过"

    after = client.get(
        f"/api/pm/documents?project_id={project['id']}", headers=auth(admin_token)
    ).json()["data"]
    assert all(d["archived"] for d in after[:3])


def test_document_edit_keeps_archive_state(client, admin_token):
    project = _create(client, admin_token, name="单据编辑保留归档")
    doc = _first_doc(client, project["id"], admin_token)
    payload = {
        "name": doc["name"],
        "flow_nodes": doc["flow_nodes"],
        "archive_files": [
            {"name": f["name"], "note": f.get("note"), "required": True} for f in doc["archive_files"]
        ],
    }
    client.post(
        f"/api/pm/documents/{doc['id']}/archive",
        json={"file_name": doc["archive_files"][0]["name"], "archived": True},
        headers=auth(admin_token),
    )
    saved = client.put(
        f"/api/pm/documents/{doc['id']}", json=payload, headers=auth(admin_token)
    )
    assert saved.status_code == 200, saved.text
    state = saved.json()["data"]
    assert state["archive_files"][0]["archived"] is True, "编辑不应清掉已勾选的归档状态"
