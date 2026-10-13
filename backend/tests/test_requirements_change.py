"""需求变更（2026-10）的回归用例。

覆盖两批变更：
1. 「追加受邀供货商」：已发布且未截止的询价单可追加未被分派的供货商
2. 「首次登录是否改密」改为按账号开关控制，**默认关闭**

这些用例固化新语义，防止回退到"已发布一律禁改分派"或"新建账号一律强制改密"。
"""
from __future__ import annotations

import pytest

from .conftest import auth


def _assignees(detail: dict) -> list[dict]:
    return detail["assignees"]


def _publish(client, token: str, rfq_id: int) -> dict:
    response = client.post(f"/api/rfqs/{rfq_id}/publish", json={}, headers=auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


def _append(client, token: str, rfq_id: int, supplier_ids: list[int]):
    return client.post(
        f"/api/rfqs/{rfq_id}/append-suppliers",
        json={"supplier_ids": supplier_ids},
        headers=auth(token),
    )


# ---------------------------------------------------------------------------
# 一、追加供货商
# ---------------------------------------------------------------------------
def test_append_supplier_to_published_rfq(client, buyer_token, accounts, rfq_factory):
    """已发布未截止：追加未被分派的供货商成功，且不影响既有分派。"""
    detail = rfq_factory(lines=3, supplier_indexes=[0])
    published = _publish(client, buyer_token, detail["id"])
    assert len(_assignees(published)) == 1

    target = accounts["suppliers"][1]["id"]
    response = _append(client, buyer_token, detail["id"], [target])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    assert "已追加 1 家" in body["message"]

    assignees = _assignees(body["data"])
    assert len(assignees) == 2
    added = [a for a in assignees if a["supplier_id"] == target][0]
    # 新分派记为待报价，并带上当前明细行数（供前端显示 0/N）
    assert added["status"] == "pending"
    assert added["line_count"] == 3
    assert added["quoted_line_count"] == 0
    # 原有分派不受影响
    original = [a for a in assignees if a["supplier_id"] == accounts["suppliers"][0]["id"]][0]
    assert original["line_count"] == 3


def test_append_rejects_already_assigned(client, buyer_token, accounts, rfq_factory):
    """已被分派的供货商不可重复追加，且返回可读原因。"""
    detail = rfq_factory(lines=2, supplier_indexes=[0])
    _publish(client, buyer_token, detail["id"])

    response = _append(client, buyer_token, detail["id"], [accounts["suppliers"][0]["id"]])
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == 40900
    assert accounts["suppliers"][0]["name"] in body["message"]


def test_append_mixed_partial_success(client, buyer_token, accounts, rfq_factory):
    """混合追加：新的成功、已分派的被跳过，并在 message 中说明。"""
    detail = rfq_factory(lines=2, supplier_indexes=[0])
    _publish(client, buyer_token, detail["id"])

    response = _append(
        client,
        buyer_token,
        detail["id"],
        [accounts["suppliers"][0]["id"], accounts["suppliers"][2]["id"]],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert "跳过 1 家" in body["message"]
    assert len(_assignees(body["data"])) == 2


def test_append_rejected_after_deadline(client, admin_token, buyer_token, accounts, rfq_factory):
    """已截止（含手动截止）后不可追加，返回 40301。"""
    detail = rfq_factory(lines=2, supplier_indexes=[0])
    _publish(client, buyer_token, detail["id"])

    closed = client.post(f"/api/rfqs/{detail['id']}/close", json={}, headers=auth(buyer_token))
    assert closed.status_code == 200, closed.text

    response = _append(client, buyer_token, detail["id"], [accounts["suppliers"][3]["id"]])
    assert response.status_code == 403, response.text
    assert response.json()["code"] == 40301


def test_append_rejected_for_draft(client, buyer_token, accounts, rfq_factory):
    """草稿不应使用追加接口（应直接编辑受邀名单）。"""
    detail = rfq_factory(lines=2, supplier_indexes=[0])
    response = _append(client, buyer_token, detail["id"], [accounts["suppliers"][1]["id"]])
    assert response.status_code == 409, response.text
    assert response.json()["code"] == 40900


def test_append_requires_internal_role(client, accounts, supplier_token, rfq_factory, buyer_token):
    """供货商不可追加供货商（越权拦截）。"""
    detail = rfq_factory(lines=1, supplier_indexes=[0])
    _publish(client, buyer_token, detail["id"])

    response = _append(client, supplier_token, detail["id"], [accounts["suppliers"][1]["id"]])
    assert response.status_code == 403, response.text
    assert response.json()["code"] == 40300


def test_appended_supplier_can_quote_without_touching_others(
    client, buyer_token, accounts, rfq_factory, supplier_token
):
    """追加后：新供货商可看到全部明细并保存报价；已报价供货商的数据不被重置。"""
    detail = rfq_factory(lines=2, supplier_indexes=[0])
    _publish(client, buyer_token, detail["id"])

    # 原供货商先报价
    original = client.get(f"/api/supplier/rfqs/{detail['id']}", headers=auth(supplier_token)).json()["data"]
    first_uid = original["lines"][0]["line_uid"]
    saved = client.put(
        f"/api/supplier/rfqs/{detail['id']}/quotes",
        json={"lines": [{"line_uid": first_uid, "price_incl_tax": "100.00", "tax_rate": "0.1300"}]},
        headers=auth(supplier_token),
    )
    assert saved.status_code == 200, saved.text

    # 追加第二家
    second = accounts["suppliers"][1]
    appended = _append(client, buyer_token, detail["id"], [second["id"]])
    assert appended.json()["code"] == 0

    # 原供货商的报价仍在（追加不应重置他人进度）
    after = client.get(f"/api/supplier/rfqs/{detail['id']}", headers=auth(supplier_token)).json()["data"]
    assert after["lines"][0]["quote"]["price_incl_tax"] == "100.00"

    # 新供货商：能看到 2 行明细、报价为空，并可保存
    from .conftest import _login  # 延迟导入避免循环

    new_token = _login(client, second["username"], second["password"])
    fresh = client.get(f"/api/supplier/rfqs/{detail['id']}", headers=auth(new_token))
    assert fresh.status_code == 200, fresh.text
    fresh_detail = fresh.json()["data"]
    assert len(fresh_detail["lines"]) == 2
    assert all(line["quote"] is None for line in fresh_detail["lines"])
    assert fresh_detail["readonly"] is False

    new_uid = fresh_detail["lines"][0]["line_uid"]
    ok = client.put(
        f"/api/supplier/rfqs/{detail['id']}/quotes",
        json={"lines": [{"line_uid": new_uid, "price_incl_tax": "88.00", "tax_rate": "0.1300"}]},
        headers=auth(new_token),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["code"] == 0


# ---------------------------------------------------------------------------
# 二、首次登录改密开关（默认关闭）
# ---------------------------------------------------------------------------
def _create_internal(client, admin_token: str, username: str, *, must_change: bool):
    return client.post(
        "/api/admin/users",
        json={
            "username": username,
            "real_name": "改密开关用例",
            "role": "buyer",
            "initial_password": "SwitchTest2026",
            "must_change_password": must_change,
        },
        headers=auth(admin_token),
    )


def _cleanup_user(client, admin_token: str, username: str) -> None:
    """停用（系统不允许删除账号，符合 FR-ACC-07）。"""
    listing = client.get(
        f"/api/admin/users?keyword={username}&page_size=50", headers=auth(admin_token)
    ).json()
    for item in listing.get("data", {}).get("items", []):
        if item["username"] == username and item["status"] == 1:
            client.post(f"/api/admin/users/{item['id']}/toggle-status", headers=auth(admin_token))


def test_new_account_default_does_not_force_password_change(client, admin_token):
    """默认（不传 must_change_password）时，新账号登录后可直接访问业务接口。"""
    username = "t_switch_default"
    response = client.post(
        "/api/admin/users",
        json={
            "username": username,
            "real_name": "默认不强制改密",
            "role": "buyer",
            "initial_password": "SwitchTest2026",
        },
        headers=auth(admin_token),
    )
    assert response.status_code == 200, response.text
    created = response.json()["data"]
    assert created["must_change_password"] is False

    from .conftest import _login

    token = _login(client, username, "SwitchTest2026")
    me = client.get("/api/auth/me", headers=auth(token))
    assert me.status_code == 200, me.text
    assert me.json()["data"]["must_change_password"] is False
    # 关键：不再被 40101 拦截
    units = client.get("/api/meta/units", headers=auth(token))
    assert units.status_code == 200, units.text
    _cleanup_user(client, admin_token, username)


def test_new_account_with_flag_on_still_forces_change(client, admin_token):
    """显式开启 must_change_password 时，仍走 40101 强制改密流程。"""
    username = "t_switch_on"
    response = _create_internal(client, admin_token, username, must_change=True)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["must_change_password"] is True

    from .conftest import _login

    token = _login(client, username, "SwitchTest2026")
    units = client.get("/api/meta/units", headers=auth(token))
    assert units.status_code == 401, units.text
    assert units.json()["code"] == 40101
    _cleanup_user(client, admin_token, username)


def test_supplier_account_respects_flag(client, admin_token):
    """供货商账号同样受该开关控制。"""
    from .conftest import _login

    # 用一个新档案（原有测试档案都已绑定账号，一对一约束下无法复用）
    created_supplier = client.post(
        "/api/admin/suppliers",
        json={"name": "开关用例供货商", "contact_name": "联系人", "contact_phone": "13800000000"},
        headers=auth(admin_token),
    )
    assert created_supplier.status_code == 200, created_supplier.text
    supplier_id = created_supplier.json()["data"]["id"]

    username = "t_switch_sup"
    response = client.post(
        "/api/admin/supplier-accounts",
        json={
            "supplier_id": supplier_id,
            "username": username,
            "initial_password": "SwitchTest2026",
            "must_change_password": False,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["must_change_password"] is False

    token = _login(client, username, "SwitchTest2026")
    detail = client.get("/api/supplier/rfqs", headers=auth(token))
    assert detail.status_code == 200, detail.text
    _cleanup_user(client, admin_token, username)
