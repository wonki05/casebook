#!/usr/bin/env python3
"""Focused research navigation/title/badge checks on built HTML or HTTP PWA.

Run after building: python tools/test_research_ui.py [--web]
Only representative detail sheets are opened; every research list row is checked.
"""
from __future__ import annotations

import argparse
import asyncio
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.async_api import async_playwright
from browser_runtime import launch_chromium
from serve_web import WebAppHandler

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = {'research-civil': '민법판례연구', 'research-criminal': '형법판례 150선'}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class QuietHandler(WebAppHandler):
    def log_message(self, format, *args):
        pass


async def block_fonts(route):
    await route.fulfill(status=200, content_type='text/css', body='')


async def list_page(page, page_id, label):
    await page.evaluate('(hash) => { location.hash = hash; }', '#/' + page_id)
    await page.wait_for_function('label => document.querySelector("#col .pagehead h1")?.textContent === label && !document.querySelector("#cs").classList.contains("show")', arg=label)


async def open_case(page, item, identity=None):
    await page.evaluate('(hash) => { location.hash = hash; }', f'#/{item["page"]}/{identity or item["id"]}')
    await page.wait_for_function('title => document.querySelector("#cs").classList.contains("show") && document.querySelector("#cs h1")?.textContent === title', arg=item['title'])
    require(await page.locator('#btnBmCase').get_attribute('data-bm') == item['id'],
            'Route selected wrong placement ID: ' + item['id'])


async def no_overflow(page, label):
    require(await page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), label + ': horizontal overflow')


async def check_rows(page, items, label):
    rendered = await page.locator('#col .entry').evaluate_all('''els => els.map(el => ({
      id:el.dataset.id, title:el.querySelector('.t').textContent,
      badge:!!el.querySelector('.ct .badge.standard'),
      citation:el.querySelector('.ct').firstChild.textContent
    }))''')
    require(rendered == [{'id': c['id'], 'title': c['title'], 'badge': bool(c.get('isStandard')),
                          'citation': c['citation']} for c in items], label + ': list order/title/citation/badge mismatch')


def toc_ordered_cases(data, page_id):
    page = next(p for p in data['pages'] if p['id'] == page_id)
    ranks = {}

    def visit(nodes, parent=()):
        for node in nodes:
            path = parent + (node['id'],)
            ranks[path] = len(ranks)
            visit(node.get('children', []), path)

    visit(data['toc'].get(page.get('tocKey', page_id), []))
    return sorted([c for c in data['cases'] if c['page'] == page_id],
                  key=lambda c: (ranks.get(tuple(c.get('tocPath', [])), len(ranks)), c['research']['order']))


async def check_civil_volumes(page, data, items):
    nodes = data['toc']['research-civil']
    require([node['id'] for node in nodes] == ['rc-1', 'rc-2', 'rc-3', 'rc-4'], 'Civil TOC must have four shared chapters')
    require(not any(node.get('children') for node in nodes), 'Civil TOC still contains volume subheadings')
    require(len(items) == 82, 'Civil collection must preserve all 82 placements')
    require([sum(c['tocPath'] == [node['id']] for c in items) for node in nodes] == [14, 17, 37, 14],
            'Civil shared chapter counts differ')
    require(await page.locator('#col details details').count() == 0, 'Civil UI still nests volume subheadings')
    labels = await page.locator('#col .toc > details > summary').evaluate_all('els => els.map(el => el.children[1].textContent)')
    require(labels == [node['label'] for node in nodes], 'Civil chapter order or labels differ')
    require(not any('1권' in label or '2권' in label for label in labels), 'Volume headings remain in civil TOC')
    for node in nodes:
        volumes = [c['research']['volume'] for c in items if c['tocPath'] == [node['id']]]
        require(volumes == sorted(volumes), 'Volume 1 must precede volume 2 within each civil chapter')

    async def assert_selection(volumes, expected_count):
        selected = await page.locator('#col [data-rvolume][aria-pressed="true"]').evaluate_all('els => els.map(el => Number(el.dataset.rvolume))')
        require(selected == volumes, 'Civil volume selection mismatch: ' + repr(selected))
        expected = [c for c in items if c['research']['volume'] in volumes]
        require(len(expected) == expected_count, 'Civil source volume count differs')
        await check_rows(page, expected, 'civil volumes ' + repr(volumes))
        await no_overflow(page, 'civil volume filters')

    require(await page.locator('#col [data-rvolume]').count() == 2, 'Civil volume buttons missing or duplicated')
    await assert_selection([1, 2], 82)
    await page.locator('#col [data-rvolume="2"]').click()
    await assert_selection([1], 52)
    # A deep link may open an excluded volume without silently changing filters.
    volume_two = next(c for c in items if c['research']['volume'] == 2)
    await open_case(page, volume_two)
    require(await page.locator('#cs .case').get_attribute('aria-label') == volume_two['title'], 'Excluded-volume route changed title')
    await page.locator('#btnCsClose').click()
    await page.wait_for_selector('#cs:not(.show)', state='attached')
    await assert_selection([1], 52)
    await page.locator('#col [data-rvolume="1"]').click()
    await assert_selection([], 0)
    await page.reload(wait_until='load')
    await page.wait_for_selector('#col [data-rvolume]')
    await assert_selection([], 0)
    await page.locator('#col [data-rvolume="2"]').click()
    await assert_selection([2], 30)
    await page.locator('#col [data-rvolume="1"]').click()
    await assert_selection([1, 2], 82)
    return {'both': 82, 'volume_1': 52, 'volume_2': 30, 'none': 0,
            'empty_selection_survives_reload': True, 'excluded_volume_route_preserves_filter': True}


async def check_badge(page, item):
    expected = bool(item.get('isStandard')) and item['group'] in ('research', 'annual', 'enbanc', 'ccourt')
    actual = await page.locator('#cs .cite-sub .badge.standard').count()
    require(actual == int(expected), 'Wrong detail standard badge: ' + item['id'])
    if expected:
        metrics = await page.locator('#cs .badge.standard').evaluate('''el => {
          const style = getComputedStyle(el), probe = document.createElement('span');
          probe.style.color = 'var(--accent-ink)'; document.body.appendChild(probe);
          const themed = style.color === getComputedStyle(probe).color;
          probe.style.color = 'var(--accent)';
          const themedBorder = style.borderColor === getComputedStyle(probe).color; probe.remove();
          const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
          ctx.fillStyle = style.backgroundColor; ctx.fillRect(0, 0, 1, 1);
          const alpha = ctx.getImageData(0, 0, 1, 1).data[3] / 255;
          return {text:el.textContent, beforeSubject:el.nextElementSibling?.classList.contains('sub'),
            rounded:parseFloat(style.borderRadius) >= 10, themed, themedBorder,
            opaqueText:style.opacity === '1', translucentFill:alpha >= .34 && alpha <= .36};
        }''')
        require(metrics == {'text': '표준판례', 'beforeSubject': True, 'rounded': True, 'themed': True,
                            'themedBorder': True, 'opaqueText': True, 'translucentFill': True},
                'Wrong badge placement/style: ' + repr(metrics))
    await no_overflow(page, item['id'])


def check_catalog_titles(data):
    checked = 0
    for path in sorted((ROOT / 'data' / 'research').glob('*catalog.json')):
        catalog = json.loads(path.read_text(encoding='utf-8'))
        collection = catalog.get('collection')
        if not collection:
            continue
        actual = {c['research']['order']: c for c in data['cases']
                  if (c.get('research') or {}).get('collection') == collection}
        expected = [c for c in catalog.get('candidates', []) if c.get('status') == 'ok']
        require(len(actual) == len(expected), f'{path.name}: imported catalog count differs')
        for candidate in expected:
            order = candidate['research']['order']
            require(order in actual and actual[order]['title'] == candidate['title'],
                    f'{path.name}: source title changed at order {order}')
            require(actual[order]['tocPath'] == candidate['tocPath'],
                    f'{path.name}: source TOC changed at order {order}')
        checked += len(expected)
    return checked


async def check_viewport(browser, base, data, width):
    ctx = await browser.new_context(viewport={'width': width, 'height': 900}, locale='ko-KR')
    await ctx.route('https://fonts.googleapis.com/**', block_fonts)
    await ctx.route('https://fonts.gstatic.com/**', block_fonts)
    page = await ctx.new_page()
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    await page.goto(base, wait_until='load')
    await page.wait_for_selector('#pagetabs [data-go]')
    pages = {p['id']: p for p in data['pages']}
    require(all(pid in pages for pid in RESEARCH), 'Research tabs absent from built data')
    await page.locator('#btnToc').click()
    sections = await page.locator('#panelBody .pages .ph').all_text_contents()
    require(sections.index('표준판례') < sections.index('판례연구') < sections.index('최신판례'),
            'Research section is not between standard and latest sections')
    for pid, label in RESEARCH.items():
        require(label in await page.locator(f'#panelBody .pages a[href="#/{pid}"]').inner_text(),
                'Wrong research navigation label')
    await page.locator('#btnTocClose').click()
    report = {'width': width, 'research': {}, 'latest': {}}
    all_cases = data['cases']
    for pid, label in RESEARCH.items():
        print(f'research-check: width {width}, {pid}', flush=True)
        items = toc_ordered_cases(data, pid)
        await list_page(page, pid, label)
        await no_overflow(page, pid)
        await check_rows(page, items, pid)
        report['research'][pid] = {'list_rows': len(items), 'standard_rows': sum(bool(c.get('isStandard')) for c in items)}
        if not items:
            report['research'][pid]['detail_checks'] = 'no registered cases'
            continue
        if pid == 'research-civil':
            report['research'][pid]['volumes'] = await check_civil_volumes(page, data, items)
        else:
            require(await page.locator('#col details details').count() > 0, pid + ': nested TOC absent')
        await page.locator('#col [data-list-open="false"]').click()
        require(await page.locator('#col details[open]').count() == 0, pid + ': collapse all failed')
        await page.locator('#col [data-list-open="true"]').click()
        require(await page.locator('#col details:not([open])').count() == 0, pid + ': expand all failed')
        await page.locator('#col details > summary').first.click()
        require(not await page.locator('#col details').first.evaluate('el => el.open'), pid + ': individual collapse failed')
        await page.locator('#col details > summary').first.click()
        selected = {items[0]['id']: items[0], max(items, key=lambda c: len(c['title']))['id']: max(items, key=lambda c: len(c['title']))}
        for standard in (True, False):
            match = next((c for c in items if bool(c.get('isStandard')) == standard), None)
            if match:
                selected[match['id']] = match
        for item in selected.values():
            await open_case(page, item)
            await check_badge(page, item)
        aliases = [(c, next((x for x in all_cases if x['page'] != pid and x.get('decisionId') == c.get('decisionId')), None)) for c in items]
        alias = next(((c, original) for c, original in aliases if original and original['title'] != c['title']), None)
        if alias:
            item, original = alias
            await open_case(page, item, original['id'])
            await check_badge(page, item)
            require(label in await page.locator('#cs .runhead').inner_text(), pid + ': legacy ID selected wrong placement')
            canonical = next(c for c in items if c['decisionId'] == item['decisionId'])
            await open_case(page, canonical, item['decisionId'])
            report['research'][pid]['legacy_and_canonical_title'] = True
        repeated = {}
        for item in items:
            repeated.setdefault(item['decisionId'], []).append(item)
        repeated = [placements for placements in repeated.values() if len(placements) > 1]
        for placements in repeated:
            for item in placements:
                await open_case(page, item)
                await check_badge(page, item)
        report['research'][pid]['repeated_decision_placements_checked'] = sum(map(len, repeated))
        report['research'][pid]['detail_checks'] = len(selected)
    for pid in ('annual', 'enbanc', 'ccourt'):
        items = [c for c in all_cases if c['page'] == pid]
        coverage = []
        for standard in (True, False):
            item = next((c for c in items if bool(c.get('isStandard')) == standard), None)
            if not item:
                continue
            await open_case(page, item)
            await check_badge(page, item)
            await page.locator('#btnCsClose').click()
            await page.wait_for_selector('#cs:not(.show)', state='attached')
            row = page.locator(f'#col .entry[data-id="{item["id"]}"]')
            require(await row.count() == 1, pid + ': case missing from selected year')
            require(await row.locator('.ct .badge.standard').count() == int(standard), pid + ': list standard badge mismatch')
            coverage.append('standard' if standard else 'nonstandard')
        report['latest'][pid] = coverage
    standard = next(c for c in all_cases if c['group'] == 'standard')
    await open_case(page, standard)
    await check_badge(page, standard)
    await page.locator('#btnCsClose').click()
    await page.wait_for_selector('#cs:not(.show)', state='attached')
    require(await page.locator('#col .badge.standard').count() == 0, 'Redundant standard badges in standard page')
    require(not errors, 'Browser exceptions: ' + repr(errors))
    await ctx.close()
    return report


async def run(web):
    if web:
        manifest = json.loads((ROOT / 'output/web/data-manifest.json').read_text(encoding='utf-8'))
        data = json.loads((ROOT / 'output/web' / manifest['cases']['url']).read_text(encoding='utf-8'))
    else:
        data = json.loads((ROOT / 'data/cases.json').read_text(encoding='utf-8'))
    catalog_count = check_catalog_titles(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/output/' + ('web/index.html' if web else 'casebook.html')
    try:
        async with async_playwright() as playwright:
            browser = await launch_chromium(playwright)
            results = [await check_viewport(browser, base, data, width) for width in (1366, 390)]
            await browser.close()
        print(json.dumps({'mode': 'web' if web else 'archive', 'catalog_titles_checked': catalog_count,
                          'results': results}, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', action='store_true')
    asyncio.run(run(parser.parse_args().web))
