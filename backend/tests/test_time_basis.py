"""时间口径用例：全系统统一使用**北京时间（UTC+8）naive**（models.app_now / utils.to_app_tz）。

背景：管理员在界面输入的「报价截止时间」就是北京时间。若按 UTC 解释，18:00 会被当作
UTC 18:00（北京次日 02:00），实际比用户意图晚 8 小时。这里固定住"输入即基准、不偏移"的语义。
"""
from __future__ import annotations

from datetime import timedelta

from .conftest import auth


def _make(client, buyer_token, deadline: str, title: str = "时间口径用例"):
    return client.post(
        "/api/rfqs",
        headers=auth(buyer_token),
        json={
            "title": title,
            "project": "测试项目",
            "deadline": deadline,
            "supplier_ids": [],
            "lines": [{"material_name": "物料", "unit": "个", "quantity": "1"}],
        },
    )


def test_naive_deadline_round_trip_has_no_shift(client, buyer_token, rfq_factory):
    """naive 输入（datetime-local 典型形态）原样存取，不得出现 ±8 小时偏移。"""
    response = _make(client, buyer_token, "2030-01-01T18:00:00")
    assert response.status_code == 200, response.text
    detail = response.json()["data"]
    assert detail["deadline"].startswith("2030-01-01T18:00:00")

    fetched = client.get(f"/api/rfqs/{detail['id']}", headers=auth(buyer_token)).json()["data"]
    assert fetched["deadline"].startswith("2030-01-01T18:00:00")

    # 带微秒的形态也保持一致
    precise = _make(client, buyer_token, "2030-06-15T09:30:45.123456", title="时间口径-微秒")
    assert precise.json()["data"]["deadline"].startswith("2030-06-15T09:30:45.123456")


def test_aware_input_is_converted_to_app_tz(client, buyer_token):
    """带时区输入统一归一到北京时间再去 tzinfo。"""
    plus8 = _make(client, buyer_token, "2030-01-01T18:00:00+08:00", title="时间口径-+08:00")
    assert plus8.status_code == 200, plus8.text
    assert plus8.json()["data"]["deadline"].startswith("2030-01-01T18:00:00")

    # 10:00Z == 北京时间 18:00
    utc = _make(client, buyer_token, "2030-01-01T10:00:00Z", title="时间口径-Z")
    assert utc.status_code == 200, utc.text
    assert utc.json()["data"]["deadline"].startswith("2030-01-01T18:00:00")

    # 北京时间 18:00 == UTC-5 的 05:00
    minus5 = _make(client, buyer_token, "2030-01-01T05:00:00-05:00", title="时间口径--05:00")
    assert minus5.status_code == 200, minus5.text
    assert minus5.json()["data"]["deadline"].startswith("2030-01-01T18:00:00")


def test_remaining_seconds_uses_app_clock(client, buyer_token, supplier_token, accounts, rfq_factory):
    """剩余时间按应用时钟（北京时间）计算，与输入基准一致。"""
    from app.models import app_now

    deadline = app_now() + timedelta(hours=2)
    detail = rfq_factory(lines=1, supplier_indexes=[0], title="时间口径-剩余")
    updated = client.put(
        f"/api/rfqs/{detail['id']}",
        headers=auth(buyer_token),
        json={
            "title": "时间口径-剩余",
            "project": "测试项目",
            "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%S"),
            "supplier_ids": [accounts["suppliers"][0]["id"]],
            "lines": [{"material_name": "物料", "unit": "个", "quantity": "1"}],
        },
    )
    assert updated.status_code == 200, updated.text
    assert client.post(f"/api/rfqs/{detail['id']}/publish", headers=auth(buyer_token)).json()["code"] == 0

    page = client.get(f"/api/supplier/rfqs/{detail['id']}", headers=auth(supplier_token)).json()["data"]
    remaining = page["remaining_seconds"]
    # 2 小时 ± 2 分钟容差（用例执行耗时）
    assert 2 * 3600 - 120 <= remaining <= 2 * 3600, remaining

    item = next(
        row
        for row in client.get("/api/supplier/rfqs?page_size=200", headers=auth(supplier_token))
        .json()["data"]["items"]
        if row["rfq_id"] == detail["id"]
    )
    assert 2 * 3600 - 120 <= item["remaining_seconds"] <= 2 * 3600


def test_published_at_uses_app_clock(client, buyer_token, accounts, rfq_factory):
    """published_at / closed_at 写入应用时钟（北京时间），与 UTC 相差 8 小时即视为回归。"""
    from app.models import app_now

    detail = rfq_factory(lines=1, supplier_indexes=[0], title="时间口径-发布时刻")
    before = app_now()
    published = client.post(f"/api/rfqs/{detail['id']}/publish", headers=auth(buyer_token)).json()["data"]
    after = app_now()
    stamp = published["published_at"]
    # 若仍按 UTC 写入，stamp 会比 before 早 8 小时，这条断言即失败
    assert stamp[:19] >= before.strftime("%Y-%m-%dT%H:%M:%S")
    assert stamp[:19] <= after.strftime("%Y-%m-%dT%H:%M:%S")

    closed = client.post(f"/api/rfqs/{detail['id']}/close", headers=auth(buyer_token)).json()["data"]
    assert closed["status"] == "closed"
    created = detail["created_at"][:19]
    assert closed["closed_at"][:19] >= created


def test_export_filename_uses_app_date(client, buyer_token, rfq_factory):
    """导出文件名日期用应用时钟，不依赖宿主机本地时区（容器通常为 UTC）。"""
    from app.models import app_now

    detail = rfq_factory(lines=1, title="时间口径-文件名")
    response = client.get(f"/api/rfqs/{detail['id']}/export", headers=auth(buyer_token))
    assert response.status_code == 200
    expected = app_now().date().strftime("%Y%m%d")
    assert f"_{expected}.xlsx" in response.headers["content-disposition"]
