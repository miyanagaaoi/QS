#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# 375px 原子测量脚本（task-6 自检用，非业务代码）
# ---------------------------------------------------------------------------
# 为什么要"原子"：browser4-cli 的 resize（CDP Emulation）会在导航/重载之间丢失，
# 而 JS 侧断点（useBreakpoint）只在 resize 事件里更新：
#   若「先 resize 再 goto」，可能出现 CSS 已按 375px 生效、JS 仍认为是桌面宽度的
#   "半状态"（页面被 200px 侧栏挤压 → 内容被裁切，但 scrollWidth 检测不出来）。
# 因此这里固定流程：resize → reload → 校验(innerWidth=375 且卡片已渲染) → 立即度量。
#
# 用法：bash frontend/src/views/system/__verify__/measure375.sh dict|account|audit-log
set -u

B="browser4-cli -s feadmin"
ROOT="D:/dsh/xunjia"
page="${1:-dict}"

$B resize 375 812 >/dev/null 2>&1
$B goto "http://127.0.0.1:5173/system/$page" >/dev/null 2>&1
sleep 2

for i in 1 2 3; do
  $B resize 375 812 >/dev/null 2>&1
  $B reload >/dev/null 2>&1
  sleep 5
  d=$($B eval --json "JSON.stringify({iw:innerWidth,cards:document.querySelectorAll('.dt-card').length,dir:getComputedStyle(document.querySelector('.admin-layout')).flexDirection,pw:Math.round(document.querySelector('.sys-page').getBoundingClientRect().width)})" 2>&1 | tail -1)
  echo "diag($page,#$i): $d"
  case "$d" in
    *'"iw":375'*'"cards":'[1-9]*) break ;;
  esac
done

$B eval "window.__MEASURE_MODE='raw';'ok'" >/dev/null 2>&1
echo "RAW($page): $($B eval --await --file "$ROOT/frontend/src/views/system/__verify__/measure-dict.js" 2>&1 | tail -1)"

$B eval "window.__MEASURE_MODE='fix';'ok'" >/dev/null 2>&1
echo "FIX($page): $($B eval --await --file "$ROOT/frontend/src/views/system/__verify__/measure-dict.js" 2>&1 | tail -1)"
