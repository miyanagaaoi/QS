"""数据隔离回归用例：我方非管理员只能看到自己发出的询价单。

需求（2026-10）：我方账号中，除管理员外其余账号信息隔离，只能看到自己发的询价。

这里锁定的是**服务端边界**，而不是前端是否隐藏按钮：
即使直接构造请求（带 `only_mine=false`、或直接拿别人的单据 ID），也拿不到他人数据。

覆盖的泄漏面（每个都必须独立断言，漏一个就是真的泄漏）：
- 列表 `/rfqs`（含用 only_mine=false 尝试绕过）
- 详情 `/rfqs/{id}`、进度 `/rfqs/{id}/progress`、导出 `/rfqs/{id}/export`
- 比价明细 `/reports/rfq-comparison` 及其导出
- 汇总统计 `/reports/summary` 及其导出（**曾经漏掉，导致采购员看到全量金额**）
"""
from __future__ import annotations

import io

import pytest

from .conftest import auth


def _make_rfq(client, token: str, title: str, supplier_ids: list[int], lines: int = 2) -> dict:
    """用指定账号创建一张草稿询价单。"""
    from datetime import datetime, timedelta

    payload = {
        "title": title,
        "project": "隔离测试",
        "deadline": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S"),
        "supplier_ids": supplier_ids,
        "lines": [
            {"material_name": f"物料{i}", "unit": "个", "quantity": str(10 * i)}
            for i in range(1, lines + 1)
        ],
    }
    response = client.post("/api/rfqs", json=payload, headers=auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def _publish(client, token: str, rfq_id: int) -> None:
    response = client.post(f"/api/rfqs/{rfq_id}/publish", json={}, headers=auth(token))
    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0, response.text


@pytest.fixture()
def two_owners(client, admin_token, buyer_token, accounts):
    """造两张分属不同人的单据：一张采购员的、一张管理员的。"""
    sup = [accounts["suppliers"][0]["id"]]
    mine = _make_rfq(client, buyer_token, "隔离用例-采购员自己的单", sup, lines=2)
    _publish(client, buyer_token, mine["id"])
    others = _make_rfq(client, admin_token, "隔离用例-管理员的单", sup, lines=3)
    _publish(client, admin_token, others["id"])
    return {"mine": mine, "others": others}


def test_buyer_list_only_returns_own_rfqs(client, buyer_token, two_owners):
    """列表只返回自己创建的；并且不能用 only_mine=false 绕过。"""
    resp = client.get("/api/rfqs?page_size=200", headers=auth(buyer_token))
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    ids = {x["id"] for x in items}
    assert two_owners["mine"]["id"] in ids
    assert two_owners["others"]["id"] not in ids

    # 显式请求"全部"也必须仍被强制过滤
    bypass = client.get("/api/rfqs?page_size=200&only_mine=false", headers=auth(buyer_token))
    assert bypass.status_code == 200, bypass.text
    bypass_ids = {x["id"] for x in bypass.json()["data"]["items"]}
    assert two_owners["others"]["id"] not in bypass_ids, "only_mine=false 绕过了隔离"


def test_buyer_cannot_read_others_rfq(client, buyer_token, two_owners):
    """详情 / 进度 / 导出 三处都不得放行他人单据。"""
    rid = two_owners["others"]["id"]
    for path in (f"/api/rfqs/{rid}", f"/api/rfqs/{rid}/progress", f"/api/rfqs/{rid}/export"):
        resp = client.get(path, headers=auth(buyer_token))
        assert resp.status_code == 403, f"{path} 未拦截：{resp.status_code} {resp.text[:120]}"
        body = resp.json()
        assert body["code"] == 40300, body


def test_buyer_cannot_compare_others_rfq(client, buyer_token, two_owners):
    """比价明细及其导出不得放行他人单据。"""
    rid = two_owners["others"]["id"]
    for path in (
        f"/api/reports/rfq-comparison?rfq_id={rid}",
        f"/api/reports/rfq-comparison/export?rfq_id={rid}",
    ):
        resp = client.get(path, headers=auth(buyer_token))
        assert resp.status_code == 403, f"{path} 未拦截：{resp.status_code}"
        assert resp.json()["code"] == 40300


def test_buyer_summary_is_scoped_to_own_rfqs(client, admin_token, buyer_token, two_owners):
    """汇总统计：采购员的统计范围必须小于管理员（曾漏掉此处隔离）。"""
    admin_sum = client.get("/api/reports/summary", headers=auth(admin_token)).json()["data"]
    buyer_sum = client.get("/api/reports/summary", headers=auth(buyer_token)).json()["data"]

    assert buyer_sum["rfq_count"] < admin_sum["rfq_count"], "采购员看到了全量询价单统计"
    assert buyer_sum["line_count"] < admin_sum["line_count"], "采购员看到了全量明细统计"
    # 采购员自己的单有 2 行
    assert buyer_sum["line_count"] >= 2


def test_buyer_summary_export_is_scoped(client, admin_token, buyer_token, two_owners):
    """导出的汇总 xlsx 必须与页面同口径，不能"页面看不到、导出里有"。"""
    import openpyxl

    def _read_count(token: str, label: str) -> int:
        resp = client.get("/api/reports/summary/export", headers=auth(token))
        assert resp.status_code == 200, resp.text
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            cells = [c for c in row if c is not None]
            if cells and str(cells[0]).strip() == label:
                return int(float(cells[1]))
        raise AssertionError(f"导出文件里找不到 {label} 行")

    admin_count = _read_count(admin_token, "询价单数")
    buyer_count = _read_count(buyer_token, "询价单数")
    assert buyer_count < admin_count, f"导出未隔离：buyer={buyer_count} admin={admin_count}"


def test_admin_still_sees_everything(client, admin_token, two_owners):
    """管理员不受隔离限制（需求明确"除去管理员"）。"""
    resp = client.get("/api/rfqs?page_size=200", headers=auth(admin_token))
    ids = {x["id"] for x in resp.json()["data"]["items"]}
    assert two_owners["mine"]["id"] in ids, "管理员看不到采购员的单据"
    assert two_owners["others"]["id"] in ids

    # 管理员可以切「我创建的」
    mine_only = client.get("/api/rfqs?page_size=200&only_mine=true", headers=auth(admin_token))
    mine_ids = {x["id"] for x in mine_only.json()["data"]["items"]}
    assert two_owners["others"]["id"] in mine_ids
    assert two_owners["mine"]["id"] not in mine_ids
