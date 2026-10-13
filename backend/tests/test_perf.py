"""性能用例：2000 明细行 × 50 家供货商的比价与汇总（PRD 8. 性能 P95 < 2s）。

数据用 Core bulk insert 直接落库（不经接口），只测「取数 + 内存组装」这一段的耗时；
同时记录完整 HTTP 接口耗时（含 JSON 序列化）作为参考。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import insert, select

from .conftest import auth

LINE_COUNT = 2000
SUPPLIER_COUNT = 50
COMPUTE_BUDGET_SECONDS = 2.0


@pytest.fixture(scope="module")
def perf_rfq(client, buyer_token):
    from app.database import SessionLocal
    from app.models import QuoteLine, Rfq, RfqLine, RfqSupplier, Supplier, User, new_line_uid, app_now

    db = SessionLocal()
    try:
        buyer = db.scalar(select(User).where(User.username == "t_buyer"))
        supplier_ids: list[int] = []
        for index in range(1, SUPPLIER_COUNT + 1):
            supplier = Supplier(name=f"性能供货商{index:02d}", status=1)
            db.add(supplier)
            db.flush()
            supplier_ids.append(supplier.id)

        rfq = Rfq(
            rfq_no="RFQPERF0001",
            title="性能压测单",
            project="性能测试",
            status="published",
            deadline=app_now() + timedelta(days=30),
            created_by=buyer.id,
            published_at=app_now(),
        )
        db.add(rfq)
        db.flush()

        now = app_now()
        line_uid_list = [new_line_uid() for _ in range(LINE_COUNT)]
        db.execute(
            insert(RfqLine),
            [
                {
                    "line_uid": uid,
                    "rfq_id": rfq.id,
                    "seq": seq,
                    "material_name": f"压测物料{seq}",
                    "spec": f"规格{seq}",
                    "unit": "个",
                    "project": "性能测试",
                    "quantity": seq % 100 + 1,
                    "created_at": now,
                }
                for seq, uid in enumerate(line_uid_list, start=1)
            ],
        )
        db.execute(
            insert(RfqSupplier),
            [
                {
                    "rfq_id": rfq.id,
                    "supplier_id": supplier_id,
                    "status": "quoted",
                    "line_count": LINE_COUNT,
                    "quoted_line_count": LINE_COUNT,
                    "created_at": now,
                }
                for supplier_id in supplier_ids
            ],
        )
        db.flush()

        assignment_ids = list(
            db.scalars(select(RfqSupplier.id).where(RfqSupplier.rfq_id == rfq.id)).all()
        )
        quote_rows = []
        for offset, assignment_id in enumerate(assignment_ids):
            base = Decimal(10 + offset % 7)
            for index, uid in enumerate(line_uid_list):
                quote_rows.append(
                    {
                        "rfq_supplier_id": assignment_id,
                        "line_uid": uid,
                        "price_incl_tax": base + Decimal(index % 50) / Decimal(10),
                        "tax_included": True,
                        "tax_rate": Decimal("0.13"),
                        "price_excl_tax": base,
                        "moq": Decimal("1"),
                        "lead_time_days": 5,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
        inserted = 0
        chunk = 5000
        for start in range(0, len(quote_rows), chunk):
            db.execute(insert(QuoteLine), quote_rows[start : start + chunk])
            inserted += len(quote_rows[start : start + chunk])
        db.commit()
        assert inserted == LINE_COUNT * SUPPLIER_COUNT
        yield {"rfq_id": rfq.id, "lines": LINE_COUNT, "suppliers": SUPPLIER_COUNT}
    finally:
        db.close()


def test_comparison_is_fast_on_large_rfq(client, buyer_token, perf_rfq):
    from app.api.report import build_comparison
    from app.database import SessionLocal
    from app.models import Rfq

    db = SessionLocal()
    try:
        rfq = db.get(Rfq, perf_rfq["rfq_id"])
        started = time.perf_counter()
        result = build_comparison(db, rfq)
        compute_seconds = time.perf_counter() - started
    finally:
        db.close()

    assert len(result.rows) == LINE_COUNT
    assert len(result.suppliers) == SUPPLIER_COUNT
    assert result.rows[0].quoted_count == SUPPLIER_COUNT
    assert compute_seconds < COMPUTE_BUDGET_SECONDS, f"比价计算耗时 {compute_seconds:.3f}s"

    started = time.perf_counter()
    response = client.get(
        f"/api/reports/rfq-comparison?rfq_id={perf_rfq['rfq_id']}", headers=auth(buyer_token)
    )
    http_seconds = time.perf_counter() - started
    assert response.status_code == 200, response.text
    print(
        f"\n[perf] {LINE_COUNT} 行 × {SUPPLIER_COUNT} 家："
        f"计算 {compute_seconds:.3f}s，HTTP(含 JSON 序列化) {http_seconds:.3f}s，"
        f"响应体 {len(response.content) / 1024 / 1024:.2f} MB"
    )


def test_summary_is_fast_on_large_rfq(client, buyer_token, perf_rfq):
    from app.api.report import build_summary
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        started = time.perf_counter()
        result = build_summary(db, rfq_id=perf_rfq["rfq_id"])
        compute_seconds = time.perf_counter() - started
    finally:
        db.close()

    assert result.rfq_count == 1
    assert result.line_count == LINE_COUNT
    assert result.invited_assignments == SUPPLIER_COUNT
    assert compute_seconds < COMPUTE_BUDGET_SECONDS, f"汇总计算耗时 {compute_seconds:.3f}s"

    started = time.perf_counter()
    response = client.get(
        f"/api/reports/summary?rfq_id={perf_rfq['rfq_id']}", headers=auth(buyer_token)
    )
    http_seconds = time.perf_counter() - started
    assert response.status_code == 200
    print(f"[perf] 汇总统计：计算 {compute_seconds:.3f}s，HTTP {http_seconds:.3f}s")
