#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_brief.py —— 《环球财经晨报 · GLOBAL BRIEF》单文件 HTML 生成器

用法:
    python3 build_brief.py data.json -o 环球财经晨报_20261021.html

输入: 符合 templates/data.template.json 结构的 JSON
输出: 单文件 HTML（内联 SVG 图表，无外部依赖）
"""

import argparse
import json
import sys
from datetime import datetime
from html import escape

# ---------------------------------------------------------------- 设计令牌

C = {
    "crimson": "#800000",
    "navy": "#1F497D",
    "blue": "#0066CC",
    "green": "#339966",
    "green_dark": "#256B4B",
    "orange": "#FF9900",
    "cyan": "#4BACC6",
    "silver": "#C0C0C0",
    "cream": "#EEECE1",
    "cream2": "#F6F4F0",
    "ink": "#1A1A1A",
    "ink2": "#3C3C3C",
    "ink3": "#6B6B6B",
    "wash_red": "#FBF7F7",
}

# 语义标签四档：文字色 / 底色
TAGS = {
    "窗口": (C["crimson"], "#F7E9E9"),
    "高位": (C["navy"], "#E7EDF5"),
    "风险": (C["green_dark"], "#E8F3EC"),
    "观察": ("#8A5A00", "#FCF4E4"),
    "中性": ("#8A5A00", "#FCF4E4"),
    "分化": ("#8A5A00", "#FCF4E4"),
    "待验证": ("#8A5A00", "#FCF4E4"),
}

SERIF = '"Noto Serif CJK SC","Source Han Serif SC","Songti SC","STSong","SimSun",serif'
SANS = '"Noto Sans CJK SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif'


def tag_style(tag):
    fg, bg = TAGS.get(tag, TAGS["观察"])
    return (
        f"display:inline-block;padding:2px 8px;border-radius:3px;"
        f"font-size:12.5px;font-weight:600;line-height:1.5;"
        f"color:{fg};background:{bg};white-space:nowrap;"
    )


def fmt_num(v, fmt="{:.4f}"):
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------- SVG 折线图

def build_chart_svg(chart, width=980, height=320):
    pad_l, pad_r, pad_t, pad_b = 66, 46, 56, 48
    pw = width - pad_l - pad_r
    ph = height - pad_t - pad_b

    y_min = float(chart["y_min"])
    y_max = float(chart["y_max"])
    y_ticks = [float(t) for t in chart.get("y_ticks", [])]
    y_format = chart.get("y_format", "{:.4f}")
    series = chart["series"]

    def parse_d(s):
        s = str(s)
        for sep in ("-", "/", "."):
            if sep in s:
                parts = s.split(sep)
                try:
                    y = int(parts[0])
                    m = int(parts[1]) if len(parts) > 1 else 1
                    return y * 12 + m
                except ValueError:
                    pass
        return 0

    ts = [parse_d(p["date"]) for p in series]
    t0, t1 = min(ts), max(ts)
    tspan = (t1 - t0) or 1

    def X(i):
        return pad_l + pw * (ts[i] - t0) / tspan

    def Y(v):
        r = (float(v) - y_min) / ((y_max - y_min) or 1)
        return pad_t + ph * (1 - r)

    parts = [f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             f'xmlns="http://www.w3.org/2000/svg" font-family={escape(SANS)}>']

    # 浅色绘图区
    parts.append(f'<rect x="{pad_l}" y="{pad_t}" width="{pw}" height="{ph}" '
                 f'fill="{C["cream2"]}" stroke="{C["silver"]}" stroke-width="1"/>')

    # Y 轴刻度线（不超过 4 条）
    for t in y_ticks:
        y = Y(t)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l+pw}" y2="{y:.1f}" '
                     f'stroke="{C["silver"]}" stroke-width="1" stroke-dasharray="3 3"/>')
        parts.append(f'<text x="{pad_l-10}" y="{y+4:.1f}" text-anchor="end" '
                     f'font-size="11.5" fill="{C["ink3"]}">{fmt_num(t, y_format)}</text>')

    # 折线
    pts = " ".join(f"{X(i):.1f},{Y(p['value']):.1f}" for i, p in enumerate(series))
    parts.append(f'<polyline points="{pts}" fill="none" stroke="{C["crimson"]}" '
                 f'stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>')

    # 关键点：空心圈 + 数值 + 时间标签
    # 标签避让规则：折线整体向右下走，所以首个点的标签放上方/下方要错开线
    n = len(series)
    halo = ' paint-order="stroke" stroke="#FFFFFF" stroke-width="4" stroke-linejoin="round"'
    for i, p in enumerate(series):
        x, y = X(i), Y(p["value"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#FFFFFF" '
                     f'stroke="{C["crimson"]}" stroke-width="2.4"/>')

        if i == 0:
            val_dy, val_anchor = -18, "start"
            time_dy, time_anchor = 26, "start"
        elif i == n - 1:
            val_dy, val_anchor = 26, "end"
            time_dy, time_anchor = -16, "end"
        else:
            val_dy, val_anchor = 26, "middle"
            time_dy, time_anchor = -16, "middle"

        parts.append(f'<text x="{x:.1f}" y="{y+val_dy:.1f}" text-anchor="{val_anchor}" '
                     f'font-size="15" font-weight="700" fill="{C["crimson"]}"{halo}>'
                     f'{fmt_num(p["value"], y_format)}</text>')

        parts.append(f'<text x="{x:.1f}" y="{y+time_dy:.1f}" text-anchor="{time_anchor}" '
                     f'font-size="11.5" fill="{C["ink3"]}"{halo}>{escape(p["label"])}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------- 段落渲染

def render_header(meta):
    return f"""
<div class="masthead">
  <div class="mh-left">
    <div class="mh-title">{escape(meta.get('title', '环球财经晨报'))}</div>
    <div class="mh-sub">{escape(meta.get('subtitle', 'GLOBAL BRIEF'))}</div>
  </div>
  <div class="mh-right">
    <div class="mh-issue">{escape(meta['issue'])}</div>
    <div class="mh-date">{escape(meta['date'])}　{escape(meta.get('weekday', ''))}</div>
  </div>
</div>"""


def render_theme(theme):
    return f"""
<div class="theme-block">
  <div class="theme-label">今日主题</div>
  <div class="theme-text">{escape(theme)}</div>
</div>"""


def render_three_points(points):
    cards = []
    for p in points:
        cards.append(f"""
  <div class="card">
    <div class="card-head">
      <span class="card-title">{escape(p['title'])}</span>
      <span style="{tag_style(p['tag'])}">{escape(p['tag'])}</span>
    </div>
    <div class="card-body">{escape(p['body'])}</div>
  </div>""")
    return f"""
<div class="section">
  <div class="sec-head"><span class="sec-bar"></span><span class="sec-title">今日三条</span></div>
  <div class="cards">{''.join(cards)}
  </div>
</div>"""


def render_thermometer(tm):
    rows = []
    for i, r in enumerate(tm["rows"]):
        fg, bg = TAGS.get(r["status"], TAGS["观察"])
        zebra = ' class="row-alt"' if i % 2 == 1 else ""
        rows.append(f"""
    <tr{zebra}>
      <td class="c-name">{escape(r['name'])}</td>
      <td class="c-val">{escape(r['value'])}</td>
      <td class="c-chg">{escape(r['change'])}</td>
      <td class="c-stat"><span style="{tag_style(r['status'])}">{escape(r['status'])}</span></td>
      <td class="c-note">{escape(r['note'])}</td>
    </tr>""")
    return f"""
<div class="section">
  <div class="sec-head"><span class="sec-bar"></span><span class="sec-title">{escape(tm.get('caption','隔夜市场温度计'))}</span></div>
  <table class="thermo">
    <thead>
      <tr><th class="c-name">资产 / 指标</th><th class="c-val">水平</th><th class="c-chg">变动</th>
      <th class="c-stat">状态</th><th class="c-note">这意味着什么</th></tr>
    </thead>
    <tbody>{''.join(rows)}
    </tbody>
  </table>
  <div class="sub-note">{escape(tm.get('asof',''))}</div>
</div>"""


def render_chart(chart):
    svg = build_chart_svg(chart)
    conv = chart.get("conversion")
    conv_html = ""
    if conv:
        base = conv.get("base_label", "")
        base_html = f'<span class="conv-base">{escape(base)}</span>' if base else ""
        items = "".join(
            f"""
      <div class="conv-item">
        <div class="conv-label">{escape(it['label'])}</div>
        <div class="conv-value">{escape(it['value'])}</div>
      </div>"""
            for it in conv["items"]
        )
        conv_html = f"""
  <div class="conv">
    <div class="conv-title">{escape(conv.get('title',''))}{base_html}</div>
    <div class="conv-items">{items}
    </div>
    <div class="conv-foot">{escape(conv.get('footnote',''))}</div>
  </div>"""
    return f"""
<div class="section">
  <div class="sec-head"><span class="sec-bar"></span><span class="sec-title">本期主图</span></div>
  <div class="chart-box">
    <div class="chart-title">{escape(chart['title'])}</div>
    <div class="chart-sub">{escape(chart['subtitle'])}</div>
    {svg}
  </div>
  {conv_html}
</div>"""


def render_numbered(title, items, cls, with_index=True):
    lis = []
    for i, it in enumerate(items, 1):
        idx = f'<span class="idx">{i}</span>' if with_index else ""
        lis.append(f"""
    <div class="nl-item">
      {idx}<div class="nl-text"><span class="nl-title">{escape(it['title'])}</span>
      <span class="nl-body">{escape(it['body'])}</span></div>
    </div>""")
    return f"""
<div class="section">
  <div class="sec-head"><span class="sec-bar"></span><span class="sec-title">{escape(title)}</span></div>
  <div class="{cls}">{''.join(lis)}
  </div>
</div>"""


def render_closing(text):
    return f"""
<div class="closing"><span class="closing-mark">“</span>{escape(text)}</div>"""


def render_footer(footer, issue):
    srcs = "".join(f"<li>{escape(s)}</li>" for s in footer.get("sources", []))
    return f"""
<div class="footer">
  <div class="foot-src">
    <div class="foot-h">数据来源</div>
    <ul>{srcs}</ul>
    <div class="foot-asof">{escape(footer.get('asof',''))}</div>
  </div>
  <div class="foot-disc">{escape(footer.get('disclaimer',''))}</div>
  <div class="foot-issue">{escape(issue)}</div>
</div>"""


# ---------------------------------------------------------------- CSS

CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:{C['cream']};}}
.page{{width:1080px;margin:0 auto;background:{C['cream']};padding:0 0 34px;
  font-family:{SANS};color:{C['ink']};-webkit-font-smoothing:antialiased;}}

/* 刊头 */
.masthead{{background:{C['crimson']};color:#fff;padding:26px 50px 22px;
  display:flex;justify-content:space-between;align-items:flex-end;}}
.mh-title{{font-family:{SERIF};font-size:44px;font-weight:700;letter-spacing:2px;line-height:1.1;}}
.mh-sub{{font-size:15px;letter-spacing:6px;opacity:.85;margin-top:6px;}}
.mh-right{{text-align:right;}}
.mh-issue{{font-family:{SERIF};font-size:26px;font-weight:700;letter-spacing:1px;}}
.mh-date{{font-size:14px;opacity:.9;margin-top:5px;}}

/* 今日主题 */
.theme-block{{margin:30px 50px 26px;padding:22px 26px;background:#FFFFFF;
  border-left:6px solid {C['crimson']};}}
.theme-label{{font-size:12.5px;letter-spacing:3px;color:{C['crimson']};font-weight:700;margin-bottom:10px;}}
.theme-text{{font-family:{SERIF};font-size:31px;line-height:1.45;font-weight:700;color:{C['ink']};}}

/* 区块 */
.section{{margin:0 50px 30px;}}
.sec-head{{display:flex;align-items:center;margin-bottom:14px;}}
.sec-bar{{display:inline-block;width:6px;height:20px;background:{C['crimson']};margin-right:11px;}}
.sec-title{{font-family:{SERIF};font-size:17.5px;font-weight:700;color:{C['navy']};letter-spacing:1px;}}

/* 今日三条卡片 */
.cards{{display:flex;gap:16px;}}
.card{{flex:1;background:#FFFFFF;padding:16px 18px 18px;border-top:3px solid {C['navy']};}}
.card-head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px;}}
.card-title{{font-family:{SERIF};font-size:16px;font-weight:700;color:{C['crimson']};}}
.card-body{{font-size:13.3px;line-height:1.75;color:{C['ink2']};text-align:justify;}}

/* 温度计 */
table.thermo{{width:100%;border-collapse:collapse;background:#FFFFFF;font-size:13.2px;}}
table.thermo th{{background:{C['navy']};color:#fff;font-weight:600;font-size:12.5px;
  padding:9px 12px;text-align:left;letter-spacing:.5px;}}
table.thermo td{{padding:9px 12px;border-bottom:1px solid #E8E4DA;vertical-align:middle;line-height:1.6;}}
table.thermo tr:last-child td{{border-bottom:none;}}
.row-alt{{background:{C['wash_red']};}}
.c-name{{width:170px;color:{C['ink']};font-weight:600;}}
.c-val{{width:110px;text-align:right;font-variant-numeric:tabular-nums;font-weight:700;color:{C['ink']};}}
.c-chg{{width:110px;text-align:right;font-variant-numeric:tabular-nums;color:{C['ink3']};}}
.c-stat{{width:78px;text-align:center;}}
.c-note{{color:{C['ink2']};}}
.sub-note{{font-size:11px;color:{C['ink3']};margin-top:8px;}}

/* 主图 */
.chart-box{{background:#FFFFFF;padding:20px 22px 14px;}}
.chart-title{{font-family:{SERIF};font-size:19px;font-weight:700;color:{C['ink']};margin-bottom:5px;}}
.chart-sub{{font-size:12px;color:{C['ink3']};margin-bottom:12px;}}
.conv{{background:#FFFFFF;margin-top:14px;padding:16px 22px 18px;border-top:1px dashed {C['silver']};}}
.conv-title{{font-size:13.5px;font-weight:700;color:{C['navy']};margin-bottom:12px;}}
.conv-base{{font-weight:400;color:{C['ink3']};font-size:12px;margin-left:8px;}}
.conv-items{{display:flex;gap:16px;}}
.conv-item{{flex:1;background:{C['cream2']};padding:12px 14px;border-left:3px solid {C['crimson']};}}
.conv-label{{font-size:11.5px;color:{C['ink3']};margin-bottom:6px;}}
.conv-value{{font-family:{SERIF};font-size:20px;font-weight:700;color:{C['crimson']};
  font-variant-numeric:tabular-nums;}}
.conv-foot{{font-size:10.8px;color:{C['ink3']};margin-top:10px;}}

/* 编号列表 */
.nl-item{{display:flex;gap:12px;background:#FFFFFF;padding:14px 18px;margin-bottom:10px;}}
.idx{{flex:0 0 24px;height:24px;border-radius:50%;background:{C['crimson']};color:#fff;
  font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;
  font-family:{SERIF};}}
.nl-text{{flex:1;}}
.nl-title{{display:block;font-family:{SERIF};font-size:15px;font-weight:700;
  color:{C['navy']};margin-bottom:5px;}}
.nl-body{{display:block;font-size:13.3px;line-height:1.75;color:{C['ink2']};text-align:justify;}}

/* 保险段 */
.ins-item{{background:#FFFFFF;padding:14px 18px;margin-bottom:10px;border-left:3px solid {C['cyan']};}}
.ins-title{{display:block;font-family:{SERIF};font-size:15px;font-weight:700;color:{C['navy']};margin-bottom:5px;}}
.ins-body{{display:block;font-size:13.3px;line-height:1.75;color:{C['ink2']};text-align:justify;}}

/* 收束 */
.closing{{margin:30px 50px;background:{C['navy']};color:#fff;padding:20px 26px;
  font-family:{SERIF};font-size:16.5px;line-height:1.7;}}
.closing-mark{{font-size:26px;opacity:.6;margin-right:4px;}}

/* 页脚 */
.footer{{margin:24px 50px 0;padding-top:16px;border-top:2px solid {C['silver']};}}
.foot-h{{font-size:11.5px;font-weight:700;color:{C['navy']};letter-spacing:1px;margin-bottom:6px;}}
.foot-src ul{{list-style:none;}}
.foot-src li{{font-size:10.8px;color:{C['ink3']};line-height:1.8;padding-left:12px;position:relative;}}
.foot-src li:before{{content:"·";position:absolute;left:2px;}}
.foot-asof{{font-size:10.8px;color:{C['ink3']};margin-top:6px;}}
.foot-disc{{font-size:10.8px;color:{C['ink3']};line-height:1.7;margin-top:12px;
  padding:10px 12px;background:{C['cream2']};}}
.foot-issue{{font-size:11px;color:{C['crimson']};font-weight:700;text-align:right;margin-top:10px;}}
"""


def build_html(data):
    meta = data["meta"]
    parts = [
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">',
        f"<title>{escape(meta.get('title','环球财经晨报'))} {escape(meta['issue'])}</title>",
        f"<style>{CSS}</style></head><body><div class=\"page\">",
        render_header(meta),
        render_theme(data["theme"]),
        render_three_points(data["three_points"]),
        render_thermometer(data["thermometer"]),
        render_chart(data["main_chart"]),
        render_numbered("今日三件事", data["three_news"], "nl"),
        render_insurance(data["insurance"]),
        render_closing(data["closing"]),
        render_footer(data["footer"], meta["issue"]),
        "</div></body></html>",
    ]
    return "\n".join(parts)


def render_insurance(items):
    lis = []
    for it in items:
        lis.append(f"""
    <div class="ins-item">
      <span class="ins-title">{escape(it['title'])}</span>
      <span class="ins-body">{escape(it['body'])}</span>
    </div>""")
    return f"""
<div class="section">
  <div class="sec-head"><span class="sec-bar"></span><span class="sec-title">保险与税务观察</span></div>
  {''.join(lis)}
</div>"""


def main():
    ap = argparse.ArgumentParser(description="生成《环球财经晨报》单文件 HTML")
    ap.add_argument("data", help="data.json 路径")
    ap.add_argument("-o", "--out", help="输出 HTML 路径（默认与 data 同名 .html）")
    args = ap.parse_args()

    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)

    out = args.out or args.data.rsplit(".", 1)[0] + ".html"
    html = build_html(data)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    n_notes = len(data.get("notes", []))
    print(f"✅ 已生成 {out}  ({len(html):,} 字符)")
    if n_notes:
        print(f"⚠️  数据备注 {n_notes} 条（内部复核用，未上图）：")
        for n in data["notes"]:
            print(f"   - {n}")


if __name__ == "__main__":
    sys.exit(main())
