# v1.1.0 — 版本发布规则

给这个 skill 立一套「改在哪、什么时候发、发了怎么验」的规矩，并把它变成脚本。

## 新增

### `scripts/sync_check.sh` —— 跑之前的同步自查

逐文件比对本地 skill 目录与 GitHub 最新 Release 的 **blob sha**（不是只看版本号），
告诉你**哪里不一致**：

```
 本地版本   1.0.0
 远端版本   v1.0.0

 ⚠️  内容不同（4）：
      ~ README.md
      ~ SKILL.md
 ⚠️  仅本地有（3）：
      + VERSION
      + scripts/publish.sh
```

| 输出 | 含义 |
|---|---|
| `✅ 已同步` | 本地与远端完全一致 |
| `⚠️ 内容不同` | 改了东西没发布 |
| `⚠️ 仅本地有` | 新增文件没进仓库 |
| `⚠️ 仅远端有` | 远端有本地没有的文件（可能是别人改过） |
| `版本号相同但内容不同` | **改了东西忘了 bump 版本号** |

退出码：`0` 已同步 / `1` 有差异 / `2` 检查失败。
支持 `--json` 输出。

### `scripts/publish.sh` —— 发一版

同步 → 列出改动 → 确认 → bump 版本 → 提交 → 打 tag → 推送 → 建 Release → **核验三项**。

```bash
bash scripts/publish.sh --dry-run     # 演一遍，不推送
bash scripts/publish.sh                # 正式发（问版本号 + 要求确认）
bash scripts/publish.sh --version 1.2.0 --yes
```

### `VERSION` 文件

版本号单一事实来源，`publish.sh` 自动 bump。

## 规则（已写进 SKILL.md / checklist.md / README.md / 模板说明）

**三条铁律**

1. **改只在本地做** —— 改本机源目录，不直接改 git 仓库、不在 GitHub 上编辑
2. **确认后才上传** —— 改完先给用户看，等明确说了「发布／发版／推一下」再推。改 ≠ 发布
3. **每次上传必须更新 Release 版本** —— 只推 tag 不建 Release 视为没发完

**版本号**：`x.y.z` semver。修 bug → patch；加功能 → minor；改结构 → major。
**改了内容就必须 bump** —— 否则别人拉到的包「内容变了但版本号没变」，没法判断新旧。

**发布后核验三项，缺一即未完成**：推送成功 / tag 在远端 / Release 存在。

## 目录结构调整

原先 `README.md` / `LICENSE` / `.gitignore` 只在 GitHub 仓库里，本地 skill 目录没有 ——
导致本地不是完整发布单元，自查脚本会一直报「仅远端有」。

现在这三个文件收进本机 skill 目录，**本地目录 = 完整发布单元**，
`publish.sh` 的 rsync 一把同步过去。

git 工作副本从 `/tmp`（会被系统清理）移到
`~/.workbuddy/skills/.repos/global-finance-newslet/`，由 `publish.sh` 自动维护。

## 工作流新增第 0 步

```
第 0 步：同步自查（约 10 秒）—— 每次跑之前必做
```

退出码 `0` 才继续。不一致就说明跑的是旧逻辑，出的图和文档对不上。

## 踩坑记录（这次踩的）

- **macOS bash 3.2 空数组在 `set -u` 下报 unbound variable** —— 改用字符串拼接
- **`$VAR` 后紧挨非 ASCII 字符时变量名会吞掉该字符首字节** ——
  `$n_local、` 里的中文逗号被吞，变量展开成空。**写 shell 时变量一律用 `${VAR}`**
- **只比版本号不够** —— 改了东西忘了 bump 时版本号一样，必须比 blob sha 才抓得住

## 验证

- `sync_check.sh` 两种模式（人读 / JSON）均验证通过
- `publish.sh --dry-run` 正确列出 7 个文件改动
- 模板冒烟测试 4 张零告警（改说明没破坏 JSON 结构）
- 发布后 `sync_check.sh` 退出码回到 0
