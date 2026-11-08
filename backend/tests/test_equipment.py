"""设备管理模块（CH-014）回归用例。

覆盖：
- 字典（9 种状态 / 11 类事件 / 5 种检验类型 / 预警阈值）
- 主台账增改查 + 台账编号唯一 + 特种设备登记号必填
- 四类子台账 CRUD、详情计数、强关联（asset_id 必须存在）
- 有子记录时禁止删设备（409），清空后可删
- 统计看板（总量/状态分布/等级分布/预警/事件统计）
- Excel 导出（表头与预警列）与导入（成功行 + 失败行原因）
- 权限：采购员可用，供货商 403
"""
from __future__ import annotations

from io import BytesIO

import pytest

from .conftest import auth


def _asset_payload(no: str = "EQ-T-001", **over) -> dict:
    payload = {
        "asset_no": no,
        "finance_no": "FA-T-001",
        "name": "测试换热器",
        "model": "BR0.35",
        "category": "换热器",
        "importance": "A",
        "is_special": False,
        "location": "测试站",
        "system_name": "热源",
        "commission_date": "2024-01-01",
        "warranty_start": "2024-01-01",
        "warranty_end": "2099-01-01",
        "design_life_years": 15,
        "scrap_date": "2039-01-01",
        "purchase_value": "100000",
        "supplier": "测试供应商",
        "status": "在用",
        "owner": "张三",
        "remark": "pytest",
    }
    payload.update(over)
    return payload


def _create_asset(client, token: str, no: str = "EQ-T-001", **over) -> dict:
    resp = client.post("/api/eq/assets", json=_asset_payload(no, **over), headers=auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    return body["data"]


# ---------------------------------------------------------------------------
# 字典
# ---------------------------------------------------------------------------
def test_meta_dictionaries_match_template(client, admin_token):
    data = client.get("/api/eq/meta", headers=auth(admin_token)).json()["data"]
    assert len(data["asset_status"]) == 9
    assert len(data["event_types"]) == 11
    assert len(data["check_types"]) == 5
    assert data["importance"] == ["A", "B", "C"]
    assert data["warranty_warn_days"] == 30
    assert data["check_warn_days"] == 15
    assert "日常巡检" in data["event_types"]
    assert "报废处置" in data["event_types"]


# ---------------------------------------------------------------------------
# 主台账
# ---------------------------------------------------------------------------
def test_create_asset_and_uniqueness(client, admin_token):
    asset = _create_asset(client, admin_token, "EQ-U-001")
    assert asset["asset_no"] == "EQ-U-001"
    assert asset["days_to_warranty"] is not None

    dup = client.post("/api/eq/assets", json=_asset_payload("EQ-U-001"), headers=auth(admin_token))
    assert dup.status_code == 409
    assert dup.json()["code"] == 40900

    bad = client.post(
        "/api/eq/assets",
        json=_asset_payload("EQ-U-002", is_special=True, special_reg_no=""),
        headers=auth(admin_token),
    )
    assert bad.status_code == 400
    assert "特种设备" in bad.json()["message"]


def test_asset_list_filters_and_pagination(client, admin_token):
    _create_asset(client, admin_token, "EQ-L-001", status="备用", importance="C")
    data = client.get("/api/eq/assets?page=1&page_size=5", headers=auth(admin_token)).json()["data"]
    assert len(data["items"]) <= 5
    assert data["meta"]["total"] >= 1

    filtered = client.get(
        "/api/eq/assets?status=备用&keyword=EQ-L-001", headers=auth(admin_token)
    ).json()["data"]
    assert any(item["asset_no"] == "EQ-L-001" for item in filtered["items"])


# ---------------------------------------------------------------------------
# 子台账
# ---------------------------------------------------------------------------
def test_child_tables_crud_and_detail(client, admin_token):
    asset = _create_asset(client, admin_token, "EQ-C-001")
    aid = asset["id"]

    event = client.post(
        "/api/eq/events",
        json={
            "asset_id": aid,
            "event_type": "定期维保",
            "occur_date": "2026-10-12",
            "plan_date": "2026-10-15",
            "content": "清洗换热板片",
            "cost": "3800",
            "accept_result": "合格",
        },
        headers=auth(admin_token),
    )
    assert event.status_code == 200, event.text
    assert event.json()["data"]["asset_no"] == "EQ-C-001"
    assert float(event.json()["data"]["cost"]) == 3800.0

    meter = client.post(
        "/api/eq/meters",
        json={
            "asset_id": aid,
            "name": "压力变送器",
            "valid_until": "2026-11-20",
            "cycle_months": 12,
            "status": "在用",
        },
        headers=auth(admin_token),
    )
    assert meter.status_code == 200, meter.text
    assert meter.json()["data"]["expire_status"] in ("warn", "ok", "overdue")

    special = client.post(
        "/api/eq/specials",
        json={"asset_id": aid, "check_type": "外部检验", "valid_until": "2027-03-17"},
        headers=auth(admin_token),
    )
    assert special.status_code == 200, special.text

    spare = client.post(
        "/api/eq/spares",
        json={
            "asset_id": aid,
            "part_name": "密封垫",
            "qty": "4",
            "unit_price": "1250",
            "replace_date": "2026-10-14",
        },
        headers=auth(admin_token),
    )
    assert spare.status_code == 200, spare.text
    assert float(spare.json()["data"]["amount"]) == 5000.0  # 金额自动 = 数量 × 单价

    detail = client.get(f"/api/eq/assets/{aid}", headers=auth(admin_token)).json()["data"]
    assert detail["event_count"] == 1
    assert detail["meter_count"] == 1
    assert detail["special_count"] == 1
    assert detail["spare_count"] == 1
    assert len(detail["events"]) == 1


def test_child_requires_existing_asset(client, admin_token):
    resp = client.post(
        "/api/eq/events",
        json={"asset_id": 999999, "event_type": "日常巡检"},
        headers=auth(admin_token),
    )
    assert resp.status_code == 400
    assert "所选设备不存在" in resp.json()["message"]


def test_delete_asset_blocked_by_children(client, admin_token):
    asset = _create_asset(client, admin_token, "EQ-D-001")
    aid = asset["id"]
    event = client.post(
        "/api/eq/events",
        json={"asset_id": aid, "event_type": "日常巡检"},
        headers=auth(admin_token),
    ).json()["data"]

    blocked = client.delete(f"/api/eq/assets/{aid}", headers=auth(admin_token))
    assert blocked.status_code == 409
    assert "子台账" in blocked.json()["message"]

    assert client.delete(f"/api/eq/events/{event['id']}", headers=auth(admin_token)).status_code == 200
    assert client.delete(f"/api/eq/assets/{aid}", headers=auth(admin_token)).status_code == 200


# ---------------------------------------------------------------------------
# 看板
# ---------------------------------------------------------------------------
def test_board_statistics(client, admin_token):
    asset = _create_asset(
        client,
        admin_token,
        "EQ-B-001",
        status="维修中",
        importance="B",
        warranty_start="1999-01-01",
        warranty_end="2000-01-01",
    )
    client.post(
        "/api/eq/events",
        json={"asset_id": asset["id"], "event_type": "故障维修", "occur_date": "2026-01-05"},
        headers=auth(admin_token),
    )
    board = client.get("/api/eq/board", headers=auth(admin_token)).json()["data"]
    assert board["total"] >= 1
    assert len(board["by_status"]) == 9
    assert len(board["by_importance"]) == 3
    assert len(board["warnings"]) == 7
    assert board["event_total"] >= 1
    # 质保已超期（2000-01-01）应计入预警
    over = next(w for w in board["warnings"] if w["label"] == "质保已超期")
    assert over["count"] >= 1


# ---------------------------------------------------------------------------
# 导出 / 导入
# ---------------------------------------------------------------------------
def test_export_assets_xlsx(client, admin_token):
    from openpyxl import load_workbook

    _create_asset(client, admin_token, "EQ-E-001")
    resp = client.get("/api/eq/assets/export", headers=auth(admin_token))
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]
    ws = load_workbook(BytesIO(resp.content)).active
    headers = [c.value for c in ws[1]]
    assert "台账编号" in headers
    assert "距质保到期(天)" in headers
    assert ws.max_row >= 2


def test_import_assets_and_events(client, admin_token):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "设备主台账"
    ws.append(["台账编号", "资产编号", "设备名称", "规格型号", "是否特种设备", "当前状态"])
    ws.append(["EQ-I-001", "FA-I-1", "导入泵", "ISG100", "否", "在用"])
    ws.append(["EQ-I-002", "", "导入阀", "DN200", "否", "在用"])
    ws.append(["EQ-I-001", "", "重复编号", "", "否", "在用"])  # 失败：编号重复
    ws.append(["EQ-I-003", "", "", "", "否", "在用"])  # 失败：缺名称
    buf = BytesIO()
    wb.save(buf)

    resp = client.post(
        "/api/eq/assets/import",
        files={"file": ("assets.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=auth(admin_token),
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["data"]
    assert result["total"] == 4
    assert result["created"] == 2
    assert result["failed"] == 2
    assert {e["row"] for e in result["errors"]} == {4, 5}

    # 事件导入：一行合法、一行台账编号不存在
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.append(["台账编号", "事件类型", "事件发生日期", "事件简述内容"])
    ws2.append(["EQ-I-001", "日常巡检", "2026-11-01", "巡检正常"])
    ws2.append(["NOT-EXIST", "故障维修", "2026-11-02", "x"])
    buf2 = BytesIO()
    wb2.save(buf2)
    resp2 = client.post(
        "/api/eq/events/import",
        files={"file": ("events.xlsx", buf2.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=auth(admin_token),
    )
    result2 = resp2.json()["data"]
    assert result2["created"] == 1
    assert result2["failed"] == 1
    assert "不存在" in result2["errors"][0]["reason"]


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def test_permissions(client, buyer_token, supplier_token):
    assert client.get("/api/eq/assets", headers=auth(buyer_token)).status_code == 200
    denied = client.get("/api/eq/assets", headers=auth(supplier_token))
    assert denied.status_code == 403
    assert denied.json()["code"] == 40300


def test_date_range_validation(client, admin_token):
    """日期倒挂必须被拒绝：质保期、检定/检验有效期。""""(CH-015)"""
    bad = client.post(
        "/api/eq/assets",
        json=_asset_payload("EQ-R-001", warranty_start="2026-12-01", warranty_end="2025-01-01"),
        headers=auth(admin_token),
    )
    assert bad.status_code == 400
    assert "质保期" in bad.json()["message"]

    asset = _create_asset(client, admin_token, "EQ-R-002")
    bad_meter = client.post(
        "/api/eq/meters",
        json={
            "asset_id": asset["id"],
            "name": "倒挂压力表",
            "last_check_date": "2026-12-01",
            "valid_until": "2026-01-01",
        },
        headers=auth(admin_token),
    )
    assert bad_meter.status_code == 400
    assert "检定有效期" in bad_meter.json()["message"]


def test_equipment_operations_are_audited(client, admin_token):
    """设备建档/改状态/删除都要写操作日志（与其它模块一致）。"""
    asset = _create_asset(client, admin_token, "EQ-AUDIT-001")
    client.put(
        f"/api/eq/assets/{asset['id']}",
        json=_asset_payload("EQ-AUDIT-001", status="维修中"),
        headers=auth(admin_token),
    )
    logs = client.get(
        "/api/admin/audit-logs?action=eq.asset.create&page_size=5", headers=auth(admin_token)
    ).json()["data"]
    assert logs["meta"]["total"] >= 1
    assert any("设备建档" in (item.get("summary") or "") for item in logs["items"])

    updated = client.get(
        "/api/admin/audit-logs?action=eq.asset.update&page_size=5", headers=auth(admin_token)
    ).json()["data"]
    assert any("状态 在用 → 维修中" in (item.get("summary") or "") for item in updated["items"])
