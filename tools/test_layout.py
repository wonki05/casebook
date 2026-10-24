#!/usr/bin/env python3
"""Check list expansion controls and responsive reader widths on the built HTML.

Usage: python tools/test_layout.py [output/casebook.html]
Only isolated browser contexts change; no source data or personal records are edited.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import sys

from playwright.async_api import async_playwright
from browser_runtime import launch_chromium

ROOT = Path(__file__).resolve().parent.parent


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read_data(path):
    text = path.read_text(encoding='utf-8')
    match = re.search(r'''<script\b[^>]*\bid=["']case-data["'][^>]*>(.*?)</script>''', text, re.S)
    require(match is not None, 'Built HTML has no embedded case-data')
    return json.loads(match.group(1))


async def block_fonts(route):
    await route.fulfill(status=200, content_type='text/css', body='')


async def go(page, page_id):
    await page.evaluate('(id) => { location.hash = "#/" + id; }', page_id)
    await page.wait_for_function('''(id) => {
      if (document.querySelector('#cs')?.classList.contains('show')) return false;
      return id === 'bookmarks' ? document.querySelector('#btnBm')?.classList.contains('on') :
        document.querySelector('#pagetabs [data-go="' + id + '"]')?.getAttribute('aria-current') === 'page';
    }''', arg=page_id.split('/')[0])


async def selection(page):
    return await page.evaluate('''() => ({
      buttons: [...document.querySelectorAll('#col [data-year], #col [data-ytab], #col [data-yyear], #col [data-filter], #col [data-afield], #col [data-acourt], #col [data-aenbanc]')]
        .map(b => [Object.assign({}, b.dataset), b.getAttribute('aria-pressed')]),
      saved: ['lawbook:annual', 'lawbook:ccourt', 'lawbook:enbanc'].map(k => [k, localStorage.getItem(k)])
    })''')


async def detail_states(scope):
    return await scope.locator('details').evaluate_all('(nodes) => nodes.map(n => n.open)')


async def command(scope, opened):
    button = scope.locator('[data-list-open="' + str(opened).lower() + '"]')
    require(await button.count() == 1, 'Each list scope needs one button per command')
    require(await button.get_attribute('type') == 'button', 'List command must be a type=button')
    await button.click()
    states = await detail_states(scope)
    require(bool(states), 'List control has no details to operate on')
    require(all(value == opened for value in states), 'List command did not update all nested details')
    return len(states)


async def no_overflow(page, label):
    dimensions = await page.evaluate('''() => ({viewport: innerWidth, document: document.documentElement.scrollWidth,
      sheet: document.querySelector('#csBox')?.scrollWidth || 0,
      sheetClient: document.querySelector('#csBox')?.clientWidth || 0,
      open: document.querySelector('#cs')?.classList.contains('show')})''')
    require(dimensions['document'] <= dimensions['viewport'] + 1, label + ': document overflows')
    if dimensions['open']:
        require(dimensions['sheet'] <= dimensions['sheetClient'] + 1, label + ': reader overflows')


async def test_lists(page, data, mobile):
    counts = {}
    standard_pages = [p['id'] for p in data['pages'] if p.get('group') == 'standard']
    require(bool(standard_pages), 'No standard-case pages to test')
    for page_id in standard_pages + ['annual', 'ccourt', 'enbanc']:
        await go(page, page_id)
        # Use populated year tabs, preserving their exact selected state across commands.
        if page_id in ('ccourt', 'enbanc'):
            await page.locator('#ytabs [data-ytab="all"]').click()
            tabs = page.locator('#ytabs [data-ytab]:not([data-ytab="all"]):not(.none)')
            require(await tabs.count() > 0, page_id + ': no populated year tab')
            await tabs.first.click()
            if page_id == 'enbanc':
                years = page.locator('#ytabs [data-yyear]:not(.none)')
                require(await years.count() > 0, 'Enbanc era has no individual years')
                await years.first.click()
        if page_id == 'annual':
            await page.locator('#btnAFilter').click()
            annual_cases = [c for c in data['cases'] if c.get('page') == 'annual' and c.get('annual')]
            latest = max(c['annual']['year'] for c in annual_cases)
            field = next(c['annual']['field'] for c in annual_cases if c['annual']['year'] == latest)
            await page.locator('[data-afield="' + field + '"]').click()
            await page.locator('#btnAFilterClose').click()
        scope = page.locator('#col .list-scope').first
        await scope.wait_for(state='visible')
        before = await selection(page)
        await command(scope, False)
        counts[page_id] = await command(scope, True)
        require(await selection(page) == before, page_id + ': expansion changed filters or stored years')
        if page_id in standard_pages:
            require(await scope.locator('details details').count() > 0, page_id + ': nested standard TOC not exercised')
        await no_overflow(page, page_id)

    # A panel command must operate on its own copy, not the underlying main list.
    await go(page, standard_pages[-1])
    main = page.locator('#col .list-scope').first
    await command(main, False)
    main_before = await detail_states(main)
    await page.locator('#btnToc').click()
    panel = page.locator('#panelBody .list-scope').first
    await panel.wait_for(state='visible')
    await command(panel, False)
    await command(panel, True)
    require(await detail_states(main) == main_before, 'Panel command changed the separate main-list scope')
    await page.locator('#btnTocClose').click()
    await command(main, True)

    # Seed a bookmark through its real UI, then exercise the separate bookmarks renderer.
    star = main.locator('[data-bm][aria-pressed="false"]').first
    require(await star.count() == 1, 'No visible case available to bookmark')
    await star.click()
    await go(page, 'bookmarks')
    bookmark_scope = page.locator('#col .list-scope').first
    await bookmark_scope.wait_for(state='visible')
    await command(bookmark_scope, False)
    counts['bookmarks'] = await command(bookmark_scope, True)
    await no_overflow(page, 'bookmarks')

    await go(page, 'laws/civil-code')
    await page.locator('.lw-goto').wait_for(state='visible')
    # This public control materializes the law's deferred body, including its supplements.
    await page.locator('.lw-goto').fill('750')
    await page.locator('.lw-goto').press('Enter')
    await page.locator('#lawText .lw-supp').wait_for(state='attached')
    body_before = await page.locator('#lawText details').evaluate_all('(nodes) => nodes.map(n => n.open)')
    require(bool(body_before), 'Law supplements must be present for scope-isolation check')
    if mobile:
        await page.locator('#btnToc').click()
        law_scope = page.locator('#panelBody .laws-nav .list-scope').first
    else:
        law_scope = page.locator('#lawsSide .list-scope').first
    await law_scope.wait_for(state='visible')
    await command(law_scope, False)
    counts['laws'] = await command(law_scope, True)
    body_after = await page.locator('#lawText details').evaluate_all('(nodes) => nodes.map(n => n.open)')
    require(body_after == body_before, 'Law-list controls changed body supplements')
    if mobile:
        await page.locator('#btnTocClose').click()
    await no_overflow(page, 'laws')
    return counts


async def test_fullscreen(page, data):
    candidates = [c for c in data['cases'] if c.get('fullText')]
    require(bool(candidates), 'No official full text for responsive reader check')
    preferred = [c for c in candidates if any(re.search(r'(?m)^\s*1\.\s*(?:사건|사안)', b.get('text', '')) for b in c['fullText'])]
    item = (preferred or candidates)[0]
    await page.set_viewport_size({'width': 1800, 'height': 1000})
    await page.evaluate('(hash) => { location.hash = hash; }', '#/' + item['page'] + '/' + item['id'])
    await page.locator('#cs.show .case').wait_for(state='visible')
    await page.locator('#btnCsFull').click()
    await page.wait_for_function('document.querySelector("#cs").classList.contains("full")')
    width = await page.locator('#cs .cs-main').evaluate('(el) => el.getBoundingClientRect().width')
    require(1098 <= width <= 1102, 'Fullscreen main width should reach 1100px at 1800px: ' + str(width))
    await page.locator('[data-tab="2"]').click()
    await page.locator('#ft').wait_for(state='visible')
    has_outline = await page.locator('#ft p.hd.h1').count() > 0
    require(has_outline, 'Responsive fixture must exercise a full-text outline')
    await no_overflow(page, 'fullscreen-1800')
    for viewport in (1366, 1024, 390):
        await page.set_viewport_size({'width': viewport, 'height': 844})
        await page.wait_for_function('''() => {
          const box = document.querySelector('#csBox'), cs = document.querySelector('#cs');
          return cs.classList.contains('wide') === (box.clientWidth >= 980);
        }''')
        await no_overflow(page, 'fullscreen-' + str(viewport))
    require(await page.locator('#btnFtOutline').is_visible(), 'Narrow fullscreen needs accessible outline button')
    require(not await page.locator('#ftOutline').is_visible(), 'Narrow fullscreen kept fixed outline beside text')
    await page.locator('#btnFtOutline').click()
    require(await page.locator('#ftOutline').is_visible(), 'Narrow outline button did not open outline')
    await page.locator('#btnFtOutline').click()
    await page.set_viewport_size({'width': 1800, 'height': 1000})
    await page.wait_for_function('document.querySelector("#cs").classList.contains("wide")')
    require(await page.locator('#cs').evaluate('(el) => el.classList.contains("full")'), 'Resizing lost stored full-screen preference')
    await no_overflow(page, 'fullscreen-restored')
    await page.locator('#btnCsClose').click()
    return {'max_main_width': width, 'outline_mobile': True, 'resize_restored': True}


async def run(path):
    data = read_data(path)
    report = {}
    async with async_playwright() as playwright:
        browser = await launch_chromium(playwright)
        try:
            for name, width, mobile in [('mobile', 390, True), ('desktop', 1366, False)]:
                print('layoutcheck: ' + name, flush=True)
                context = await browser.new_context(viewport={'width': width, 'height': 844}, is_mobile=mobile,
                                                    has_touch=mobile, locale='ko-KR')
                await context.route('https://fonts.googleapis.com/**', block_fonts)
                await context.route('https://fonts.gstatic.com/**', block_fonts)
                page = await context.new_page()
                page.set_default_timeout(10000)
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
                try:
                    await page.goto(path.as_uri(), wait_until='load')
                    await page.locator('#pagetabs [data-go]').first.wait_for(state='visible')
                    result = {'list_details': await test_lists(page, data, mobile)}
                    if not mobile:
                        result['fullscreen'] = await test_fullscreen(page, data)
                    require(not errors, 'Browser errors: ' + repr(errors))
                    result['errors'] = errors
                    result['passed'] = True
                    report[name] = result
                except Exception as error:
                    report[name] = {'passed': False, 'error': str(error), 'browser_errors': errors}
                finally:
                    await context.close()
        finally:
            await browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(result.get('passed') for result in report.values()) else 1


def main():
    path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'output' / 'casebook.html'
    try:
        return asyncio.run(run(path))
    except Exception as error:
        print(json.dumps({'passed': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())