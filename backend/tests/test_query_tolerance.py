"""查询参数容错用例：空串筛选参数必须按「未传」处理（前端清空条件时透传 ""）。

背景：前端 query 对象初始值为 ''，直接展开透传会让 FastAPI 把 ``date_from=`` 解析失败，
返回 40001 并让列表页永远为空（页头统计正常 → "共 0 张单据"的自相矛盾显示）。
"""
from __future__ import annotations

from .conftest import auth

EMPTY_QUERY = "status=&keyword=&date_from=&date_to=&page=&page_size=&only_mine="


def test_list_accepts_blank_filters(client, buyer_token):
    plain = client.get("/api/rfqs?page_size=100", headers=auth(buyer_token))
    assert plain.status_code == 200, plain.text
    baseline = plain.json()["data"]

    blank = client.get(f"/api/rfqs?{EMPTY_QUERY}", headers=auth(buyer_token))
    assert blank.status_code == 200, blank.text
    body = blank.json()
    assert body["code"] == 0
    data = body["data"]
    # 与"完全不传筛选"等价，而不是返回 0 条
    assert data["meta"]["total"] == baseline["meta"]["total"]
    assert [item["id"] for item in data["items"]] == [item["id"] for item in baseline["items"]]
    assert data["meta"]["page"] == 1 and data["meta"]["page_size"] == 20

    # 纯空白同样按未传处理
    spaced = client.get("/api/rfqs?status=%20%20&keyword=%20&date_from=%20", headers=auth(buyer_token))
    assert spaced.status_code == 200, spaced.text
    assert spaced.json()["data"]["meta"]["total"] == baseline["meta"]["total"]

    # 真实筛选值仍然生效
    keyword = baseline["items"][0]["rfq_no"]
    filtered = client.get(f"/api/rfqs?keyword={keyword}", headers=auth(buyer_token))
    assert filtered.status_code == 200
    assert [item["rfq_no"] for item in filtered.json()["data"]["items"]] == [keyword]


def test_list_rejects_truly_invalid_values_with_friendly_message(client, buyer_token):
    bad_date = client.get("/api/rfqs?date_from=2026-13-99", headers=auth(buyer_token))
    assert bad_date.status_code == 400
    assert bad_date.json()["code"] == 40001
    assert "date_from：日期格式应为 YYYY-MM-DD" in bad_date.json()["message"]

    bad_page = client.get("/api/rfqs?page=abc", headers=auth(buyer_token))
    assert bad_page.status_code == 400
    assert "page：必须为整数" in bad_page.json()["message"]

    over = client.get("/api/rfqs?page_size=500", headers=auth(buyer_token))
    assert over.status_code == 400
    assert "page_size：不能超过 200" in over.json()["message"]

    out_of_range = client.get("/api/rfqs?page=0", headers=auth(buyer_token))
    assert out_of_range.status_code == 400


def test_summary_and_exports_accept_blank_filters(client, buyer_token):
    plain = client.get("/api/reports/summary", headers=auth(buyer_token)).json()["data"]
    blank = client.get(
        "/api/reports/summary?date_from=&date_to=&project=&supplier_ids=&rfq_id=&status=&only_unquoted=",
        headers=auth(buyer_token),
    )
    assert blank.status_code == 200, blank.text
    data = blank.json()["data"]
    assert data["rfq_count"] == plain["rfq_count"]
    assert data["line_count"] == plain["line_count"]
    assert data["invited_assignments"] == plain["invited_assignments"]
    assert data["quoted_assignments"] == plain["quoted_assignments"]
    assert data["best_amount"] == plain["best_amount"]

    # supplier_ids 空串视为"全部"，不能退化成 [0]
    assert data["by_supplier"] == plain["by_supplier"]

    export = client.get(
        "/api/reports/summary/export?date_from=&date_to=&project=&supplier_ids=&rfq_id=&status=",
        headers=auth(buyer_token),
    )
    assert export.status_code == 200, export.text
    assert export.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_comparison_blank_rfq_id_is_clear_error(client, buyer_token, rfq_factory):
    detail = rfq_factory(lines=2, title="参数容错-比价")

    blank = client.get("/api/reports/rfq-comparison?rfq_id=", headers=auth(buyer_token))
    assert blank.status_code == 400
    assert blank.json()["code"] == 40001
    assert blank.json()["message"] == "请选择询价单"

    missing = client.get("/api/reports/rfq-comparison", headers=auth(buyer_token))
    assert missing.status_code == 400
    assert missing.json()["message"] == "请选择询价单"

    blank_export = client.get("/api/reports/rfq-comparison/export?rfq_id=", headers=auth(buyer_token))
    assert blank_export.status_code == 400
    assert blank_export.json()["code"] == 40001

    ok = client.get(
        f"/api/reports/rfq-comparison?rfq_id={detail['id']}&only_unquoted=",
        headers=auth(buyer_token),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["rfq_id"] == detail["id"]


def test_supplier_blank_filters(client, supplier_token):
    plain = client.get("/api/supplier/rfqs?page_size=100", headers=auth(supplier_token)).json()["data"]
    blank = client.get(
        "/api/supplier/rfqs?page=&page_size=&my_status=&keyword=&only_open=",
        headers=auth(supplier_token),
    )
    assert blank.status_code == 200, blank.text
    data = blank.json()["data"]
    assert data["meta"]["total"] == plain["meta"]["total"]
    assert [item["rfq_id"] for item in data["items"]] == [item["rfq_id"] for item in plain["items"]]

    history = client.get("/api/supplier/quotes/history?page=&page_size=&rfq_id=&line_uid=", headers=auth(supplier_token))
    assert history.status_code == 200, history.text
    assert history.json()["code"] == 0
    assert history.json()["data"]["meta"]["page_size"] == 50


def test_rfq_export_blank_include_quotes_uses_default(client, buyer_token, rfq_factory):
    detail = rfq_factory(lines=2, title="参数容错-导出")
    response = client.get(
        f"/api/rfqs/{detail['id']}/export?include_quotes=", headers=auth(buyer_token)
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "filename*=UTF-8''" in response.headers["content-disposition"]

    only_lines = client.get(
        f"/api/rfqs/{detail['id']}/export?include_quotes=false", headers=auth(buyer_token)
    )
    assert only_lines.status_code == 200

    bad = client.get(
        f"/api/rfqs/{detail['id']}/export?include_quotes=maybe", headers=auth(buyer_token)
    )
    assert bad.status_code == 400
    assert "include_quotes：必须为 true/false" in bad.json()["message"]
