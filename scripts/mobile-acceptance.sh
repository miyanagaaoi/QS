#!/usr/bin/env bash
# 移动端布局元素级验收（375px）
#
# 为什么需要它：`document.documentElement.scrollWidth <= innerWidth` 只能发现"页面级横向滚动条"，
# 无法发现**内容被 overflow:hidden 静默裁切**的情况（本项目踩过：AdminLayout 手机端缺
# flex-direction:column，内容区被压到 156px，而 scrollWidth 仍是 375）。
# 因此这里逐元素比较右边界，并输出关键容器宽度与热区尺寸。
#
# 用法：
#   bash scripts/mobile-acceptance.sh [BASE_URL] [SESSION]
# 前置：目标地址可访问，且该 browser4 会话已处于登录态（本脚本不负责登录）。
set -uo pipefail

BASE="${1:-http://127.0.0.1:5173}"
SESSION="${2:-mobile-check}"

PAGES=(
  "/purchase/rfq"
  "/purchase/rfq/new"
  "/purchase/report"
  "/system/account"
  "/system/dict"
  "/system/audit-log"
)

PROBE_OUT="$(dirname "$0")/.mobile-probe.json"
PROBE_B64="$(base64 -w0 <<'JS'
(() => {
  const vw = window.innerWidth;
  const overflow = [];
  document.querySelectorAll("*").forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    const tag = el.tagName.toLowerCase();
    if (tag === "html" || tag === "body") return;
    let p = el.parentElement, inScroller = false;
    while (p) {
      const ov = getComputedStyle(p).overflowX;
      if (ov === "auto" || ov === "scroll") { inScroller = true; break; }
      p = p.parentElement;
    }
    if (inScroller) return;
    if (r.right > vw + 1) {
      overflow.push(tag + "." + String(el.className || "").slice(0, 60) + " w=" + Math.round(r.width) + " over=" + Math.round(r.right - vw));
    }
  });
  const small = [];
  document.querySelectorAll("button, a, [role=button]").forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return;
    if (r.height < 44 || r.width < 44) {
      small.push(el.tagName.toLowerCase() + "." + String(el.className || "").slice(0, 40) + " " + Math.round(r.width) + "x" + Math.round(r.height));
    }
  });
  const body = document.querySelector(".al-body") || document.querySelector(".sl-body") || document.querySelector("main");
  const layout = document.querySelector(".admin-layout") || document.querySelector(".supplier-layout");
  return JSON.stringify({
    vw: vw,
    scrollWidth: document.documentElement.scrollWidth,
    contentWidth: body ? Math.round(body.getBoundingClientRect().width) : null,
    layoutDir: layout ? getComputedStyle(layout).flexDirection : null,
    cards: document.querySelectorAll(".dt-card, .lines-mobile .m-card, .mat").length,
    tables: document.querySelectorAll(".el-table").length,
    overflowCount: overflow.length,
    overflowTop: overflow.slice(0, 5),
    under44: small.slice(0, 6),
    apiErrors: Array.from(document.querySelectorAll(".el-message--error, .el-alert--error")).map(e => e.textContent.trim().slice(0, 50)),
  });
})()
JS
)"
[ -n "$PROBE_B64" ] || { echo "base64 不可用，请安装 coreutils"; exit 1; }

PASS=0; FAIL=0
echo "======================================================"
echo " 移动端元素级验收（375px）  目标: $BASE  会话: $SESSION"
echo "======================================================"

for p in "${PAGES[@]}"; do
  browser4-cli -s "$SESSION" goto "${BASE}${p}" >/dev/null 2>&1 || true
  sleep 2
  # resize 后必须 reload，否则布局不会按新视口重排（实测踩过）
  browser4-cli -s "$SESSION" resize 375 812 >/dev/null 2>&1 || true
  browser4-cli -s "$SESSION" reload >/dev/null 2>&1 || true
  sleep 3
  browser4-cli -s "$SESSION" eval --base64 "$PROBE_B64" 2>/dev/null | tail -1 > "$PROBE_OUT"
  echo
  echo "── $p"
  python - "$PROBE_OUT" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().strip()
try:
    d = json.loads(raw)
except Exception:
    print("   [x] 探针失败（未登录/页面未渲染？）:", raw[:100])
    sys.exit(2)
bad = []
if d["scrollWidth"] > d["vw"]:
    bad.append(f"页面级横向滚动 {d['scrollWidth']} > {d['vw']}")
if d["overflowCount"]:
    bad.append(f"元素越界 {d['overflowCount']} 个：{d['overflowTop']}")
if d["contentWidth"] and d["contentWidth"] < d["vw"] * 0.85:
    bad.append(f"内容区被挤压至 {d['contentWidth']}px（视口 {d['vw']}，应接近满宽）")
if d["under44"]:
    bad.append(f"热区 <44px：{d['under44']}")
if d["apiErrors"]:
    bad.append(f"页面报错：{d['apiErrors']}")
mark = "OK" if not bad else "!!"
print(f"   [{mark}] scrollW={d['scrollWidth']}/{d['vw']} 内容区={d['contentWidth']}px "
      f"flexDir={d['layoutDir']} 卡片={d['cards']} 表格={d['tables']} 越界={d['overflowCount']}")
for b in bad:
    print("        -", b)
sys.exit(1 if bad else 0)
PY
  if [ $? -eq 0 ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
done

rm -f "$PROBE_OUT"
echo
echo "======================================================"
echo " 结果：通过 $PASS / 失败 $FAIL"
echo "======================================================"
echo "（会话 '$SESSION' 未自动关闭；如需清理：browser4-cli -s $SESSION close）"
[ "$FAIL" -eq 0 ] || exit 1
