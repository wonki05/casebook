#!/usr/bin/env python3
"""HTTP/PWA regression checks using isolated browser profiles at a project subpath.

Run after python tools/make.py validate data build web.
No source data or personal records outside temporary browser contexts change.
"""
from __future__ import annotations

import asyncio
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
from playwright.async_api import async_playwright
from browser_runtime import launch_chromium

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'output' / 'web'

def require(condition, message):
    if not condition:
        raise AssertionError(message)

def normalized(text):
    return re.sub(r'\s+', '', str(text).replace('【', '[').replace('】', ']')
                  .replace('〖', '[').replace('〗', ']'))

def read_verified(ref):
    path = (WEB / ref['url']).resolve()
    require(path.is_relative_to(WEB.resolve()), 'Data descriptor escaped web directory')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref['sha256'], f'Hash mismatch: {ref["url"]}')
    return json.loads(raw)

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

async def block_fonts(route):
    await route.fulfill(status=200, content_type='text/css', body='')

async def ready(page):
    await page.wait_for_selector('#pagetabs [data-go]', timeout=20000)
    require(not await page.locator('#bootError').count(), 'Reader failed to initialize')

async def open_case(page, item, canonical=False):
    identity = item['decisionId'] if canonical else item['id']
    await page.evaluate('(hash) => { location.hash = hash; }', f'#/{item["page"]}/{identity}')
    await page.wait_for_function(
        '(title) => document.querySelector("#cs").classList.contains("show") && document.querySelector(".case h1")?.textContent === title',
        arg=item['title'], timeout=10000)

async def check_fulltext(page, item, full):
    await page.locator('[data-tab="2"]').click()
    await page.wait_for_selector('#ft', timeout=15000)
    actual = normalized(await page.locator('#ft').inner_text())
    passage = next(normalized(block.get('text', '')) for block in full
                   if len(normalized(block.get('text', ''))) >= 80)[:80]
    require(passage in actual, f'Wrong or missing official text for {item["id"]}')

async def test_reader(browser, base, data, laws, item, full):
    context = await browser.new_context(viewport={'width': 1280, 'height': 900},
                                        accept_downloads=True, locale='ko-KR')
    await context.route('https://fonts.googleapis.com/**', block_fonts)
    await context.route('https://fonts.gstatic.com/**', block_fonts)
    page = await context.new_page()
    page_errors, console_errors, requests = [], [], []
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)
    page.on('request', lambda request: requests.append(request.url))
    legacy_note = '이전 HTML에서 작성한 메모'
    unknown_id = 'retained-unknown-decision'
    await context.add_init_script(script="""(() => {
      if (!localStorage.getItem('test:seeded')) {
        const seed = %s;
        localStorage.setItem('lawbook:notes', JSON.stringify(seed.notes));
        localStorage.setItem('lawbook:bookmarks', JSON.stringify(seed.bookmarks));
        localStorage.setItem('test:seeded', 'yes');
      }
    })();""" % json.dumps({'notes': {item['id']: legacy_note, unknown_id: '미분류 기록'},
                           'bookmarks': [item['id'], unknown_id]}, ensure_ascii=False))
    print('webcheck: loading reader', flush=True)
    await page.goto(base, wait_until='load')
    await ready(page)
    require(not any('/data/fulltext.' in url for url in requests), 'Initial page downloaded full text eagerly')
    require(not any('/data/laws.' in url for url in requests), 'Initial page downloaded all laws eagerly')
    require(await page.locator('.entry').count() > 0, 'Initial contents list is empty')
    require(await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Desktop overflow')
    await open_case(page, item)
    require(not any('/data/fulltext.' in url for url in requests), 'Summary opening downloaded full text')
    await page.evaluate('location.hash = "#/annual"')
    await page.wait_for_function('!document.querySelector("#cs").classList.contains("show")')
    await open_case(page, item, canonical=True)
    await check_fulltext(page, item, full)
    require(any('/data/fulltext.' in url for url in requests), 'Full text was not loaded on demand')

    (ROOT / 'shots').mkdir(exist_ok=True)
    await page.screenshot(path=str(ROOT / 'shots' / 'web-desktop.png'))
    print('webcheck: full text and routes OK', flush=True)
    await page.locator('[data-tab="4"]').click()
    require(await page.locator('#memo').input_value() == legacy_note, 'Legacy note migration lost its text')
    changed_note = legacy_note + '\n웹앱에서 추가한 기록'
    await page.locator('#memo').fill(changed_note)
    stored = await page.evaluate('JSON.parse(localStorage.getItem("lawbook:notes"))')
    require(stored.get(item['decisionId']) == changed_note, 'Notes are not keyed by stable decision ID')
    require(stored.get(unknown_id) == '미분류 기록', 'Unknown note was discarded')
    require(await page.locator('#btnBmCase').get_attribute('aria-pressed') == 'true', 'Legacy bookmark not restored')
    await page.locator('#btnCsClose').click()
    await page.wait_for_function('!document.querySelector("#cs").classList.contains("show")')
    await page.locator('#btnSet').click()
    async with page.expect_download() as download_info:
        await page.locator('[data-personal-export]').click()
    download = await download_info.value
    downloaded = await download.path()
    backup = json.loads(Path(downloaded).read_text(encoding='utf-8'))
    require(backup['format'] == 'lawbook-personal', 'Wrong backup format')
    require(backup['notes'][item['decisionId']] == changed_note, 'Export omitted latest note')
    require(unknown_id in backup['notes'], 'Export dropped unknown record')
    incoming = {'format': 'lawbook-personal', 'version': 1,
                'bookmarks': [item['id'], 'another-unknown-decision'],
                'notes': {item['id']: '가져온 서로 다른 메모', 'another-unknown-decision': '보존할 새 기록'}}
    await page.locator('#personalImport').set_input_files({
        'name': 'personal-test.json', 'mimeType': 'application/json',
        'buffer': json.dumps(incoming, ensure_ascii=False).encode('utf-8')})
    await page.wait_for_function('document.querySelector("#personalStatus")?.textContent.includes("가져왔습니다.")')
    merged = await page.evaluate('JSON.parse(localStorage.getItem("lawbook:notes"))')
    require(changed_note in merged[item['decisionId']] and '가져온 서로 다른 메모' in merged[item['decisionId']],
            'Import overwrote conflicting notes')
    require(merged.get('another-unknown-decision') == '보존할 새 기록', 'Import discarded unknown ID')
    require(await page.evaluate('!!localStorage.getItem("lawbook:before-import")'), 'Import did not keep backup')
    await page.locator('[data-check-update]').click()
    await page.wait_for_function('document.querySelector("#dataStatus")?.textContent === "최신 자료입니다."')
    print('webcheck: personal records OK; checking service worker', flush=True)
    registration = await asyncio.wait_for(page.evaluate('navigator.serviceWorker.ready.then(r => ({scope:r.scope, active:!!r.active}))'), timeout=20)
    require(registration['active'] and registration['scope'].endswith('/output/web/'), 'Incorrect PWA scope')
    await page.wait_for_function('!!navigator.serviceWorker.controller', timeout=15000)
    await page.locator('[data-download-offline]').click()
    await page.wait_for_function('document.querySelector("#dataStatus")?.textContent.includes("개를 저장했습니다.")',
                                 timeout=60000)
    require(not page_errors, 'Runtime exceptions: ' + repr(page_errors))
    require(not console_errors, 'Unexpected browser errors: ' + repr(console_errors))
    print('webcheck: offline package downloaded', flush=True)
    personal_before = await page.evaluate('localStorage.getItem("lawbook:notes")')

    # A new navigation must work without JS-memory state and without network.
    await context.set_offline(True)
    await page.reload(wait_until='load')
    await ready(page)
    require(await page.evaluate('window.CasebookData.status().offline'), 'Offline corpus fallback not used')
    await open_case(page, item, canonical=True)
    await check_fulltext(page, item, full)
    await page.evaluate('location.hash = "#/laws/civil-code"')
    await page.wait_for_selector('.lw-art', timeout=15000)
    offline_laws = await page.evaluate('window.CasebookData.loadLaws()')
    require(offline_laws == laws, 'Offline laws differ from the complete verified data package')
    civil = next(law for law in laws['laws'] if law['id'] == 'civil-code')
    distant_article = next(article for article in civil['articles'] if article['no'] == '제1100조')
    # The reader appends articles in chunks; navigation must reveal a distant article.
    await page.locator('.lw-goto').fill('1100')
    await page.locator('.lw-goto').press('Enter')
    target = page.locator('#civil-code-art-1100.hit')
    await target.wait_for(state='visible')
    displayed = normalized(await target.locator('.lw-art-b').inner_text())
    require(all(normalized(text) in displayed for _, text in distant_article['b'] if text),
            'Offline distant article content differs from the verified Civil Code')
    require(await target.evaluate('(el) => { const r = el.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; }'),
            'Offline article navigation did not scroll the selected article into view')
    require(await page.evaluate('localStorage.getItem("lawbook:notes")') == personal_before,
            'Data cache operation changed personal notes')
    require(not page_errors, 'Offline runtime exceptions: ' + repr(page_errors))
    await context.close()
    return {'legacy_and_canonical_routes': True, 'lazy_fulltext': True,
            'note_migration_export_import': True, 'unknown_notes_preserved': True,
            'service_worker_subpath': True, 'offline_reload_text_and_laws': True}

async def test_update_failures(browser, base, manifest):
    # Isolate provider checks from SW interception.
    async def new_context():
        ctx = await browser.new_context(service_workers='block')
        await ctx.route('https://fonts.googleapis.com/**', block_fonts)
        await ctx.route('https://fonts.gstatic.com/**', block_fonts)
        return ctx

    print('webcheck: offline reader OK; checking bad updates', flush=True)
    bad_schema = dict(manifest, schemaVersion=999)
    ctx = await new_context()
    await ctx.route('**/data-manifest.json', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps(bad_schema)))
    page = await ctx.new_page()
    await page.goto(base)
    await page.wait_for_selector('#bootError')
    require('형식' in await page.locator('#bootError').inner_text(), 'Unknown data schema was accepted')
    await ctx.close()

    ctx = await new_context()
    await ctx.route('**/' + manifest['cases']['url'], lambda route: route.fulfill(
        status=200, content_type='application/json', body='{"cases":[]}'))
    page = await ctx.new_page()
    await page.goto(base)
    await page.wait_for_selector('#bootError')
    require('무결성' in await page.locator('#bootError').inner_text(), 'Corrupt data hash was accepted')
    await ctx.close()

    ctx = await new_context()
    page = await ctx.new_page()
    await page.goto(base)
    await ready(page)
    previous_version = await page.evaluate('window.CasebookData.status().version')
    await ctx.route('**/data-manifest.json', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps(bad_schema)))
    await page.reload()
    await ready(page)
    state = await page.evaluate('window.CasebookData.status()')
    require(state['offline'] and state['version'] == previous_version, 'Bad update displaced valid cached data')
    await ctx.close()
    return {'incompatible_schema_rejected': True, 'corrupt_hash_rejected': True,
            'failed_update_keeps_previous_version': True}

async def test_mobile(browser, base, item):
    ctx = await browser.new_context(viewport={'width': 390, 'height': 844},
                                    is_mobile=True, has_touch=True, locale='ko-KR')
    await ctx.route('https://fonts.googleapis.com/**', block_fonts)
    await ctx.route('https://fonts.gstatic.com/**', block_fonts)
    page = await ctx.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    await page.goto(base)
    await ready(page)
    await open_case(page, item)
    require(await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),
            'Mobile reader overflows horizontally')
    await page.screenshot(path=str(ROOT / 'shots' / 'web-mobile.png'))
    await page.locator('#btnCsClose').click()
    await page.wait_for_function('!document.querySelector("#cs").classList.contains("show")')
    await page.locator('#btnSet').click()
    await page.wait_for_selector('[data-download-offline]')
    require(await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),
            'Mobile settings overflow horizontally')
    require(not errors, 'Mobile exceptions: ' + repr(errors))
    await ctx.close()
    return {'mobile_reader_and_settings': True}

async def run():
    print('webcheck: validating package', flush=True)
    require((WEB / 'index.html').is_file(), 'Build web first: python tools/make.py web')
    manifest = json.loads((WEB / 'data-manifest.json').read_text(encoding='utf-8'))
    require(manifest['schemaVersion'] == 1, 'Unexpected manifest schema')
    data = read_verified(manifest['cases'])
    laws = read_verified(manifest['laws'])
    original = json.loads((ROOT / 'data' / 'cases.json').read_text(encoding='utf-8'))
    original_by_id = {c['id']: c for c in original['cases']}
    checked_fulltext = 0
    for item in data['cases']:
        require(not item.get('fullText'), 'List payload embeds full text')
        if item.get('fullTextRef'):
            require(read_verified(item['fullTextRef']) == original_by_id[item['id']]['fullText'],
                    f'Web packaging changed original full text: {item["id"]}')
            checked_fulltext += 1
    require(checked_fulltext > 0 and len(laws['laws']) > 0, 'No corpus to test')
    item = next(c for c in data['cases'] if c.get('fullTextRef') and c.get('decisionId'))
    full = read_verified(item['fullTextRef'])
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/output/web/index.html'
    report = {'data_hashes_and_fulltext_unchanged': checked_fulltext,
              'placements': len(data['cases']), 'laws': len(laws['laws'])}
    try:
        print('webcheck: starting Playwright driver', flush=True)
        p = await asyncio.wait_for(async_playwright().start(), timeout=25)
        try:
            print('webcheck: launching browser', flush=True)
            browser = await asyncio.wait_for(launch_chromium(p), timeout=40)
            try:
                report.update(await asyncio.wait_for(test_reader(browser, base, data, laws, item, full), timeout=150))
                report.update(await asyncio.wait_for(test_update_failures(browser, base, manifest), timeout=90))
                report.update(await asyncio.wait_for(test_mobile(browser, base, item), timeout=45))
            finally:
                await asyncio.wait_for(browser.close(), timeout=10)
        finally:
            await asyncio.wait_for(p.stop(), timeout=10)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report

if __name__ == '__main__':
    asyncio.run(run())
