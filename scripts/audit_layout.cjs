/**
 * audit_layout.cjs —— 版面体检（不出图，只报建议）
 *
 * 用法:
 *   node audit_layout.cjs cards/            // 审 card-01..09.html
 *   node audit_layout.cjs cards/card-01.html
 *
 * 检查六项:
 *   1. overlap   同层元素矩形相交 —— 内容遮挡
 *   2. whitespace 视觉块内部的面积占用率 —— 留白过多
 *   3. clipped   文本溢出容器 —— 截断、叠字
 *   4. tiny      字号小于手机可读下限
 *   5. contrast  文字与背景的对比度（WCAG）
 *   6. hierarchy 字号层级是否足够拉开
 *
 * 退出码: 0 = 无阻断问题；1 = 有 block 级问题
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

const AUDIT = () => {
  /* ---------- 工具 ---------- */
  const parseColor = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] };
  };
  const lum = (c) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const over = (fg, bg) => {
    const a = fg.a;
    return { r: fg.r * a + bg.r * (1 - a), g: fg.g * a + bg.g * (1 - a), b: fg.b * a + bg.b * (1 - a), a: 1 };
  };
  const contrast = (c1, c2) => {
    const l1 = lum(c1), l2 = lum(c2);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };
  /** 向上找到第一个不透明背景 */
  const effectiveBg = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const cs = getComputedStyle(n);
      const c = parseColor(cs.backgroundColor);
      if (c && c.a === 1) return c;
      n = n.parentElement;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const isSvgPart = (el) => el.namespaceURI === SVG_NS || !!el.ownerSVGElement;
  const name = (el) => {
    if (el.namespaceURI === SVG_NS) return 'svg:' + el.tagName.toLowerCase();
    const cls = (el.getAttribute && el.getAttribute('class')) || '';
    const c = String(cls).split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    return el.tagName.toLowerCase() + (c ? '.' + c : '');
  };
  const area = (r) => Math.max(0, r.width) * Math.max(0, r.height);

  const out = { overlap: [], whitespace: [], ellipsis: [], clipped: [], tiny: [], contrast: [], sizes: {}, geom: {} };

  const page = document.querySelector('.page');
  if (page) {
    const pr = page.getBoundingClientRect();
    out.geom = { w: Math.round(pr.width), h: Math.round(pr.height) };
    // 图文比：视觉件列总高 / 正文页高
    let vh = 0;
    page.querySelectorAll('.it-r').forEach((v) => { vh += v.getBoundingClientRect().height; });
    out.geom.visualH = Math.round(vh);
    out.geom.visualRatio = +(vh / pr.height).toFixed(3);
  }

  /* ---------- 1. 遮挡：同一父节点下的子元素两两求交 ----------
     排除 SVG 内部：折线图的背景 rect / 填充 polygon / 线 polyline / 数据点 circle / 标签 text
     本来就互相叠着，那是图表的正常画法，不是遮挡 */
  const seen = new Set();
  document.querySelectorAll('.page *').forEach((parent) => {
    if (isSvgPart(parent)) return;
    const kids = [...parent.children].filter((k) => {
      if (isSvgPart(k)) return false;
      const cs = getComputedStyle(k);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      if (cs.position === 'absolute' || cs.position === 'fixed') return false; // 装饰层不算遮挡
      const r = k.getBoundingClientRect();
      return r.width > 1 && r.height > 1;
    });
    for (let i = 0; i < kids.length; i++) {
      for (let j = i + 1; j < kids.length; j++) {
        const a = kids[i].getBoundingClientRect();
        const b = kids[j].getBoundingClientRect();
        const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ox > 2 && oy > 2) {
          const key = name(kids[i]) + '|' + name(kids[j]);
          if (seen.has(key)) continue;
          seen.add(key);
          out.overlap.push({
            a: name(kids[i]), b: name(kids[j]),
            ox: Math.round(ox), oy: Math.round(oy),
            in: name(parent),
          });
        }
      }
    }
  });

  /* ---------- 1b. 跨层级压盖：结论条 / 口径注行 vs 最后一条讯息 ----------
     上面第 1 项只在**同一个父节点**下两两求交。.strip 与 .items 是 .page 的
     兄弟子元素，.strip 与最后一条 .item 更不是兄弟 —— 所以「结论条压住
     最后一条讯息」这种事故，第 1 项永远抓不到。
     2026-10-22 实测就中招了：结论条与最后一条白色卡片重叠 26–28px，
     肉眼能看见文字被压掉半行，体检却全绿。
     这里补一条纵向序列检查：.items 内最后一条 .item 的底边，
     必须落在 .strip 顶边之上。 */
  const itemsBox = page && page.querySelector('.items');
  const stripBox = page && page.querySelector('.strip');
  if (itemsBox && stripBox) {
    const itemEls = [...itemsBox.querySelectorAll(':scope > .item')];
    if (itemEls.length) {
      const last = itemEls[itemEls.length - 1].getBoundingClientRect();
      const st = stripBox.getBoundingClientRect();
      const gap = Math.round(st.top - last.bottom);
      if (gap < 0) {
        out.overlap.push({
          a: 'div.item(最后一条)', b: 'div.strip', ox: 0, oy: -gap, in: 'div.page',
        });
      } else if (gap < 12) {
        out.whitespace.push({
          target: 'item→strip 间距', h: gap, fill: +(gap / 18).toFixed(2),
        });
      }
    }
  }

  /* ---------- 2. 留白：视觉件列内部被子元素吃掉的比例 ---------- */
  page.querySelectorAll('.it-r').forEach((vbox) => {
    const br = vbox.getBoundingClientRect();
    if (area(br) < 1000) return;
    const target = vbox.querySelector('.mn, .grid') || vbox;
    const tr = target.getBoundingClientRect();
    const kids = [...target.children];
    if (!kids.length) return;
    // 纵向覆盖法：判断「有没有哪一段纵向空间是空的」，而不是「子元素面积占比」。
    // 面积法对细长元素无效 —— 一条 3px 宽的连接线铺满 200px 高，面积占比只有 3%，
    // 但它恰恰是那个把空白填满的东西。2026-10-22 04 卡的 steps 就是这么被误判成
    // 「内部只填了 33%」的。所以这里先按 flex 主轴方向分流：
    //   纵向排布 → 量「子元素纵向区间的并集」占总高的比例
    //   横向排布 → 才退回面积法
    const dir = getComputedStyle(target).flexDirection;
    let ratio;
    if (dir === 'column' || dir === 'column-reverse') {
      const top = tr.top, bottom = tr.bottom;
      const spans = kids
        .map((k) => k.getBoundingClientRect())
        .filter((r) => r.height > 0)
        .map((r) => [Math.max(top, r.top), Math.min(bottom, r.bottom)])
        .filter(([a, b]) => b > a)
        .sort((a, b) => a[0] - b[0]);
      let covered = 0, cursor = top;
      for (const [a, b] of spans) {
        if (b <= cursor) continue;          // 整段已被前面的区间盖住，跳过
        covered += b - Math.max(a, cursor); // 只累加露出来的那一截
        cursor = b;
      }
      ratio = covered / Math.max(1, bottom - top);
    } else {
      let filled = 0;
      kids.forEach((k) => { filled += area(k.getBoundingClientRect()); });
      ratio = filled / area(tr);
    }
    const info = { target: name(target), h: Math.round(tr.height), fill: +ratio.toFixed(2) };
    // —— steps 视觉件豁免留白判定 ——
    // 2026-10-22 胡子哥要求：「这样的排版要杜绝，中间太空，顶底压边。
    // 可以调整到居中，上下留空。」所以 steps 现在是**故意**上下留空的：
    // 节点组垂直居中、连接线固定 32px，容器再高也不会被填满。
    // 它的填充率天然低（实测 46%），这不是留白病，正是要的效果 —— 必须豁免，
    // 否则每天都会报一条「留白过多」，久了就没人看体检报告了。
    if (!target.classList.contains('mn-steps')) out.whitespace.push(info);
  });

  /* ---------- 3. 截断 / 4. 小字 / 5. 对比度 ---------- */
  const sizes = {};

  /* ---------- 2.5 网格行内重叠 ----------
   * 指标网格用 grid-auto-rows:1fr 平分高度。一旦容器比「行数 × 行内容高」矮，
   * 每行就被压到内容以下，数值行会直接压在名称行上 —— 文字互相叠着，
   * 但每一条文字自己都没超出父容器，所以第 3 项「截断」抓不到。
   * 判据：格子 scrollHeight 明显超过自身高度。
   */
  document.querySelectorAll('.gc, .mx-row, .ms-node, .rs-row, .mb-row').forEach((el) => {
    const h = el.getBoundingClientRect().height;
    if (h <= 0) return;
    const over = el.scrollHeight - el.clientHeight;
    if (over > 3) {
      out.overlap.push({
        a: name(el), b: name(el.firstElementChild) || '自身',
        ox: 0, oy: over, in: name(el.parentElement),
      });
    }
  });

  document.querySelectorAll('.page *').forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!hasText) return;

    // 省略号截断：nowrap + text-overflow:ellipsis 时，超出部分会被直接吃掉，
    // 图上表现为「字被腰斩看不到」——比溢出还容易被忽略，因为它不报错、不留痕
    if (cs.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1) {
      out.ellipsis.push({
        el: name(el), need: el.scrollWidth, have: el.clientWidth,
        text: (el.textContent || '').trim().slice(0, 18),
      });
    }

    // 截断：只有当某个祖先真的会裁剪时才算。
    // 只对比 scrollWidth/clientWidth 会把「82px 数字配 line-height 1.02」这种正常溢出行盒误报成截断
    const clipper = (() => {
      let n = el.parentElement;
      while (n && n !== document.body) {
        const o = getComputedStyle(n).overflow;
        if (o && o !== 'visible') return n;
        n = n.parentElement;
      }
      return null;
    })();
    if (clipper) {
      const cr = clipper.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      const dx = Math.max(0, er.right - cr.right, cr.left - er.left);
      const dy = Math.max(0, er.bottom - cr.bottom, cr.top - er.top);
      if (dx > 2 || dy > 2) {
        out.clipped.push({ el: name(el), by: name(clipper), dx: Math.round(dx), dy: Math.round(dy) });
      }
    }

    const fs = parseFloat(cs.fontSize);
    if (fs) {
      const key = String(Math.round(fs));
      sizes[key] = (sizes[key] || 0) + 1;
      if (fs < 22) {
        out.tiny.push({ el: name(el), fs: Math.round(fs), text: (el.textContent || '').trim().slice(0, 18) });
      }
      // 对比度
      const fg = parseColor(cs.color);
      if (fg) {
        const bg = effectiveBg(el);
        const ratio = contrast(over(fg, bg), bg);
        const bold = parseInt(cs.fontWeight, 10) >= 700;
        const large = fs >= 32 && bold;
        const need = large ? 3.0 : 4.5;
        if (ratio < need) {
          out.contrast.push({
            el: name(el), fs: Math.round(fs), ratio: +ratio.toFixed(2), need,
            text: (el.textContent || '').trim().slice(0, 18),
          });
        }
      }
    }
  });
  out.sizes = sizes;

  /* ---------- 7. 信息重复：文字区把视觉件里的数字又说一遍 ----------
     导语复述视觉块是可接受的（导语就是摘要）；但正文再复述一遍，等于白占 60 字，
     读者读到的是同���件事的第二遍。01 号卡折线 + 三格数字板曾是这个毛病。
     新结构里要查两处：卡级结论条 .strip，以及条目自己的 .it-desc 相对同条 .it-r。 */
  const numTokens = (root) => {
    const seen = new Set();
    root.querySelectorAll('*').forEach((el) => {
      if (el.children.length) return;              // 只取叶子，避免整块文本重复计数
      const toks = (el.textContent || '').match(/\d[\d,]*\.?\d*%?/g) || [];
      toks.forEach((t) => {
        const n = t.replace(/[,\s]/g, '');
        const digits = n.replace(/[^\d]/g, '');
        if (digits.length < 3) return;             // 跳过 1–2 位数
        if (/^(19|20)\d{2}$/.test(digits)) return;  // 年份不是数据，别报
        seen.add(n);
      });
    });
    return seen;
  };
  const norm = (s) => s.replace(/[,\s]/g, '');

  const stripEl = document.querySelector('.strip');
  if (stripEl) {
    const stripTxt = norm(stripEl.textContent);
    const seen = new Set();
    document.querySelectorAll('.it-r').forEach((v) => {
      numTokens(v).forEach((n) => seen.add(n));
    });
    const dup = [...seen].filter((n) => stripTxt.includes(n));
    if (dup.length) out.dupnum = dup.slice(0, 4);
  }

  // 同一条目内：描述句/正文段落复述了同一视觉件里的数字
  // 2026-10-22：正文段落层（.it-prose）纳入检查 —— 连续文字段落最容易
  // 把视觉件上的大数字再抄一遍，等于白占一整行。
  const itemDup = [];
  document.querySelectorAll('.item').forEach((it) => {
    const d = it.querySelector('.it-desc') || it.querySelector('.it-prose');
    const v = it.querySelector('.it-r');
    if (!d || !v) return;
    const dt = norm(d.textContent);
    numTokens(v).forEach((n) => {
      if (dt.includes(n)) itemDup.push(n);
    });
  });
  if (itemDup.length) out.dupitem = [...new Set(itemDup)].slice(0, 4);

  /* ---------- 8. 溢出：视觉件内容顶出容器 ----------
     flex + 高度链最容易在这里翻车（子块算得 0 高、绝对定位的 SVG 画到外面）。
     视觉上表现为「数字被边框切掉」「图形画到卡片外」，是本流水线最常见的版面事故。 */
  const spill = [];
  const spillSeen = new Set();
  document.querySelectorAll('.it-r, .it-l, .item').forEach((box) => {
    const q = box.getBoundingClientRect();
    let maxB = 0, maxR = 0, culprit = null;
    box.querySelectorAll('*').forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.height <= 0 || b.width <= 0) return;
      const ob = b.bottom - q.bottom, orr = b.right - q.right;
      if (ob > maxB) { maxB = ob; culprit = el; }
      if (orr > maxR) { maxR = orr; if (!culprit) culprit = el; }
    });
    const over = Math.max(maxB, maxR);
    if (over > 2) {
      const key = name(box) + '|' + name(culprit);
      if (spillSeen.has(key)) return;
      spillSeen.add(key);
      spill.push({ box: name(box), by: name(culprit), over: Math.round(over) });
    }
  });
  // 正文页整体超框
  const pg = page ? page.getBoundingClientRect() : null;
  if (pg) {
    let over = 0, who = null;
    page.querySelectorAll('*').forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.height <= 0) return;
      const o = Math.max(b.bottom - pg.bottom, b.right - pg.right);
      if (o > over) { over = o; who = el; }
    });
    if (over > 2) spill.push({ box: 'div.page', by: name(who), over: Math.round(over) });
  }
  out.spill = spill;

  return out;
};

async function auditPage(browser, htmlPath) {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1500 } });
  await page.goto('file://' + htmlPath, { waitUntil: 'networkidle' });
  await page.waitForTimeout(350);
  const r = await page.evaluate(AUDIT);
  await page.close();
  return r;
}

function report(file, r) {
  const lines = [];
  let blocks = 0;
  const say = (lv, msg) => { if (lv === 'B') blocks++; lines.push(`    [${lv}] ${msg}`); };

  if (r.geom.w && (r.geom.w !== 1080 || r.geom.h !== 1440)) say('B', `正文页 ${r.geom.w}x${r.geom.h}`);
  if (r.geom.visualRatio !== undefined) {
    const pct = (r.geom.visualRatio * 100).toFixed(0);
    if (r.geom.visualRatio < 0.5) say('W', `图文比偏低：视觉块只占正文页 ${pct}%`);
    else lines.push(`    ·  图文比 ${pct}%`);
  }
  if (r.overlap.length) r.overlap.forEach((o) => say('B', `遮挡 ${o.a} × ${o.b} 重叠 ${o.ox}×${o.oy}px（在 ${o.in} 里）`));
  const ws = r.whitespace;
  if (ws.length) {
    const worst = ws.reduce((a, b) => (a.fill < b.fill ? a : b));
    const avg = ws.reduce((s, w) => s + w.fill, 0) / ws.length;
    const pct = (x) => (x * 100).toFixed(0) + '%';
    if (worst.fill < 0.62 && worst.h > 300) {
      say('W', `留白过多 ${worst.target} 高 ${worst.h}px，内部只填了 ${pct(worst.fill)}`);
    } else {
      lines.push(`    ·  视觉块内部填充 平均 ${pct(avg)}，最低 ${pct(worst.fill)}（${worst.target}）`);
    }
  }
  if (r.ellipsis.length) r.ellipsis.forEach((c) => say('B', `文字被吃掉 ${c.el} 需 ${c.need}px 只有 ${c.have}px「${c.text}」`));
  if (r.clipped.length) r.clipped.forEach((c) => say('B', `截断 ${c.el} 被 ${c.by} 切掉 ${c.dx}×${c.dy}px`));
  if (r.tiny.length) {
    const uniq = [...new Map(r.tiny.map((t) => [t.el + t.fs, t])).values()];
    uniq.slice(0, 6).forEach((t) => say('W', `小字 ${t.fs}px（手机约 ${(t.fs * 0.36).toFixed(1)}pt） ${t.el}「${t.text}」`));
  }
  if (r.contrast.length) {
    const uniq = [...new Map(r.contrast.map((t) => [t.el + t.fs, t])).values()];
    uniq.slice(0, 6).forEach((t) => say('W', `对比度不足 ${t.ratio}:1（需 ${t.need}） ${t.el}「${t.text}」`));
  }
  if (r.dupnum) r.dupnum.forEach((n) => say('W', `信息重复：视觉件报 ${n}，结论条又说了一遍——结论条该写「所以呢」`));
  if (r.dupitem) r.dupitem.forEach((n) => say('W', `信息重复：同一条目的解释句复述了视觉件里的 ${n}`));
  if (r.spill && r.spill.length) {
    r.spill.forEach((s) => say('B', `溢出 ${s.box} 里的 ${s.by} 顶出 ${s.over}px`));
  }
  const sz = Object.keys(r.sizes).map(Number).sort((a, b) => b - a);
  lines.push(`    ·  字号分布 ${sz.join(' / ')}px`);

  const flag = blocks ? '❌' : lines.some((l) => l.includes('[W]')) ? '⚠️ ' : '✔ ';
  console.log(`${flag} ${path.basename(file)}`);
  console.log(lines.join('\n'));
  return blocks;
}

(async () => {
  const target = path.resolve(process.argv[2] || 'cards');
  if (!fs.existsSync(target)) { console.error('❌ 找不到:', target); process.exit(1); }
  const files = fs.statSync(target).isDirectory()
    ? fs.readdirSync(target).filter((f) => /^card-.*\.html$/.test(f)).sort().map((f) => path.join(target, f))
    : [target];

  const browser = await chromium.launch();
  let blocks = 0;
  for (const f of files) blocks += await report(f, await auditPage(browser, f));
  await browser.close();

  console.log(`\n共 ${files.length} 张，阻断级问题 ${blocks} 处`);
  console.log('图例  ❌ 必须修   ⚠️  建议修   ✔ 通过');
  process.exit(blocks ? 1 : 0);
})();
