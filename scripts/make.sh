#!/usr/bin/env bash
# make.sh —— 《胡子哥财经晨报》四图流水线一键执行
#
# 为什么要有这个脚本：
#   2026-10-22 那轮调版，一次会话跑了 85 次 build_cards、13 次 render、13 次 audit，
#   每一条都是单独一次工具调用、单独一次模型往返 —— 光「把三个命令串起来」这件事
#   就消耗了大量 token 和时间。这个脚本把整条链固定下来，改一次、跑一次、看一份摘要。
#
# 用法:
#   ./make.sh            全流程：算账 → 重建 → 渲染 → 体检 → 诊断
#   ./make.sh plan       只看竖向预算账（不动文件）
#   ./make.sh dry        只跑文案预检，不写 HTML
#   ./make.sh build      只重建 HTML（不渲染）
#   ./make.sh 4          只处理第 4 张（重建 → 渲染 → 体检）
#
# 路径可通过环境变量覆盖:
#   BRIEF_PROJ   项目根（默认 ~/WorkBuddy/每日简讯/global-brief）
#   BRIEF_DATA   data.json
#   BRIEF_OUT    输出目录（默认 $BRIEF_PROJ/cards）
#
# 退出码: 0 干净；1 阻断级问题；2 只有告警
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ="${BRIEF_PROJ:-${HOME}/WorkBuddy/每日简讯/global-brief}"
DATA="${BRIEF_DATA:-${PROJ}/data.json}"
OUT="${BRIEF_OUT:-${PROJ}/cards}"
MODE="${1:-all}"

# ---------- 运行时探测（沙箱里 PATH 不可靠） ----------
NODE=""
for c in "${HOME}"/.workbuddy/binaries/node/versions/*/bin/node /opt/homebrew/bin/node /usr/local/bin/node; do
  if [ -x "${c}" ]; then NODE="${c}"; break; fi
done
if [ -z "${NODE}" ]; then echo "❌ 找不到 node"; exit 1; fi
export NODE_PATH="${NODE_PATH:-${HOME}/.workbuddy/binaries/node/workspace/node_modules}"
export DOCTOR_NODE="${NODE}"

PY=""
for c in "${HOME}"/.workbuddy/binaries/python/versions/*/bin/python3 /usr/bin/python3; do
  if [ -x "${c}" ]; then PY="${c}"; break; fi
done
if [ -z "${PY}" ]; then echo "❌ 找不到 python3"; exit 1; fi

if [ ! -f "${DATA}" ]; then
  echo "❌ 找不到 ${DATA}"
  echo "   可用 BRIEF_DATA=/path/to/data.json ./make.sh 指定"
  exit 1
fi

ONLY=""
case "${MODE}" in
  all|build|plan|dry) ;;
  [0-9]*) ONLY="${MODE}" ;;
  *) echo "❌ 不认识的模式：${MODE}（用 all / plan / dry / build / 数字）"; exit 1 ;;
esac

# ---------- 分模式 ----------
if [ "${MODE}" = "plan" ]; then
  "${PY}" "${HERE}/build_cards.py" "${DATA}" -o "${OUT}" --plan
  exit $?
fi
if [ "${MODE}" = "dry" ]; then
  "${PY}" "${HERE}/build_cards.py" "${DATA}" -o "${OUT}" --dry
  exit $?
fi

# ---------- 全流程 ----------
echo "════ 1/4  重建 HTML"
BUILD_ARGS=""
[ -n "${ONLY}" ] && BUILD_ARGS="--only ${ONLY}"
# shellcheck disable=SC2086
"${PY}" "${HERE}/build_cards.py" "${DATA}" -o "${OUT}" ${BUILD_ARGS}
BUILD_RC=$?
if [ "${BUILD_RC}" -eq 1 ]; then
  echo "✋ 构建崩溃，停在这里"
  exit 1
fi

[ "${MODE}" = "build" ] && exit "${BUILD_RC}"

echo ""
echo "════ 2/4  渲染 PNG"
if [ -n "${ONLY}" ]; then
  "${NODE}" "${HERE}/render.cjs" "${OUT}/card-0${ONLY}.html"
else
  "${NODE}" "${HERE}/render.cjs" "${OUT}"
fi
RENDER_RC=$?

echo ""
echo "════ 3/4  版面体检"
if [ -n "${ONLY}" ]; then
  "${NODE}" "${HERE}/audit_layout.cjs" "${OUT}/card-0${ONLY}.html"
else
  "${NODE}" "${HERE}/audit_layout.cjs" "${OUT}"
fi
AUDIT_RC=$?

echo ""
echo "════ 4/4  盒模型诊断（估算 vs 实测）"
DOC_ARGS="--quiet"
[ -n "${ONLY}" ] && DOC_ARGS="${DOC_ARGS} --only ${ONLY}"
# shellcheck disable=SC2086
"${PY}" "${HERE}/doctor.py" "${DATA}" "${OUT}" ${DOC_ARGS}
DOC_RC=$?

# ---------- 汇总 ----------
echo ""
echo "════ 汇总"
[ "${BUILD_RC}" -eq 2 ] && echo "  预检  ⚠️ 有告警（见上）" || echo "  预检  ✔"
[ "${RENDER_RC}" -eq 0 ] && echo "  渲染  ✔" || echo "  渲染  ❌ 有版式问题"
[ "${AUDIT_RC}" -eq 0 ] && echo "  体检  ✔" || echo "  体检  ❌ 有阻断级问题"
[ "${DOC_RC}" -eq 0 ] && echo "  诊断  ✔ 估算与实测一致" || echo "  诊断  ❌ 有偏差或阻断"

if [ "${AUDIT_RC}" -ne 0 ] || [ "${DOC_RC}" -ne 0 ]; then
  exit 1
fi
[ "${BUILD_RC}" -eq 2 ] && exit 2
exit 0
