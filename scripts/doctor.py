#!/usr/bin/env python3
"""doctor.py —— 预算账 + 浏览器实测对照，一次跑完

为什么有这个文件：
  2026-10-22 那轮调版，为了定位「文字顶出白卡 5px」，我先算了 54 次内联 Python 探针、
  又写了 39 个临时 playwright 量测脚本，一次会话 85 次重建、1.07 亿 input token。
  真正的问题不是算得慢，是**每次只量一个数就得单开一次工具轮**。

  这个脚本把三件事合并成一次输出：
    1. plan_card() 的预算账（可用多少、每条分到多少、缺多少）
    2. doctor.cjs 量到的真实盒模型（行数、溢出、留白）
    3. 两者逐项对照 —— 估错的地方一眼看到，而不是靠猜

用法:
  python3 doctor.py <data.json> <cards 目录>
  python3 doctor.py data.json cards --quiet      # 只打不一致的
  python3 doctor.py data.json cards --no-cjs     # 不跑浏览器，只算账

前置:
  doctor.cjs 的 JSON 由本脚本自动调用生成（--no-cjs 可跳过）

退出码: 0 全部对齐；1 有偏差或阻断问题
"""

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_cards as B  # noqa: E402


def run_doctor_cjs(cards_dir, only=None):
    """调 doctor.cjs 拿实测数据，失败返回 None（不阻断纯算账模式）。"""
    node = os.environ.get("DOCTOR_NODE") or "node"
    json_path = "/tmp/doctor.json"
    cmd = [node, os.path.join(HERE, "doctor.cjs"), cards_dir, "--quiet", "--json", json_path]
    if only:
        cmd += ["--only", str(only)]
    env = dict(os.environ)
    # 沙箱里 node 常被钩子拦，这里沿用调用方的 NODE_PATH
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
        if r.returncode not in (0, 1):
            sys.stderr.write(f"  ⚠️ doctor.cjs 退出码 {r.returncode}：{r.stderr.strip()[:300]}\n")
            return None
    except Exception as e:
        sys.stderr.write(f"  ⚠️ 跑不了 doctor.cjs（{e}），只输出算账结果\n")
        return None
    if not os.path.exists(json_path):
        return None
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="预算账 + 实测对照")
    ap.add_argument("data", help="data.json 路径")
    ap.add_argument("cards", help="card-NN.html 所在目录")
    ap.add_argument("--only", type=int, help="只看第 N 张")
    ap.add_argument("--no-cjs", action="store_true", help="跳过浏览器实测，只算账")
    ap.add_argument("--quiet", action="store_true", help="只打不一致的条目")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    cards = data["cards"]

    actual = None if args.no_cjs else run_doctor_cjs(args.cards, args.only)
    by_file = {}
    if actual:
        for c in actual.get("cards", []):
            idx = int(c["file"].split("-")[1].split(".")[0])
            by_file[idx] = c

    diffs = 0      # 估算与实测不一致的项数
    blocks = 0     # 阻断级问题

    for i, card in enumerate(cards, 1):
        if args.only and i != args.only:
            continue
        p = B.plan_card(card)
        a = by_file.get(i)

        head = f"\n=== {i:02d}  {p['section']}  条目 {p['n_items']}"
        if p["squeezed"]:
            head += "   ❌ 文字底线被侵占"
            blocks += 1
        print(head)
        print(f"    可用 {p['stack']}px   需求 {sum(p['need'])}px   缺口 {p['over']:+d}px")

        for d in p["items"]:
            line = (f"    it{d['idx']} 「{d['kicker'] or '网格'}」"
                    f"  正文 {d['prose_chars']:>3}字 est {d['prose_lines']}行"
                    f" / 排得下 {d['lines_fit']}行"
                    f"  需求 {d['need']} 底线 {d['floor']} 分到 {d['alloc']}")

            # 与实测对照
            if a:
                ai = a["items"][d["idx"]] if d["idx"] < len(a.get("items", [])) else None
                if ai:
                    real_lines = ai.get("proseLines")
                    real_h = ai.get("itemH")
                    marks = []
                    if real_lines is not None and real_lines != d["prose_lines"]:
                        # 正文行数估算 vs 实测 —— 字宽模型漂移会在这里显形
                        marks.append(f"❌ 行数 est {d['prose_lines']} ≠ 实测 {real_lines}")
                        diffs += 1
                    if real_h is not None and abs(real_h - d["alloc"]) > 2:
                        marks.append(f"△ 高度 分{d['alloc']} 实测{real_h}")
                        diffs += 1
                    if ai.get("over", 0) > 0:
                        marks.append(f"❌ 顶出 {ai['over']}px")
                        blocks += 1
                    line += ("   " + "  ".join(marks)) if marks else "   ✓"
            print(line)

            if d["cut_lines"]:
                print(f"         → 砍 {d['cut_lines']} 行，压到 {d['target_chars']} 字以内")

        # 结论条 / 口径注 的估算 vs 实测
        if a:
            if a.get("strip") and p["body_lines"]:
                sl = a["strip"]["lines"]
                ok = sl == p["body_lines"]
                if not ok:
                    diffs += 1
                print(f"    结论条  est {p['body_lines']}行 / 实测 {sl}行"
                      f"   文字宽 {a['strip']['textW']}px"
                      + ("" if ok else "   ❌"))
            if a.get("note") and p["note_lines"]:
                nl = a["note"]["lines"]
                ok = nl == p["note_lines"]
                if not ok:
                    diffs += 1
                print(f"    口径注  est {p['note_lines']}行 / 实测 {nl}行"
                      f"   行高 {a['note']['lh']}px"
                      + ("" if ok else "   ❌"))
            if "gapItemToStrip" in a:
                g = a["gapItemToStrip"]
                # 1px 容差：margin-top 18px 实测常是 17.9（亚像素舍入），不是真挤
                bad = g < B.STRIP_GAP - 1
                if bad:
                    blocks += 1
                print(f"    条目→结论条留白 {g}px（下限 {B.STRIP_GAP}px）"
                      + ("   ❌ 太挤" if bad else "   ✓"))
            if a.get("steps"):
                s = a["steps"]
                print(f"    steps 上下留白 {s['topPad']} / {s['botPad']}"
                      f"（不对称 {s['asym']}px）"
                      + ("" if s["asym"] <= 8 else "   ❌ 没居中"))
                if s["asym"] > 8:
                    blocks += 1

        if not args.quiet:
            print(f"    需求明细 need={p['need']}  cap={p['cap']}  alloc={p['alloc']}")
        if not a:
            print("    ⚠️ 没有实测数据（--no-cjs 或 doctor.cjs 失败），只报估算")

    print("\n" + "─" * 60)
    if not actual:
        print("只算了账。要对照真实渲染，去掉 --no-cjs 并确保 node 可用。")
    else:
        if diffs:
            print(f"⚠️ 估算与实测不一致 {diffs} 处 —— 字宽/行高常量需要重新标定")
        else:
            print("✔ 估算与实测全部一致（字宽模型没有漂移）")
        if blocks:
            print(f"❌ 阻断级问题 {blocks} 处 —— 砍字，不要砍字号")
        else:
            print("✔ 无阻断级问题")
        tags = actual.get("tagSummary") or {}
        if tags:
            print(f"标签 {tags.get('total')} 个 / {tags.get('words')} 个词 / "
                  f"规格 {tags.get('specVariants')} 种"
                  + ("" if tags.get("specVariants") == 1 else "  ❌ 规格不唯一")
                  + ("" if not tags.get("conflict") else
                     "  ❌ 同词多色：" + "、".join(x["word"] for x in tags["conflict"])))

    return 1 if (diffs or blocks) else 0


if __name__ == "__main__":
    sys.exit(main())
