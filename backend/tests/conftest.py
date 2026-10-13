"""pytest 全局夹具。

关键点：
- **必须在导入 app 之前**设置环境变量，把测试数据库切到独立文件 `data/test_xunjia.db`，
  避免污染开发库 `data/xunjia.db`（task-4 验收要求独立测试库）。
- `XUNJIA_BCRYPT_ROUNDS=4` 降低 bcrypt 轮数加速用例。
- `XUNJIA_SEED_DEMO=0`：只保留默认管理员与字典种子，业务数据由用例自行构造。
"""
from __future__ import annotations

import os
import pathlib

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
# 每个进程一个独立测试库：避免与并发运行的其他人（或上一次残留）争抢同一个文件
TEST_DB = BACKEND_DIR / "data" / f"test_xunjia_{os.getpid()}.db"

os.environ["XUNJIA_DATABASE_URL"] = f"sqlite:///./data/{TEST_DB.name}"
os.environ["XUNJIA_BCRYPT_ROUNDS"] = "4"
os.environ["XUNJIA_SEED_DEMO"] = "0"
os.environ["XUNJIA_ADMIN_PASSWORD"] = "Admin@2026"
os.environ["XUNJIA_UPLOAD_DIR"] = "./data/test_uploads"

for _suffix in ("", "-wal", "-shm"):
    _stale = pathlib.Path(str(TEST_DB) + _suffix)
    if _stale.exists():
        try:
            _stale.unlink()
        except PermissionError:  # pragma: no cover - 其他进程仍占用时忽略
            pass

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DOC_SAMPLE_XLS = BACKEND_DIR.parent / "doc" / "示例.xls"

ADMIN_PWD = "TestAdmin2026"
BUYER_PWD = "TestBuyer2026"
SUPPLIER_PWD = "TestSupplier2026"


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """收尾：释放引擎并清理本次进程的测试库，避免残留文件。"""
    try:
        from app.database import engine

        engine.dispose()
    except Exception:  # pragma: no cover - 导入失败时忽略
        pass
    for suffix in ("", "-wal", "-shm"):
        stale = pathlib.Path(str(TEST_DB) + suffix)
        if stale.exists():
            try:
                stale.unlink()
            except PermissionError:  # pragma: no cover
                pass


@pytest.fixture(scope="session")
def client():
    """带 lifespan 的 TestClient（触发建表 + 种子数据）。"""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def accounts(client):
    """构造测试账号：1 管理员 + 1 采购员 + 5 家供货商（独立于演示数据）。"""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Supplier, User
    from app.security import hash_password

    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.username == "t_admin"))
        if existing is None:
            db.add(
                User(
                    username="t_admin",
                    password_hash=hash_password(ADMIN_PWD),
                    real_name="测试管理员",
                    role="admin",
                    status=1,
                    must_change_password=False,
                )
            )
            db.add(
                User(
                    username="t_buyer",
                    password_hash=hash_password(BUYER_PWD),
                    real_name="测试采购员",
                    role="buyer",
                    status=1,
                    must_change_password=False,
                )
            )
            for index in range(1, 6):
                supplier = Supplier(
                    name=f"测试供货商{index}",
                    contact_name=f"联系人{index}",
                    contact_phone=f"1380000000{index}",
                    contact_email=f"sup{index}@test.example",
                    status=1,
                )
                db.add(supplier)
                db.flush()
                db.add(
                    User(
                        username=f"t_sup{index}",
                        password_hash=hash_password(SUPPLIER_PWD),
                        real_name=f"联系人{index}",
                        role="supplier",
                        supplier_id=supplier.id,
                        status=1,
                        must_change_password=False,
                    )
                )
            db.commit()

        suppliers = db.scalars(
            select(Supplier).where(Supplier.name.like("测试供货商%")).order_by(Supplier.id)
        ).all()
        return {
            "admin": {"username": "t_admin", "password": ADMIN_PWD},
            "buyer": {"username": "t_buyer", "password": BUYER_PWD},
            "suppliers": [
                {"id": s.id, "name": s.name, "username": f"t_sup{i}", "password": SUPPLIER_PWD}
                for i, s in enumerate(suppliers, start=1)
            ],
        }
    finally:
        db.close()


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]["token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def admin_token(client, accounts) -> str:
    return _login(client, accounts["admin"]["username"], accounts["admin"]["password"])


@pytest.fixture(scope="session")
def buyer_token(client, accounts) -> str:
    return _login(client, accounts["buyer"]["username"], accounts["buyer"]["password"])


@pytest.fixture(scope="session")
def supplier_token(client, accounts) -> str:
    first = accounts["suppliers"][0]
    return _login(client, first["username"], first["password"])


@pytest.fixture(scope="session")
def supplier2_token(client, accounts) -> str:
    second = accounts["suppliers"][1]
    return _login(client, second["username"], second["password"])


@pytest.fixture
def rfq_factory(client, buyer_token, accounts):
    """按需创建草稿询价单的工厂夹具。"""
    created: list[int] = []

    def _create(*, lines: int = 3, supplier_indexes: list[int] | None = None, deadline_days: int = 3, title: str = "测试询价单"):
        from datetime import datetime, timedelta

        indexes = supplier_indexes if supplier_indexes is not None else [0]
        payload = {
            "title": title,
            "project": "测试项目",
            "deadline": (datetime.now() + timedelta(days=deadline_days)).strftime("%Y-%m-%dT%H:%M:%S"),
            "remark": "测试备注",
            "internal_remark": "内部备注",
            "supplier_ids": [accounts["suppliers"][i]["id"] for i in indexes],
            "lines": [
                {
                    "material_name": f"物料{seq}",
                    "spec": f"规格{seq}",
                    "unit": "个",
                    "project": "测试项目",
                    "quantity": str(seq * 10),
                }
                for seq in range(1, lines + 1)
            ],
        }
        response = client.post("/api/rfqs", json=payload, headers=auth(buyer_token))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["code"] == 0, body
        created.append(body["data"]["id"])
        return body["data"]

    yield _create

    for rfq_id in created:
        client.delete(f"/api/rfqs/{rfq_id}", headers=auth(buyer_token))
