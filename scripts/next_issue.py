#!/usr/bin/env python3
"""
next_issue.py —— 期次归档与编号递增

每天自动跑时，「这一期是第几期、上一期的 data.json 叫什么」不能靠记忆，
也不能靠日期推算（可能断更、可能补更）。做法是从**归档文件名**里找最大编号。

目录约定（在工作目录下）：
  data.json            —— 当前正在做的这一期
  data_YYYYMMDD.json   —— 历史归档，一期一个
  archive.json         —— 期次台账（编号 / 日期 / 三个 md 文件名 / 状态）

用法：
  # 1) 开新一期：归档当前 data.json，返回新一期该用的编号与日期
  python3 next_issue.py --workdir <工作目录> --start

  # 2) 只查：看看下一期该用几号
  python3 next_issue.py --workdir <工作目录>

  # 3) 关掉这一期：把当前期登记进 archive.json
  python3 next_issue.py --workdir <工作目录> --close --issue No.002

退出码：0 正常；1 参数/文件问题
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys

ARCHIVE = "archive.json"


def log(t):
    print(t, flush=True)


def list_issues(workdir):
    """扫出所有已知期号：data.json 的 + 归档文件里的 + archive.json 的。

    归档文件名形如 data_20261022.json —— 文件名只带**日期**，
    期号要从归档文件的 meta.issue 里读（更可靠）。
    为什么要扫归档文件：agent 有可能直接覆盖 data.json 而忘了先归档，
    这时如果只读 data.json，编号会退回上一期、造成重号。
    """
    issues = {}   # "No.002" -> {"date": "2026.10.22", "src": "data.json"}
    dates = set()

    def add(meta, src):
        if not meta:
            return
        if meta.get("issue"):
            issues[meta["issue"]] = {"date": meta.get("date", ""), "src": src}
        if meta.get("date"):
            dates.add(meta["date"].replace(".", "").replace("-", ""))

    dj = os.path.join(workdir, "data.json")
    if os.path.exists(dj):
        try:
            with open(dj, encoding="utf-8") as f:
                add(json.load(f).get("meta", {}), "data.json")
        except Exception as e:
            log(f"  [WARN] 读 data.json 失败: {str(e)[:80]}")

    for fn in sorted(os.listdir(workdir)):
        m = re.match(r"^data_(\d{8})\.json$", fn)
        if not m:
            continue
        dates.add(m.group(1))
        try:
            with open(os.path.join(workdir, fn), encoding="utf-8") as f:
                add(json.load(f).get("meta", {}), fn)
        except Exception:
            pass   # 归档文件坏了不该阻断编号计算

    aj = os.path.join(workdir, ARCHIVE)
    if os.path.exists(aj):
        try:
            with open(aj, encoding="utf-8") as f:
                arch = json.load(f)
            for rec in arch.get("issues", []):
                if rec.get("issue"):
                    issues[rec["issue"]] = {"date": rec.get("date", ""), "src": ARCHIVE}
                    if rec.get("date"):
                        dates.add(rec["date"].replace(".", "").replace("-", ""))
        except Exception as e:
            log(f"  [WARN] 读 {ARCHIVE} 失败: {str(e)[:80]}")

    return issues, sorted(dates)


def next_issue_no(issues, dates=None, workdir=None):
    """从已知期号里算下一个。No.007 -> No.008。

    **保底逻辑**：如果所有期号都读不出来（归档文件损坏、台账丢了），
    宁可**跳过**几期，也不能退回 No.001 —— 重号意味着历史内容被覆盖、
    推送出去两期一样的编号。宁可空号，不可重号。
    """
    nums = []
    for k in issues:
        m = re.search(r"(\d+)", k)
        if m:
            nums.append(int(m.group(1)))
    if nums:
        return max(nums) + 1

    # 期号全丢：从归档文件的**日期**数量推断已经出了多少期
    if dates:
        log(f"  [WARN] 期号全部不可读，按已归档 {len(dates)} 期推算，宁可跳号不重号")
        return len(dates) + 1
    return 1


def archive_current(workdir, issues):
    """把当前 data.json 存成 data_YYYYMMDD.json（按它自己的 meta.date）。

    **空骨架不归档**：如果上一轮 agent 开了新一期就中断了，data.json 里
    躺着的是空骨架。把它归档成 data_<日期>.json 会让「已出过的期数」虚增，
    也会让那一天在归档目录里留下一份没有内容的记录。
    """
    dj = os.path.join(workdir, "data.json")
    if not os.path.exists(dj):
        log("  [跳过] 没有 data.json 可归档")
        return None
    try:
        with open(dj, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log(f"  [WARN] data.json 解析失败，不归档: {str(e)[:80]}")
        return None
    meta = data.get("meta", {})
    if not data.get("cards"):
        log("  [跳过] data.json 是空骨架（无卡片内容），不归档")
        return None
    d = (meta.get("date") or "").replace(".", "").replace("-", "")
    if not d:
        log("  [WARN] data.json 的 meta.date 为空，跳过归档")
        return None
    dest = os.path.join(workdir, f"data_{d}.json")
    if os.path.exists(dest):
        log(f"  [复用] 归档已存在: {os.path.basename(dest)}")
        return dest
    shutil.copy2(dj, dest)
    log(f"  [OK] 已归档: {os.path.basename(dest)}")
    return dest


def reset_data_json(workdir, issue, date_str):
    """把 data.json 重置成下一期的空骨架。

    为什么必须做：归档之后 data.json 里还留着上一期的 meta（No.001 / 旧日期）。
    agent 拿到编号后如果直接改内容、忘了改 meta，就会把上一期的东西
    改一改又发一遍 —— 编号对不上、内容也是旧的。**留一个明确写着
    「这一期该填什么」的骨架，比留一份旧内容安全得多。**
    """
    dj = os.path.join(workdir, "data.json")
    skeleton = {
        "meta": {
            "issue": issue,
            "date": date_str,
            "weekday": "一二三四五六日"[datetime.date.today().weekday()],
            "title": "胡子哥财经晨报",
            "title_en": "GLOBAL BRIEF · DAILY",
            "_待填": "本文件是本期骨架。卡片内容见 templates/data.template.json，"
                     "四张卡分别是：01 今日三条 / 02 隔夜市场温度 / 03 今日三件事 / 04 保险与税务观察。"
        },
        "cards": [],
        "footer": {
            "disclaimer": "本内容仅为公开信息整理，不构成任何投资建议。",
            "_待填": "填数据来源与风险提示"
        }
    }
    with open(dj, "w", encoding="utf-8") as f:
        json.dump(skeleton, f, ensure_ascii=False, indent=2)
    log(f"  [OK] data.json 已重置为 {issue} 骨架（内容待填）")
    return dj


def close_issue(workdir, issue, status="done", extra=None):
    """把当前期登记进 archive.json。"""
    aj = os.path.join(workdir, ARCHIVE)
    arch = {"issues": []}
    if os.path.exists(aj):
        try:
            with open(aj, encoding="utf-8") as f:
                arch = json.load(f)
        except Exception:
            pass
    arch.setdefault("issues", [])

    dj = os.path.join(workdir, "data.json")
    date_str = ""
    if os.path.exists(dj):
        with open(dj, encoding="utf-8") as f:
            date_str = json.load(f).get("meta", {}).get("date", "")

    rec = {"issue": issue, "date": date_str, "status": status,
           "closed_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    if extra:
        rec.update(extra)
    # 同编号不重复登记（重跑时覆盖）
    arch["issues"] = [r for r in arch["issues"] if r.get("issue") != issue]
    arch["issues"].append(rec)
    arch["issues"].sort(key=lambda r: r.get("issue", ""))

    with open(aj, "w", encoding="utf-8") as f:
        json.dump(arch, f, ensure_ascii=False, indent=2)
    log(f"  [OK] 已登记 {issue} → {ARCHIVE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--start", action="store_true", help="开新一期：归档当前 data.json")
    ap.add_argument("--close", action="store_true", help="关掉当前期：登记进 archive.json")
    ap.add_argument("--issue", default="", help="配合 --close 使用")
    ap.add_argument("--status", default="done", help="配合 --close 使用：done / skipped / failed")
    args = ap.parse_args()

    workdir = os.path.abspath(args.workdir)
    if not os.path.isdir(workdir):
        print(f"❌ 工作目录不存在: {workdir}")
        sys.exit(1)

    log("=" * 48)
    log(" 期次管理")
    log("=" * 48)

    issues, dates = list_issues(workdir)
    log(f" 已知期号 : {', '.join(sorted(issues.keys())) or '（无）'}")
    log(f" 已知日期 : {', '.join(dates) or '（无）'}")

    if args.start:
        log("\n→ 归档当前期")
        archive_current(workdir, issues)
        issues, dates = list_issues(workdir)

    n = next_issue_no(issues, dates, workdir)
    today = datetime.date.today()
    date_str = today.strftime("%Y.%m.%d")
    issue = f"No.{n:03d}"
    log("")
    log(f" 下一期编号 : {issue}")
    log(f" 今日日期   : {date_str}（{'一二三四五六日'[today.weekday()]}）")
    log(f" 归档文件名 : data_{today.strftime('%Y%m%d')}.json")

    if args.start:
        log("\n→ 重置 data.json 为新一期骨架")
        reset_data_json(workdir, issue, date_str)
    else:
        log("\n  （加 --start 会自动归档上一期并重置 data.json 骨架）")

    if args.close:
        if not args.issue:
            print("\n❌ --close 需要配 --issue No.XXX")
            sys.exit(1)
        log("")
        log("→ 关闭当前期")
        close_issue(workdir, args.issue, args.status)


if __name__ == "__main__":
    main()
