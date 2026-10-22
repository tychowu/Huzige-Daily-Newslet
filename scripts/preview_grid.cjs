/**
 * preview_grid.cjs —— 生成「朋友圈四图」预览图
 *
 * 用法:
 *   node preview_grid.cjs cards/            // 读 card-01..04.png → grid-preview.png
 *   node preview_grid.cjs cards/ out.png
 *
 * 原理: 朋友圈 4 张图是 2×2 缩略图，每张只显示**中心 1:1**。
 *       用 CSS background-size:cover + center 在正方形容器里铺，
 *       当原图是 1080×1735 时，正好等价于裁出中心 1080×1080 的那一段。
 *       所以这张预览图 = 用户在朋友圈里真正看到的样子。
 *
 * 提醒: 朋友圈单图会显示顶部 banner 一部分、正文页中段、footer 被裁掉，
 *       这不是 bug。发布时如果需要 footer 完整可见，得用长图。
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
    try {
      return require(c);
    } catch (e) {
      /* next */
    }
  }
  console.error('❌ 未找到 playwright');
  process.exit(1);
}

const { chromium } = loadPlaywright();

const dir = path.resolve(process.argv[2] || 'cards');
const out = path.resolve(process.argv[3] || path.join(dir, 'grid-preview.png'));

const files = fs
  .readdirSync(dir)
  .filter((f) => /^card-\d+\.png$/.test(f))
  .sort()
  .slice(0, 4);

if (files.length < 4) {
  console.error(`❌ 需要 4 张 card-NN.png，当前只有 ${files.length} 张`);
  process.exit(1);
}

const COLS = 2;
const TILE = 460;
const GAP = 8;
const PAD = 14;

const tiles = files
  .map((f) => {
    // 必须内联成 data URI：setContent 的页面基址是 about:blank，
    // 直接用 file:// 会被安全策略拦掉，缩略图全是空白
    const b64 = fs.readFileSync(path.join(dir, f)).toString('base64');
    return `<div class="t" style="background-image:url('data:image/png;base64,${b64}')"></div>`;
  })
  .join('\n');

const rows = Math.ceil(files.length / COLS);
const W = TILE * COLS + GAP * (COLS - 1) + PAD * 2;

const html = `<!doctype html><meta charset="utf-8"><style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{width:${W}px;background:#EDEDED;
       padding:${PAD}px;font:400 13px/1.5 "PingFang SC",sans-serif;color:#666}
  .grid{display:grid;grid-template-columns:repeat(${COLS},${TILE}px);gap:${GAP}px}
  .t{width:${TILE}px;height:${TILE}px;background-size:cover;background-position:center;
     background-color:#fff;border-radius:3px}
  .cap{margin-top:12px;text-align:center;letter-spacing:.02em}
</style>
<div class="grid">${tiles}</div>
<div class="cap">朋友圈四图预览 · 每格只显示中心 1:1（footer 会被裁掉，属正常）</div>`;

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: W, height: TILE * rows + 200 }, deviceScaleFactor: 2 });
  await page.setContent(html, { waitUntil: 'networkidle' });
  await page.waitForTimeout(400);
  await page.screenshot({ path: out, fullPage: true });
  await browser.close();
  const kb = (fs.statSync(out).size / 1024).toFixed(0);
  console.log(`✔ ${path.basename(out)}  ${kb}KB  (${files.length} 格, ${COLS}×${rows})`);
})();
