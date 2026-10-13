"""安全与可见性用例：供货商越权、我方可见范围、并发/截止锁定、附件白名单（TC-17/19/30/31/32/34/35）。"""
from __future__ import annotations

from sqlalchemy import select

from .conftest import auth


def _forbidden_audits(target_like: str) -> int:
    from app.database import SessionLocal
    from app.models import AuditLog

    db = SessionLocal()
    try:
        rows = db.scalars(
            select(AuditLog).where(
                AuditLog.action == "security.forbidden", AuditLog.target_id.like(target_like)
            )
        ).all()
        return len(rows)
    finally:
        db.close()


def test_supplier_cannot_access_reports(client, supplier_token):
    before = _forbidden_audits("/api/reports/%")
    response = client.get(
        "/api/reports/rfq-comparison?rfq_id=1", headers=auth(supplier_token)
    )
    assert response.status_code == 403
    assert response.json()["code"] == 40300
    assert _forbidden_audits("/api/reports/%") == before + 1

    assert client.get("/api/reports/summary", headers=auth(supplier_token)).status_code == 403
    assert (
        client.get("/api/reports/summary/export", headers=auth(supplier_token)).status_code == 403
    )


def test_supplier_cannot_use_internal_endpoints(client, supplier_token, rfq_factory, buyer_token):
    detail = rfq_factory(lines=2, title="越权测试")
    rfq_id = detail["id"]
    assert client.post(f"/api/rfqs/{rfq_id}/publish", headers=auth(buyer_token)).json()["code"] == 0

    before = _forbidden_audits(f"/api/rfqs/{rfq_id}/quotes")
    response = client.get(f"/api/rfqs/{rfq_id}/quotes", headers=auth(supplier_token))
    assert response.status_code == 403
    assert response.json()["code"] == 40300
    assert _forbidden_audits(f"/api/rfqs/{rfq_id}/quotes") == before + 1

    # 我方列表 / 进度 / 导出同样拒绝
    assert client.get("/api/rfqs", headers=auth(supplier_token)).status_code == 403
    assert client.get(f"/api/rfqs/{rfq_id}/progress", headers=auth(supplier_token)).status_code == 403
    assert client.get(f"/api/rfqs/{rfq_id}/export", headers=auth(supplier_token)).status_code == 403


def test_supplier_cannot_open_unassigned_rfq(client, accounts, rfq_factory, buyer_token):
    """TC-34：未分派给本公司的单据一律 403 并留痕。"""
    detail = rfq_factory(lines=1, supplier_indexes=[0], title="未分派测试")
    rfq_id = detail["id"]
    assert client.post(f"/api/rfqs/{rfq_id}/publish", headers=auth(buyer_token)).json()["code"] == 0

    third = accounts["suppliers"][2]
    token = client.post(
        "/api/auth/login", json={"username": third["username"], "password": third["password"]}
    ).json()["data"]["token"]

    before = _forbidden_audits(f"rfq:{rfq_id}")
    response = client.get(f"/api/supplier/rfqs/{rfq_id}", headers=auth(token))
    assert response.status_code == 403
    assert response.json()["code"] == 40300
    assert _forbidden_audits(f"rfq:{rfq_id}") == before + 1

    # 未分派的单据不出现在待报价列表中
    listing = client.get("/api/supplier/rfqs", headers=auth(token)).json()["data"]
    assert all(item["rfq_id"] != rfq_id for item in listing["items"])


def test_buyer_visibility_scope(client, admin_token, buyer_token, rfq_factory):
    """PRD 3.3-4：采购员只能看自己创建的单，管理员看全部。"""
    own = rfq_factory(lines=1, title="采购员自己的单")
    imported = client.post(
        "/api/rfqs",
        headers=auth(admin_token),
        json={
            "title": "管理员创建的单",
            "project": "测试项目",
            "deadline": "2030-01-01T00:00:00",
            "supplier_ids": [],
            "lines": [{"material_name": "物料", "unit": "个", "quantity": "1"}],
        },
    )
    assert imported.status_code == 200, imported.text
    other_id = imported.json()["data"]["id"]

    buyer_list = client.get("/api/rfqs?page_size=200", headers=auth(buyer_token)).json()["data"]
    assert any(item["id"] == own["id"] for item in buyer_list["items"])
    assert all(item["id"] != other_id for item in buyer_list["items"])

    admin_list = client.get("/api/rfqs?page_size=200", headers=auth(admin_token)).json()["data"]
    assert any(item["id"] == other_id for item in admin_list["items"])

    before = _forbidden_audits(f"rfq:{other_id}")
    denied = client.get(f"/api/rfqs/{other_id}", headers=auth(buyer_token))
    assert denied.status_code == 403
    assert denied.json()["code"] == 40300
    assert _forbidden_audits(f"rfq:{other_id}") == before + 1

    assert client.delete(f"/api/rfqs/{other_id}", headers=auth(admin_token)).json()["code"] == 0


def test_supplier_id_in_body_is_ignored(client, accounts, buyer_token, rfq_factory, supplier_token, supplier2_token):
    """安全红线：一律使用 token 中的 supplier_id，忽略前端传入值。"""
    detail = rfq_factory(lines=1, supplier_indexes=[0, 1], title="supplier_id 注入")
    rfq_id = detail["id"]
    assert client.post(f"/api/rfqs/{rfq_id}/publish", headers=auth(buyer_token)).json()["code"] == 0
    uid = detail["lines"][0]["line_uid"]
    other_supplier_id = accounts["suppliers"][1]["id"]

    response = client.put(
        f"/api/supplier/rfqs/{rfq_id}/quotes",
        headers=auth(supplier_token),
        json={
            "supplier_id": other_supplier_id,
            "submit": False,
            "lines": [{"line_uid": uid, "price_incl_tax": "12.34", "tax_included": True, "tax_rate": "0.13"}],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["my_status"] == "quoted"

    # 他方（供应商2）的填报页依然没有报价
    other = client.get(f"/api/supplier/rfqs/{rfq_id}", headers=auth(supplier2_token)).json()["data"]
    assert other["my_status"] == "pending"
    assert all(line["quote"] is None for line in other["lines"])

    prices = client.get(
        f"/api/reports/rfq-comparison?rfq_id={rfq_id}", headers=auth(buyer_token)
    ).json()["data"]["rows"][0]["prices"]
    assert prices == {str(accounts["suppliers"][0]["id"]): "12.34"}


def test_published_and_closed_guards(client, buyer_token, supplier_token, rfq_factory):
    detail = rfq_factory(lines=2, title="锁定测试")
    rfq_id = detail["id"]
    uid = detail["lines"][0]["line_uid"]

    assert client.post(f"/api/rfqs/{rfq_id}/publish", headers=auth(buyer_token)).json()["code"] == 0

    # 已发布：明细不可增删改（40900）
    assert client.delete(f"/api/rfqs/{rfq_id}", headers=auth(buyer_token)).json()["code"] == 40900
    update = client.put(
        f"/api/rfqs/{rfq_id}",
        headers=auth(buyer_token),
        json={"title": "改标题", "project": "测试项目", "deadline": "2030-01-01T00:00:00", "supplier_ids": [], "lines": []},
    )
    assert update.json()["code"] == 40900

    # 已截止：报价被拒（40301）
    assert client.post(f"/api/rfqs/{rfq_id}/close", headers=auth(buyer_token)).json()["code"] == 0
    late = client.put(
        f"/api/supplier/rfqs/{rfq_id}/quotes",
        headers=auth(supplier_token),
        json={"submit": False, "lines": [{"line_uid": uid, "price_incl_tax": "1.00"}]},
    )
    assert late.status_code == 403
    assert late.json()["code"] == 40301
    assert client.get(
        f"/api/supplier/rfqs/{rfq_id}", headers=auth(supplier_token)
    ).json()["data"]["readonly"] is True


def test_optimistic_lock_conflict(client, buyer_token, supplier_token, rfq_factory):
    detail = rfq_factory(lines=1, title="乐观锁测试")
    rfq_id = detail["id"]
    uid = detail["lines"][0]["line_uid"]
    assert client.post(f"/api/rfqs/{rfq_id}/publish", headers=auth(buyer_token)).json()["code"] == 0

    first = client.put(
        f"/api/supplier/rfqs/{rfq_id}/quotes",
        headers=auth(supplier_token),
        json={"submit": False, "lines": [{"line_uid": uid, "price_incl_tax": "10.00"}]},
    )
    assert first.status_code == 200
    stale = client.put(
        f"/api/supplier/rfqs/{rfq_id}/quotes",
        headers=auth(supplier_token),
        json={
            "submit": False,
            "expected_updated_at": "2020-01-01T00:00:00",
            "lines": [{"line_uid": uid, "price_incl_tax": "9.00"}],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == 40900


def test_attachments_whitelist_and_isolation(client, buyer_token, supplier_token, supplier2_token, monkeypatch):
    from app.config import settings

    bad_type = client.post(
        "/api/supplier/attachments",
        headers=auth(supplier_token),
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert bad_type.status_code == 400
    assert bad_type.json()["code"] == 40001

    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    oversized = client.post(
        "/api/supplier/attachments",
        headers=auth(supplier_token),
        files={"file": ("big.pdf", b"x" * (2 * 1024 * 1024), "application/pdf")},
    )
    assert oversized.status_code == 400
    assert "上限" in oversized.json()["message"]

    ok = client.post(
        "/api/supplier/attachments",
        headers=auth(supplier_token),
        files={"file": ("行附件.pdf", b"%PDF-1.4 test", "application/pdf")},
    )
    assert ok.status_code == 200, ok.text
    stored = ok.json()["data"]["filename"]
    assert stored.endswith(".pdf")

    assert client.get(f"/api/supplier/attachments/{stored}", headers=auth(supplier_token)).status_code == 200
    assert client.get(f"/api/supplier/attachments/{stored}", headers=auth(buyer_token)).status_code == 200
    other = client.get(f"/api/supplier/attachments/{stored}", headers=auth(supplier2_token))
    assert other.status_code == 403


def test_password_change_invalidates_token(client, accounts):
    """FR-ACC-05 / FR-ACC-12：改密后既有会话（token）立即失效。"""
    from app.database import SessionLocal
    from app.models import User
    from app.security import hash_password

    db = SessionLocal()
    try:
        db.add(
            User(
                username="t_rotate",
                password_hash=hash_password("Rotate2026a"),
                real_name="改密用例",
                role="buyer",
                status=1,
                must_change_password=False,
            )
        )
        db.commit()
    finally:
        db.close()

    token = client.post(
        "/api/auth/login", json={"username": "t_rotate", "password": "Rotate2026a"}
    ).json()["data"]["token"]
    assert client.get("/api/rfqs?page_size=1", headers=auth(token)).status_code == 200

    changed = client.post(
        "/api/auth/change-password",
        headers=auth(token),
        json={"old_password": "Rotate2026a", "new_password": "Rotate2026b"},
    )
    assert changed.status_code == 200, changed.text

    expired = client.get("/api/rfqs?page_size=1", headers=auth(token))
    assert expired.status_code == 401
    assert expired.json()["code"] == 40100

    new_token = client.post(
        "/api/auth/login", json={"username": "t_rotate", "password": "Rotate2026b"}
    ).json()["data"]["token"]
    assert client.get("/api/rfqs?page_size=1", headers=auth(new_token)).status_code == 200
