/**
 * doctor.cjs —— 一次量完四张卡的全部盒模型 / 行数 / 标签 / 留白
 *
 * 为什么有这个文件：
 *   2026-10-22 那轮调版，为了定位「文字顶出白卡 5px」，临时写了 39 个 playwright
 *   量测脚本、跑了 54 次内联 Python 探针，一次会话 85 次重建、1.07 亿 input token。
 *   真正的病是**每次量一个数都要单开一次工具轮**。这个脚本把需要的数一次全吐出来。
 *
 * 用法:
 *   node doctor.cjs <cards 目录>              // 全量
 *   node doctor.cjs <cards 目录> --json /tmp/d.json
 *   node doctor.cjs <cards 目录> --only 4     // 只量第 4 张
 *   node doctor.cjs <cards 目录> --quiet      // 只打问题，不打明细
 *
 * 输出:
 *   stdout  人类可读摘要（默认只打「有问题」的，--verbose 打全表）
 *   JSON    结构化数据，供 doctor.py 与后续分析复用
 *
 * 退出码: 0 无阻断；1 有 overflow（文字溢出容器）
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

function loadPlaywright() {
  const candidates = [
    'playwright',
    'playwright-core',
    path.join(os.homedir(), 'node_modules', 'playwright'),
    path.join(os.homedir(), 'node_modules', 'playwright-core'),
    '/opt/homebrew/lib/node_modules/playwright',
    '/usr/local/lib/node_modules/playwright',
  ];
  for (const c of candidates) {
    try { return require(c); } catch (e) { /* next */ }
  }
  console.error('❌ 未找到 playwright');
  process.exit(1);
}
const { chromium } = loadPlaywright();

/* ---------- 参数 ---------- */
const argv = process.argv.slice(2);
const dir = argv.find((a) => !a.startsWith('--') && !/^\d+$/.test(a) && a !== '') || 'cards';
const onlyIdx = (() => {
  const i = argv.indexOf('--only');
  return i >= 0 ? parseInt(argv[i + 1], 10) : null;
})();
const jsonOut = (() => {
  const i = argv.indexOf('--json');
  return i >= 0 ? argv[i + 1] : null;
})();
const QUIET = argv.includes('--quiet');
const VERBOSE = argv.includes('--verbose');

/* ---------- 页面内测量 ---------- */
const MEASURE = () => {
  const R = (el) => el.getBoundingClientRect();
  const px = (v) => parseFloat(v) || 0;
  const hex = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(Number);
    return '#' + p.slice(0, 3).map((n) => Math.round(n).toString(16).padStart(2, '0')).join('').toUpperCase();
  };
  const lum = (h) => {
    const n = h.replace('#', '');
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16);
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const cr = (a, b) => {
    if (!a || !b) return null;
    const l1 = lum(a), l2 = lum(b);
    return +(((Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)).toFixed(2));
  };

  const out = { items: [], tags: [], problems: [] };

  /* 页面总高 */
  out.pageH = +document.body.getBoundingClientRect().height.toFixed(1);

  /* 主标题 */
  const hl = document.querySelector('.headline');
  if (hl) {
    const cs = getComputedStyle(hl);
    out.headline = {
      size: px(cs.fontSize),
      lines: Math.round(R(hl).height / (px(cs.fontSize) * 1.28)),
      h: +R(hl).height.toFixed(1),
    };
  }

  /* 三条讯息 */
  document.querySelectorAll('.item').forEach((it, i) => {
    const l = it.querySelector('.it-l');
    const kick = it.querySelector('.it-k');
    const title = it.querySelector('.it-title');
    const prose = it.querySelector('.it-prose');
    const d = { idx: i, itemH: +R(it).height.toFixed(1) };
    if (l) {
      const ls = getComputedStyle(l);
      d.lW = +(R(l).width - px(ls.paddingLeft) - px(ls.paddingRight)).toFixed(1);
      d.lClient = l.clientHeight;
      d.lScroll = l.scrollHeight;
      d.over = d.lScroll - d.lClient;   // >0 = 文字顶出容器
    }
    if (kick) d.kickH = +R(kick).height.toFixed(1);
    if (title) {
      const cs = getComputedStyle(title);
      d.titleLH = +px(cs.lineHeight).toFixed(1);
      d.titleLines = Math.round(R(title).height / px(cs.lineHeight));
      d.titleH = +R(title).height.toFixed(1);
    }
    if (prose) {
      const cs = getComputedStyle(prose);
      d.proseLH = +px(cs.lineHeight).toFixed(1);
      d.proseH = +R(prose).height.toFixed(1);
      d.proseLines = Math.round(R(prose).height / px(cs.lineHeight));
      d.proseW = +(R(prose).width - px(cs.paddingLeft) - px(ls0(prose))).toFixed(1);
    }
    function ls0(el) { return getComputedStyle(el).paddingRight; }
    /* 视觉件 */
    const v = it.querySelector('.mn');
    if (v) {
      let ink = 0;
      [...v.children].forEach((k) => { ink += k.getBoundingClientRect().height; });
      d.visual = {
        cls: v.className,
        h: +R(v).height.toFixed(1),
        ink: +ink.toFixed(1),
        fill: R(v).height > 0 ? +(ink / R(v).height).toFixed(2) : null,
      };
    }
    out.items.push(d);
  });

  /* 结论条 */
  const strip = document.querySelector('.strip');
  if (strip) {
    const cs = getComputedStyle(strip);
    const r = R(strip);
    const padY = px(cs.paddingTop) + px(cs.paddingBottom);
    const lh = px(cs.lineHeight);
    out.strip = {
      boxH: +r.height.toFixed(1),
      padY,
      lh: +lh.toFixed(1),
      lines: Math.round((r.height - padY) / lh),
      textW: +(r.width - px(cs.paddingLeft) - px(cs.paddingRight) - px(cs.borderLeftWidth)).toFixed(1),
      top: +r.top.toFixed(1),
    };
  }

  /* items 末条底边 → strip 顶边 的留白 */
  const items = document.querySelector('.items');
  if (items && strip) {
    const last = items.querySelector('.item:last-child');
    if (last) out.gapItemToStrip = +(R(strip).top - R(last).bottom).toFixed(1);
  }

  /* 口径注 */
  const note = document.querySelector('.note');
  if (note) {
    const cs = getComputedStyle(note);
    const r = R(note);
    out.note = {
      boxH: +r.height.toFixed(1),
      lh: +px(cs.lineHeight).toFixed(1),
      lines: Math.round(r.height / px(cs.lineHeight)),
      textW: +(r.width - px(cs.paddingLeft) - px(cs.borderLeftWidth)).toFixed(1),
    };
  }

  /* tailrow */
  const tail = document.querySelector('.tailrow');
  if (tail) out.tailH = +R(tail).height.toFixed(1);

  /* steps 上下留白是否对称 —— 用户明确要求「居中，上下留空」 */
  const steps = document.querySelector('.mn-steps');
  if (steps) {
    const sr = R(steps);
    const nodes = [...steps.querySelectorAll('.ms-node')];
    if (nodes.length) {
      const firstTop = R(nodes[0]).top - sr.top;
      const lastBot = R(nodes[nodes.length - 1]).bottom - sr.top;
      out.steps = {
        boxH: +sr.height.toFixed(1),
        topPad: +firstTop.toFixed(1),
        botPad: +(sr.height - lastBot).toFixed(1),
        asym: +Math.abs(firstTop - (sr.height - lastBot)).toFixed(1),
      };
      if (out.steps.asym > 8) {
        out.problems.push({ level: 'warn', what: `steps 上下留白不对称，差 ${out.steps.asym}px` });
      }
    }
  }

  /* 全部标签：文字 / 配色 / 规格 / 对比度 */
  document.querySelectorAll('.tag, .tag-inline, .gc-tag').forEach((el) => {
    const cs = getComputedStyle(el);
    const fg = hex(cs.color), bg = hex(cs.backgroundColor);
    out.tags.push({
      txt: el.textContent.trim(),
      cls: el.className,
      fg, bg,
      fs: px(cs.fontSize),
      fw: cs.fontWeight,
      pad: cs.padding,
      rad: px(cs.borderRadius),
      cr: cr(fg, bg),
    });
  });

  /* 跨层级压盖：最后一条 item 底边 vs strip 顶边 */
  if (typeof out.gapItemToStrip === 'number' && out.gapItemToStrip < 0) {
    out.problems.push({ level: 'block', what: `最后一条讯息压住结论条 ${-out.gapItemToStrip}px` });
  }
  /* 文字溢出 */
  out.items.forEach((d) => {
    if (d.over > 0) {
      out.problems.push({ level: 'block', what: `it${d.idx} 正文顶出容器 ${d.over}px（lScroll ${d.lScroll} / lClient ${d.lClient}）` });
    }
  });

  return out;
};

/* ---------- 主流程 ---------- */
(async () => {
  const files = fs.readdirSync(dir)
    .filter((f) => /^card-\d+\.html$/.test(f))
    .sort()
    .filter((f) => (onlyIdx ? parseInt(f.match(/\d+/)[0], 10) === onlyIdx : true));

  if (!files.length) {
    console.error('❌ 目录里没有 card-NN.html：' + dir);
    process.exit(1);
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1440 } });
  const report = { dir, cards: [], problems: [] };

  for (const f of files) {
    await page.goto('file://' + path.resolve(dir, f), { waitUntil: 'load' });
    const m = await page.evaluate(MEASURE);
    m.file = f;
    report.cards.push(m);
    m.problems.forEach((p) => report.problems.push({ file: f, ...p }));
  }
  await browser.close();

  /* ---- stdout ---- */
  const blocks = report.problems.filter((p) => p.level === 'block');
  if (!QUIET) {
    for (const c of report.cards) {
      const bad = c.problems.length > 0;
      if (!bad && !VERBOSE) continue;
      const head = `${bad ? '❌' : '✔'} ${c.file}  页高 ${c.pageH}`;
      console.log(head);
      if (VERBOSE) {
        c.items.forEach((d) => {
          console.log(`   it${d.idx} itemH=${d.itemH} lW=${d.lW} lClient=${d.lClient} lScroll=${d.lScroll}`
            + ` kick=${d.kickH} title=${d.titleH}(${d.titleLines}行)`
            + ` prose=${d.proseH}(${d.proseLines}行×${d.proseLH})`
            + (d.visual ? ` vis=${d.visual.h}(fill ${d.visual.fill})` : ''));
        });
        if (c.strip) console.log(`   strip ${c.strip.lines}行 盒高${c.strip.boxH} 文字宽${c.strip.textW}  与条目留白 ${c.gapItemToStrip}px`);
        if (c.note) console.log(`   note ${c.note.lines}行 盒高${c.note.boxH}`);
        if (c.steps) console.log(`   steps 容器${c.steps.boxH} 上留白${c.steps.topPad} 下留白${c.steps.botPad} 不对称${c.steps.asym}px`);
      }
      c.problems.forEach((p) => console.log(`   [${p.level === 'block' ? 'B' : 'W'}] ${p.what}`));
    }
    if (!report.problems.length) console.log('✔ 四张卡盒模型全部正常（无溢出 / 无压盖 / steps 对称）');
  }

  /* 标签一致性：同一文字必须只有一种配色 */
  const byWord = new Map();
  report.cards.forEach((c) => c.tags.forEach((t) => {
    if (!byWord.has(t.txt)) byWord.set(t.txt, new Set());
    byWord.get(t.txt).add(`${t.fg}/${t.bg}`);
  }));
  const conflict = [...byWord.entries()].filter(([, s]) => s.size > 1);
  const allTags = report.cards.flatMap((c) => c.tags);
  const specSet = new Set(allTags.map((t) => `${t.fs}|${t.fw}|${t.pad}|${t.rad}`));
  report.tagSummary = {
    total: allTags.length,
    words: byWord.size,
    specVariants: specSet.size,
    specs: [...specSet],
    conflict: conflict.map(([w, s]) => ({ word: w, variants: [...s] })),
  };

  if (!QUIET) {
    console.log(`\n标签：${allTags.length} 个 / ${byWord.size} 个词 / 规格 ${specSet.size} 种`
      + (specSet.size > 1 ? '  ❌ 规格不唯一' : '  ✔')
      + (conflict.length ? `  ❌ 同词多色：${conflict.map(([w]) => w).join('、')}` : '  ✔ 无同词多色'));
  }

  if (jsonOut) {
    fs.writeFileSync(jsonOut, JSON.stringify(report, null, 1));
    if (!QUIET) console.log(`\nJSON → ${jsonOut}`);
  }

  process.exit(blocks.length ? 1 : 0);
})();
