/**
 * render.cjs —— 批量把卡片 HTML 截图成 PNG
 *
 * 用法:
 *   node render.cjs <目录>              // 截 card-*.html → card-*.png
 *   node render.cjs <a.html> [out.png]  // 单文件模式
 *
 * 规格: 1080 CSS 宽、deviceScaleFactor=2（导出 2160px）、fullPage
 * 额外检查: 正文页 .page 是否为 1080x1440，溢出会报警
 */

const path = require('path');
const fs = require('fs');
const os = require('os');

/** 依次尝试多个位置加载 playwright，避免 NODE_PATH 未设置时找不到 */
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
    try {
      return require(c);
    } catch (e) {
      /* try next */
    }
  }
  console.error('❌ 未找到 playwright。请先安装：');
  console.error('   cd ~ && npm i playwright && npx playwright install chromium');
  process.exit(1);
}

const { chromium } = loadPlaywright();

async function shoot(browser, htmlPath, pngPath) {
  const page = await browser.newPage({
    viewport: { width: 1080, height: 1400 },
    deviceScaleFactor: 2,
  });
  await page.goto('file://' + htmlPath, { waitUntil: 'networkidle' });
  await page.waitForTimeout(450);

  const diag = await page.evaluate(() => {
    const p = document.querySelector('.page');
    if (!p) return null;
    const pr = p.getBoundingClientRect();
    // 找出最深的内容底边（含被 flex 压缩后溢出的子元素）
    let maxBottom = 0;
    p.querySelectorAll('*').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.height > 0) maxBottom = Math.max(maxBottom, r.bottom - pr.top);
    });
    // 子元素越出父容器（多见于视觉件被压扁后内容溢出、压住说明行）
    // 注意：新结构的容器是 .it-r / .it-l（旧的 .vbox 已不存在）
    let spill = 0;
    p.querySelectorAll('.it-r, .it-l').forEach((box) => {
      box.querySelectorAll('*').forEach((el) => {
        const par = el.parentElement;
        if (!par) return;
        const r = el.getBoundingClientRect();
        const q = par.getBoundingClientRect();
        if (r.height > 0 && q.height > 0 && r.bottom > q.bottom + 2) spill++;
      });
    });
    // 主标题是否折行（nowrap 下若超宽会被容器裁切，用行数判定）
    let headLines = 0;
    p.querySelectorAll('.hl1').forEach((el) => {
      const lh = parseFloat(getComputedStyle(el).lineHeight) || 1;
      const rows = Math.round(el.getBoundingClientRect().height / lh);
      headLines = Math.max(headLines, rows);
      if (el.scrollWidth > el.clientWidth + 2) headLines = Math.max(headLines, 99);
    });
    return {
      w: Math.round(pr.width),
      h: Math.round(pr.height),
      contentH: Math.round(maxBottom),
      spill,
      headLines,
    };
  });

  await page.screenshot({ path: pngPath, fullPage: true });
  const full = await page.evaluate(() => document.querySelector('.card').getBoundingClientRect().height);
  await page.close();

  const kb = (fs.statSync(pngPath).size / 1024).toFixed(0);
  const issues = [];
  if (diag) {
    if (diag.w !== 1080 || diag.h !== 1440) {
      issues.push(`正文页 ${diag.w}x${diag.h}（应为 1080x1440）`);
    }
    if (diag.contentH > diag.h + 1) {
      issues.push(`内容超出 ${diag.contentH - diag.h}px`);
    }
    if (diag.spill > 0) {
      issues.push(`${diag.spill} 处子元素越出所在 visual 卡`);
    }
    if (diag.headLines > 1) {
      issues.push(`主标题折行 ${diag.headLines} 行`);
    }
  }
  const flag = issues.length ? `  ⚠️  ${issues.join(' / ')}` : '';
  console.log(`  ✔ ${path.basename(pngPath)}  ${kb}KB  (${1080}x${Math.round(full)} css)${flag}`);
  return issues;
}

async function main() {
  const target = process.argv[2];
  if (!target) {
    console.error('用法: node render.cjs <目录|html> [out.png]');
    process.exit(1);
  }
  const abs = path.resolve(target);
  if (!fs.existsSync(abs)) {
    console.error(`❌ 找不到: ${abs}`);
    process.exit(1);
  }

  const browser = await chromium.launch();
  let allIssues = [];

  if (fs.statSync(abs).isDirectory()) {
    const files = fs.readdirSync(abs).filter((f) => /^card-.*\.html$/.test(f)).sort();
    if (!files.length) {
      console.error('❌ 目录里没有 card-*.html');
      await browser.close();
      process.exit(1);
    }
    for (const f of files) {
      const htmlPath = path.join(abs, f);
      const pngPath = htmlPath.replace(/\.html$/, '.png');
      allIssues = allIssues.concat(await shoot(browser, htmlPath, pngPath));
    }
    console.log(`\n✅ 共导出 ${files.length} 张`);
  } else {
    const pngPath = process.argv[3] ? path.resolve(process.argv[3]) : abs.replace(/\.html?$/, '.png');
    allIssues = await shoot(browser, abs, pngPath);
  }

  await browser.close();
  if (allIssues.length) {
    console.log('\n⚠️  有版式问题需要修（见上）');
  }
}

main().catch((e) => {
  console.error('❌ 截图失败:', e.message);
  process.exit(1);
});
