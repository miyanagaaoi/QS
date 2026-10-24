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
