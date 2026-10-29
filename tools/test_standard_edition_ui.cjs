/* Focused browser checks using Node to avoid Windows asyncio socketpair setup. */
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
async function main() {
  const data = JSON.parse(fs.readFileSync(path.join(root, 'data/cases.json'), 'utf8'));
  const base = data.cases.find(c => c.page === 'std-constitution');
  data.cases = [[3, '2000-01-01', false], [1, '2020-01-01', true], [2, '2010-01-01', false]].map(([order, date, removed], i) => ({
    ...structuredClone(base), id: `fixture-${i}`, decisionId: `fixture-decision-${i}`,
    title: `테스트 판례 ${i}`, decisionDate: date, standard: {order, removed},
    facts: [{n: '', text: '사실관계 테스트 원문'}],
    fieldSources: {facts: {type: 'standard', sources: [{format: 'xlsx', book: '표준판례', edition: '2026', sheet: '행정법', rows: [9, 10]}]}}
  }));
  data.cases.push({...structuredClone(data.cases[1]), id: 'fixture-research', page: 'research-criminal', title: '연구 제목', standard: {removed: true}, research: {order: 1}});
  let html = fs.readFileSync(path.join(root, 'src/design-d.html'), 'utf8');
  const appScript = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(x => x[1]).find(x => x.includes('function caseHTML'));
  new vm.Script(appScript);
  const extract = name => appScript.match(new RegExp('^function ' + name + '\\([^]*?^}', 'm'))[0];
  const declarations = ['standardRemoved', 'caseTitle'].map(name => appScript.match(new RegExp('^const ' + name + ' = [^\\n]+', 'm'))[0]);
  const context = vm.createContext({
    S: {standardSort: 'source', bookmarks: new Set(), tab: 1},
    pageOf: page => ({group: page.startsWith('std-') ? 'standard' : 'research', label: '과목'}),
    esc: value => String(value || ''), sec: (n, heading, body) => `<h3>${heading}</h3>${body}`,
    itemsHTML: rows => (rows || []).map(x => x.text).join('\n'), srcHTML: () => '',
    hasToc: () => false, subjLabel: () => '헌법', recordKey: c => c.decisionId,
    courtIcon: () => '', standardBadge: () => '', tabHTML: () => '', caseNavHTML: () => '',
  });
  vm.runInContext([...declarations, ...['compareStandardCases', 'fieldSourceHTML', 'summaryHTML', 'caseHTML'].map(extract)].join('\n'), context);
  const rows = data.cases.slice(0, 3);
  for (const [mode, expected] of [['source', [1, 2, 0]], ['date-asc', [0, 2, 1]], ['date-desc', [1, 2, 0]]]) {
    context.S.standardSort = mode;
    assert.deepEqual(rows.slice().sort(context.compareStandardCases).map(x => x.id), expected.map(i => `fixture-${i}`));
  }
  context.item = rows[1];
  assert.equal(vm.runInContext('caseTitle(item)', context), '테스트 판례 1*');
  assert(context.caseHTML(rows[1]).includes('이 판례는 개정판에는 삭제되었음.</p>\n    <div class="tabs"'));
  assert(!context.caseHTML(rows[0]).includes('standard-removed'));
  assert(!context.caseHTML(data.cases[3]).includes('standard-removed'));
  assert(context.summaryHTML(rows[1]).includes('사실관계의 요지'));
  assert(context.fieldSourceHTML(rows[1], 'facts').includes('행정법 · 9, 10행'));
  const personal = require(path.join(root, 'src/personal-data.js'));
  const migrated = personal.normalize({bookmarks: ['old'], notes: {old: '이전 메모', canonical: '새 메모'}}, [{id: 'placement', decisionId: 'canonical', legacyIds: ['old']}]);
  assert.deepEqual(migrated.bookmarks, ['canonical']);
  assert(migrated.notes.canonical.includes('이전 메모') && migrated.notes.canonical.includes('새 메모'));
  console.log('PASS actual template JS syntax, 3 sorting modes, scoped removal title/notice, facts, source rows, alias note preservation');
  if (process.argv.includes('--logic-only')) return;
  for (const [marker, file] of [['__DATA_PROVIDER_JS__', 'data-provider.js'], ['__PERSONAL_DATA_JS__', 'personal-data.js']]) {
    html = html.replace(marker, () => fs.readFileSync(path.join(root, 'src', file), 'utf8').replaceAll('</script', '<\\/script'));
  }
  html = html.replace('__CASE_DATA_JSON__', () => JSON.stringify(data).replaceAll('</', '<\\/')).replace('__LAWS_DATA_B64__', '');
  const fixture = path.join(root, 'output/tmp-2026/ui-fixture.html');
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
      await page.goto(url + '#/std-constitution'); await page.waitForSelector('[data-standard-sort]');
      const ids = () => page.locator('#col .entry').evaluateAll(els => els.map(e => e.dataset.id));
      assert.deepEqual(await ids(), ['fixture-1', 'fixture-2', 'fixture-0']);
      await page.locator('#col [data-list-open=false]').click();
      await page.locator('#col [data-standard-sort]').selectOption('date-asc');
      assert.deepEqual(await ids(), ['fixture-0', 'fixture-2', 'fixture-1']);
      assert.equal(await page.locator('#col details[open]').count(), 0);
      await page.locator('#col [data-standard-sort]').selectOption('date-desc');
      assert.deepEqual(await ids(), ['fixture-1', 'fixture-2', 'fixture-0']);
      await page.reload(); await page.waitForSelector('[data-standard-sort]');
      assert.equal(await page.locator('#col [data-standard-sort]').inputValue(), 'date-desc');
      await page.goto(url + '#/std-constitution/fixture-1'); await page.waitForSelector('.standard-removed');
      assert.equal(await page.locator('.case h1').innerText(), '테스트 판례 1*');
      assert.equal(await page.locator('.standard-removed').innerText(), '이 판례는 개정판에는 삭제되었음.');
      assert(await page.locator('.standard-removed').evaluate(e => e.nextElementSibling.classList.contains('tabs')));
      assert.equal(await page.locator('.standard-removed').evaluate(e => getComputedStyle(e).fontSize), await page.locator('[data-tab="1"]').evaluate(e => getComputedStyle(e).fontSize));
      assert((await page.locator('#tabpanel').innerText()).includes('사실관계의 요지'));
      assert((await page.locator('#tabpanel').innerText()).includes('행정법 · 9, 10행'));
      await page.goto(url + '#/std-constitution/fixture-0'); await page.waitForFunction(() => document.querySelector('.case h1')?.textContent === '테스트 판례 0');
      assert.equal(await page.locator('.standard-removed').count(), 0);
      await page.goto(url + '#/research-criminal/fixture-research'); await page.waitForFunction(() => document.querySelector('.case h1')?.textContent === '연구 제목');
      assert.equal(await page.locator('.standard-removed').count(), 0);
      assert.equal(await page.locator('#col [data-standard-sort]').count(), 0);
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));
      assert.deepEqual(errors, []);
      await page.close();
      console.log(`PASS ${width}px: sort, persistence, collapsed state, removal scope, facts, source rows, overflow, JS errors`);
    }
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
