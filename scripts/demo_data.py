#!/usr/bin/env python
"""生成展示用实例数据（可直接重复运行，每次先清理旧的演示数据）。

生成的演示内容：
- 11 张询价单：6 张已截止（报价齐）/ 3 张进行中（其中 2 张故意只报一半，用于催办场景）/
  2 张草稿（1 张只有表头无明细，用于展示"不完整草稿"）
- 164 条报价行，覆盖 4 档税率、有/无 MOQ、交期与到货日期、备注
- 188 条改价历史：约 1/3 的供货商做了一次改价，用于演示"改价留痕"
- 计 41 条分派（受邀家次），响应率约 73%，最低价分散在不同供货商（体现比价价值）

设计要点：
1. **全程走 API**（登录、建单、发布、报价、改价、提交），不直接写库。
   这样产生的数据与真实业务完全一致：报价完整度会自动算出 pending/partial/quoted，
   改价会真实写入 quote_history，关键操作会留审计日志。
2. **可重复运行**：先把上一次生成的演示单据（标题带"【演示】"前缀）按外键顺序清理，
   再重新生成。
3. **时间自洽**：单号由后端按创建日期生成（RFQ+YYYYMMDD+序号），因此创建时间取"今天"，
   用**截止时间**区分状态（过去=已截止 / 未来=进行中），避免"单号 1013 但创建时间 0831"
   这种自相矛盾的数据。已截止单据的 deadline 通过 DB 回填到过去，由系统惰性判定生效。

用法：
    python scripts/demo_data.py                # 默认 http://127.0.0.1:8000
    python scripts/demo_data.py --base http://127.0.0.1:18000   # 单镜像容器
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
random.seed(20261013)  # 固定随机种子，保证每次生成的数据一致

PREFIX = "【演示】"
OK = FAIL = 0


def say(msg: str) -> None:
    print(msg, flush=True)


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/") + "/api"
        self.token: str | None = None

    def _req(self, method: str, path: str, body=None, token: str | None = None, raw=False):
        data = json.dumps(body, ensure_ascii=True).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        tok = token if token is not None else self.token
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                return resp.status, (payload if raw else json.loads(payload))
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            try:
                return exc.code, json.loads(payload or b"{}")
            except json.JSONDecodeError:
                return exc.code, {"code": exc.code, "message": payload[:200].decode("utf-8", "replace")}

    def get(self, path, token=None):
        return self._req("GET", path, token=token)

    def post(self, path, body=None, token=None):
        return self._req("POST", path, body if body is not None else {}, token=token)

    def put(self, path, body=None, token=None):
        return self._req("PUT", path, body if body is not None else {}, token=token)

    def delete(self, path, token=None):
        return self._req("DELETE", path, token=token)

    def login(self, username: str, password: str) -> str | None:
        status, body = self._req("POST", "/auth/login", {"username": username, "password": password})
        if body.get("code") == 0:
            return body["data"]["token"]
        return None


def check(cond: bool, label: str, detail: str = "") -> bool:
    global OK, FAIL
    if cond:
        OK += 1
        say(f"  ✓ {label}")
    else:
        FAIL += 1
        say(f"  ✗ {label}" + (f" — {str(detail)[:160]}" if detail else ""))
    return cond


# ---------------------------------------------------------------------------
# 演示数据定义
# ---------------------------------------------------------------------------
# 供货商在 rfq["sups"] 里按"竞争力"排序：索引 0 最强，报价最低。
# 每行预先指定由哪家最低（best_of），保证比价表里"最低"是多列分布而不是一家通吃。
#
# 注意：物料单位必须取自计量单位字典（个/台/套/包/支/桶/米/千克/件/箱/卷/张），
# 否则发布会因"单位不在计量单位字典内"被校验拦截 —— 这是系统的正确行为。
# 注意：id 顺序影响列表倒序后的首屏内容。
# 报表页默认选中最近的一张单据，若最新是"无明细草稿"会显示空状态，
# 所以把草稿与进行中的单据放在最前创建（时间更早），让有完整报价的已截止单据排在列表最上面。
GROUPS = [
    {
        "project": "食堂",
        "due_days": 0,
        "batch": 1,
        "sups": [0, 1, 2],
        "status": "draft",
        "lines": [],
    },
    {
        "project": "园区物业",
        "due_days": 6,
        "batch": 2,
        "sups": [0, 1, 2, 3, 4],
        "status": "published",
        "lines": [
            ("垃圾袋", "大号 80×100cm 50 只/卷", "卷", 60, 26.00),
            ("消毒液", "84 消毒液 5L", "桶", 10, 48.00),
            ("拖把", "平板旋转式", "个", 12, 56.00),
            ("扫帚套装", "含簸箕", "套", 15, 32.00),
        ],
    },
    {
        "project": "综合办公室",
        "due_days": 3,
        "batch": 1,
        "sups": [0, 1, 2, 4],
        "status": "published",
        "lines": [
            ("打印纸 A3", "80g 500 张/包", "包", 40, 45.00),
            ("硒鼓", "适配 HP CF280A", "个", 12, 268.00),
            ("麦克风电池", "9V 碱性", "个", 40, 6.50),
            ("白板", "90×120cm 磁性", "张", 3, 320.00),
            ("文件柜", "四层钢制", "个", 4, 680.00),
        ],
    },
    {
        "project": "化验室",
        "due_days": -8,
        "batch": 5,
        "sups": [0, 1, 3, 4],
        "lines": [
            ("一次性手套", "丁腈 M 号", "包", 30, 39.00),
            ("烧杯", "250ml 玻璃", "个", 40, 12.80),
            ("洗瓶", "500ml", "个", 20, 9.60),
            ("标签纸", "防水 50×30mm", "卷", 60, 14.20),
        ],
    },
    {
        "project": "质检部",
        "due_days": -13,
        "batch": 4,
        "sups": [1, 2, 3, 4],
        "lines": [
            ("游标卡尺", "0-150mm", "个", 8, 165.00),
            ("千分尺", "0-25mm", "个", 5, 238.00),
            ("样品袋", "自封 20×28cm", "包", 1000, 0.85),
        ],
    },
    {
        "project": "设备维护部",
        "due_days": -20,
        "batch": 3,
        "sups": [0, 2, 3, 4],
        "lines": [
            ("轴承", "6204-2RS", "个", 40, 36.00),
            ("液压油", "46# 18L", "桶", 8, 380.00),
            ("砂纸", "320 目", "张", 200, 2.50),
            ("内六角扳手组套", "1.5-10mm", "套", 6, 96.00),
            ("电工胶带", "PVC 阻燃", "卷", 100, 5.60),
            ("万用表", "数字式", "台", 4, 268.00),
            ("电缆", "YJV 3×4mm²", "米", 200, 24.50),
        ],
    },
    {
        "project": "生产一车间",
        "due_days": -27,
        "batch": 2,
        "sups": [0, 1, 2, 4],
        "lines": [
            ("丁腈手套", "L 号 100 只/盒", "包", 50, 42.00),
            ("防尘口罩", "KN95", "个", 500, 3.20),
            ("护目镜", "防冲击", "个", 30, 26.00),
            ("安全帽", "ABS 黄色", "个", 20, 58.00),
            ("工作服", "春秋长袖", "件", 25, 128.00),
        ],
    },
    {
        "project": "行政管理部",
        "due_days": -34,
        "batch": 1,
        "sups": [0, 1, 2, 3, 4],
        "lines": [
            ("A4 复印纸 70g", "500 张/包", "包", 120, 18.50),
            ("中性笔 0.5mm 黑色", "12 支/盒", "支", 720, 1.85),
            ("订书机", "12 号", "个", 15, 28.00),
            ("文件收纳盒", "A4 竖式", "个", 40, 15.50),
            ("白板笔", "可擦 3mm", "支", 80, 6.80),
            ("垃圾桶", "10L 塑料", "个", 12, 32.00),
        ],
    },
]

# 税率必须取自税率字典（0.13 / 0.09 / 0.06 / 0.03 / 0.00）
TAX_RATES = ["0.1300", "0.1300", "0.1300", "0.0900", "0.0600", "0.0300"]


def clear_previous() -> int:
    """删除上一次生成的演示单据（标题以 PREFIX 开头）。

    通过 DB 直接清理，原因：
    - 删除接口禁止删除"有分派记录"的单据（历史报价快照需要可追溯），
      而演示数据必然有分派，靠接口删除会失败并静默残留 —— 之前就是这样
      导致数据翻倍（15 张演示单据残留）。
    - 演示数据是我方自造、可再生，这里按外键顺序清理干净是可接受的。

    清理顺序：改价历史 → 报价行 → 分派记录 → 询价明细 → 询价单。
    """
    from sqlalchemy import delete, select

    from app.database import SessionLocal  # noqa: PLC0415
    from app.models import (  # noqa: PLC0415
        QuoteHistory,
        QuoteLine,
        Rfq,
        RfqLine,
        RfqSupplier,
    )

    db = SessionLocal()
    try:
        rfqs = db.scalars(select(Rfq).where(Rfq.title.like(f"{PREFIX}%"))).all()
        if not rfqs:
            return 0
        rfq_ids = [r.id for r in rfqs]
        assignment_ids = list(
            db.scalars(select(RfqSupplier.id).where(RfqSupplier.rfq_id.in_(rfq_ids))).all()
        )
        if assignment_ids:
            db.execute(delete(QuoteHistory).where(QuoteHistory.rfq_supplier_id.in_(assignment_ids)))
            db.execute(delete(QuoteLine).where(QuoteLine.rfq_supplier_id.in_(assignment_ids)))
            db.execute(delete(RfqSupplier).where(RfqSupplier.id.in_(assignment_ids)))
        db.execute(delete(RfqLine).where(RfqLine.rfq_id.in_(rfq_ids)))
        db.execute(delete(Rfq).where(Rfq.id.in_(rfq_ids)))
        db.commit()
        return len(rfq_ids)
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--admin-user", default="admin")
    ap.add_argument("--admin-password", default="Admin@2026")
    args = ap.parse_args()

    say("=" * 62)
    say(f" 生成展示用实例数据  目标: {args.base}")
    say("=" * 62)

    api = Api(args.base)
    status, body = api.get("/health")
    if body.get("code") != 0:
        say("服务未就绪，终止。")
        return 1

    token = api.login(args.admin_user, args.admin_password)
    if not token:
        say(f"管理员 {args.admin_user} 登录失败。")
        return 1
    api.token = token
    say(f"  管理员登录成功（{args.admin_user}）")

    # 供货商档案 + 账号
    _, body = api.get("/meta/suppliers")
    suppliers = body.get("data") or []
    _, body = api.get("/admin/supplier-accounts?page_size=100")
    accounts = {x["supplier_id"]: x for x in ((body.get("data") or {}).get("items") or [])}
    say(f"  供货商档案 {len(suppliers)} 家，其中已建账号 {len(accounts)} 家")

    # 确保参与演示的供货商账号密码可用（统一 supplier123，不强制改密）
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
    from app.database import SessionLocal  # noqa: E402
    from app.models import User  # noqa: E402
    from app.security import hash_password  # noqa: E402

    db = SessionLocal()
    try:
        fixed = 0
        for sid in {s["id"] for s in suppliers}:
            user = db.query(User).filter(User.supplier_id == sid, User.role == "supplier").first()
            if user:
                user.password_hash = hash_password("supplier123")
                user.must_change_password = False
                user.status = 1
                fixed += 1
        db.commit()
        say(f"  已统一 {fixed} 个供货商账号的演示密码为 supplier123（便于切换账号演示）")
    finally:
        db.close()

    # 后续多个步骤都要用到的 DB 查询能力，统一在此导入
    from sqlalchemy import select  # noqa: PLC0415

    from app.models import Rfq, RfqLine, RfqSupplier  # noqa: PLC0415

    say("\n[0] 清理上一次的演示数据")
    removed = clear_previous()
    say(f"  已删除上一批演示单据 {removed} 张" if removed else "  没有旧的演示单据，跳过")

    _, body = api.get("/meta/units")
    units = [u["name"] for u in (body.get("data") or [])]
    say(f"  计量单位字典 {len(units)} 项")

    say("\n[1] 生成询价单与报价")
    created: list[dict] = []
    for gi, group in enumerate(GROUPS, start=1):
        target_status = group.get("status", "closed")
        due_days = group["due_days"]
        # 时间自洽原则：单号里的日期 = created_at 的日期。单号由后端按创建日期生成
        # （RFQ + YYYYMMDD + 序号），若把 created_at 回填成过去就会与单号矛盾
        # （编号 1013 但创建时间 08-31）。因此创建时间统一取今天，
        # 用**截止时间**来区分状态：负值 → 已截止；正值 → 进行中。
        #
        # 注意：发布时截止时间必须晚于当前时间（发布校验），所以这里先给未来值，
        # 稍后再用 DB 把"已截止"那些单据的 deadline 回填到过去，
        # 由系统的惰性判定置为已截止（顺带验证了"截止时间已过即已截止"这条规则）。
        created_at = min(
            datetime.now().replace(hour=8, minute=30, second=0, microsecond=0),
            datetime.now() - timedelta(hours=1),
        )
        if target_status == "closed":
            deadline = (datetime.now() + timedelta(days=2)).replace(
                hour=17, minute=0, second=0, microsecond=0
            )
        elif target_status == "published":
            # 进行中：截止时间放在未来，且各单据错开（小时偏移随单据变化）
            hours = 4 + (hash(group["project"]) % 9)
            deadline = (datetime.now() + timedelta(days=abs(due_days), hours=hours)).replace(
                minute=0, second=0, microsecond=0
            )
        else:
            deadline = None

        sup_ids = [suppliers[i]["id"] for i in group["sups"] if i < len(suppliers)]
        payload = {
            "title": f"{PREFIX}{group['project']}采购询价·第{group.get('batch', gi)}批",
            "project": group["project"],
            "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%S") if deadline else None,
            "remark": "请按含税单价报价，注明交货周期与最小起订量。",
            "internal_remark": f"{group['project']}常规补货，优先考虑交货速度。",
            "supplier_ids": sup_ids,
            "lines": [
                {
                    "material_name": name,
                    "spec": spec,
                    "unit": unit,
                    "project": group["project"],
                    "quantity": str(qty),
                    "remark": "",
                }
                for (name, spec, unit, qty, _base) in group["lines"]
            ],
        }
        status_code, body = api.post("/rfqs", payload)
        if body.get("code") != 0:
            check(False, f"建单失败：{group['project']}", body.get("message"))
            continue
        rfq = body["data"]
        rid = rfq["id"]
        # 每行的"最低价归属"按行号轮换，保证比价表里最低价分散在不同供货商，
        # 而不是某一家通吃（那也体现不出比价的价值）。
        n_lines = len(group["lines"])
        pool = group["sups"]
        best_of = [[pool[(li + k) % len(pool)] for k in range(2)] for li in range(n_lines)]
        detail = {
            "id": rid,
            "no": rfq["rfq_no"],
            "project": group["project"],
            "group": group,
            "sup_ids": sup_ids,
            "created_at": created_at,
            "deadline": deadline,
            "target_status": target_status,
            "best_of": best_of,
        }

        if target_status == "draft":
            created.append(detail)
            check(True, f"草稿 {rfq['rfq_no']}（无明细，展示不完整草稿）")
            continue

        status_code, body = api.post(f"/rfqs/{rid}/publish")
        if body.get("code") != 0:
            check(False, f"发布失败：{rfq['rfq_no']}", body.get("message"))
            continue
        # 注意：best_of 在创建阶段就已算好并放进 detail，此处不要覆盖
        created.append(detail)
        check(True, f"{'已发布' if target_status == 'published' else '已截止'} {rfq['rfq_no']}"
                   f"（{len(group['lines'])} 行 / 邀请 {len(sup_ids)} 家）")

    say("\n[2] 录入各供货商报价")
    # 供应商竞争力倍率：索引越小越便宜（模拟不同供货商的报价水平）
    RATE = [1.00, 1.045, 1.09, 1.14, 1.20]
    for detail in created:
        group = detail["group"]
        if not group["lines"]:
            continue
        rid = detail["id"]
        _, body = api.get(f"/rfqs/{rid}")
        lines = body["data"]["lines"]
        sups = group["sups"]
        best_of = detail.get("best_of") or [list(range(2)) for _ in lines]

        # 让两张进行中的单据呈现"已报一部分"的催办场景：
        # 报表/进度页需要真实数据才能展示"未报价名单"与响应率不足的状态。
        partial = detail["target_status"] == "published" and any(
            k in group["project"] for k in ("综合办公室", "园区物业")
        )
        if partial:
            quoting = sups[: max(2, len(sups) // 2)]  # 报一半，留一半待催办
        else:
            quoting = sups

        for pos, sup_idx in enumerate(quoting):
            if sup_idx >= len(suppliers):
                continue
            supplier = suppliers[sup_idx]
            account = accounts.get(supplier["id"])
            if not account:
                continue
            sup_api = Api(args.base)
            sup_token = sup_api.login(account["username"], "supplier123")
            if not sup_token:
                check(False, f"{supplier['name']} 登录失败（报价跳过）")
                continue
            sup_api.token = sup_token

            quotes = []
            for li, line in enumerate(lines):
                base = group["lines"][li][4]
                # best_of[li] 是该行的"最低价候选池"（含 2 家），池内越靠前越便宜；
                # 不在池内的供货商按更大的倍率报价。
                line_pool = best_of[li] if li < len(best_of) else []
                pos_in_pool = line_pool.index(sup_idx) if sup_idx in line_pool else len(line_pool)
                factor = RATE[sup_idx] * (1.0 + 0.012 * pos_in_pool)
                # 加一点行内噪声，避免价格过于规整
                factor *= 1.0 + random.uniform(-0.008, 0.008)
                price = round(base * factor, 2)
                if pos_in_pool == 0:
                    price = round(base, 2)  # 该行的最低价锚定在基准价
                row = {
                    "line_uid": line["line_uid"],
                    "price_incl_tax": f"{price:.2f}",
                    "tax_included": True,
                    "tax_rate": random.choice(TAX_RATES),
                    "moq": random.choice([None, "1", "5", "10", "20"]),
                    "lead_time_days": random.choice([2, 3, 5, 7, 10, 15]),
                    "arrival_date": (date.today() + timedelta(days=random.choice([3, 5, 8, 12]))).isoformat(),
                    "remark": random.choice(["", "", "含运费", "货到付款", "需提前 3 天下单"]),
                }
                if row["moq"] is None:
                    del row["moq"]
                quotes.append(row)

            status_code, res = sup_api.put(f"/supplier/rfqs/{rid}/quotes", {"lines": quotes})
            if res.get("code") != 0:
                check(False, f"{supplier['name']} 报价失败（{detail['no']}）", res.get("message"))
                continue

            # 约 1/3 的供货商做一次改价，用于展示"改价历史"
            if pos % 3 == 0 and len(quotes) >= 2:
                revised = []
                for row in quotes[:2]:
                    new_price = round(float(row["price_incl_tax"]) * 0.97, 2)
                    item = dict(row)
                    item["price_incl_tax"] = f"{new_price:.2f}"
                    revised.append(item)
                sup_api.put(f"/supplier/rfqs/{rid}/quotes", {"lines": revised})

            # 全部提交：提交后状态为"已报价"，报表里的"报价家数"才准确。
            # （若只保存不提交，会得到 partial 状态，列表上出现"已填 N 行但显示未报价"的观感）
            sup_api.post(f"/supplier/rfqs/{rid}/submit")

        quoted_n = len(quoting)
        check(True, f"{detail['no']}：{quoted_n} 家已报价"
                   + ("（1 家故意未报价，用于展示催办场景）" if partial else ""))

    say("\n[3] 为种子单据补充报价（让示例单据也有比价数据）")
    # 种子单据（RFQ...0001 办公用品 / 0002 车间耗材）原本没有报价，
    # 报表一打开容易是空的；这里给它们也生成报价，并把创建时间回填到更早，
    # 使整套演示数据看起来像持续积累的业务记录。
    seed_base = {
        "办公用品": 18.5,
        "车间耗材": 42.0,
    }
    db = SessionLocal()
    try:
        seed_rfqs = db.scalars(
            select(Rfq).where(~Rfq.title.like(f"{PREFIX}%")).order_by(Rfq.id)
        ).all()
        for rfq in seed_rfqs:
            if rfq.status == "draft":
                continue
            lines = db.scalars(
                select(RfqLine).where(RfqLine.rfq_id == rfq.id).order_by(RfqLine.seq)
            ).all()
            assigns = db.scalars(
                select(RfqSupplier).where(RfqSupplier.rfq_id == rfq.id)
            ).all()
            if not lines or not assigns:
                continue
            # 已经有报价就跳过（避免重复叠加）
            if any((a.quoted_line_count or 0) > 0 for a in assigns):
                say(f"  {rfq.rfq_no} 已有报价，跳过")
                continue
            # 单号是 seed 时按"那一天"生成的（RFQ + 日期 + 序号），
            # 所以创建时间不能回填成别的日期，否则"单号 1013 / 创建时间 0831"自相矛盾。
            # 统一对齐到今天，只保留时间上的先后（早于演示单据的 09:30）。
            rfq.created_at = datetime.now().replace(hour=8, minute=5, second=0, microsecond=0)
            db.commit()

            rid = rfq.id
            _, body = api.get("/admin/supplier-accounts?page_size=100")
            accounts_map = {
                x["supplier_id"]: x for x in ((body.get("data") or {}).get("items") or [])
            }
            for ai, assignment in enumerate(assigns):
                account = accounts_map.get(assignment.supplier_id)
                if not account:
                    continue
                sup_api = Api(args.base)
                sup_token = sup_api.login(account["username"], "supplier123")
                if not sup_token:
                    continue
                sup_api.token = sup_token
                quotes = []
                for li, line in enumerate(lines):
                    base = seed_base.get(rfq.project or "", 20.0) * (1 + li * 0.35)
                    factor = RATE[ai % len(RATE)] * (1.0 + random.uniform(-0.01, 0.01))
                    quote_row = {
                        "line_uid": line.line_uid,
                        "price_incl_tax": f"{round(base * factor, 2):.2f}",
                        "tax_included": True,
                        "tax_rate": random.choice(TAX_RATES),
                        "lead_time_days": random.choice([3, 5, 7, 10]),
                        "arrival_date": (
                            date.today() + timedelta(days=random.choice([5, 8, 12]))
                        ).isoformat(),
                        "remark": random.choice(["", "含运费", "货到付款"]),
                    }
                    if random.random() < 0.5:
                        quote_row["moq"] = random.choice(["1", "5", "10"])
                    quotes.append(quote_row)
                _, res = sup_api.put(f"/supplier/rfqs/{rid}/quotes", {"lines": quotes})
                if res.get("code") == 0:
                    sup_api.post(f"/supplier/rfqs/{rid}/submit")
            check(True, f"{rfq.rfq_no}（{rfq.project}）补录 {len(assigns)} 家报价")
    finally:
        db.close()

    say("\n[4] 收尾：回填时间分布 + 把已截止的单据置为过去")
    # 顺序很关键：报价必须在"截止时间回填到过去"之前完成（截止后禁止再报价）。
    #
    # 1) created_at / published_at 回填成 days_ago 天前，让列表与报表的时间分布自然；
    # 2) 目标为 closed 的单据，把 deadline 回填到过去 —— 系统的惰性判定会把它自动
    #    视为已截止（同时验证了"截止时间已过即已截止"这条规则），无需手动调截止接口。
    db = SessionLocal()
    try:
        now = datetime.now()
        closed_n = 0
        for detail in created:
            rfq = db.get(Rfq, detail["id"])
            if not rfq:
                continue
            rfq.created_at = detail["created_at"]
            if rfq.status != "draft":
                rfq.published_at = detail["created_at"] + timedelta(hours=2)
            if detail["target_status"] == "closed":
                # 截止时间 = 当前时刻往前倒推（天 + 小时偏移），并归到整点。
                # 小时偏移与单据 id 相关，避免多张单据的截止时间撞在同一时刻。
                # 倒推保证一定早于当前时间；末尾再兜一次"晚于创建时间"。
                days_back = abs(int(detail["group"]["due_days"])) or 3
                past_deadline = (
                    now - timedelta(days=days_back, hours=6 + (rfq.id % 7))
                ).replace(minute=0, second=0, microsecond=0)
                if past_deadline <= rfq.created_at:
                    past_deadline = rfq.created_at + timedelta(hours=2 + (rfq.id % 5))
                rfq.deadline = past_deadline
                rfq.status = "closed"
                rfq.closed_at = past_deadline + timedelta(minutes=12)
                closed_n += 1
        db.commit()
        say(f"  已回填 {len(created)} 张单据的时间；{closed_n} 张置为已截止（deadline 在过去）")
    finally:
        db.close()

    for detail in created:
        if detail["target_status"] == "published":
            say(f"  保留 {detail['no']} 为进行中（截止 {detail['deadline']:%Y-%m-%d %H:%M}）")

    say("\n[4] 汇总演示数据")
    _, body = api.get("/rfqs?page_size=200")
    items = [x for x in ((body.get("data") or {}).get("items") or []) if x["title"].startswith(PREFIX)]
    _, body = api.get("/reports/summary?page_size=1")
    summary = body.get("data") or {}
    _, body = api.get("/admin/audit-logs?page_size=1")
    audit_total = ((body.get("data") or {}).get("meta") or {}).get("total", 0)

    say(f"  单据 {len(items)} 张：")
    for x in sorted(items, key=lambda v: v["id"]):
        say(f"    {x['rfq_no']}  {x['status']:9s}  {x['line_count']:2d} 行  "
            f"受邀 {x['supplier_count']} 家 / 已报 {x['quoted_count']} 家  {x['title']}")
    say(f"  统计汇总：询价单 {summary.get('rfq_count')} 张 / 明细 {summary.get('line_count')} 行 / "
        f"响应率 {summary.get('response_rate')} / 最低价合计 ¥{summary.get('best_amount')}")
    say(f"  操作日志累计 {audit_total} 条")

    say("\n" + "=" * 62)
    say(f" 完成：成功 {OK} / 失败 {FAIL}")
    say("=" * 62)
    say(" 登录演示：")
    say("   管理员  admin / Admin@2026          → 报价单、统计报表、账号管理")
    say("   采购员  wangcaigou / buyer123       → 仅看自己创建的单据")
    say("   供货商  hengxin_wenju / supplier123 → 手机端填报报价")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
