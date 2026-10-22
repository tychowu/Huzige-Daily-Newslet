#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_cards.py —— 《胡子哥财经晨报》四张紧凑卡生成器

用法:
    python3 build_cards.py data.json -o out/

产出:
    out/card-01.html ... card-04.html   每张 = banner + 1080x1440 正文页 + footer
    再交给 render.cjs 批量截图

版式约束（手机阅读优先，勿改）:
    · 画布宽 1080，正文页严格 1080x1440（3:4）
    · 一张卡装 2–3 条讯息，每条 = 眉标 + 结论 + 一句解释 + 一个视觉件
    · banner 在页面范围外；footer 紧凑，只放本页来源 + 免责 + 大二维码
    · 段落名做成本页右下角角标；footer 不放期号、不放页码
    · 主标题单行自适应（≤52px），任何文字不小于 22px
"""

import argparse
import base64
import json
import math
import os
import re
import sys
from html import escape

# ---------------------------------------------------------------- 设计令牌

CRIMSON = "#800000"
NAVY = "#1F497D"
INK = "#1A1A1A"
INK2 = "#2E2E2E"
# 次要灰：#6B6558 在米底上的对比度 5.45:1（WCAG AA 要求 4.5:1）
INK3 = "#6B6558"
INK4 = "#4A4438"
PAPER = "#FAF8F3"
CARD = "#FFFFFF"
LINE = "#E6DFD0"
UP_RED = "#B3261E"       # 涨（中国习惯）
DOWN_GREEN = "#1E7B4E"   # 跌

# 语义标签配色 · 四档互斥 · 全局唯一一套规则
#
#   2026-10-22 定稿（胡子哥最终裁定，**这是唯一有效版本，不要再自行"优化"**）：
#     窗口 = 绿   高位 = 蓝   风险 = 红   观察 = 黄
#
#   四条色相来自胡子哥指定的截图取样（Pillow 逐像素取文字色 + 底色），
#   不是推导出来的，别再拿色相间距/饱和度理论去改它。取色结果：
#     绿  文字 #266C4B  底 #E8F3EC   （截图 1）
#     黄  文字 #8B5B10  底 #FCF3E4   （截图 2）
#
#   实测对比度（对自家浅底，WCAG AA 门槛 4.5:1）：
#     风险 9.27:1 > 高位 7.73:1 > 窗口 5.55:1 > 观察 5.30:1
#   这个梯度是**有意保留**的，不是缺陷：红最重 → 第一眼先看到「风险」，
#   绿/黄偏轻 → 作为背景性状态标注退到第二层。别再按"对比度必须齐平"去压平它。
#
#   ⚠ 已知取舍（改之前先想清楚）：窗口绿 #266C4B 与「跌」绿 #1E7B4E 色相仅差 0.7°。
#   同框时靠**浅绿底色 + 胶囊形状**区分，不靠色相。这是胡子哥定的方案，
#   若要拉开差异，只能把窗口绿往青偏（H160°+），需先问他。
TAGS = {
    "窗口": ("#266C4B", "#E8F3EC"),      # 时机有利 → 墨绿（H152°，截取样值）
    "高位": ("#1F497D", "#E7EDF5"),      # 历史偏高 → 海军蓝（H213°，改前值，照旧）
    "风险": ("#800000", "#F7E9E9"),      # 需要留意 → 品牌深红（H0°，改前值，照旧）
    "观察": ("#8B5B10", "#FCF3E4"),      # 方向待定 → 金棕黄（H37°，截取样值）
    # legacy 旧标签全部收敛到「观察」。留着是为了兼容老数据，
    # 但**新内容不许再写这些词**（预检会拦）。
    "中性": ("#8B5B10", "#FCF3E4"),
    "分化": ("#8B5B10", "#FCF3E4"),
    "待验证": ("#8B5B10", "#FCF3E4"),
}

# 标签的四个语义档（新内容只能用这四个词）
TAG_CANON = ("窗口", "高位", "风险", "观察")
# legacy 词 → 规范词的收敛表
TAG_ALIAS = {"中性": "观察", "分化": "观察", "待验证": "观察", "承压": "风险"}

SERIF = '"Songti SC","Source Han Serif SC","Noto Serif CJK SC","STSong",serif'
SANS = '"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei",sans-serif'

CONTENT_W = 1080 - 68 * 2          # 正文页可用宽 = 944

# 正文页竖向预算（用来算每个条目能分到多少高度，视觉件按实际像素画，不留白）
PAGE_H = 1440
PAD_T = 44
PAD_B = 34
HEAD_GAP = 14
ITEM_GAP = 12
ITEM_PAD_V = 18
ITEM_PAD_H = 22
IT_R_W = 356                       # 右侧视觉件列宽
IT_R_PAD = 14
IT_L_GAP = 22
ITEM_BORDER = 2                    # .item 的上下 1px 边框

# 左栏文字列的真实可用宽（浏览器 2026-10-22 实测）
#   .item 内容宽 = 944 - 2×ITEM_PAD_H - 2×1px 边框 = 898
#   非宽表件：.it-l = 898 - IT_R_W - IT_L_GAP = 520
#   宽表件：  .it-l = 898
# 早先按 944 - 2×22 = 900 算，多出 2px 边框 —— 宽度算宽 2px，
# 折行临界时就会少算一行，文字顶出容器。
IT_L_W = (CONTENT_W - ITEM_PAD_H * 2 - ITEM_BORDER
          - IT_R_W - IT_L_GAP)      # = 520
IT_L_W_WIDE = CONTENT_W - ITEM_PAD_H * 2 - ITEM_BORDER   # = 898

# 一条 item 的「非视觉件」固定开销，分两层：
#   ITEM_CHROME —— item 自己的上下 padding + 1px 边框（左右两栏都要扣）
#   VIS_CHROME  —— 右侧视觉件容器的上下 padding（只有右栏要扣）
# 漏掉哪一层，容器就会比预算矮一截，表现为附属统计/侧栏最后一行被裁。
ITEM_CHROME = ITEM_PAD_V * 2 + 2
VIS_CHROME = IT_R_PAD * 2
CHROME = ITEM_CHROME + VIS_CHROME

# 左栏文字列的实测行高（浏览器 2026-10-22 量出来的，不要凭感觉改）
# .it-k 实测 42px：tag 的 24px 文字 × line-height 1.5 = 36px，加上下 padding 3+3 = 42px。
# 早先写 40px，每条少算 2px，三条就是 6px —— 文字就会顶出白卡底边。
KICK_H = 42          # .it-k 眉标行
TITLE_LINE_H = 47    # .it-title 36px × line-height 1.3（实测 46.8）
DESC_LINE_H = 42     # .it-desc 28px × line-height 1.5
LT_GAP = 7           # .it-l 子元素之间的 gap
PTS_HEAD = 23        # .it-pts 的 margin-top 11 + padding-top 11 + 分隔线 1
PTS_ROW = 35         # 单条要点行高（24px × line-height 1.45）
PTS_GAP = 9          # 要点之间的 gap
LT_PAD = 26          # .it-l 右侧内边距的保守预留（要点行要缩进）
PTS_DOT = 18         # 要点菱形点 7 + 间距 11

# 正文段落层（.it-prose）—— 连续文字段落，不是要点
# 2026-10-22 胡子哥定：「新闻内容用连续的文字语句，不分要点」。
# 于是左栏变成：眉标 / 结论句(36px) / 正文段落(24px)。desc 层在段落模式下不用。
# 实测 line-height = 37.2px（24 × 1.55），取整 38 —— 宁可多 0.8px 也不让文字被裁。
PROSE_LINE_H = 38    # .it-prose 24px × line-height 1.55
# .it-prose 实际没有 padding（浏览器实测 padding-left/right 均为 0px），
# 段落靠 text-align:justify 撑满整行。早先这里扣 30px「预留」，
# 等于凭空少算 30px 宽 → 折行数多算 1 行 → 左栏高度虚高 38px。
PROSE_PAD = 0
PROSE_MAX = 260      # 单条正文的字数上限——超出就是没做取舍

# 结论条（strip）实测行高
BODY_LINE_H = 48      # .strip 30px × line-height 1.6（浏览器实测 48）
BODY_PAD = 24        # 上下 padding 12 + 12
BODY_MT = 12         # margin-top
NOTE_LINE_H = 39     # .note 24px × line-height 1.6（浏览器实测 38.4，取整 39）
TAIL_MT = 10         # .tailrow 的 margin-top

# 结论条文字可用宽（2026-10-22 浏览器实测 = 903）。
# 早先写 CONTENT_W - 40 = 904，多算 1px —— 恰好够在临界时少算一行，
# 结论条就会多占 48px，把下面整块内容顶出去。这里改成实测常量。
STRIP_TEXT_W = 903

# 结论条与上方条目卡之间必须留的呼吸空间。
# 2026-10-22 胡子哥指出「底部结论条和上面白色的新闻卡片中间没有留空」——
# 结论条是米色底 + 红左边框，条目卡是白底，两块挨在一起像同一块面板，
# 读者分不清哪里是正文哪里是总结。留白太小（<12px）视觉上等于没留。
STRIP_GAP = 18       # 结论条上方留白（.strip margin-top）

# 口径注（.note）在 .tailrow 里与右下角角标（.corner-box）并排，
# 所以口径注的可用宽度要减掉角标占的那一截。
# 角标宽度 = 文字宽 + 圆点 7 + 间距 9 + 左右 padding 26 + 边框 2
CORNER_DOT_W = 7
CORNER_GAP = 9
CORNER_PAD = 26
CORNER_BORDER = 2
CORNER_FONT = 23
TAILROW_GAP = 24     # .tailrow 里 note 与 corner 之间的 gap
NOTE_PAD_L = 16      # .note 的 padding-left
NOTE_BORDER_L = 4    # .note 的 border-left

# 文案长度硬约束
LEAD_EM = 30
BODY_MAX = 46                      # 卡级结论条，一到两行
DESC_MAX = 18                      # 条目解释句 —— 必须单行，细节下沉到要点层
NOTE_MAX = 60

HEAD_BASE = 52                     # 主标题基准字号
HEAD_FLOOR = 34                    # 单行压到这个字号还放不下，才允许换行


# ---------------------------------------------------------------- 小工具

def rich(s):
    """转义 + 支持 [[强调]] 与换行"""
    s = escape(str(s))
    s = s.replace("[[", '<span class="hl">').replace("]]", "</span>")
    s = s.replace("\n", "<br/>")
    return s


def canon_tag(tag):
    """把旧标签词收敛到四档规范词。

    中性 / 分化 / 待验证 三个旧词在语义上都是「方向不明」，
    渲染时一律显示成「观察」—— 这样四张图上的标签词表也是同一套，
    不只是颜色统一、词还不统一。
    """
    if not tag:
        return ""
    return TAG_ALIAS.get(tag, tag)


def tag_badge(tag, cls="tag"):
    """渲染一个语义标签。

    颜色永远走 TAGS 表，四档互斥。表里没有的词一律按「观察」渲染并报预检 ——
    宁可显示成中性档，也不能自己挑个颜色，那样四张图的着色规则就不统一了。
    """
    tag = canon_tag(tag)
    if not tag:
        return ""
    fg, bg = TAGS.get(tag, TAGS["观察"])
    return (f'<span class="{cls}" style="color:{fg};background:{bg}">{escape(tag)}</span>')


def fmt(v, pattern="{:.2f}"):
    try:
        return pattern.format(float(v))
    except (TypeError, ValueError):
        return str(v)


# —— ASCII 可见字符的实测字宽（em）——
# 2026-10-22 用 Chromium 在 24px PingFang SC 下逐字量出来的（每字重复 20 次取均值）。
# 旧版只分「数字 / 拉丁 / 标点」三类，粗估严重失真：
#   - 句点 . 实际 0.264，旧版按 0.52 算 → 每句多算近一倍宽
#   - 大写 W 实际 0.930，旧版按 0.544 算 → 标题「WTI」会算窄一半
#   - 小写 i/l/f 实际 0.24–0.34，旧版按 0.544 算 → 英文单词算宽近一倍
#   这些误差直接决定折行数，折行数决定版面高度，最终表现为「文字顶出容器 4px」。
ASCII_W = {
    "0": 0.600, "1": 0.401, "2": 0.600, "3": 0.600, "4": 0.600,
    "5": 0.600, "6": 0.600, "7": 0.547, "8": 0.600, "9": 0.600,
    "!": 0.333, '"': 0.427, "#": 0.600, "$": 0.600, "%": 0.970,
    "&": 0.726, "'": 0.244, "(": 0.333, ")": 0.333, "*": 0.506,
    "+": 0.605, ",": 0.264, "-": 0.605, ".": 0.264, "/": 0.500,
    ":": 0.264, ";": 0.264, "<": 0.605, "=": 0.605, ">": 0.605,
    "?": 0.537, "@": 0.858,
    "A": 0.657, "B": 0.677, "C": 0.728, "D": 0.706, "E": 0.637,
    "F": 0.577, "G": 0.748, "H": 0.720, "I": 0.237, "J": 0.517,
    "K": 0.690, "L": 0.588, "M": 0.882, "N": 0.719, "O": 0.767,
    "P": 0.642, "Q": 0.767, "R": 0.676, "S": 0.632, "T": 0.619,
    "U": 0.714, "V": 0.639, "W": 0.930, "X": 0.637, "Y": 0.662,
    "Z": 0.624,
    "[": 0.333, "\\": 0.500, "]": 0.333, "^": 0.518, "_": 0.500,
    "`": 0.333,
    "a": 0.559, "b": 0.586, "c": 0.547, "d": 0.586, "e": 0.555,
    "f": 0.343, "g": 0.591, "h": 0.556, "i": 0.256, "j": 0.267,
    "k": 0.529, "l": 0.235, "m": 0.855, "n": 0.559, "o": 0.586,
    "p": 0.586, "q": 0.586, "r": 0.365, "s": 0.505, "t": 0.355,
    "u": 0.560, "v": 0.482, "w": 0.755, "x": 0.509, "y": 0.496,
    "z": 0.487,
    "{": 0.333, "|": 0.195, "}": 0.333, "~": 0.500,
}

# —— 中文标点的实测字宽（em）——
# 2026-10-22 修正：标点是**全宽 1.0**，不是 0.525。
# 之前用「独立 span 重复 20 次」标定，量到 0.525 —— 那是 Chromium 的
# **连排标点压缩**（text-spacing-trim：连续标点会各让出 0.35 em）造成的假象。
# 真实正文里标点多是单个出现，宽度就是整整 1 em。
# 改用「在真实正文里逐字量 Range 宽度」复标：
#   '，' 53 次全是 1.000，'。' 26 次全是 1.000，'；' '、' '：' '「' '」' 同理。
# 这个系数错了 0.475 em，一段 140 字里 12 个标点就多算 5.7 个字宽 ——
# 折行数凭空少 1 行，左栏高度少算 38px，文字就顶出白色卡片 4px。
# 「？！」这类全角问号叹号本来就全宽，系数不变。
CJK_PUNCT_W = {
    "，": 1.000, "。": 1.000, "、": 1.000, "；": 1.000, "：": 1.000,
    "？": 1.000, "！": 1.000, "（": 1.000, "）": 1.000,
    "《": 1.000, "》": 1.000, "「": 1.000, "」": 1.000,
    "『": 1.000, "』": 1.000, "【": 1.000, "】": 1.000,
    "…": 1.000, "—": 1.000, "～": 1.000, "·": 1.000,
    "×": 0.605, "÷": 0.605, "±": 0.605, "°": 0.331,
    "％": 1.000, "￥": 1.000, "＄": 1.000,
    "–": 0.605, "‒": 0.605, "－": 1.000, "＋": 1.000,
}


def em_width(text):
    """估算一段文字的 em 宽度（每个字宽以 em 为单位）。

    系数全部是 **浏览器实测值**（Chromium 24px PingFang SC，逐字重复 20 次取均值），
    不是拍脑袋的分类估值。理由：折行数 = ceil(em宽 × 字号 / 可用宽)，
    而折行数直接决定左栏高度、左栏高度决定条目高度、条目高度决定版面比例 ——
    字宽估错 5%，版面就错一整行，最后表现为「文字顶出白色卡片 4px」。

    实测要点（2026-10-22）：
      汉字 1.0；中文标点多为 0.525（不是 1.0！）；
      ASCII 逐字不同 —— W 0.93 / m 0.855 / . 0.264 / i 0.256 / 空格 0.333
    """
    total = 0.0
    for ch in str(text):
        if ch in ASCII_W:
            total += ASCII_W[ch]
        elif ch in CJK_PUNCT_W:
            total += CJK_PUNCT_W[ch]
        elif ch.isspace():
            total += 0.333
        elif ord(ch) < 0x2000:
            # 未收录的 ASCII 控制/扩展字符：按 0.6 估（数字宽度附近）
            total += 0.6
        else:
            # 其余（含所有汉字与全角符号）按全宽算
            total += 1.0
    return total or 1.0


def fit_headline(text, max_w=CONTENT_W, base=HEAD_BASE, floor=HEAD_FLOOR):
    """主标题单行自适应：能一行就一行，放不下才缩小，缩到下限仍放不下才换行"""
    lines = str(text).split("\n")
    em = max(em_width(re.sub(r"\[\[|\]\]", "", ln)) for ln in lines)
    size = min(base, int(max_w / em))
    return max(floor, size)


def est_lines(text, width_px, font_px):
    """估算一段文字折几行。

    模型：**行数 = ceil(整段自然宽 / 容器宽)**。
    2026-10-22 用 Chromium 实测 11 段正文验证，11/11 与浏览器实际行数完全一致。

    为什么能这么准 —— 两条铁律：

    1. **字宽必须是逐字实测值**（见 ASCII_W / CJK_PUNCT_W 两张表）。
       之前用「数字 / 拉丁 / 标点」三档粗估，中文标点按 0.525 算（实际 1.0），
       一段 140 字里 12 个标点就少算 5.7 个字宽 ≈ 137px，折行数凭空少 1 行。

    2. **不能再乘 0.98 之类的安全系数**。
       早先写「每行容量 = 宽度 × 0.97」，等于把 3% 余量**按行累乘** ——
       估 3 行时实际容量只剩 0.97³ ≈ 91%，明明一行放得下也判成 2 行。
       后果是口径注多算 38px，条目区被撑破，结论条压住最后一条讯息。
       现在字宽表已经精确到 0.1px，再叠系数只会引入偏差。

    换句话说：**精度来自标定，不来自保守**。想要留余量，就在内容稿阶段砍字，
    不要在排版阶段偷偷改宽度 —— 那会让所有行的断点都算错。
    """
    if not text:
        return 0
    plain = re.sub(r"\[\[|\]\]", "", str(text))
    total_px = em_width(plain) * font_px
    return max(1, int(math.ceil(total_px / max(1.0, width_px))))


def corner_box_width(text):
    """右下角段落名角标（.corner-box）实际占多宽。

    角标在 .tailrow 里与口径注并排，会把口径注挤窄。
    口径注的真实可用宽度必须减掉它 —— 以前按整行宽算，
    结果口径注实际折了 3 行、预算只算 2 行，结论条被条目卡压住 28px。
    """
    if not text:
        return 0
    return (em_width(text) * CORNER_FONT + CORNER_DOT_W + CORNER_GAP
            + CORNER_PAD + CORNER_BORDER)


def note_text_width(corner_text):
    """口径注（.note）在 .tailrow 里真正能用的文字宽度（px）。"""
    w = (CONTENT_W - TAILROW_GAP - corner_box_width(corner_text)
         - NOTE_PAD_L - NOTE_BORDER_L)
    return max(220, int(w))


def clean(s):
    return re.sub(r"\[\[|\]\]", "", str(s or ""))


# ---------------------------------------------------------------- 视觉件自然高度

def left_natural_h(item, w_left):
    """估算左栏文字列需要多高（眉标 + 结论 + 正文段落〔或解释 + 要点〕）。

    这一栏以前**根本没进预算模型** —— 只算了右栏视觉件，于是加了要点层之后
    左栏内容比容器高，第三条要点直接被裁掉。左右两栏是并排的，
    真正的需求是**两者取大**，不是相加。

    w_left 是左栏可用宽度（像素）。

    两种正文形态（二选一，prose 优先）：
      · prose —— 连续文字段落（2026-10-22 起的主形态）
      · desc + points —— 旧形态（结论句 / 一句钩子 / 短点列表）
    """
    h = 0
    if item.get("kicker") or item.get("tag"):
        h += KICK_H
    if item.get("title"):
        h += est_lines(item.get("title", ""), w_left - LT_PAD, 36) * TITLE_LINE_H

    prose = clean(item.get("prose", ""))
    pts = [clean(p) for p in (item.get("points") or []) if clean(p)]

    if prose:
        # 连续正文：整段折行，行数由字数与栏宽决定
        h += est_lines(prose, w_left - PROSE_PAD, 24) * PROSE_LINE_H
    else:
        if item.get("desc"):
            h += est_lines(item.get("desc", ""), w_left - LT_PAD, 28) * DESC_LINE_H
        if pts:
            # 要点区自身的头部开销（分隔线 + 上下 padding）
            h += PTS_HEAD
            for p in pts:
                h += est_lines(p, w_left - LT_PAD - PTS_DOT, 24) * PTS_ROW
            h += PTS_GAP * (len(pts) - 1)

    # .it-l 内部有 gap:7px，每个子元素之间都要算一次
    n_child = 0
    if item.get("kicker") or item.get("tag"):
        n_child += 1
    if item.get("title"):
        n_child += 1
    if prose:
        n_child += 1
    else:
        if item.get("desc"):
            n_child += 1
        if pts:
            n_child += 1
    h += LT_GAP * max(0, n_child - 1)
    return h


def visual_natural_h(item, w):
    """估算一条讯息的「不被挤压时需要多高」（**item 总高**，含自身 padding）。

    这是版面配比的核心：一张卡里每条讯息占多高，应该由内容密度决定，
    而不是人手填一个权重。10 项指标网格天生需要 5 行 × 73px，
    一个大数字 + 两条附属统计天生只要 209px —— 硬拉平就会一个被压扁、一个空一半。

    左右两栏是并排的，所以需求取**两栏的较大值**，不是相加。
    左栏（眉标+结论+解释+要点）由 left_natural_h 算。

    返回 (需要高度, 富余上限)。
    富余上限的意思是：超过这个高度，再宽的容器也没意义，硬撑只会变成大片空白。
    """
    v = item.get("visual") or {}
    t = v.get("type", "")

    # ---- 左栏（宽表件 layout=wide 时文字在上方，宽度是整行）
    if item.get("layout") == "wide":
        w_left = IT_L_W_WIDE
    else:
        w_left = IT_L_W
    lh = left_natural_h(item, w_left)

    if t == "grid":
        # 网格是宽表（layout=wide），铺满整行。分到的高度里要先扣掉上面的文字块，
        # 所以需求 = 文字块 + 网格本体。漏掉文字块那一段，网格就会被压到裁字。
        #
        # 行高按实测来：一个格子 scrollHeight 是 72px（40px 数值行 + 25px 名称行 +
        # 上下 padding 18px），再加 1px 边框 = 73。估算低于这个数，
        # grid-auto-rows:1fr 就会把格子压到内容高度以下，两行文字直接叠在一起。
        #
        # 关键：这是**下限**。grid-auto-rows:1fr 会把网格拉伸填满容器 ——
        # 给它 644px 高，5 行就变成 129px/行。所以 73px 只是「不被压扁」的底线，
        # 实际高度由分配结果决定。
        cols = int(v.get("cols", 2))
        rows = -(-len(v.get("items", [])) // max(1, cols))
        grid_h = rows * 73
        # 宽表件是「文字在上、表格在下」的纵向结构，两段相加
        h = lh + 14 + grid_h + CHROME
        return h, int(h * 1.42)

    if t == "steps":
        n = len(v.get("items", []))
        # 节点实测净高 54px（11px padding×2 + 32px 序号圆），连接线最小 20px。
        # 富余高度现在由连接线吸收（见 v_ministeps），所以这里只给「不被压扁」
        # 的绝对底线：n 个节点 + n-1 段线。给多了不会更安全，只会让这一条
        # 抢走左栏正文的高度预算。
        vis_h = n * 74 + 12
        need = vis_h + CHROME
        return max(need, lh + ITEM_CHROME), int(max(need, lh + ITEM_CHROME) * 1.22)

    if t == "bar":
        n = len(v.get("items", []))
        vis_h = n * 92 + 20
        need = vis_h + CHROME
        return max(need, lh + ITEM_CHROME), int(max(need, lh + ITEM_CHROME) * 1.34)

    if t == "num":
        # 大数字 + 附属统计。实测：2 条附属的净高要 209px（数字 48px 占 49，
        # mx 两行 95px + 上边距与分隔线 25px），所以需求不能按「大数字 132」算。
        extra = len(v.get("extra", []))
        vis_h = 96 + extra * 76 + 25
        need = vis_h + CHROME
        return max(need, lh + ITEM_CHROME), int(max(need, lh + ITEM_CHROME) * 1.15)

    if t == "line":
        # 大数字 + 折线图 + 时间轴。折线至少要 128px 才有走势可看
        vis_h = 92 + 128 + 42
        need = vis_h + CHROME
        return max(need, lh + ITEM_CHROME), int(max(need, lh + ITEM_CHROME) * 1.34)

    if t == "ring":
        # 环与侧栏并排（按宽度分 46% / 54%），高度上两者各自都能用满容器高。
        # 所以需求 = max(环直径, 侧栏总高) + chrome。
        n_side = len(v.get("side", []))
        side_h = n_side * 62 if n_side else 0
        ring_h = min(168, int((w - 16) * 0.46)) if n_side else 168
        need = max(ring_h, side_h) + CHROME
        return max(need, lh + ITEM_CHROME), int(max(need, lh + ITEM_CHROME) * 1.20)

    if t == "photo":
        need = 260 + CHROME
        return max(need, lh + ITEM_CHROME), int(max(need, lh + ITEM_CHROME) * 1.34)

    need = 120 + CHROME
    return max(need, lh + ITEM_CHROME), int(max(need, lh + ITEM_CHROME) * 1.34)


def allocate_heights(items, stack_h, w):
    """按内容密度把可用高度分给各条讯息。

    核心原则：**同一张卡里，各条讯息的高度差不该超过内容密度本身要求的幅度**。
    一条讯息占多大面积，由它的内容量决定，不靠人手填权重 —— 但也不该让一条
    独占半张卡、把邻居挤成两行。

    这是一个**带上下界的分配问题**：每条的下界是它的自然需求 need，
    上界是它的富余上限 cap，总和必须正好等于 stack_h。

    四步：
      1. 每条先拿到自己的需求（need）—— 谁都不该被压扁。
      2. 若需求总和超预算：**只从视觉件富余里挤**，文字底线一分不动。
      3. 有富余就在各自上限内摊开（密度大的自然占大面积）。
      4. 摊不掉的富余给需求量最大的那条（说明这一卡内容偏少，由预检报警）。

    之前的版本有个致命 bug：分配总和会**超出** stack_h 几十像素，
    最后一条讯息被下面的结论条压住、底部还留一条空带。
    现在每一步都按 stack_h 收敛，误差不超过 1px。
    """
    n = len(items)
    if n == 0:
        return []
    need = [visual_natural_h(it, w)[0] for it in items]
    cap = [visual_natural_h(it, w)[1] for it in items]
    total_need = sum(need) or 1

    # —— 宽表件（grid）是**弹性件**：
    #    grid-auto-rows:1fr 会把网格拉伸填满容器，所以它天生能吸收富余。
    #    它的下限是硬保护（表格不能被压扁），上限交给「吸收剩余」这一步。
    elastic = [i for i, it in enumerate(items)
               if (it.get("visual") or {}).get("type") == "grid"]

    # —— 条目高度分两层：**文字底线** 与 **视觉件富余**
    #
    # left_floor[i] = 左栏文字块高度 + ITEM_CHROME，这是**硬底线**：
    # 左栏的眉标 / 标题 / 正文折行数全部由字宽模型算出，压不动。
    # 富余部分（need 里超出 left_floor 的）全属视觉件，视觉件是弹性件。
    #
    # 为什么要分层：早先超预算时直接「按需求比例压缩」，
    # 三条各摊到不足 —— 文字被压出白色卡片（实测顶出 5px）。
    # 比例压缩看起来公平，实际是**把文字的不可压缩部分当成了弹性部分**。
    # 正确做法：先保每条的文字底线，再从视觉件富余里挤。
    left_floor = [left_natural_h(it, (IT_L_W_WIDE if it.get("layout") == "wide" else IT_L_W))
                  + ITEM_CHROME for it in items]

    # —— 第一步：内容本身超预算时，先压视觉件富余，绝不侵占文字底线
    if total_need > stack_h:
        slack = [max(0, need[i] - left_floor[i]) for i in range(n)]
        total_slack = sum(slack)
        deficit = total_need - stack_h

        if total_slack >= deficit:
            # 富余够挤：只从视觉件富余里按比例扣，文字底线一分不动。
            #
            # 可扣额度 = heights[i] - left_floor[i]（当前还握着多少视觉件富余），
            # **不能**写成 need[i] - max(heights[i], left_floor[i]) —— heights 初值
            # 就是 need，那样算出来恒为 0，循环空转后把全部缺口压到最后一条上
            # （实测 card-03 第三条凭空少 20px，正文顶出 15px）。
            heights = list(need)
            remain = deficit
            for _ in range(24):
                if remain <= 1:
                    break
                head = [max(0, heights[i] - left_floor[i]) for i in range(n)]
                head_sum = sum(head)
                if head_sum <= 0:
                    break
                before = remain
                cut = [min(head[i], int(remain * head[i] / head_sum)) for i in range(n)]
                for i in range(n):
                    if cut[i]:
                        heights[i] -= cut[i]
                remain = deficit - (sum(need) - sum(heights))
                if before - remain <= 0:      # 没进展就收手，别转圈
                    break
            heights[-1] += stack_h - sum(heights)
            return [max(96, hh) for hh in heights]

        # 富余挤完还差 —— 这是**真内容超预算**（文字底线之和已超 stack_h），
        # 只能按底线比例摊。预检会另行报 ⚠ 提示该砍字。
        base = sum(left_floor) or 1
        heights = [max(96, int(stack_h * fl / base)) for fl in left_floor]
        heights[-1] += stack_h - sum(heights)
        return [max(96, hh) for hh in heights]

    # —— 第二步：每条先拿到自己的需求
    heights = list(need)

    # —— 第三步：富余在各自上限内摊开（弹性件不参与，它最后兜底）
    #
    # 关键：**按比例分配必须逐条封顶**。曾经写成
    #   heights[i] += int(surplus * head[i] / head_sum)
    # 只有一条 fixed 时 head_sum == head[i]，这一条就把全部富余拿走，
    # 直接突破自己的 cap（窄件 339 拿到 643，超上限 389 一大截，
    # 页面多出空白，而弹性件一点没分到）。
    # 正确做法：先按比例算，再逐条夹在 cap 以内，剩下的留到下一轮。
    fixed = [i for i in range(n) if i not in elastic]
    surplus = stack_h - sum(heights)
    for _ in range(12):
        if surplus <= 1:
            break
        head = [max(0, cap[i] - heights[i]) if i in fixed else 0 for i in range(n)]
        head_sum = sum(head)
        if head_sum <= 0:
            break
        before = surplus
        # 先按比例分，但每条只给到自己的 head 上限
        give = [min(head[i], int(surplus * head[i] / head_sum)) for i in range(n)]
        for i in range(n):
            if give[i]:
                heights[i] += give[i]
        surplus = stack_h - sum(heights)
        if before - surplus <= 0:      # 没进展就收手，别转圈
            break

    # —— 第四步：比例摊分的零头，一次 1px 补齐（头部余量最大者优先）
    while surplus > 1:
        cands = [i for i in range(n) if i in fixed and cap[i] - heights[i] > 0]
        if not cands:
            break
        i = max(cands, key=lambda k: cap[k] - heights[k])
        heights[i] += 1
        surplus -= 1

    # —— 第五步：还有剩 → 先给弹性件（宽表网格会 1fr 拉伸，正好填满）
    rest = stack_h - sum(heights)
    if rest > 1:
        if elastic:
            heights[elastic[0]] += rest
        else:
            # 没有弹性件 → 给需求量最大的那条（说明这一卡内容偏少，由预检报警）
            i = max(range(n), key=lambda k: need[k])
            heights[i] += rest

    # —— 最后：把高度和**精确对齐**到 stack_h，绝不让总和超预算
    diff = stack_h - sum(heights)
    if diff != 0:
        if diff > 0:
            heights[max(range(n), key=lambda k: need[k])] += diff
        else:
            # 超了：从「高于自身需求最多」的那条开始削，削到刚好不超需求
            over = -diff
            while over > 0:
                cand = [i for i in range(n) if heights[i] > need[i]]
                if not cand:
                    break
                i = max(cand, key=lambda k: heights[k] - need[k])
                take = min(over, heights[i] - need[i])
                heights[i] -= take
                over -= take

    return [max(96, hh) for hh in heights]


# ---------------------------------------------------------------- 预算账（唯一一份）
#
# 为什么抽成函数：这张账原来内嵌在 main() 的预检里，只能"顺带"算，
# 不能单独查、不能结构化输出。结果每次排查版面都要另写一个临时脚本重算一遍
# （2026-10-22 那轮写了 39 个 playwright 脚本 + 54 次内联 Python 探针）——
# 两份实现一漂，诊断结论和真实渲染就对不上。
#
# 现在 plan_card() 是**唯一**的预算账实现：main() 的预检、doctor.py 的诊断、
# 以后的任何分析都只能调它。要改预算逻辑，改这里一处。

def plan_card(card):
    """算一张卡的竖向预算账，返回结构化诊断。

    返回字段：
      stack      可用给条目的总高
      need[]     每条的自然需求
      cap[]      每条的富余上限
      floor[]    每条的「文字底线」（左栏文字 + chrome，压不动）
      alloc[]    实际分配
      over       条目总需求 − 可用（>0 表示真超预算）
      items[]    逐条明细：字号行数、可用行数、需砍几行、建议目标字数
    """
    items = card.get("items") or []
    n = len(items)
    inner_w = IT_R_W - IT_R_PAD * 2

    head_h = int(fit_headline(card["headline"]) * 1.28) + HEAD_GAP
    note_lines = (est_lines(card.get("note", ""),
                            note_text_width(card.get("corner") or card.get("section", "")),
                            24)
                  if card.get("note") else 0)
    note_h = note_lines * NOTE_LINE_H
    body_lines = (est_lines("".join(card.get("body", [])), STRIP_TEXT_W, 30)
                  if card.get("body") else 0)
    body_h = (body_lines * BODY_LINE_H + BODY_PAD + STRIP_GAP
              if card.get("body") else 0)
    tail_h = max(note_h, 40) + TAIL_MT

    gap_total = ITEM_GAP * max(0, n - 1)
    stack = PAGE_H - PAD_T - PAD_B - head_h - body_h - tail_h - gap_total

    need, cap, floor = [], [], []
    for it in items:
        nd, cp = visual_natural_h(it, inner_w)
        need.append(nd)
        cap.append(cp)
        w = IT_L_W_WIDE if it.get("layout") == "wide" else IT_L_W
        floor.append(left_natural_h(it, w) + ITEM_CHROME)

    alloc = allocate_heights(items, stack, inner_w)

    detail = []
    for i, it in enumerate(items):
        w = IT_L_W_WIDE if it.get("layout") == "wide" else IT_L_W
        prose = clean(it.get("prose", ""))
        ptxt_lines = est_lines(prose, w - PROSE_PAD, 24) if prose else 0
        n_pts = len([p for p in (it.get("points") or []) if clean(p)])

        # 分配到的空间里，文字能占多高、能排几行
        text_avail = alloc[i] - ITEM_CHROME - KICK_H - TITLE_LINE_H - LT_GAP * 2
        if n_pts:
            text_avail -= n_pts * (PTS_ROW + PTS_GAP)
        lines_fit = max(0, int(text_avail // PROSE_LINE_H)) if prose else 0

        cut_lines = max(0, ptxt_lines - lines_fit)
        # 建议目标字数：按「可用行数 / 当前行数」等比缩，再留 2 字余量防临界翻行
        target_chars = None
        if cut_lines:
            per_line = em_width(prose) / max(1, ptxt_lines)
            target_chars = max(20, int(per_line * lines_fit) - 2)

        detail.append({
            "idx": i,
            "kicker": clean(it.get("kicker", "")),
            "prose_chars": len(prose),
            "prose_lines": ptxt_lines,
            "lines_fit": lines_fit,
            "cut_lines": cut_lines,
            "target_chars": target_chars,
            "need": need[i],
            "cap": cap[i],
            "floor": floor[i],
            "alloc": alloc[i],
            "squeezed": alloc[i] < floor[i],     # 文字被压 → 一定会溢出
        })

    return {
        "section": clean(card.get("section", "")),
        "n_items": n,
        "head_h": head_h,
        "note_lines": note_lines,
        "body_lines": body_lines,
        "tail_h": tail_h,
        "stack": stack,
        "need": need,
        "cap": cap,
        "floor": floor,
        "alloc": alloc,
        "over": sum(need) - stack,
        "items": detail,
        "squeezed": [d for d in detail if d["squeezed"]],
    }


# ---------------------------------------------------------------- 视觉件：迷你折线

def fit_number_size(value, unit, w, cap=None, avail_h=None):
    """大数字自动降档，同时受宽度与高度约束。

    宽度：之前 109.16 美元用 104px 字号会横向溢出 24px，手机上顶出边框。
    高度：数字字号也要吃得下容器高度 —— line-height:1.02 让实际占位比字号多 2%，
          再加上附属统计的行高，光看宽度会算出偏大的字号，最后 10px 被裁掉。

    avail_h 传入时按 min(宽度上限, 高度上限) 逐档往下试。
    """
    s = str(value)
    n_digit = sum(1 for c in s if c.isdigit())
    n_dot = sum(1 for c in s if c == ".")
    n_other = len(s) - n_digit - n_dot
    uw = (len(str(unit)) * 26) if unit else 0
    gap = 8 if unit else 0
    top = cap or 104
    h_cap = int(avail_h) if avail_h else top
    top = min(top, h_cap)
    for size in range(top, 27, -3):
        num_w = n_digit * size * 0.58 + n_dot * size * 0.30 + n_other * size * 0.64
        if num_w + uw + gap <= w:
            return size
    return 28


def v_miniline(v, w, h):
    """小折线：一个大数值 + 走势 + 时间标签。给「一个数字讲一件事」用。

    折线用百分比坐标画在绝对定位层上，而不是 SVG viewBox：
    viewBox 一旦跟容器实际高度对不上（容器是 flex 分配的，Python 端算不准），
    图形就会被等比压扁、缩到中间一半宽度，时间标签还会掉出容器。
    改成 HTML 绝对定位后，坐标永远跟着容器走，文字也不受缩放影响。
    """
    series = v["series"]
    vals = [float(p["value"]) for p in series]
    vmin, vmax = min(vals), max(vals)
    span = (vmax - vmin) or 1.0
    n = len(series)

    # 四周留一点余量，圆点才不会被容器边缘切掉
    pad_x, pad_y = 4.0, 9.0
    def P(i):
        x = pad_x + (100 - pad_x * 2) * (i / max(1, n - 1))
        y = pad_y + (100 - pad_y * 2) * (1 - (vals[i] - vmin) / span)
        return x, y

    color = v.get("color", NAVY)
    pts = [P(i) for i in range(n)]
    poly = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    area = f"{pts[0][0]:.2f},{100-pad_y:.2f} {poly} {pts[-1][0]:.2f},{100-pad_y:.2f}"

    svg = (f'<svg class="plot-svg" viewBox="0 0 100 100" preserveAspectRatio="none" '
           f'xmlns="http://www.w3.org/2000/svg">'
           f'<polygon points="{area}" fill="{color}" opacity="0.09"/>'
           f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="4" '
           f'stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
           f'</svg>')
    dots = "".join(
        f'<i class="mn-dot" style="left:{x:.2f}%;top:{y:.2f}%;border-color:{color}"></i>'
        for x, y in pts
    )

    # 首末时间标签
    axis = ""
    labs = [(series[0].get("label", ""), "left"), (series[-1].get("label", ""), "right")]
    labs = [l for l in labs if l[0]]
    if labs:
        axis = ('<div class="mn-axis">'
                + "".join(f'<span class="ax-{pos}">{escape(t)}</span>' for t, pos in labs)
                + '</div>')

    val = v.get("value", fmt(vals[-1], v.get("label_format", "{:.4f}")))
    unit = f'<span class="mn-unit">{escape(v["unit"])}</span>' if v.get("unit") else ""
    vsize = fit_number_size(val, v.get("unit", ""), w, cap=58)
    head = (f'<div class="mn-val"><span class="mn-num" style="font-size:{vsize}px">'
            f'{escape(str(val))}</span>{unit}</div>')
    cap = f'<div class="mn-cap">{escape(v["caption"])}</div>' if v.get("caption") else ""
    return (f'<div class="mn mn-line">{head}'
            f'<div class="mn-plot">{svg}{dots}</div>{axis}{cap}</div>')


# ---------------------------------------------------------------- 视觉件：迷你大数字

def v_mininum(v, w, h):
    """一个大数字 + 单位 + 一行说明 + 可选附属统计。

    附属统计很关键：视觉面板是有底色的方块，只放一个数字的话，
    面板上下全是空的，看着像没做完。给它挂两三条真实数据，面板就被填满了。
    """
    it = v["item"]
    color = {"up": UP_RED, "down": DOWN_GREEN}.get(
        it.get("tone"), CRIMSON if it.get("hl") else INK)
    n_extra = len(v.get("extra", []))
    # 主数字的口径说明写在视觉件层级（v["label"]），不是 item 层级。
    # 早先只读 item["label"]，于是 04 卡的「非港元保单演示上限」整句丢失 ——
    # 大数字 6.5% 浮在面板里，读者根本不知道它是什么。
    # 两个位置都读，兼容两种写法。
    cap = v.get("label") or it.get("label") or ""
    cap_h = (int(24 * 1.45) + 8) if cap else 0      # .mn-cap 行高 + margin-top
    # 高度换算：附属统计每行 76px（32px 数值 + 23px 说明 + 11px 间距），
    # 再加 .mx 自己的上边距 13 + 分隔线内边距 12 = 25px 的一次性开销。
    # 剩下才是大数字的地盘。之前只按高度档（104/88/68）选字号、没算附属统计占位，
    # 结果 2 条附属 + 104px 大数字塞进 155px 容器，直接裁掉 50px。
    budget = max(56, h - n_extra * 76 - 25 - 22 - cap_h)
    size = {"xl": 104, "l": 88, "m": 68}.get(v.get("size"), 0)
    if not size:
        size = min(104, int(budget * 0.86))
    # 宽度兜底：数字 + 单位必须一行塞进视觉列，否则会顶出边框
    size = fit_number_size(it["value"], it.get("unit", ""), w, cap=size, avail_h=budget)
    unit = f'<span class="mn-unit">{escape(it["unit"])}</span>' if it.get("unit") else ""
    label = f'<div class="mn-cap">{escape(cap)}</div>' if cap else ""

    extra = ""
    if v.get("extra"):
        rows = "".join(
            f'<div class="mx-row"><span class="mx-v">{escape(str(e["value"]))}</span>'
            f'<span class="mx-l">{escape(e["label"])}</span></div>'
            for e in v["extra"]
        )
        extra = f'<div class="mx">{rows}</div>'

    cls = "mn mn-num mn-num-full" if extra else "mn mn-num"
    return (f'<div class="{cls}">'
            f'<div class="mn-big" style="color:{color};font-size:{size}px">'
            f'<span class="mn-n">{escape(str(it["value"]))}</span>{unit}</div>{label}{extra}</div>')


# ---------------------------------------------------------------- 视觉件：迷你条形

def v_minibar(v, w, h):
    """横向条。mode:
       center —— 以 0 为中轴，负值往左长（涨跌分化用这个）
       level  —— 从 0 起长（两个水平值对比用这个，能看出「几乎一样高」）
       max    —— 全部按最大值归一（占比构成用这个）
    """
    items = v["items"]
    mode = v.get("mode", "center")
    nums = [float(i.get("val", i.get("pct", 0))) for i in items]
    mx = max(abs(x) for x in nums) or 1.0

    rows = []
    for it, num in zip(items, nums):
        disp = it.get("display", f"{num:+g}" if mode == "center" else f"{num:g}")
        if mode == "center":
            color = it.get("color") or (UP_RED if num >= 0 else DOWN_GREEN)
            frac = abs(num) / mx
            if num >= 0:
                fill = (f'<div class="mb-fill" style="width:{frac*50:.1f}%;'
                        f'background:{color}"></div>')
            else:
                fill = (f'<div class="mb-fill mb-left" style="width:{frac*50:.1f}%;'
                        f'background:{color}"></div>')
            track = f'<div class="mb-track mb-center">{fill}</div>'
        else:
            color = it.get("color") or NAVY
            frac = abs(num) / mx
            fill = (f'<div class="mb-fill" style="width:{frac*100:.1f}%;'
                    f'background:{color}"></div>')
            track = f'<div class="mb-track">{fill}</div>'
        rows.append(
            f'<div class="mb-row">'
            f'<div class="mb-top"><span class="mb-l">{escape(it["label"])}</span>'
            f'<span class="mb-v" style="color:{color}">{escape(str(disp))}</span></div>'
            f'{track}</div>'
        )
    cap = f'<div class="mn-cap">{escape(v["caption"])}</div>' if v.get("caption") else ""
    return f'<div class="mn mn-bar">{("".join(rows))}{cap}</div>'


# ---------------------------------------------------------------- 视觉件：迷你流程

def v_ministeps(v, w, h):
    """2–4 步因果链，压缩版。

    坑（2026-10-22 胡子哥 04 卡踩到）：原先每个「节点 + 连接线」包成一组、
    组用 flex:1 均分整列高度、组内 justify-content:center。节点多的时候
    看着正常，但只剩 2 个节点时，每组分到一百六七十 px、节点只有 54px，
    组内居中就在节点上下各空出五六十 px —— 中间那道本来负责「连起来」的
    细线因为是固定 14px，几乎看不见，整件看上去像两块浮空的标签。

    改法：不再分组，节点与连接线全部拍平成 .mn-steps 的同级子元素，
    节点 flex:0 0 auto（自身高度不变），连接线 flex:1 1 auto 吸收全部
    富余高度。这样无论 2 个还是 4 个节点，链条都严丝合缝地铺满整列，
    线越长越显眼，不会再有空白带。
    """
    parts = []
    items = v["items"]
    n = len(items)
    for i, it in enumerate(items):
        tone = it.get("tone", "plain")
        node = (f'<div class="ms-node ms-{tone}">'
                f'<span class="ms-no">{i+1}</span>'
                f'<span class="ms-t">{escape(it["text"])}</span></div>')
        parts.append(node)
        if i < n - 1:
            parts.append('<div class="ms-link"></div>')
    return f'<div class="mn mn-steps" style="height:{h}px">{"".join(parts)}</div>'


# ---------------------------------------------------------------- 视觉件：迷你环

def v_miniring(v, w, h):
    """环形进度 + 右侧数据列。

    坑：环形一旦用 SVG viewBox 画，容器被 flex 压矮时整圈等比缩小，
    圈里的百分比跟着缩到十几像素，手机上完全看不清。
    所以圈只画圈（不含字），百分比用 HTML 绝对定位叠在圈心，字号永远是真实 px。
    """
    pct = float(v["pct"])
    color = v.get("color", CRIMSON)
    n_side = len(v.get("side", []))
    # 环的直径由**宽度**决定，不由高度决定。
    # 之前按「高度减侧栏行数」倒推：侧栏 3 行要 186px，高度不够时环被压到 96px，
    # 内径只剩 68px，而「76.1%」在 26px 字号下宽 73px —— 数字直接压在环上。
    # 正确做法：环与侧栏**并排分宽度**。环占容器宽的 46%（上限 168），
    # 侧栏拿剩下的（实测 178px 足够放「美债 10 年期」这类标签）。
    #
    # 高度上：环和侧栏是并排的，**各自都能用满容器高度**。
    # 侧栏用 space-evenly 均分，所以侧栏不需要预留高度差；
    # 环则直接取 min(容器高, 宽度算出来的值)。
    side_need = n_side * 62 if n_side else 0
    ring_by_w = int((w - (16 if n_side else 0)) * 0.46)
    ring = int(min(168, max(88, min(ring_by_w, h - 8))))
    r, sw = 118, 22
    circ = 2 * 3.141592653589793 * r
    dash = circ * pct / 100.0
    svg = (
        f'<svg viewBox="0 0 300 300" preserveAspectRatio="xMidYMid meet" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<circle cx="150" cy="150" r="{r}" fill="none" stroke="#EDE7DA" stroke-width="{sw}"/>'
        f'<circle cx="150" cy="150" r="{r}" fill="none" stroke="{color}" stroke-width="{sw}" '
        f'stroke-linecap="round" stroke-dasharray="{dash:.1f} {circ:.1f}" '
        f'transform="rotate(-90 150 150)"/>'
        f'</svg>'
    )

    # 圈内径（去掉环的描边宽度）才是数字能用的空间。
    # 之前字号写死 46px，"76.1%" 宽约 110px 而内径只有 118px，
    # 数字直接压在环上。这里按内径反推字号，并给 ringinner 留位置。
    #
    # 关键：字号**下限必须跟着内径走**。内径装不下就先砍「口径」那行，
    # 再砍百分比字号，绝不写死下限 —— 写死就会出现「数字压在环上」。
    pct_txt = f"{pct:g}%"
    inner_d = ring * (2 * (r - sw / 2)) / 300.0          # 折算成实际像素的内径
    inner_txt = v.get("inner", "")
    # 文字实际占宽：百分比按 0.58/字宽（含点号的窄字符略打折），口径按 1.0/字宽
    pct_w_em = sum(0.58 if c.isdigit() else (0.30 if c == "." else 0.62) for c in pct_txt)
    pct_size = int(min(46, max(14, (inner_d - 12) / max(0.1, pct_w_em))))
    inner_size = int(min(22, max(11, pct_size * 0.46)))

    # ★ 宽度约束（2026-10-22 修）：口径行是 white-space:nowrap，
    #   之前只按**高度**算字号，完全没管宽度 —— 「12 月加息 25bp 定价」12 个字宽
    #   远超内径，被 .mn-ringwrap 的 overflow:hidden 裁掉 27px（体检 B 级）。
    #   口径行放不下就整行去掉（它只是补充说明，百分比才是主角）。
    if inner_txt:
        inner_w_em = em_width(inner_txt)
        if inner_size * inner_w_em > inner_d - 10:
            inner_txt = ""
            inner_size = 0

    # 两行文字（百分比 + 口径）总高不能超过内径
    total_h = pct_size + inner_size * 1.25 + 6
    if total_h > inner_d - 6:
        # 先砍口径行（它可以整行去掉），再砍百分比字号
        if inner_txt and pct_size + 6 <= inner_d - 6:
            inner_txt = ""
            inner_size = 0
            total_h = pct_size + 6
        if total_h > inner_d - 6:
            pct_size = max(12, int(pct_size * (inner_d - 8) / max(1, total_h)))
            inner_size = 0 if not inner_txt else max(10, int(inner_size * (inner_d - 8) / total_h))
    mid = (f'<div class="mn-ringmid">'
           f'<div class="mn-ringpct" style="color:{color};font-size:{pct_size}px">{escape(pct_txt)}</div>'
           + (f'<div class="mn-ringinner" style="font-size:{inner_size}px">'
              f'{escape(inner_txt)}</div>' if inner_txt else '')
           + '</div>')

    side = ""
    if v.get("side"):
        # 侧栏在环的右边竖排（值在上、说明在下）
        rows = "".join(
            f'<div class="rs-row"><span class="rs-v">{escape(str(s["value"]))}</span>'
            f'<span class="rs-l">{escape(s["label"])}</span></div>'
            for s in v["side"]
        )
        side = f'<div class="mn-ringside mn-ringside-fill">{rows}</div>'

    cap = f'<div class="mn-cap mn-cap-full">{escape(v["caption"])}</div>' if v.get("caption") else ""
    return (f'<div class="mn mn-ring">'
            f'<div class="mn-ringrow">'
            f'<div class="mn-ringwrap" style="width:{ring}px;height:{ring}px">{svg}{mid}</div>'
            f'{side}</div>{cap}</div>')

# ---------------------------------------------------------------- 视觉件：温度网格（宽）

def v_grid(v):
    """隔夜十项一览。宽件用 5 列 × 2 行，窄件用 2 列 × 5 行。"""
    cells = []
    for it in v["items"]:
        status = canon_tag(it.get("status"))
        fg, bg = TAGS.get(status, TAGS["观察"])
        chg = it.get("change", "")
        chg_color = UP_RED if chg.startswith("+") else (DOWN_GREEN if chg.startswith("-") else INK3)
        cells.append(
            f'<div class="gc">'
            f'<div class="gc-top"><span class="gc-name">{escape(it["name"])}</span>'
            f'<span class="gc-val">{escape(it["value"])}</span></div>'
            f'<div class="gc-foot">'
            f'<span class="gc-chg" style="color:{chg_color}">{escape(chg)}</span>'
            f'<span class="gc-tag" style="color:{fg};background:{bg}">{escape(status)}</span>'
            f'</div></div>'
        )
    cols = int(v.get("cols", 2))
    return f'<div class="grid" style="grid-template-columns:repeat({cols},1fr)">{"".join(cells)}</div>'


# ---------------------------------------------------------------- 视觉件：配图

def v_photo(v, base_dir):
    """真实图片。src 可以是相对 data.json 的路径，也可以是绝对路径。"""
    src = v.get("src", "")
    if not src:
        return ""
    path = src if os.path.isabs(src) else os.path.join(base_dir, src)
    if not os.path.exists(path):
        print(f"⚠️  配图不存在: {path}", file=sys.stderr)
        return ""
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    cap = f'<div class="mn-cap">{escape(v["caption"])}</div>' if v.get("caption") else ""
    return (f'<div class="mn mn-photo">'
            f'<img src="data:image/{mime};base64,{b64}" alt=""/>{cap}</div>')


# ---------------------------------------------------------------- 视觉件分发

def render_visual(v, w, h, base_dir):
    t = v.get("type")
    if t == "line":
        return v_miniline(v, w, h)
    if t == "num":
        return v_mininum(v, w, h)
    if t == "bar":
        return v_minibar(v, w, h)
    if t == "steps":
        return v_ministeps(v, w, h)
    if t == "ring":
        return v_miniring(v, w, h)
    if t == "grid":
        return v_grid(v)
    if t == "photo":
        return v_photo(v, base_dir)
    raise SystemExit(f"❌ 未知视觉类型: {t}")


# ---------------------------------------------------------------- 条目

def render_item(item, w, item_h, base_dir, idx, vis_h=None):
    """一条讯息 = 眉标 + 结论 + 解释 + 视觉件

    layout="wide" 时视觉件占满整行（用于温度计网格这种宽表），文字在上、图在下。

    item_h 是这条 item 的总高（由 allocate_heights 按内容密度算出），会写进 inline style。
    vis_h 是视觉件的净高（扣掉 padding），传给视觉件决定内部怎么画。
    两者必须分开 —— 混用会让 item 实际高度比预算少一截，底部就空出一块。
    """
    h = item_h
    kick = item.get("kicker", "")
    tag = item.get("tag", "")
    tag_html = tag_badge(tag, "tag tag-inline")
    kick_html = f'<span class="it-kick">{escape(kick)}</span>' if kick else ""

    title_html = f'<div class="it-title">{rich(item["title"])}</div>' if item.get("title") else ""
    desc_html = f'<div class="it-desc">{rich(item["desc"])}</div>' if item.get("desc") else ""

    # 正文段落层：连续文字，不分要点（2026-10-22 起的主形态）。
    # 一段文字写完放不下时**不能裁字**——裁字比少说一句难看得多。
    # 做法是预检报警让人回去精简，渲染端只负责把它完整画出来。
    prose = clean(item.get("prose", ""))
    prose_html = f'<div class="it-prose">{rich(item["prose"])}</div>' if prose else ""

    # 要点层：旧形态（desc + points）保留，prose 存在时不再渲染。
    # 左侧文字列实测填充率只有 47–75%，每条空着 78–166px。
    # 点必须短（一行放得下），写成完整句子会折行，反而把空吃掉又撑破容器。
    #
    # 关键：**按可用高度决定渲染几条**。容器装不下就少渲染一条，
    # 绝不让 CSS 去裁字 —— 裁字比少一条难看得多。
    pts = [clean(p) for p in (item.get("points") or []) if clean(p)]
    if prose:
        pts = []
    if pts and h:
        if item.get("layout") == "wide":
            w_left = IT_L_W_WIDE
        else:
            w_left = IT_L_W
        # 本条分到的高度里，左栏能用的净高（扣掉 item 上下 padding 与边框）
        avail = h - ITEM_CHROME
        base = left_natural_h(item, w_left)          # 含全部要点的需求
        per_pt = PTS_ROW + PTS_GAP
        # 每少渲染一条，能省下多少（最后一条还要少一个 gap）
        while len(pts) > 1 and base > avail:
            base -= per_pt
            pts = pts[:-1]
        # 即便只剩一条也装不下 → 这条内容真的超了，交给预检报警，不在这里裁字
    pts_html = ""
    if pts:
        rows = "".join(
            f'<div class="pt"><i class="pt-dot"></i>'
            f'<span class="pt-t">{escape(p)}</span></div>'
            for p in pts
        )
        pts_html = f'<div class="it-pts">{rows}</div>'

    if vis_h is None:
        vis_h = max(60, h - CHROME) if h else 0

    # 分配高度写死，杜绝 flex 再改一遍
    hs = f' style="height:{h}px;flex:0 0 {h}px"' if h else ' style="flex:0 0 auto"'

    vis = item.get("visual")
    wide = item.get("layout") == "wide"
    if not vis:
        return (f'<div class="item item-txt"{hs}>'
                f'<div class="it-l">'
                f'<div class="it-k">{tag_html}{kick_html}</div>'
                f'{title_html}{desc_html}{prose_html}'
                f'</div></div>')

    if wide:
        # 宽件：文字在上，视觉件占满下面的整行
        vis_html = (f'<div class="it-r it-r-wide">'
                    f'{render_visual(vis, w, vis_h, base_dir)}</div>')
        return (f'<div class="item item-wide"{hs}>'
                f'<div class="it-l it-l-wide">{title_html}{desc_html}{prose_html}{pts_html}</div>'
                f'{vis_html}</div>')

    vis_html = f'<div class="it-r">{render_visual(vis, w, vis_h, base_dir)}</div>'
    return (f'<div class="item item-vis"{hs}>'
            f'<div class="it-l">'
            f'<div class="it-k">{tag_html}{kick_html}</div>'
            f'{title_html}{desc_html}{prose_html}{pts_html}'
            f'</div>{vis_html}</div>')


# ---------------------------------------------------------------- 卡片

def render_card(card, meta, footer, qr_uri, total, base_dir):
    # ---- 竖向预算：先算死每条能分到多高，视觉件再按这个像素画，避免留白
    head_size = fit_headline(card["headline"])
    head_h = int(head_size * 1.28) + HEAD_GAP

    # 口径注在 .tailrow 里与右下角角标并排 —— 宽度必须减掉角标占的那一截。
    # 以前按整行宽（922px）估，浏览器里实际只有 695px（04 卡），
    # 少估一行 = 38px，结论条被上面的条目卡压住 28px。
    corner_txt = card.get("corner") or card.get("section", "")
    note_w = note_text_width(corner_txt)
    note_lines = est_lines(card.get("note", ""), note_w, 24)
    note_h = (note_lines * NOTE_LINE_H) if card.get("note") else 0

    body_lines = est_lines("".join(card.get("body", [])), STRIP_TEXT_W, 30)
    # body_h 含结论条自己的 margin-top（= STRIP_GAP），stack_h 里不再重复扣
    body_h = (body_lines * BODY_LINE_H + BODY_PAD + STRIP_GAP) if card.get("body") else 0

    # 口径注与角标现在同处 .tailrow 一行，高度取两者的较大值
    corner_h = 40                       # 右下角段落名角标
    tail_h = max(note_h, corner_h) + TAIL_MT  # tailrow 的 margin-top

    items = card.get("items", [])
    inner_w = IT_R_W - IT_R_PAD * 2
    wide_w = IT_L_W_WIDE

    # STRIP_GAP 是结论条上方的强制留白，已计入 body_h。
    # 以前 .strip 的 margin-top 只有 12px，视觉上两块面板贴在一起；
    # 现在留 18px，白卡与米色结论条之间能看出明确的分界。
    stack_h = PAGE_H - PAD_T - PAD_B - head_h - body_h - tail_h
    stack_h -= ITEM_GAP * max(0, len(items) - 1)
    heights = allocate_heights(items, stack_h, inner_w)

    parts = []
    for it, item_h in zip(items, heights):
        vis = it.get("visual")
        if not vis:
            parts.append(render_item(it, inner_w, 0, base_dir, len(parts)))
            continue
        if it.get("layout") == "wide":
            # 宽件：文字块在上，视觉件吃剩下的高度
            # 文字块高度要用 left_natural_h 统一算（宽表件左栏也是整行宽），
            # 不能再用老的 title+desc 公式 —— 否则要点层被算漏，网格会压扁。
            #
            # 高度链：item 上下 padding + 边框 + 文字块 + 间距14 + .it-r 的上下 padding + 网格
            # 少减一项，网格就会超出 item，底下的条目被压掉一截（实测溢出 37px）。
            text_h = left_natural_h(it, wide_w)
            vis_h = max(120, item_h - text_h - ITEM_CHROME - VIS_CHROME - 14)
            parts.append(render_item(it, wide_w - IT_R_PAD * 2, item_h, base_dir,
                                     len(parts), vis_h=vis_h))
        else:
            parts.append(render_item(it, inner_w, item_h, base_dir, len(parts)))

    items_html = "".join(parts)

    body_html = ""
    if card.get("body"):
        body_html = f'<div class="strip" style="margin-top:{STRIP_GAP}px">{"".join(rich(p) for p in card["body"])}</div>'
    note_html = f'<div class="note">{rich(card["note"])}</div>' if card.get("note") else ""

    # 右下角角标：只有段落名，不带「· 机制」这类后缀
    corner_html = ""
    if corner_txt:
        corner_html = (f'<div class="corner"><span class="corner-box">'
                       f'<span class="corner-dot"></span>{escape(corner_txt)}</span></div>')
    src = card.get("sources") or footer.get("sources", "")

    en = meta.get("title_en", "GLOBAL BRIEF · DAILY")
    en_html = "".join(
        f'<span class="ce{" sp" if ch == " " else ""}">{escape(ch)}</span>' for ch in en
    )
    no = card.get("no", "01")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{escape(meta.get('title','胡子哥财经晨报'))} {no}</title>
<style>{CSS}</style></head>
<body><div class="card">

<div class="banner">
  <div class="bn-left">
    <div class="bn-title">{escape(meta.get('title','胡子哥财经晨报'))}</div>
    <div class="bn-en">{en_html}</div>
  </div>
  <div class="bn-right">
    <div class="bn-issue">{escape(meta.get('issue','No.001'))}</div>
    <div class="bn-date">{escape(meta.get('date',''))}　{escape(meta.get('weekday',''))}</div>
  </div>
</div>

<div class="page">
  <h1 class="hl1" style="font-size:{head_size}px">{rich(card['headline'])}</h1>
  <div class="items">{items_html}</div>
  {body_html}
  <div class="tailrow">
    {note_html}
    {corner_html}
  </div>
</div>

<div class="foot">
  <div class="foot-main">
    <div class="foot-txt">
      <div class="fs"><span class="fh">数据来源</span>{rich(src)}</div>
      <div class="fd">{rich(footer.get('disclaimer',''))}</div>
    </div>
    <div class="foot-qr"><img src="{qr_uri}" alt="微信二维码"/></div>
  </div>
</div>

</div></body></html>"""


# ---------------------------------------------------------------- CSS

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{background:#FFFFFF}
.card{width:1080px;font-family:%(SANS)s;color:%(INK)s;-webkit-font-smoothing:antialiased}

/* ---------- banner ---------- */
.banner{height:118px;background:%(CRIMSON)s;display:flex;align-items:center;
  justify-content:space-between;padding:0 68px;position:relative}
/* banner 底部不要加任何描边或分隔线：深红块与米色正文页直接切 */
.bn-left{display:inline-flex;flex-direction:column;align-items:stretch}
.bn-title{font-family:%(SERIF)s;font-size:46px;font-weight:700;color:#fff;
  letter-spacing:4px;line-height:1.1;white-space:nowrap}
.bn-en{display:flex;justify-content:space-between;align-self:stretch;
  font-size:21px;font-weight:600;color:rgba(255,255,255,.96);
  margin-top:9px;line-height:1;letter-spacing:0}
.ce{flex:0 0 auto}
.ce.sp{flex:0 0 0}
.bn-right{text-align:right}
.bn-issue{font-size:27px;font-weight:700;color:#fff;letter-spacing:1px}
.bn-date{font-size:23px;color:rgba(255,255,255,.82);margin-top:5px}

/* ---------- 正文页 1080x1440 ---------- */
.page{width:1080px;height:%(PAGE_H)dpx;background:%(PAPER)s;padding:%(PAD_T)dpx 68px %(PAD_B)dpx;
  display:flex;flex-direction:column;overflow:hidden;position:relative}

.hl1{font-family:%(SERIF)s;font-weight:700;line-height:1.28;letter-spacing:1px;
  color:%(INK)s;flex:0 0 auto;white-space:nowrap;margin-bottom:%(HEAD_GAP)dpx}
.hl1 .hl{color:%(CRIMSON)s}

/* ---------- 条目列表 ---------- */
.items{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;gap:%(ITEM_GAP)dpx}
/* flex:0 0 auto 是底线 —— 高度由 Python 端按内容密度算好后写进 inline style。
   这里如果写 flex:1 1 0（等分），浏览器会把分配结果全改掉：
   高密度的网格被压扁裁字、低密度的数字件空掉一半 */
.item{display:flex;gap:%(IT_L_GAP)dpx;background:%(CARD)s;border:1px solid %(LINE)s;
  border-radius:9px;padding:%(ITEM_PAD_V)dpx %(ITEM_PAD_H)dpx;min-height:0;
  flex:0 0 auto;overflow:hidden;box-sizing:border-box}
.item-txt{background:transparent;border:none;padding:%(ITEM_PAD_V)dpx 0;
  border-top:1px solid %(LINE)s;border-radius:0}
.item-txt:first-child{border-top:none;padding-top:2px}
/* 宽件：文字在上、宽表在下，网格才能横着铺开 */
.item-wide{flex-direction:column;gap:14px}
/* 权重必须高于 .it-l / .it-r，否则会被后者的规则覆盖回去。
   height 必须是 100%% 而不能写 auto —— auto 会断开高度链，
   .grid 的 flex:1 就算不出高度，5 行网格被压扁、格子里的文字直接被裁掉 */
.item-wide .it-l{flex:0 0 auto;justify-content:flex-start}
.item-wide .it-r{flex:1 1 auto;width:100%%;min-width:0;height:100%%;display:flex;
  flex-direction:column;align-items:stretch;justify-content:flex-start;overflow:hidden}
.item-wide .it-r .grid{flex:1 1 auto;min-height:0}
/* 顶部对齐：内容多的条目顶格，少的条目上方留白也是正常的呼吸感；
   用 center 的话，一条被拉高的 item 里文字会垂到中间，看着像掉下去了 */
.it-l{flex:1 1 auto;min-width:0;min-height:0;display:flex;flex-direction:column;
  justify-content:flex-start;gap:7px}
.it-k{display:flex;align-items:center;gap:12px;flex:0 0 auto}
.it-kick{font-size:26px;font-weight:700;color:%(INK2)s;letter-spacing:1px}
.it-title{font-size:36px;font-weight:700;line-height:1.3;color:%(INK)s}
.it-title .hl{color:%(CRIMSON)s}
.it-desc{font-size:28px;line-height:1.5;color:#3C3C3C}
.it-desc .hl{color:%(CRIMSON)s;font-weight:700}
/* 正文段落层（2026-10-22 起的主形态）：连续文字，不分要点。
   24px 与要点同字号（正文页内不低于 22px 的硬下限），
   行距放到 1.62 —— 中文段落行距挤在一起读起来是"墙"，读者会跳读。
   首行不缩进，用整段左对齐：手机上 24px 缩进两格反而挤。 */
.it-prose{font-size:24px;line-height:1.55;color:#3C3C3C;text-align:justify;
  word-break:break-word;overflow-wrap:anywhere}
.it-prose .hl{color:%(CRIMSON)s;font-weight:700}
/* 要点层：吃掉左侧文字列的富余高度。
   左栏实测填充率只有 47–75%%，每条空 78–166px，够放 3 个要点。
   用 flex:1 + space-evenly 均分，卡片变高时要点自动摊开而不是底部留白 */
.it-pts{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;
  justify-content:space-evenly;gap:9px;margin-top:11px;padding-top:11px;
  border-top:1px solid #E9E2D4}
.pt{display:flex;align-items:flex-start;gap:11px;min-width:0}
.pt-dot{flex:0 0 auto;width:7px;height:7px;margin-top:11px;background:%(INK3)s;
  border-radius:1px;transform:rotate(45deg)}
.pt-t{font-size:24px;line-height:1.45;color:%(INK3)s;min-width:0}

/* 标签：全局唯一一套规格。
   以前 .tag(24/3px12/r4) 、.tag-inline(24/2px11/r4) 、.gc-tag(22/2px9/r3)
   三处各写各的 —— 同一张图里标签有大有小有圆有方，看着就像没统一的。
   现在三者共用同一套：24px / 内边距 3px 12px / 圆角 4px / 字重 600。
   字号下限是 22px（体检脚本按 22px 卡），24px 是安全的。 */
.tag{display:inline-block;padding:3px 12px;border-radius:4px;font-size:24px;
  font-weight:600;line-height:1.5;white-space:nowrap}
.tag-inline{font-size:24px;padding:3px 12px;border-radius:4px;vertical-align:2px}

/* ---------- 右侧视觉件 ---------- */
/* 视觉件列是固定宽的，内部的图必须靠 min-height:0 + overflow:hidden 收缩。
   关键：.mn 必须撑满 .it-r（align-items:stretch + 满高），
   否则 flex:1 的子块在 auto 高度父级里算出来是 0，SVG 会画到容器外面去。 */
.it-r{flex:0 0 %(IT_R_W)dpx;min-width:0;height:100%%;display:flex;flex-direction:column;
  align-items:stretch;justify-content:center;background:#FBF8F1;border-radius:7px;
  padding:%(IT_R_PAD)dpx;overflow:hidden;box-sizing:border-box}
.mn{width:100%%;height:100%%;display:flex;flex-direction:column;justify-content:center;
  min-width:0;min-height:0;align-items:stretch;overflow:hidden}
.mn-val{display:flex;align-items:baseline;gap:8px;line-height:1.02;flex:0 0 auto}
.mn-num{font-family:%(SERIF)s;font-weight:700;color:%(INK)s;
  font-variant-numeric:tabular-nums}
.mn-unit{font-size:26px;font-weight:600;color:%(INK3)s}
.mn-cap{font-size:24px;line-height:1.45;color:%(INK3)s;margin-top:8px;flex:0 0 auto}
/* 折线绘图层：百分比坐标 + 绝对定位，永远跟着容器走。
   不用 SVG viewBox 是因为容器高度由 flex 分配，Python 端算不准，
   viewBox 对不上就会被等比压扁、缩到中间一半宽，标签还会掉出容器。 */
.mn-plot{flex:1 1 auto;min-height:0;position:relative;margin-top:10px;width:100%%}
.mn-plot .plot-svg{position:absolute;inset:0;width:100%%;height:100%%;display:block;
  overflow:visible}
.mn-dot{position:absolute;width:13px;height:13px;margin:-6.5px 0 0 -6.5px;border-radius:50%%;
  background:#FFFFFF;border:4px solid %(NAVY)s;box-sizing:border-box}
.mn-axis{flex:0 0 auto;display:flex;justify-content:space-between;margin-top:8px}
.mn-axis span{font-size:23px;color:%(INK3)s;line-height:1.2}
.mn-axis .ax-right{text-align:right}
/* 大数字：主数字水平居中，说明文字跟着居中。
   2026-10-22 胡子哥：「这样的主视觉图排版不好，数字应该居中，
   现在处于左上角比较奇怪。」
   —— .mn-big 是 flex 行，主数字在行内靠左（align-items 默认 stretch +
   justify-content 默认 flex-start），所以数字贴在面板左上角。
   改成 justify-content:center 让「数字+单位」这一组居中。
   注意 .mn-cap（说明文字）也要居中，否则数字居中、说明靠左，
   两行对不齐，反而更乱。 */
.mn-num{justify-content:flex-start;gap:2px;align-items:center}
.mn-num-full{justify-content:flex-start;gap:2px;align-items:center}
.mn-big{display:flex;align-items:baseline;justify-content:center;gap:8px;
  width:100%%;line-height:1.02;
  font-family:%(SERIF)s;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap;
  flex:0 0 auto}
.mn-n{font-size:inherit}
.mn-num .mn-cap{text-align:center;width:100%%}

/* 附属统计：把大数字面板剩下的空间用真实数据填满。
   justify-content:space-between 让两条附属统计分摊掉中间的空档，
   不然数字都堆在底部，中间还是一大片白。 */
.mx{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;justify-content:space-evenly;
  gap:11px;margin-top:13px;padding-top:12px;border-top:1px solid #E4DDCB}
.mx-row{display:flex;align-items:baseline;gap:10px;min-width:0}
.mx-v{flex:0 0 auto;font-family:%(SERIF)s;font-size:32px;font-weight:700;color:%(INK)s;
  font-variant-numeric:tabular-nums;line-height:1.2;white-space:nowrap}
.mx-l{flex:1 1 auto;font-size:23px;color:%(INK3)s;line-height:1.35;min-width:0}

/* 条形：行均分整列高度，条本身跟着长高，避免面板下半截空着 */
.mn-bar{justify-content:flex-start;gap:14px}
.mb-row{width:100%%;flex:1 1 auto;min-height:0;display:flex;flex-direction:column;
  justify-content:center}
.mb-top{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px}
.mb-l{font-size:25px;color:%(INK2)s;font-weight:600;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.mb-v{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.mb-track{height:22px;background:#EAE3D5;border-radius:3px;overflow:hidden}
/* 中轴模式：0 在正中，负值往左长 */
.mb-center{position:relative;background:linear-gradient(to right,#EAE3D5 0 50%%,#EAE3D5 50%% 100%%)}
.mb-center::after{content:"";position:absolute;left:50%%;top:-2px;bottom:-2px;width:1px;
  background:#C9BFA9}
.mb-fill{height:100%%;border-radius:3px}
.mb-left{margin-left:auto}

/* 流程：节点与连接线同级平铺，节点定高、连接线固定长度。
   2026-10-22 胡子哥圈出 04 卡这条：「中间太空，顶底压边。
   可以调整到居中，上下留空。」
   —— 原来连接线 flex:1 吃掉全部富余高度，于是节点 1 贴面板顶、
   节点 2 贴面板底，中间拉出一条上百 px 的细线，看着像两个浮空的标签。
   现在改成：连接线固定 32px（够看清是箭头），整组用 justify-content:center
   垂直居中，多出来的空间平分到上下 —— 节点挨在一起、上下留白。
   「不分组均分」这条不能回头：分组会让 2 节点时组内上下各空五六十 px，
   连接线被压到看不见，比现在更糟。 */
.mn-steps{justify-content:center;gap:0}
.ms-node{display:flex;align-items:center;gap:13px;padding:11px 14px;border-radius:7px;
  background:#F2EEE4;flex:0 0 auto}
.ms-link{position:relative;width:3px;height:32px;flex:0 0 auto;
  margin:0 0 0 29px;background:#CFC4AC}
.ms-link::after{content:"";position:absolute;left:50%%;bottom:0;transform:translateX(-50%%);
  border-left:5px solid transparent;border-right:5px solid transparent;
  border-top:7px solid #CFC4AC}
.ms-no{flex:0 0 32px;height:32px;line-height:32px;border-radius:50%%;background:%(NAVY)s;
  color:#fff;font-size:22px;font-weight:700;text-align:center;font-variant-numeric:tabular-nums}
.ms-t{font-size:25px;font-weight:600;color:%(INK2)s;line-height:1.25}
/* 步骤节点的「风险」变体：必须与 TAGS 里的「风险」保持同一色值。
   2026-10-22 定稿后「风险」= 品牌深红 #800000 / 粉底 #F7E9E9，
   这个变体跟着一起回到红。改 TAGS 时这里必须同步，否则会出现第五种颜色。 */
.ms-risk{background:#F7E9E9}
.ms-risk .ms-no{background:%(CRIMSON)s}
.ms-risk .ms-t{color:%(CRIMSON)s}

/* 环：左环 + 右列，说明文字另起一整行
   注意：环和侧栏必须包在一层 row 里 —— 直接用 flex-wrap 的话，
   说明文字的 100%% 宽度会把侧栏挤到下一行，整块高度就爆了 */
.mn-ring{flex-direction:column;align-items:stretch;justify-content:center;gap:0}
.mn-ringrow{display:flex;align-items:center;gap:16px;width:100%%;flex:1 1 auto;min-height:0;min-width:0}
.mn-ringwrap{flex:0 0 auto;position:relative;overflow:hidden;flex-shrink:0}
.mn-ringwrap svg{position:absolute;inset:0;width:100%%;height:100%%;display:block}
.mn-ringmid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:2px;pointer-events:none}
/* 百分比字号由 Python 按圈内径算好后内联给出，CSS 里不再写死，
   否则 46px 的固定值会盖掉内联，数字直接压在环上 */
.mn-ringpct{font-family:%(SERIF)s;font-weight:700;line-height:1;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.mn-ringinner{color:%(INK3)s;line-height:1.2;white-space:nowrap}
/* 侧栏跟着环高均匀分布，不挤在顶部（环是主角，数据是配角但要陪满） */
.mn-ringside-fill{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;
  justify-content:space-evenly;gap:4px}
.rs-row{display:flex;flex-direction:column;gap:2px;min-width:0}
.rs-v{font-family:%(SERIF)s;font-size:31px;font-weight:700;color:%(INK)s;line-height:1.1;
  font-variant-numeric:tabular-nums}
.rs-l{font-size:22px;color:%(INK3)s;line-height:1.25;min-width:0}
.mn-cap-full{flex:0 0 auto;width:100%%;margin-top:9px}

/* 配图 */
.mn-photo{justify-content:center;gap:8px}
.mn-photo img{width:100%%;flex:1 1 auto;min-height:0;object-fit:cover;border-radius:6px;
  display:block}

/* ---------- 温度网格（宽件） ---------- */
.grid{display:grid;grid-template-columns:1fr 1fr;flex:1 1 auto;min-height:0;
  grid-auto-rows:1fr;gap:0;align-content:stretch}
.gc{padding:9px 20px;border-bottom:1px solid #EFE9DC;border-right:1px solid #EFE9DC;
  display:flex;flex-direction:column;justify-content:center;min-width:0;min-height:0;
  gap:3px}
.gc:nth-child(2n){border-right:none}
.gc-top{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.gc-name{font-size:25px;color:%(INK3)s;line-height:1.25;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.gc-val{font-family:%(SERIF)s;font-size:40px;font-weight:700;color:%(INK)s;
  font-variant-numeric:tabular-nums;line-height:1.15;white-space:nowrap}
.gc-foot{display:flex;align-items:center;justify-content:space-between;margin-top:0;gap:10px}
.gc-chg{font-size:24px;font-variant-numeric:tabular-nums;white-space:nowrap}
/* 网格级标签与条目级标签同规格（见 .tag 处的说明） */
.gc-tag{font-size:24px;padding:3px 12px;border-radius:4px;font-weight:600;
  line-height:1.5;white-space:nowrap}

/* ---------- 卡级结论条 / 口径注 ---------- */
.strip{font-size:30px;line-height:1.6;color:%(INK2)s;flex:0 0 auto;margin-top:12px;
  padding:12px 18px;background:#F2EEE4;border-left:5px solid %(CRIMSON)s;border-radius:0 6px 6px 0}
.strip .hl{color:%(CRIMSON)s;font-weight:700}
/* 口径注与右下角角标并排成一行 —— 原来各占一行，白白吃掉 50px。
   条目区抢不到高度的时候，省下来的每一像素都要还给内容。 */
.tailrow{flex:0 0 auto;display:flex;align-items:flex-end;justify-content:space-between;
  gap:24px;margin-top:10px}
.tailrow .note{flex:1 1 auto;min-width:0}
.note{font-size:24px;line-height:1.6;color:%(INK3)s;
  padding-left:16px;border-left:4px solid #D8D0BE}

/* ---------- 右下角段落名角标 ---------- */
.corner{flex:0 0 auto;display:flex;justify-content:flex-end}
.corner-box{display:inline-flex;align-items:center;gap:9px;font-size:23px;color:%(INK3)s;
  background:#EFEBE0;border:1px solid #E2DACA;border-radius:4px;padding:5px 13px;
  line-height:1.2;white-space:nowrap}
.corner-dot{width:7px;height:7px;background:%(CRIMSON)s;border-radius:1px;flex:0 0 auto}

/* ---------- footer（只两行 + 大二维码） ---------- */
.foot{background:#F1EDE2;border-top:3px solid %(CRIMSON)s;padding:18px 68px 16px}
.foot-main{display:flex;gap:30px;align-items:center}
.foot-txt{flex:1 1 auto;min-width:0}
.fh{display:inline-block;font-size:19px;font-weight:700;color:%(INK3)s;
  letter-spacing:1px;margin-right:9px}
.fs{font-size:19px;line-height:1.6;color:%(INK4)s}
.fd{font-size:19px;line-height:1.6;color:%(INK3)s;margin-top:7px}
.foot-qr{flex:0 0 auto;line-height:0}
.foot-qr img{width:140px;height:140px;display:block;background:#fff;padding:6px;
  border:1px solid #DDD5C4;border-radius:5px}
""" % {"SANS": SANS, "SERIF": SERIF, "CRIMSON": CRIMSON, "NAVY": NAVY,
       "INK": INK, "INK2": INK2, "INK3": INK3, "INK4": INK4,
       "PAPER": PAPER, "CARD": CARD, "LINE": LINE,
       "PAGE_H": PAGE_H, "PAD_T": PAD_T, "PAD_B": PAD_B,
       "HEAD_GAP": HEAD_GAP, "ITEM_GAP": ITEM_GAP,
       "ITEM_PAD_V": ITEM_PAD_V, "ITEM_PAD_H": ITEM_PAD_H,
       "IT_R_W": IT_R_W, "IT_R_PAD": IT_R_PAD, "IT_L_GAP": IT_L_GAP}


# ---------------------------------------------------------------- main

def load_qr():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(here, "assets", "wechat-qr.png")
    if not os.path.exists(p):
        print(f"⚠️  未找到二维码 {p}，footer 将留白", file=sys.stderr)
        return ""
    with open(p, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def main():
    ap = argparse.ArgumentParser(description="生成《胡子哥财经晨报》四张紧凑卡")
    ap.add_argument("data", help="data.json 路径")
    ap.add_argument("-o", "--out", default="out", help="输出目录")
    ap.add_argument("--only", type=int, metavar="N",
                    help="只重建第 N 张（改一卡不必全量重建）")
    ap.add_argument("--dry", action="store_true",
                    help="只跑预检、不写 HTML（改文案时反复试算用）")
    ap.add_argument("--plan", action="store_true",
                    help="打印每张卡的竖向预算账后退出（不写文件）")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)

    cards = data["cards"]
    total = len(cards)
    meta, footer = data["meta"], data["footer"]
    qr = load_qr()
    base_dir = os.path.dirname(os.path.abspath(args.data))

    os.makedirs(args.out, exist_ok=True)
    bad = 0
    for i, card in enumerate(cards, 1):
        card.setdefault("no", f"{i:02d}")
        if args.only and i != args.only:
            continue

        # --plan：只把预算账打出来，不跑文案预检、不写文件。
        # 排查「文字顶出白卡 / 版面被挤扁」时先跑这个，比出图再量快得多。
        if args.plan:
            p = plan_card(card)
            print(f"\n=== {i:02d} {p['section']}  条目 {p['n_items']}")
            print(f"  可用 {p['stack']}px（页高 {PAGE_H} − 上下边距 − 刊头 {p['head_h']}"
                  f" − 结论条 − 口径注 − 条目间距）")
            print(f"  需求合计 {sum(p['need'])}px   缺口 {p['over']:+d}px"
                  + ("   ← 文字底线被侵占，必须砍字" if p["squeezed"]
                     else "   ← 超的部分从视觉件富余里挤，文字不受影响"
                     if p["over"] > 0 else "   ✔ 装得下"))
            for d in p["items"]:
                mark = "✗ 文字被压" if d["squeezed"] else "✓"
                extra = ""
                if d["cut_lines"]:
                    extra = (f"   → 砍 {d['cut_lines']} 行，压到 {d['target_chars']} 字以内")
                print(f"    it{d['idx']} 「{d['kicker'] or '网格'}」 "
                      f"正文 {d['prose_chars']:>3} 字 / {d['prose_lines']} 行，"
                      f"排得下 {d['lines_fit']} 行；"
                      f"需求 {d['need']} 底线 {d['floor']} 分到 {d['alloc']} {mark}{extra}")
            continue

        flag = ""
        n_items = len(card.get("items", []))
        if n_items < 2 or n_items > 4:
            flag += f"  ⚠️ 条目数 {n_items}（建议 2–3 条）"
        for it in card.get("items", []):
            d = len(clean(it.get("desc", "")))
            if d > DESC_MAX:
                flag += f"  ⚠️ 条目「{clean(it.get('kicker',''))}」解释 {d} 字 > {DESC_MAX}"
            if not it.get("title"):
                flag += f"  ⚠️ 条目「{clean(it.get('kicker',''))}」缺结论句"
            if not it.get("visual"):
                flag += f"  ⚠️ 条目「{clean(it.get('kicker',''))}」没有配图"

            # ---- 标签：四档白名单 ----
            # 2026-10-22 胡子哥：「现在的颜色比较乱，有些还没有颜色。
            # 帮我梳理这些标签，保证每张图上标签的着色规则统一。」
            # 规则只有四条合法档：窗口 / 高位 / 风险 / 观察。
            # legacy 词（中性/分化/待验证）会收敛到「观察」，但要报出来让人改掉。
            tg = it.get("tag", "")
            if tg and tg not in TAGS:
                flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」标签「{tg}」不在四档内"
                         f" —— 只能用 {'/'.join(TAG_CANON)}")
            elif tg in TAG_ALIAS:
                flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」用了旧标签「{tg}」"
                         f" —— 改成「{TAG_ALIAS[tg]}」")
            v0 = it.get("visual") or {}
            for gi in (v0.get("items") or []):
                st = gi.get("status", "")
                if st and st not in TAGS:
                    flag += (f"  ⚠️ 网格项「{clean(gi.get('name',''))}」状态「{st}」不在四档内"
                             f" —— 只能用 {'/'.join(TAG_CANON)}")
                elif st in TAG_ALIAS:
                    flag += (f"  ⚠️ 网格项「{clean(gi.get('name',''))}」用了旧状态「{st}」"
                             f" —— 改成「{TAG_ALIAS[st]}」")

            # ---- 正文段落模式（prose）----
            # 连续文字段落是 2026-10-22 起的主形态：不分要点，一段讲完。
            # 稿件阶段不设字数上限（写足写完整），取舍统一在这里按版面拦：
            # 装不下就回去精简，不要靠裁字或压字号解决。
            prose = clean(it.get("prose", ""))
            if prose:
                p_len = len(prose)
                if p_len > PROSE_MAX:
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」正文 {p_len} 字 "
                             f"> {PROSE_MAX} —— 按版式取舍后精简，别整段硬塞")
                if it.get("points"):
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」同时有 prose 和 points"
                             f" —— 二选一，prose 优先")
                if it.get("desc"):
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」同时有 prose 和 desc"
                             f" —— prose 模式下 desc 会被忽略，钩子请并进正文")
                # 行数估算：左栏宽度与要点层同一套账
                if it.get("layout") == "wide":
                    wl1 = IT_L_W_WIDE
                else:
                    wl1 = IT_L_W
                p_lines = est_lines(prose, wl1 - PROSE_PAD, 24)
                if p_lines > 9:
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」正文 {p_len} 字 ≈ {p_lines} 行"
                             f" —— 一条正文最多 9 行，砍到 200 字以内")

            # desc 不能和 title 说同一句话。
            # 写文案时最容易犯的错：把结论句原样抄一遍当解释句，
            # 读者看到两遍同一句话，就觉得「就这一句话，没别的了」。
            t_clean = clean(it.get("title", ""))
            d_clean = clean(it.get("desc", ""))
            if t_clean and d_clean and (t_clean in d_clean or d_clean in t_clean):
                flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」解释句与结论句重复"
                         f"—— 解释句要写「所以呢」，不是重复「是什么」")

            # 要点必须短：一行放得下。写成完整句子会折行，
            # 既把空吃掉又撑破容器，得不偿失。
            # 判断用 em 宽度而不是字数 —— "道指 +1.02%，标普 +0.28%" 有 18 个字符
            # 但只占 11 个字宽，一行放得下。按字符数判断会误报。
            if it.get("layout") == "wide":
                wl0 = IT_L_W_WIDE
            else:
                wl0 = IT_L_W
            pt_w = wl0 - LT_PAD - PTS_DOT
            n_pts = len([p for p in (it.get("points") or []) if clean(p)])
            for p in (it.get("points") or []):
                p = clean(p)
                if not p:
                    continue
                if est_lines(p, pt_w, 24) > 1:
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」要点 "
                             f"「{p}」放不下，要点要短句（一行放得下）")
            if n_pts > 4:
                flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」要点 "
                         f"{n_pts} 条 > 4")

            # 来源信息只放 footer。视觉件里再写一遍「USDCNH 纽约尾盘」「CME FedWatch · 10/20」
            # 这类来源/时点，是同一句话在同一页出现两次，读者只会觉得啰嗦。
            v = it.get("visual") or {}
            for src in (v.get("caption", ""), (v.get("item") or {}).get("label", "")):
                src = clean(src)
                if re.search(r"(尾盘|收盘|截至|纽约|香港|路透|彭博|矩阵|来源|数据)",
                             src):
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」视觉件里写了来源"
                             f"「{src}」—— 来源统一放 footer，视觉件只讲结论")
                if len(src) > 16:
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker',''))}」视觉件说明 {len(src)} 字"
                             f" > 16，视觉件里不写解释句")

        # —— 高度配比合理性：内容密度与占屏面积必须匹配
        # 账全部走 plan_card()，不再在这里重写一遍（两份实现一漂，诊断就和渲染对不上）
        n_items = len(card.get("items", []))
        if n_items >= 2:
            plan = plan_card(card)
            hs = plan["alloc"]
            needs = plan["need"]
            caps = plan["cap"]

            # 文字底线被侵占 → 一定会顶出白卡，这是**阻断级**问题
            for d in plan["squeezed"]:
                flag += (f"  ⚠️ 条目「{d['kicker'] or '网格'}」文字底线 {d['floor']}px "
                         f"只分到 {d['alloc']}px（差 {d['floor'] - d['alloc']}px）"
                         f"—— 正文会顶出白卡，砍字")

            # 最挤的一条：拿到的不到需求的 88%，说明密度分配失灵了
            for it, hh, nd in zip(card["items"], hs, needs):
                if nd > 0 and hh < nd * 0.88:
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker','')) or '网格'}」"
                             f"内容密度高（需 {nd}px）却只分到 {hh}px，会被压扁")
            # 落差过大：最高条超过最低条 2.2 倍，视觉上会明显失衡
            if min(hs) > 0 and max(hs) / min(hs) > 2.2:
                flag += (f"  ⚠️ 条目高度落差 {max(hs)//min(hs)}×（{min(hs)}–{max(hs)}px），"
                         f"配比过陡，考虑合并或加一条讯息")
            # 撑不住：某条超过了它的自然高度上限，说明这一张的讯息太少、内容太轻，
            # 剩下的高度全压在它身上，就会出现「上半张有内容、下半张空白」。
            for it, hh, cp in zip(card["items"], hs, caps):
                if hh > cp * 1.12:
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker','')) or '网格'}」"
                             f"分到 {hh}px 但自然上限只有 {cp}px，会出现大片空白 —— "
                             f"这一张讯息偏少，考虑合并成一条或补一条")

            # 正文行数超出可用行数：直接给「砍到几行 / 砍到多少字」
            for d in plan["items"]:
                if d["cut_lines"] > 0:
                    flag += (f"  ⚠️ 条目「{d['kicker'] or '网格'}」正文 {d['prose_chars']} 字 "
                             f"≈ {d['prose_lines']} 行，但只排得下 {d['lines_fit']} 行 —— "
                             f"砍掉 {d['cut_lines']} 行，压到 {d['target_chars']} 字以内")

            # 要点降档：写了几条要点，实际渲染了几条。少渲染的那几条
            # 就是被版面挤掉的 —— 内容再重要，渲染不出来等于没写。
            for it, hh in zip(card["items"], hs):
                pts = [p for p in (it.get("points") or []) if clean(p)]
                if not pts:
                    continue
                if it.get("layout") == "wide":
                    wl = IT_L_W_WIDE
                else:
                    wl = IT_L_W
                avail = hh - ITEM_CHROME
                base = left_natural_h(it, wl)
                keep = len(pts)
                while keep > 1 and base > avail:
                    base -= PTS_ROW + PTS_GAP
                    keep -= 1
                if keep < len(pts):
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker','')) or '网格'}」"
                             f"要点渲染 {keep}/{len(pts)} 条 —— "
                             f"版面装不下，砍要点或砍别的内容")
                if base > avail:
                    flag += (f"  ⚠️ 条目「{clean(it.get('kicker','')) or '网格'}」"
                             f"左栏文字需 {base}px 但只有 {avail}px，文字会被裁")
        b = len(clean("".join(card.get("body", []))))
        if b > BODY_MAX:
            flag += f"  ⚠️ 结论条 {b} 字 > {BODY_MAX}"
        if flag:
            bad += 1

        if args.dry:
            size = fit_headline(card["headline"])
            print(f"  ⊘ card-{i:02d}（dry run，未写文件） {card.get('section','')}  "
                  f"{n_items} 条  标题 {size}px{flag}")
            continue

        html = render_card(card, meta, footer, qr, total, base_dir)
        out = os.path.join(args.out, f"card-{i:02d}.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        size = fit_headline(card["headline"])
        print(f"  ✔ {out}  {card.get('section','')}  {n_items} 条  标题 {size}px{flag}")

    print(f"\n✅ 共 {total} 张卡片，输出到 {args.out}/")
    if bad:
        print(f"   ⚠️ {bad} 张有问题：砍字，不要砍字号。")
    if not args.dry:
        print("   下一步: node render.cjs " + args.out)

    # 返回码语义（make.sh 靠它决定是否继续）：
    #   0 = 干净   2 = 有告警（出图仍可看，但要改）   1 = 真崩溃（异常抛出）
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
