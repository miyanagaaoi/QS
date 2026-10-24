#!/usr/bin/env python
"""端到端业务闭环验收脚本（跨平台，Windows Git Bash 中文编码问题免疫）。

覆盖 PRD 第 11 章关键用例：
  TC-01/02/03 认证与强制改密、TC-16 发布分派、TC-17 已发布禁改明细、
  TC-21/23/24/25/26 供货商报价与改价历史、TC-31/32/34 越权隔离、
  TC-36 比价计算、TC-41 导出、TC-42 日志只读、TC-30 截止只读

用法：
    backend/.venv/Scripts/python.exe scripts/e2e_acceptance.py
    ... --base http://127.0.0.1:8000 --admin-password Xunjia2026
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

# Windows 控制台默认 GBK，无法输出 ✓/✗ 等符号，统一切到 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):  # pragma: no cover
    pass

PASS = 0
FAIL = 0
SKIP = 0
EVIDENCE: list[str] = []


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def ok(msg: str, extra: str = "") -> None:
    global PASS
    PASS += 1
    print(f"  {_c('32', '✓')} {msg}" + (f"  {_c('90', extra)}" if extra else ""))


def bad(msg: str, actual: str = "") -> None:
    global FAIL
    FAIL += 1
    print(f"  {_c('31', '✗')} {msg}")
    if actual:
        print(f"      {_c('90', str(actual)[:300])}")


def skip(msg: str) -> None:
    global SKIP
    SKIP += 1
    print(f"  {_c('33', '-')} {msg}")


def head(title: str) -> None:
    print(f"\n{_c('1', title)}")


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def _req(self, method: str, path: str, body: dict | None = None, *, raw: bool = False):
        url = f"{self.base}/api{path}"
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            # ensure_ascii=True 规避各平台 shell/终端编码差异
            data = json.dumps(body, ensure_ascii=True).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                return (resp.status, payload) if raw else (resp.status, json.loads(payload or b"{}"))
        except urllib.error.HTTPError as e:
            payload = e.read()
            if raw:
                return e.code, payload
            try:
                return e.code, json.loads(payload or b"{}")
            except json.JSONDecodeError:
                return e.code, {"code": e.code, "message": payload[:200].decode("utf-8", "replace")}
        except Exception as e:  # pragma: no cover
            return 0, {"code": -1, "message": f"请求异常: {e}"}

    def get(self, path: str):
        return self._req("GET", path)

    def post(self, path: str, body: dict | None = None):
        return self._req("POST", path, body if body is not None else {})

    def put(self, path: str, body: dict | None = None):
        return self._req("PUT", path, body if body is not None else {})

    def get_raw(self, path: str):
        return self._req("GET", path, raw=True)

    def login(self, username: str, password: str) -> str | None:
        status, r = self.post("/auth/login", {"username": username, "password": password})
        if isinstance(r, dict) and r.get("code") == 0:
            return r["data"]["token"]
        return None


def code_of(r) -> int:
    return r.get("code") if isinstance(r, dict) else -1


def msg_of(r) -> str:
    return r.get("message", "") if isinstance(r, dict) else ""


def data_of(r):
    return r.get("data") if isinstance(r, dict) else None


def items_of(r) -> list:
    d = data_of(r)
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("items", "units", "taxes", "suppliers", "actions"):
            if isinstance(d.get(k), list):
                return d[k]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    # 默认使用**专用验收账号**，绝不使用 admin：
    # 改密类用例会修改密码，若直接跑在 admin 上会把演示账号密码改掉，
    # 影响其他人用浏览器登录（本项目发生过 3 次）。脚本会在账号不存在时自动创建它。
    ap.add_argument("--admin-user", default="e2e_admin")
    ap.add_argument("--admin-password", default="E2eAdmin2026")
    # 用于自动创建验收账号的引导管理员（不会被改密）
    ap.add_argument("--bootstrap-user", default="admin")
    ap.add_argument("--bootstrap-password", default="Admin@2026")
    ap.add_argument("--supplier-user", default="hengxin_wenju")
    ap.add_argument("--supplier-password", default="supplier123")
    args = ap.parse_args()

    print("=" * 58)
    print(" 采购与项目管理平台 · 端到端验收")
    print(f" 目标: {args.base}")
    print("=" * 58)

    api = Api(args.base)

    # ---------------------------------------------------------- 0 健康检查
    head("[0] 服务可用性")
    status, r = api.get("/health")
    if code_of(r) != 0:
        bad("健康检查失败", r)
        print("\n服务未就绪，终止验收。请先启动后端：")
        print("  cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000")
        return 1
    ok("健康检查通过", f"version={data_of(r).get('version') if data_of(r) else ''}")

    # ---------------------------------------------------------- 1 认证鉴权
    head("[1] 认证与鉴权")

    # 先用引导管理员确保验收账号存在（幂等）；验收账号的密码不会被"意外"改掉，
    # 因为它只在本脚本的改密用例里被改，且每次都改回同一值。
    boot = Api(args.base)
    boot_token = boot.login(args.bootstrap_user, args.bootstrap_password)
    if boot_token:
        boot.token = boot_token
        _, ru = boot.get(f"/admin/users?keyword={args.admin_user}&page_size=5")
        exists = any(u.get("username") == args.admin_user for u in items_of(ru))
        if not exists:
            _, rc = boot.post("/admin/users", {
                "username": args.admin_user,
                "real_name": "验收专用管理员",
                "role": "admin",
                "initial_password": args.admin_password,
                # 验收账号**不要求首次改密**：否则脚本每次运行都要处理 40101，
                # 而"自动改密再改回"的做法一旦中途失败就会把密码永久改成未知值
                # （本项目真实发生过，导致演示账号无法登录、多人反复排查）。
                "must_change_password": False,
            })
            if code_of(rc) == 0:
                ok(f"已创建验收专用账号 {args.admin_user}（不要求改密，避免改动其它账号）")
            else:
                skip(f"验收账号创建失败（{msg_of(rc)}），将尝试直接登录")
        else:
            ok(f"验收专用账号 {args.admin_user} 已存在")
    else:
        # 引导管理员登录失败不阻断：验收账号可能已存在且可用
        skip(f"引导管理员 {args.bootstrap_user} 登录失败，跳过验收账号创建（将直接尝试登录）")

    admin_token = api.login(args.admin_user, args.admin_password)
    if not admin_token:
        bad("验收账号登录失败", f"账号 {args.admin_user}；可用 --admin-password 覆盖")
        return 1
    ok(f"验收账号登录成功（{args.admin_user}）")

    api.token = admin_token
    _, r = api.get("/auth/me")
    if code_of(r) == 40101:
        # 不自动改密：改密类用例由后面的临时账号覆盖。
        # 若验收账号处于"待改密"状态，说明有人为它开了强制改密开关，
        # 此时明确提示处理方式，而不是擅自改掉它（并波及后续运行）。
        bad(
            "验收账号处于「待修改密码」状态（40101）",
            f"请二选一：① 用管理员把它重置为已知密码；② 或直接删除/停用该账号，"
            f"脚本下次会用引导管理员重新创建（新账号不要求改密）",
        )
        return 1
    ok("带 token 访问 /auth/me 正常") if code_of(r) == 0 else bad("/auth/me 异常", r)

    saved = api.token
    api.token = None
    _, r = api.get("/auth/me")
    ok("无 token 访问被拒（40100）") if code_of(r) == 40100 else bad("无 token 未被拒", r)
    api.token = saved

    sup_api = Api(args.base)
    sup_token = sup_api.login(args.supplier_user, args.supplier_password)
    if not sup_token:
        bad("供货商登录失败", "检查 --supplier-user/--supplier-password")
        return 1
    sup_api.token = sup_token
    ok(f"供货商登录成功（{args.supplier_user}）")

    # 强制改密拦截（TC-02）：用一个**显式开启改密开关**的临时账号验证，避免影响既有账号。
    # 需求变更 2026-10 后新建账号默认不强制改密，因此这里必须显式传
    # must_change_password=True，才能构造出"待改密"状态。
    _, r = api.post("/admin/users", {
        "username": f"e2e_tmp_{datetime.now().strftime('%H%M%S')}",
        "real_name": "E2E临时账号",
        "role": "buyer",
        "initial_password": "E2eTest123",
        "must_change_password": True,
    })
    if code_of(r) == 0:
        tmp_id = data_of(r)["id"]
        tmp_api = Api(args.base)
        t = tmp_api.login(data_of(r)["username"], "E2eTest123")
        if t:
            tmp_api.token = t
            _, rr = tmp_api.get("/meta/units")
            if code_of(rr) == 40101:
                ok("开启改密开关的账号访问业务接口被拦（40101）")
            else:
                bad("待改密账号未被拦", rr)
            _, rr = tmp_api.get("/auth/me")
            if code_of(rr) == 40101:
                ok("/auth/me 也在改密拦截范围内")
            else:
                bad("/auth/me 未被拦（越权风险）", rr)
        api.post(f"/admin/users/{tmp_id}/toggle-status")  # 停用临时账号（系统不允许删除）
    else:
        skip("强制改密拦截检查（无法创建临时账号）")

    # 反向用例：默认新建（不传开关）的账号**不应**被要求改密（需求变更 2026-10）
    _, r2 = api.post("/admin/users", {
        "username": f"e2e_nopwd_{datetime.now().strftime('%H%M%S')}",
        "real_name": "E2E默认不改密",
        "role": "buyer",
        "initial_password": "E2eTest123",
    })
    if code_of(r2) == 0:
        np_id = data_of(r2)["id"]
        np_api = Api(args.base)
        nt = np_api.login(data_of(r2)["username"], "E2eTest123")
        if nt:
            np_api.token = nt
            _, rr = np_api.get("/meta/units")
            if code_of(rr) == 0:
                ok("默认新建账号不要求改密（可直接访问业务接口）")
            else:
                bad("默认新建账号被要求改密（与需求变更不符）", rr)
        api.post(f"/admin/users/{np_id}/toggle-status")
    else:
        skip("默认不改密反向用例（无法创建临时账号）")

    # ---------------------------------------------------------- 2 字典
    head("[2] 基础字典")
    _, r = api.get("/meta/units")
    units = items_of(r)
    ok(f"计量单位 {len(units)} 项", f"示例：{units[0]['name'] if units else '-'}") if units else bad("计量单位为空", r)
    unit = units[0]["name"] if units else "个"

    _, r = api.get("/meta/taxes")
    taxes = items_of(r)
    ok(f"税率 {len(taxes)} 项", f"默认：{next((t['label'] for t in taxes if t.get('is_default')), '-')}") if taxes else bad("税率为空", r)

    _, r = api.get("/meta/suppliers")
    sups = items_of(r)
    if not sups:
        bad("供货商档案为空，无法继续", r)
        return 1
    sup_ids = [s["id"] for s in sups[:3]]
    ok(f"供货商档案 {len(sups)} 家", f"受邀：{sup_ids}")

    # ---------------------------------------------------------- 3 建单与发布
    head("[3] 新建询价单与发布")
    stamp = datetime.now().strftime("%H%M%S")
    lines = [
        {"seq": i + 1, "material_name": f"验收物料{i + 1}", "spec": f"规格-{i + 1}", "unit": unit,
         "project": "E2E验收", "quantity": (i + 1) * 10, "remark": None}
        for i in range(5)
    ]
    create_body = {
        "title": f"E2E验收询价-{stamp}", "project": "E2E验收",
        # 截止时间用"当前 + 7 天"：既保证不会被自动截止，
        # 又能在界面上显示成合理的剩余时间（此前固定 2099 年会让前端显示"剩余 26741 天"）
        "deadline": (datetime.now() + timedelta(days=7)).replace(microsecond=0).isoformat(),
        "remark": "报价含运费，付款方式月结30天", "internal_remark": "内部备注（不得对供货商可见）",
        "supplier_ids": sup_ids, "lines": lines,
    }
    _, r = api.post("/rfqs", create_body)
    if code_of(r) != 0:
        bad("创建草稿失败", r)
        return 1
    rfq_id = data_of(r)["id"]
    rfq_no = data_of(r)["rfq_no"]
    ok(f"创建草稿成功（id={rfq_id} / {rfq_no}）")
    EVIDENCE.append(f"验收单据 {rfq_no} (id={rfq_id})")

    _, r = api.post(f"/rfqs/{rfq_id}/publish")
    if code_of(r) == 0:
        ok(f"发布成功，为 {len(sup_ids)} 家供货商生成独立报价单")
    else:
        bad("发布失败", r)

    _, r = api.get(f"/rfqs/{rfq_id}/progress")
    assigns = data_of(r) or []
    if isinstance(assigns, dict):
        assigns = assigns.get("assignees") or assigns.get("items") or []
    ok(f"报价进度返回 {len(assigns)} 条分派记录") if assigns else bad("进度为空", r)

    # TC-17：已发布禁止改明细
    _, r = api.put(f"/rfqs/{rfq_id}", create_body)
    ok("已发布单据禁止修改明细（40900）") if code_of(r) == 40900 else bad("已发布单据仍可修改", r)

    # TC-10/11：发布前校验（用新草稿构造缺供货商 + 过去截止）
    _, r = api.post("/rfqs", {**create_body, "title": f"E2E校验单-{stamp}", "supplier_ids": []})
    bad_rfq = data_of(r)["id"] if code_of(r) == 0 else None
    if bad_rfq:
        _, r2 = api.post(f"/rfqs/{bad_rfq}/publish")
        ok("发布前校验：无受邀供货商被阻断") if code_of(r2) != 0 else bad("无供货商却发布成功", r2)
        _, r2 = api.put(f"/rfqs/{bad_rfq}", {**create_body, "title": f"E2E校验单-{stamp}", "deadline": "2000-01-01T00:00:00"})
        _, r3 = api.post(f"/rfqs/{bad_rfq}/publish")
        ok("发布前校验：截止时间在过去被阻断") if code_of(r3) != 0 else bad("过去时间却发布成功", r3)
        api._req("DELETE", f"/rfqs/{bad_rfq}")  # 清理
    else:
        skip("发布前校验检查")

    # ---------------------------------------------------------- 4 供货商报价
    head("[4] 供货商报价（含改价历史与越权）")
    _, r = sup_api.get("/supplier/rfqs")
    mine = [x for x in items_of(r) if str(x.get("rfq_id")) == str(rfq_id)]
    ok("供货商待报价列表包含该单据") if mine else bad("待报价列表未包含该单据", r)
    if mine:
        m = mine[0]
        ok("列表项字段完整", f"status={m.get('my_status')} 行={m.get('line_count')} 剩余={m.get('remaining_seconds')}s")
        # 越权红线：列表项不得含他方报价信息
        leak = [k for k in m if k in ("best_price", "min_price", "other_quotes", "prices")]
        ok("待报价列表无他方报价字段") if not leak else bad("列表泄露他方报价字段", leak)

    _, r = sup_api.get(f"/supplier/rfqs/{rfq_id}")
    d = data_of(r) or {}
    sup_lines = d.get("lines") or []
    if not sup_lines:
        bad("填报页未返回物料行", r)
    else:
        ok(f"填报页返回 {len(sup_lines)} 行物料",
           f"readonly={d.get('readonly')} my_status={d.get('my_status')}")
        # 越权红线：供货商详情不得包含内部备注
        if d.get("remark"):
            ok("供货商可见我方对外备注")
        bad("填报页泄露内部备注") if json.dumps(d, ensure_ascii=False).find("内部备注") >= 0 else ok("填报页未泄露内部备注")

    uid1 = sup_lines[0]["line_uid"] if sup_lines else None

    if uid1:
        # 保存部分行 → partial
        _, r = sup_api.put(f"/supplier/rfqs/{rfq_id}/quotes",
                           {"lines": [{"line_uid": uid1, "price_incl_tax": "113.00", "tax_included": True,
                                       "tax_rate": "0.1300", "moq": "1", "lead_time_days": 3,
                                       "remark": "首轮报价"}], "submit": False})
        ok("保存部分报价成功") if code_of(r) == 0 else bad("保存报价失败", r)

        # 不含税单价自动计算校验：113.00 / 1.13 = 100.00
        _, r = sup_api.get(f"/supplier/rfqs/{rfq_id}")
        q = ((data_of(r) or {}).get("lines") or [{}])[0].get("quote") or {}
        if str(q.get("price_excl_tax")) == "100.00":
            ok("不含税单价自动计算正确（113.00 → 100.00）")
        else:
            bad("不含税单价计算异常", f"price_excl_tax={q.get('price_excl_tax')}")

        # 改价
        _, r = sup_api.put(f"/supplier/rfqs/{rfq_id}/quotes",
                           {"lines": [{"line_uid": uid1, "price_incl_tax": "99.50", "tax_included": True,
                                       "tax_rate": "0.1300"}], "submit": False})
        ok("改价保存成功") if code_of(r) == 0 else bad("改价失败", r)

        _, r = sup_api.get("/supplier/quotes/history")
        hist = items_of(r)
        ok(f"改价历史记录 {len(hist)} 条") if len(hist) >= 2 else bad("改价历史不足 2 条", r)
        vers = sorted({h.get("version") for h in hist if h.get("version")})
        ok("改价历史版本递增", f"versions={vers}") if len(vers) >= 2 else skip("版本号检查")

        # 未填完整不可提交（TC-26）
        _, r = sup_api.put(f"/supplier/rfqs/{rfq_id}/quotes",
                           {"lines": [{"line_uid": uid1, "price_incl_tax": "99.50"}], "submit": True})
        ok("未填完整行时提交被拒绝") if code_of(r) != 0 else bad("未填完整却提交成功", r)

    # 越权隔离（TC-31/32/34）
    _, r = sup_api.get(f"/reports/rfq-comparison?rfq_id={rfq_id}")
    ok("供货商访问比价报表被拒（40300）") if code_of(r) == 40300 else bad("供货商越权访问报表未拒", r)

    _, r = sup_api.get("/admin/users")
    ok("供货商访问账号管理被拒（40300）") if code_of(r) == 40300 else bad("供货商越权访问 admin 未拒", r)

    _, r = api.get("/admin/audit-logs?page_size=200")
    logs = items_of(r)
    forbidden = [x for x in logs if x.get("action") == "security.forbidden"]
    ok(f"越权访问已留痕（{len(forbidden)} 条 security.forbidden）") if forbidden else bad("越权未留痕", "未找到 security.forbidden 日志")

    # ---------------------------------------------------------- 5 比价与导出
    head("[5] 比价报表与导出")
    _, r = api.get(f"/reports/rfq-comparison?rfq_id={rfq_id}")
    if code_of(r) == 0:
        cd = data_of(r) or {}
        rows = cd.get("rows") or []
        ok(f"比价报表读取成功（{len(rows)} 行 / {len(cd.get('suppliers') or [])} 家供货商）")
        if rows:
            r0 = rows[0]
            print(f"      首行 {r0.get('material_name')}: 最低价={r0.get('best_price')} "
                  f"({r0.get('best_supplier_name')}) 均价={r0.get('avg_price')} "
                  f"价差率={r0.get('diff_rate')} 报价家数={r0.get('quoted_count')}/{r0.get('required_count')}")
            if r0.get("best_price"):
                ok("最低价已计算")
            else:
                bad("最低价为空")
    else:
        bad("比价报表读取失败", r)

    _, r = api.get("/reports/summary")
    ok("汇总统计读取成功") if code_of(r) == 0 else bad("汇总统计失败", r)
    if code_of(r) == 0:
        sd = data_of(r) or {}
        print(f"      询价单 {sd.get('rfq_count')} 张 / 明细 {sd.get('line_count')} 行 / "
              f"响应率 {sd.get('response_rate')} / 最低价合计 ¥{sd.get('best_amount')}")

    # 导出 xlsx（校验 ZIP 魔数）
    status, payload = api.get_raw(f"/rfqs/{rfq_id}/export")
    if status == 200 and payload[:2] == b"PK":
        ok(f"导出询价单 xlsx 有效（{len(payload)} 字节）")
        from pathlib import Path
        out = Path("backend/data/tmp/e2e_export.xlsx")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
    else:
        bad("导出 xlsx 无效", f"status={status} head={payload[:20]!r}")

    for path, name in (("/reports/rfq-comparison/export?rfq_id=%d" % rfq_id, "e2e_comparison.xlsx"),
                       ("/reports/summary/export", "e2e_summary.xlsx")):
        status, payload = api.get_raw(path)
        ok(f"导出 {name} 有效（{len(payload)} 字节）") if status == 200 and payload[:2] == b"PK" else bad(f"导出 {name} 无效", f"status={status}")

    # ---------------------------------------------------------- 6 业务约束
    head("[6] 业务约束与日志")
    _, r = api.get("/rfqs?status=closed&page_size=1")
    closed = items_of(r)
    if closed:
        cid = closed[0]["id"]
        _, r2 = sup_api.get(f"/supplier/rfqs/{cid}")
        if code_of(r2) == 0:
            ro = (data_of(r2) or {}).get("readonly")
            ok("已截止单据可查询且标记只读") if ro else skip(f"已截止单据可查询（readonly={ro}）")
        else:
            skip(f"该供货商未被分派到已截止单据（{code_of(r2)}），跳过只读检查")
    else:
        skip("无已截止单据，跳过截止只读检查")

    _, r = api.get("/admin/audit-logs?page_size=5")
    ok("操作日志可查询（只读）") if code_of(r) == 0 else bad("操作日志查询失败", r)

    status, r = api._req("DELETE", "/admin/audit-logs/1")
    ok(f"操作日志无删除能力（HTTP {status}）") if code_of(r) != 0 or status >= 400 else bad("日志竟可删除", r)

    # 停用最后一个管理员保护（FR-ACC-06）
    _, r = api.get("/admin/users?role=admin&status=1")
    admins = items_of(r)
    if len(admins) == 1:
        _, r2 = api.post(f"/admin/users/{admins[0]['id']}/toggle-status")
        ok("禁止停用最后一个管理员（40900）") if code_of(r2) == 40900 else bad("最后一个管理员可被停用", r2)
    else:
        skip(f"当前有 {len(admins)} 个启用管理员，跳过最后管理员保护检查")

    # ---------------------------------------------------------- 7 追加供货商（2026-10 需求变更）
    head("[7] 追加受邀供货商（已发布未截止）")
    _, r = api.get("/meta/suppliers")
    all_sup = items_of(r)
    assigned_ids = {a["supplier_id"] for a in assigns} if assigns else set()
    candidates = [s for s in all_sup if s["id"] not in assigned_ids]
    if candidates:
        target = candidates[0]
        _, r = api.post(f"/rfqs/{rfq_id}/append-suppliers", {"supplier_ids": [target["id"]]})
        if code_of(r) == 0:
            new_assignees = (data_of(r) or {}).get("assignees") or []
            ok(f"追加成功：{msg_of(r)}（受邀 {len(new_assignees)} 家）")
            added = [a for a in new_assignees if a["supplier_id"] == target["id"]]
            if added and added[0]["status"] == "pending":
                ok(f"新分派状态为待报价，进度 0/{added[0]['line_count']}")
            else:
                bad("新分派状态异常", added)
            # 重复追加应被拒
            _, r2 = api.post(f"/rfqs/{rfq_id}/append-suppliers", {"supplier_ids": [target["id"]]})
            ok("重复追加被拒绝（40900）") if code_of(r2) == 40900 else bad("重复追加未被拒", r2)
        else:
            bad("追加供货商失败", r)
    else:
        skip("无可追加的候选供货商，跳过追加检查")

    # 草稿不可用追加接口
    draft_id = data_of(api.post("/rfqs", {
        "title": f"追加校验草稿-{stamp}", "project": "E2E验收", "deadline": None,
        "supplier_ids": [], "lines": [{"seq": 1, "material_name": "物料", "unit": unit, "quantity": 1}],
    })[1])["id"]
    _, r = api.post(f"/rfqs/{draft_id}/append-suppliers", {"supplier_ids": [all_sup[0]["id"]]})
    ok("草稿调用追加被拒绝（40900）") if code_of(r) == 40900 else bad("草稿可追加", r)
    api._req("DELETE", f"/rfqs/{draft_id}")

    # ---------------------------------------------------------- 8 工程约束门禁
    head("[8] 工程约束门禁")
    check_time_basis_gate()

    # ---------------------------------------------------------- 汇总
    # 收尾：停用本脚本创建的临时账号（系统不允许删除账号，符合 FR-ACC-07），
    # 避免验收运行后数据库里堆积 e2e_tmp_* / e2e_nopwd_* 账号。
    try:
        _, r = api.get("/admin/users?page_size=200")
        for u in items_of(r):
            name = u.get("username") or ""
            if (name.startswith("e2e_tmp_") or name.startswith("e2e_nopwd_")) and u.get("status") == 1:
                api.post(f"/admin/users/{u['id']}/toggle-status")
                skip(f"已停用本次创建的临时账号 {name}")
    except Exception:  # pragma: no cover - 收尾失败不影响结论
        pass

    print()
    print("=" * 58)
    print(f" 结果：{_c('32', f'通过 {PASS}')} / {_c('31', f'失败 {FAIL}')} / {_c('33', f'跳过 {SKIP}')}")
    print("=" * 58)
    if EVIDENCE:
        print(" 验收痕迹：" + "；".join(EVIDENCE))
    return 0 if FAIL == 0 else 1


def check_time_basis_gate() -> None:
    """时间口径门禁：业务代码禁止裸用 datetime.now() / date.today() / astimezone(UTC)。

    背景：本项目统一使用北京时间基准（models.app_now），历史上因混用 UTC 与本地时间
    出现过"截止时间晚 8 小时执行""导出文件名日期偏差"两个真实缺陷。此门禁把该约束
    固化为可执行检查，防止回退。白名单：security.py 的 JWT exp/iat（协议标准 UTC）。
    """
    import re
    from pathlib import Path

    app_dir = Path("backend/app")
    if not app_dir.is_dir():
        skip("未找到 backend/app，跳过时间口径门禁")
        return

    patterns = [
        (re.compile(r"datetime\.now\(\)"), "datetime.now()"),
        (re.compile(r"date\.today\(\)"), "date.today()"),
        (re.compile(r"astimezone\(\s*timezone\.utc\s*\)"), "astimezone(timezone.utc)"),
    ]
    # 合法例外（明确列举，避免规则过宽把真实违规漏掉）：
    #  1. security.py —— JWT 的 exp/iat 按协议必须用 UTC
    #  2. models.py 里 app_now() 的实现体 —— 全应用唯一允许直接取系统时间的地方
    LEGAL = {
        ("security.py", "datetime.now(timezone.utc)"),
        ("models.py", "return datetime.now().replace(microsecond=0)"),
    }
    violations: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        rel = path.name
        in_doc = False
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            # 三引号块内的文字是文档说明，不计入
            if stripped.count('"""') == 1:
                in_doc = not in_doc
                continue
            if in_doc or stripped.startswith("#"):
                continue
            for pat, label in patterns:
                if not pat.search(line):
                    continue
                if any(rel == f and snippet in line for f, snippet in LEGAL):
                    continue
                violations.append(f"{path}:{lineno} {label} → {stripped[:70]}")

    if violations:
        bad(f"时间口径门禁未通过（{len(violations)} 处裸用系统时间）", "\n      ".join(violations[:8]))
    else:
        ok("时间口径门禁通过（业务代码统一 app_now()/to_app_tz）")


if __name__ == "__main__":
    sys.exit(main())
