#!/usr/bin/env bash
# publish.sh —— 发一版到 GitHub（本地改完、确认后跑这个）
#
# 流程：同步文件 → 自查 → 确认 → bump 版本 → 提交 → 打 tag → 推送 → 建 Release → 核验
#
# 用法：
#   bash scripts/publish.sh                 # 交互式：列出改动、要求确认、问版本号
#   bash scripts/publish.sh --version 1.1.0 # 指定版本号（跳过版本号提问）
#   bash scripts/publish.sh --yes           # 跳过确认（已确认过再用）
#   bash scripts/publish.sh --dry-run       # 只演一遍，不推送不建 Release
#
# 退出码：0 = 发布成功且核验通过；1 = 失败

set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="tychowu/Huzige-Daily-Newslet"
CLONE="$HOME/.workbuddy/skills/.repos/global-finance-newslet"

VERSION_ARG=""
ASSUME_YES=0
DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION_ARG="${2:-}"; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
done

fail() { echo ""; echo "❌ $1"; exit 1; }

# ── 0. 前置检查 ───────────────────────────────────────────────────
command -v gh >/dev/null || fail "找不到 gh，先装 GitHub CLI 并登录"
gh auth status >/dev/null 2>&1 || fail "gh 未登录，先跑 gh auth login"

# ── 1. 同步本地 skill 目录到 git 工作副本 ─────────────────────────
# 这一步是「本地改完 → 确认 → 上传」的关键：改的是 skill 目录，
# 发布只是把改动搬进 git 仓库。改一处就够，不会漏同步。
if [ ! -d "$CLONE/.git" ]; then
  echo "工作副本不存在，克隆中..."
  mkdir -p "$(dirname "$CLONE")"
  git clone -q "https://github.com/$REPO.git" "$CLONE" || fail "克隆失败"
fi

cd "$CLONE" || fail "进不去工作副本 $CLONE"
git fetch -q origin || fail "拉取失败"
git checkout -q main 2>/dev/null
git reset -q --hard origin/main || fail "重置到远端 main 失败"

# 同步文件（排除 .git / 缓存 / legacy / 运行产物）
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '__pycache__/' \
  --exclude 'cards/' \
  --exclude 'out/' \
  --exclude 'scripts/legacy/' \
  --exclude '*.pyc' \
  "$SKILL_DIR/" "$CLONE/"

# ── 2. 展示改动 ──────────────────────────────────────────────────
CHANGED=$(git status --porcelain)
if [ -z "$CHANGED" ]; then
  echo ""
  echo "ℹ️  没有任何文件改动 —— 无需发布。"
  echo "   （如果确实改了东西，检查是否落在排除名单里）"
  exit 0
fi

echo ""
echo "════════════════════════════════════════"
echo " 待发布改动"
echo "════════════════════════════════════════"
git status --short
echo ""
DIFFSTAT=$(git diff --stat | tail -1)
echo " 统计：$DIFFSTAT"
echo ""

# 未提交的新文件也要算进改动统计
NEW=$(git status --porcelain | grep -c '^??' || true)
if [ "${NEW:-0}" != "0" ]; then
  echo " ⚠️  有 ${NEW} 个新文件未纳入版本控制 —— 确认它们该进仓库"
  echo ""
fi

# ── 3. 确认 ──────────────────────────────────────────────────────
if [ "$DRY_RUN" = "1" ]; then
  echo "🔍 --dry-run：到此为止，不推送、不建 Release"
  exit 0
fi

if [ "$ASSUME_YES" != "1" ]; then
  echo "════════════════════════════════════════"
  read -r -p " 确认发布以上改动？(y/N) " ans
  case "$ans" in
    y|Y|yes|YES) ;;
    *) echo ""; echo "已取消，未推送任何东西。"; exit 0 ;;
  esac
  echo ""
fi

# ── 4. 版本号 ────────────────────────────────────────────────────
CURRENT=$(tr -d '[:space:]' < "$SKILL_DIR/VERSION")
if [ -z "$VERSION_ARG" ]; then
  # 默认建议 patch 位 +1
  MAJ=$(echo "$CURRENT" | cut -d. -f1)
  MIN=$(echo "$CURRENT" | cut -d. -f2)
  PAT=$(echo "$CURRENT" | cut -d. -f3)
  SUGGEST="$MAJ.$MIN.$((PAT+1))"
  read -r -p " 版本号（当前 ${CURRENT}，回车用 ${SUGGEST}）：" VERSION_ARG
  [ -z "$VERSION_ARG" ] && VERSION_ARG="$SUGGEST"
fi

if ! echo "$VERSION_ARG" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  fail "版本号格式不对：${VERSION_ARG}（应该是 x.y.z）"
fi

if [ "$VERSION_ARG" = "$CURRENT" ]; then
  fail "版本号与当前相同（${CURRENT}）。改了东西就要 bump 版本号 —— 这正是 sync_check.sh 报的『版本号相同但内容不同』"
fi

# 检查这个版本号是不是已经发过了
EXIST=$(gh release list --repo "$REPO" --limit 100 --json tagName --jq ".[].tagName" 2>/dev/null | grep -c "^v${VERSION_ARG}$" || true)
if [ "${EXIST:-0}" != "0" ]; then
  fail "v${VERSION_ARG} 已经存在了，换个版本号"
fi

echo "$VERSION_ARG" > "$SKILL_DIR/VERSION"
cp "$SKILL_DIR/VERSION" "$CLONE/VERSION"

# Release 说明是一次性文件：发布前可以写，publish.sh 用完会删掉。
# 没写就用 GitHub 自动生成的提交列表兜底。
if [ ! -f "$SKILL_DIR/RELEASE_NOTES.md" ]; then
  echo "ℹ️  没有 RELEASE_NOTES.md —— Release 说明将用 GitHub 自动生成的提交列表"
  echo "   （想自定义说明：先写 ~/.workbuddy/skills/global-finance-newslet/RELEASE_NOTES.md）"
fi

# ── 5. 提交 + 打 tag + 推送 ──────────────────────────────────────
git add -A
COMMIT_MSG="v${VERSION_ARG}：$(cd "$SKILL_DIR" && git --no-pager log -1 --pretty=%s 2>/dev/null || echo "发布 ${VERSION_ARG}")"
git -c user.name=tychowu -c user.email=tychowu@gmail.com commit -q -m "v${VERSION_ARG}" || fail "提交失败"

git tag -a "v${VERSION_ARG}" -m "v${VERSION_ARG}" || fail "打 tag 失败"

echo "→ 推送 main 与 tag..."
git push -q origin main || fail "推送 main 失败"
git push -q origin "v${VERSION_ARG}" || fail "推送 tag 失败"

# ── 6. 建 Release ────────────────────────────────────────────────
# 推 tag 不会自动建 Release（本仓库没配 Actions），必须手动建。
# 先查重再补 —— 不凭印象说「没建」。
if gh release view "v${VERSION_ARG}" --repo "$REPO" >/dev/null 2>&1; then
  echo "→ Release 已存在（可能是 Actions 自动建的），跳过创建"
else
  # Release 说明是**一次性**的：源目录里的 RELEASE_NOTES.md 用完即删，
  # 不该留在仓库里（它只描述那一版的改动，下一版就过期了）。
  NOTES="$SKILL_DIR/RELEASE_NOTES.md"
  if [ -f "$NOTES" ]; then
    gh release create "v${VERSION_ARG}" --repo "$REPO" --title "v${VERSION_ARG}" --notes-file "$NOTES" \
      || fail "创建 Release 失败"
    rm -f "$NOTES"
    rm -f "$CLONE/RELEASE_NOTES.md"
    echo "→ 已用掉 RELEASE_NOTES.md（一次性文件，不留在仓库）"
  else
    gh release create "v${VERSION_ARG}" --repo "$REPO" --title "v${VERSION_ARG}" \
      --generate-notes || fail "创建 Release 失败"
  fi
fi

# ── 7. 核验三项（缺一即发布未完成） ──────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo " 发布核验"
echo "════════════════════════════════════════"

OK=1

# ① 推送成功
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
  echo " ✅ 推送成功 —— 本地与远端 main 一致"
else
  echo " ❌ 推送核验失败"; OK=0
fi

# ② tag 已存在
if git ls-remote --tags origin "refs/tags/v${VERSION_ARG}" | grep -q .; then
  echo " ✅ Tag v${VERSION_ARG} 已在远端"
else
  echo " ❌ Tag v${VERSION_ARG} 不在远端"; OK=0
fi

# ③ Release 存在
if gh release view "v${VERSION_ARG}" --repo "$REPO" >/dev/null 2>&1; then
  echo " ✅ Release v${VERSION_ARG} 已创建"
else
  echo " ❌ Release v${VERSION_ARG} 不存在"; OK=0
fi

echo ""
if [ "$OK" = "1" ]; then
  echo " 🎉 v${VERSION_ARG} 发布完成"
  echo "    https://github.com/$REPO/releases/tag/v${VERSION_ARG}"
  echo ""
  echo " 最后一步：跑 scripts/sync_check.sh 确认本地与远端已同步"
else
  echo " ⚠️  发布未完成 —— 上面有 ❌ 项，需要手工处理"
  exit 1
fi
