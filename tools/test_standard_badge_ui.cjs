/* 표준판례 배지 링크·페이지별 출처 표시 검사 (Node + Playwright; test_standard_edition_ui.cjs 와 같은 방식).
   헌법재판소 주요결정 상세창의 "표준판례" 배지는 표준판례 페이지의 그 재판 상세창(#/std-<과목>/<id>)으로 가는 링크여야 하고,
   배치가 여럿이면 ① ② … 로 모두 고를 수 있어야 하며, 키보드와 북마크 뷰에서도 동작해야 한다. */
const fs = require('node:fs'), path = require('node:path');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {pathToFileURL} = require('node:url'), {spawnSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
let playwright;
try { playwright = require('playwright'); }
catch {
  const result = spawnSync(process.env.CASEBOOK_PYTHON || 'python', ['-c', 'import pathlib,playwright;print(pathlib.Path(playwright.__file__).parent / "driver" / "package")'], {encoding: 'utf8', timeout: 15000});
  if (result.status !== 0) throw new Error(result.stderr || 'Playwright package unavailable');
  playwright = require(result.stdout.trim());
}
function fixtures(data) {
  const std = data.cases.find(c => c.page === 'std-constitution' && c.summaryType === 'standard' && (c.issues || []).length && (c.tocPath || []).length);
  const cc = data.cases.find(c => c.page === 'ccourt' && c.summaryType === 'official' && (c.issues || []).length);
  assert(std && cc, 'fixture sources missing in data/cases.json');
  const strip = c => { const x = structuredClone(c); delete x.fullText; delete x.fullTextRef; return x; };
  const placements = [0, 1].map(i => ({id: `fixture-std-${i}`, page: 'std-constitution', subject: 'constitution', title: `표준판례 배치 ${'①②'[i]}`, tocPath: std.tocPath}));
  const stds = placements.map((p, i) => ({...strip(std), id: p.id, decisionId: 'fixture-decision', title: p.title, standard: {order: i + 1}}));
  const ccFix = {...strip(cc), id: 'fixture-cc', decisionId: 'fixture-decision-cc', title: '헌법재판소 배치', isStandard: true, standardPlacements: placements,
    summaryType: 'official', summaryPrecedence: ['official', 'standard', 'editorial'],
    fieldSources: {...cc.fieldSources, issues: {type: 'official', label: '국가법령정보센터', url: ''}, holdings: {type: 'official', label: '국가법령정보센터', url: ''}}};
  const edFix = {...strip(cc), id: 'fixture-ed', decisionId: 'fixture-decision-ed', title: '편집 요약 배치', isStandard: false, summaryType: 'editorial',
    summaryPrecedence: ['official', 'standard', 'editorial'], issues: [{n: '1.', text: '편집 쟁점인지 여부(적극)'}], holdings: [{n: '1.', text: '편집 요지'}],
    fieldSources: {issues: {type: 'editorial', label: '편집 요약', basis: {label: '헌법재판소 최근 주요결정 게시물', url: 'https://www.ccourt.go.kr/site/kor/ex/bbs/View.do?cbIdx=1195&bcIdx=1'}},
      holdings: {type: 'editorial', label: '편집 요약', basis: {label: '헌법재판소 최근 주요결정 게시물', url: 'https://www.ccourt.go.kr/site/kor/ex/bbs/View.do?cbIdx=1195&bcIdx=1'}},
      facts: {type: 'missing'}, statutes: {type: 'missing'}, precedents: {type: 'missing'}, subjectStatutes: {type: 'missing'}}};
  delete edFix.standardPlacements;
  return [...stds, ccFix, edFix];
}
async function main() {
  const data = JSON.parse(fs.readFileSync(path.join(root, 'data/cases.json'), 'utf8'));
  data.cases = fixtures(data);
  let html = fs.readFileSync(path.join(root, 'src/design-d.html'), 'utf8');
  const appScript = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(x => x[1]).find(x => x.includes('function caseHTML'));
  new vm.Script(appScript);
  const extract = name => appScript.match(new RegExp('^function ' + name + '\\([^]*?^}', 'm'))[0];
  const declaration = name => appScript.match(new RegExp('^const ' + name + ' = (?:[^\\n]*\\{\\r?\\n[^]*?^\\};|[^\\n]+)', 'm'))[0];   // 한 줄 또는 `=> {` … `};` 블록(CRLF 허용)
  const context = vm.createContext({
    S: {view: 'page', bookmarks: new Set(), tab: 1},
    pageOf: page => ({group: page.startsWith('std-') ? 'standard' : page, label: page === 'std-constitution' ? '헌법 표준판례' : '헌법재판소 주요결정'}),
    esc: value => String(value == null ? '' : value).replace(/[&<>"']/g, m => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[m])),
    tocLabels: () => ['제1편', '기본권'],
  });
  vm.runInContext(['STANDARD_BADGE_GROUPS', 'standardPlacements', 'circled', 'standardPlacementPath', 'standardBadge'].map(declaration).concat([extract('standardNoteHTML'), extract('fieldSourceHTML')]).join('\n'), context);
  for (const name of ['standardPlacements', 'standardPlacementPath', 'standardBadge']) vm.runInContext(`globalThis.${name} = ${name}`, context);   // const 선언은 전역 객체에 오르지 않는다
  const [std0, , ccFix, edFix] = data.cases;
  assert.equal(context.standardBadge(ccFix), '<span class="badge standard">표준판례</span>');
  const linked = context.standardBadge(ccFix, true);
  assert(linked.startsWith('<a class="badge standard" href="#/std-constitution/fixture-std-0"'));
  assert(linked.includes('>표준판례 ①</a><a class="badge standard" href="#/std-constitution/fixture-std-1"') && linked.endsWith('>②</a>'));
  assert(linked.includes('title="표준판례 수록본 보기: 헌법 표준판례 › 제1편 › 기본권 › 표준판례 배치 ①"'));
  assert(linked.includes('aria-label="표준판례 수록본 2/2 보기:'));
  assert.equal(context.standardBadge({...ccFix, standardPlacements: ccFix.standardPlacements.slice(0, 1)}, true).match(/>([^<]*)<\/a>/)[1], '표준판례');
  assert.equal(context.standardBadge(std0, true), '');
  assert.equal(context.standardBadge({...ccFix, isStandard: false}, true), '');
  assert(context.standardNoteHTML(ccFix).includes('href="#/std-constitution/fixture-std-1"'));
  assert.equal(context.standardNoteHTML({...ccFix, summaryType: 'standard'}), '');
  assert.equal(context.standardNoteHTML(edFix), '');
  assert.equal(context.fieldSourceHTML(ccFix, 'issues'), '<p class="note">출처: 국가법령정보센터 공식 수록본</p>');
  assert(context.fieldSourceHTML(edFix, 'issues').includes('근거: <a href="https://www.ccourt.go.kr/site/kor/ex/bbs/View.do?cbIdx=1195&amp;bcIdx=1" target="_blank" rel="noopener">헌법재판소 최근 주요결정 게시물</a>'));
  assert.equal(context.fieldSourceHTML({...edFix, fieldSources: {issues: {type: 'editorial', label: '편집 요약'}}}, 'issues'), '<p class="note">※ 편집 요약 — 원출처의 판시사항·요지가 아닙니다.</p>');
  assert.equal(context.fieldSourceHTML({fieldSources: {issues: {type: 'supplemental', label: '케이스노트 수록본 · 사용자 제공'}}}, 'issues'), '<p class="note">출처: 케이스노트 수록본 · 사용자 제공</p>');
  console.log('PASS template JS syntax, badge span/link, multi-placement labels, tooltip path, note and editorial basis');
  if (process.argv.includes('--logic-only')) return;
  for (const [marker, file] of [['__DATA_PROVIDER_JS__', 'data-provider.js'], ['__PERSONAL_DATA_JS__', 'personal-data.js']]) {
    html = html.replace(marker, () => fs.readFileSync(path.join(root, 'src', file), 'utf8').replaceAll('</script', '<\\/script'));
  }
  html = html.replace('__CASE_DATA_JSON__', () => JSON.stringify(data).replaceAll('</', '<\\/')).replace('__LAWS_DATA_B64__', '');
  const fixture = path.join(root, 'output/tmp-2026/badge-fixture.html');
  fs.mkdirSync(path.dirname(fixture), {recursive: true}); fs.writeFileSync(fixture, html);
  let browser;
  const options = {headless: true, timeout: 30000};
  if (process.env.CASEBOOK_BROWSER_CHANNEL) options.channel = process.env.CASEBOOK_BROWSER_CHANNEL;
  try { browser = await playwright.chromium.launch(options); }
  catch (error) {
    if (!String(error).includes("Executable doesn't exist")) throw error;
    const edge = [process.env['ProgramFiles(x86)'], process.env.ProgramFiles, process.env.LOCALAPPDATA].filter(Boolean).map(base => path.join(base, 'Microsoft/Edge/Application/msedge.exe')).find(p => fs.existsSync(p));
    if (!edge) throw error;
    browser = await playwright.chromium.launch({...options, executablePath: edge});
  }
  try {
    for (const width of [390, 1440]) {
      const page = await browser.newPage({viewport: {width, height: 900}}); page.setDefaultTimeout(10000);
      const errors = []; page.on('pageerror', e => errors.push(String(e)));
      await page.route('https://fonts.googleapis.com/**', route => route.abort());
      const url = pathToFileURL(fixture).href;
      const title = () => page.locator('.case h1').innerText();
      const waitTitle = t => page.waitForFunction(x => document.querySelector('.case h1')?.textContent === x, t);
      await page.goto(url + '#/ccourt/fixture-cc'); await waitTitle('헌법재판소 배치');
      const badges = page.locator('.cite-sub a.badge.standard');
      assert.equal(await badges.count(), 2);
      assert.deepEqual(await badges.evaluateAll(els => els.map(e => [e.textContent, e.getAttribute('href')])),
        [['표준판례 ①', '#/std-constitution/fixture-std-0'], ['②', '#/std-constitution/fixture-std-1']]);
      assert((await badges.first().getAttribute('title')).startsWith('표준판례 수록본 보기: 헌법 표준판례 › '));
      let panel = await page.locator('#tabpanel').innerText();
      assert(panel.includes('출처: 국가법령정보센터 공식 수록본') && panel.includes('표준판례에도 수록되어 있습니다') && panel.includes('표준판례 배치 ②'));
      assert(!panel.includes('표준판례 수록본 우선'));
      await badges.first().click(); await waitTitle('표준판례 배치 ①');
      assert.equal(await page.evaluate(() => location.hash), '#/std-constitution/fixture-std-0');
      assert.equal(await page.locator('.cite-sub a.badge.standard').count(), 0);
      assert((await page.locator('#tabpanel').innerText()).includes('표준판례 수록본 우선'));
      await page.goto(url + '#/ccourt/fixture-cc'); await waitTitle('헌법재판소 배치');
      await page.locator('.cite-sub a.badge.standard').nth(1).focus(); await page.keyboard.press('Enter'); await waitTitle('표준판례 배치 ②');
      assert.equal(await page.evaluate(() => location.hash), '#/std-constitution/fixture-std-1');
      await page.evaluate(() => localStorage.setItem('lawbook:bookmarks', JSON.stringify(['fixture-decision-cc'])));
      await page.goto(url + '#/bookmarks/fixture-cc'); await page.reload(); await waitTitle('헌법재판소 배치');
      assert.equal(await page.locator('#col .entry a.badge.standard, #col .entry span.badge.standard').count(), 1);
      assert.equal(await page.locator('#col .entry a.badge.standard').count(), 0);   // 목록 항목(링크 안)에서는 표식만
      await page.locator('.cite-sub a.badge.standard').first().click(); await waitTitle('표준판례 배치 ①');
      assert.equal(await page.evaluate(() => location.hash), '#/std-constitution/fixture-std-0');
      await page.goto(url + '#/ccourt/fixture-ed'); await waitTitle('편집 요약 배치');
      assert.equal(await page.locator('.cite-sub .badge.standard').count(), 0);
      panel = await page.locator('#tabpanel').innerText();
      assert(panel.includes('※ 편집 요약') && panel.includes('근거: 헌법재판소 최근 주요결정 게시물'));
      assert.equal(await page.locator('#tabpanel .note a[href^="https://www.ccourt.go.kr/"]').count(), 2);
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS ${width}px: badge links, click/keyboard navigation, bookmarks view, editorial basis, overflow, JS errors`);
    }
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
