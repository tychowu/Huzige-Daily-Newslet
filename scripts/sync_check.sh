#!/usr/bin/env bash
# sync_check.sh —— 跑 skill 之前的同步自查
#
# 用途：确认本机 skill 目录与 GitHub 上的最新 Release 是否一致。
#       不一致时明确告诉你「哪里不一致」，而不是让你自己 diff。
#
# 用法：
#   bash scripts/sync_check.sh            # 自查（只读，不改任何东西）
#   bash scripts/sync_check.sh --json     # 机器可读输出
#
# 退出码：
#   0 = 已同步（本地与 GitHub 最新 Release 完全一致）
#   1 = 有差异（本地领先 / 远端领先 / 文件内容不同）
#   2 = 检查失败（网络、仓库不存在等）
#
# 注意：macOS 自带 bash 3.2，空数组在 `set -u` 下会报 unbound variable，
#       所以这里用字符串拼接而不是数组。

set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="tychowu/Huzige-Daily-Newslet"

REMOTE_TAG=$(gh release list --repo "$REPO" --limit 1 --json tagName \
             --jq '.[0].tagName' 2>/dev/null)
if [ -z "$REMOTE_TAG" ]; then
  echo "❌ 取不到 $REPO 的 Release 列表（检查 gh 登录状态与网络）" >&2
  exit 2
fi

LOCAL_VER=$(tr -d '[:space:]' < "$SKILL_DIR/VERSION" 2>/dev/null)
if [ -z "$LOCAL_VER" ]; then
  echo "❌ 本地缺少 VERSION 文件" >&2
  exit 2
fi

TREE=$(gh api "repos/$REPO/git/trees/$REMOTE_TAG?recursive=1" 2>/dev/null)
if [ -z "$TREE" ]; then
  echo "❌ 取不到 $REMOTE_TAG 的文件树" >&2
  exit 2
fi

# git hash-object 的等价实现：sha1("blob <len>\0" + content)
blob_sha() {
  local f="$1" len
  len=$(wc -c < "$f" | tr -d ' ')
  { printf "blob %s\0" "$len"; cat "$f"; } | shasum | awk '{print $1}'
}

# 参与同步的本地文件（与发布范围一致）
LOCAL_FILES=$(cd "$SKILL_DIR" && find . -type f \
  -not -path './.git/*' -not -path './__pycache__/*' -not -name '.DS_Store' \
  -not -path './scripts/legacy/*' | sed 's|^\./||' | sort)

DIFFS=""
ONLY_LOCAL=""
ONLY_REMOTE=""

for f in $LOCAL_FILES; do
  [ -z "$f" ] && continue
  local_sha=$(blob_sha "$SKILL_DIR/$f")
  remote_sha=$(echo "$TREE" | python3 -c "
import json,sys
t=json.load(sys.stdin).get('tree',[])
print(next((e.get('sha','') for e in t if e.get('path')=='''$f''' and e.get('type')=='blob'),''))
")
  if [ -z "$remote_sha" ]; then
    ONLY_LOCAL="$ONLY_LOCAL$f "
  elif [ "$local_sha" != "$remote_sha" ]; then
    DIFFS="$DIFFS$f "
  fi
done

for f in $(echo "$TREE" | python3 -c "
import json,sys
t=json.load(sys.stdin).get('tree',[])
for e in t:
    if e.get('type')=='blob': print(e.get('path',''))
" | sort); do
  [ -z "$f" ] && continue
  [ -f "$SKILL_DIR/$f" ] || ONLY_REMOTE="$ONLY_REMOTE$f "
done

n_diff=$(echo "$DIFFS" | wc -w | tr -d ' ')
n_local=$(echo "$ONLY_LOCAL" | wc -w | tr -d ' ')
n_remote=$(echo "$ONLY_REMOTE" | wc -w | tr -d ' ')
IN_SYNC="no"
if [ "$n_diff" = "0" ] && [ "$n_local" = "0" ] && [ "$n_remote" = "0" ]; then
  IN_SYNC="yes"
fi

if [ "${1:-}" = "--json" ]; then
  python3 -c "
import json
print(json.dumps({
  'local_version': '$LOCAL_VER',
  'remote_tag': '$REMOTE_TAG',
  'in_sync': '$IN_SYNC' == 'yes',
  'modified': '$DIFFS'.split(),
  'only_local': '$ONLY_LOCAL'.split(),
  'only_remote': '$ONLY_REMOTE'.split(),
}, ensure_ascii=False))
"
else
  echo "════════════════════════════════════════"
  echo " 同步自查 · $REPO"
  echo "════════════════════════════════════════"
  echo " 本地版本   $LOCAL_VER"
  echo " 远端版本   $REMOTE_TAG"
  echo ""

  if [ "$IN_SYNC" = "yes" ]; then
    echo " ✅ 已同步 —— 本地与 GitHub 最新 Release 完全一致"
    echo ""
  else
    [ "$n_diff" != "0" ] && { echo " ⚠️  内容不同（${n_diff}）："; for f in $DIFFS; do echo "      ~ $f"; done; }
    [ "$n_local" != "0" ] && { echo " ⚠️  仅本地有（${n_local}）："; for f in $ONLY_LOCAL; do echo "      + $f"; done; }
    [ "$n_remote" != "0" ] && { echo " ⚠️  仅远端有（${n_remote}）："; for f in $ONLY_REMOTE; do echo "      - $f"; done; }
    echo ""
    if [ "$LOCAL_VER" = "${REMOTE_TAG#v}" ]; then
      echo " 版本号相同但内容不同 —— 改了东西忘了 bump 版本号"
    else
      echo " 版本号不一致（本地 $LOCAL_VER / 远端 ${REMOTE_TAG#v}）"
    fi
    echo ""
    echo " 处理方式：确认改动无误后跑 scripts/publish.sh 发一版"
    echo ""
  fi
fi

[ "$IN_SYNC" = "yes" ] && exit 0
exit 1
