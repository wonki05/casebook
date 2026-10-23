#!/usr/bin/env python3
"""Independent QA sweep for a built design: opens every case via hash routing on mobile + desktop,
clicks every tab-like control, collects page errors / console errors / horizontal overflow.

Usage: python3 tools/sweep.py output/casebook.html
"""
import sys, os, json, asyncio
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from browser_runtime import launch_chromium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = json.load(open(os.path.join(ROOT, 'data', 'cases.json'), encoding='utf-8'))
TAB_SEL = "[role=tab], [data-tab], .tab, .tabs button, .reader-tabs button"


def collect_console(message, errors, ignored_fonts):
    if message.type != 'error':
        return
    location = message.location or {}
    url = location.get('url', '')
    # Only identified Google Fonts resource errors are ignored.
    if (urlparse(url).hostname in ('fonts.googleapis.com', 'fonts.gstatic.com')
            and ('Failed to load resource' in message.text or 'net::ERR_' in message.text)):
        ignored_fonts.append(message.text)
    else:
        errors.append('console.error: ' + message.text + (' [' + url + ']' if url else ''))


def report_failed(report):
    for result in report.values():
        if result['errors'] or result['overflow'] or result['empty']:
            return True
        laws, annual = result['laws'], result['annual']
        if (laws.get('error') or not laws.get('civil_articles')
                or not laws.get('const_v1_articles') or not laws.get('goto750')
                or not laws.get('const_v1_old_banner')):
            return True
        if (annual.get('error') or annual.get('entries') != annual['expected']
                or annual.get('unfielded') or not annual.get('filter_opens')):
            return True
        for key in YEAR_TAB_PAGES:
            yt = result[key]
            if (yt.get('error') or yt.get('entries') != yt['expected'] or yt.get('all_pressed') != 'all'
                    or yt.get('tabs') != yt['expected_tabs'] or yt.get('labels') != '전체분야 전체연도'
                    or yt.get('tab_entries') != yt['tab_expected'] or yt.get('subject_entries') != yt['subject_expected']
                    or yt.get('empty_tab') != yt['empty_tab_expected'] or yt.get('empty_subject') != yt['empty_subject_expected']):
                return True
    return False


YEAR_TAB_PAGES = ('ccourt', 'enbanc')


def tab_of(tabs, year):
    return next((t['id'] for t in tabs if t['from'] <= year <= t['to']), None)


async def check_year_tabs(page, page_id, vw, overflow):
    """헌법재판소 주요결정·대법원 전원합의체: 과목 칩(전체분야) 아래 선고연도 탭(전체연도 + 연도·연대).
    전체연도면 모든 판례, 탭 하나를 누르면 그 연도(연대)의 판례만, 과목 칩을 누르면 그 과목만 보여야 한다.
    수록 판례가 한 해·한 과목뿐이어도 필터 고장을 잡도록 판례가 없는 탭·과목을 눌러 0건인지도 본다."""
    cases = [c for c in DATA['cases'] if c.get('page') == page_id]
    tabs = DATA.get('yearTabs', {}).get(page_id, [])
    case_tab = {c['id']: tab_of(tabs, int(c['decisionDate'][:4])) for c in cases}
    newest = next((t['id'] for t in tabs if t['id'] in case_tab.values()), None)
    subject = cases[0]['subject'] if cases else None
    chip_subjects = [s['id'] for s in DATA['subjects'] if s.get('standard') is not False or any(c['subject'] == s['id'] for c in cases)]
    empty_tab = next((t['id'] for t in tabs if t['id'] not in case_tab.values()), None)
    empty_subject = next((s for s in chip_subjects if not any(c['subject'] == s for c in cases)), None)
    count = "document.querySelectorAll('#ylist .entry').length"
    pressed = "[...document.querySelectorAll('#ytabs [aria-pressed=true]')].map(b => b.dataset.ytab).join(',')"
    r = {'expected': len(cases), 'expected_tabs': len(tabs),
         'tab_expected': sum(1 for c in cases if case_tab[c['id']] == newest),
         'subject_expected': sum(1 for c in cases if c['subject'] == subject),
         'empty_tab_expected': f'{empty_tab}:0' if empty_tab else None,
         'empty_subject_expected': f'{empty_subject}:0' if empty_subject else None}
    try:
        await page.evaluate(f"location.hash = '#/{page_id}'")
        await page.wait_for_selector('#ytabs [data-ytab]', timeout=5000)
        r['labels'] = await page.evaluate("[...document.querySelectorAll('#col [data-filter=all], #ytabs [data-ytab=all]')].map(b => b.textContent).join(' ')")
        r['tabs'] = await page.evaluate("document.querySelectorAll('#ytabs [data-ytab]:not([data-ytab=all])').length")
        await page.click('#ytabs [data-ytab=all]')
        await page.wait_for_timeout(50)
        r['all_pressed'] = await page.evaluate(pressed)
        r['entries'] = await page.evaluate(count)
        if newest:
            await page.click(f'#ytabs [data-ytab="{newest}"]')
            await page.wait_for_timeout(50)
        r['tab_entries'] = await page.evaluate(count)
        await page.click('#ytabs [data-ytab=all]')
        if empty_tab:
            await page.click(f'#ytabs [data-ytab="{empty_tab}"]')
            await page.wait_for_timeout(50)
            r['empty_tab'] = f"{await page.evaluate(pressed)}:{await page.evaluate(count)}"
            await page.click('#ytabs [data-ytab=all]')
        if subject:
            await page.click(f'#col [data-filter="{subject}"]')
            await page.wait_for_timeout(50)
        r['subject_entries'] = await page.evaluate(count)
        if empty_subject:
            await page.click(f'#col [data-filter="{empty_subject}"]')
            await page.wait_for_timeout(50)
            r['empty_subject'] = f"{empty_subject}:{await page.evaluate(count)}"
        await page.click('#col [data-filter=all]')
        sw = await page.evaluate('document.documentElement.scrollWidth')
        if sw > vw + 1: overflow.append((page_id, sw))
    except Exception as e:
        r['error'] = str(e)[:200]
    return r


async def run(path):
    url = 'file://' + os.path.abspath(path)
    async with async_playwright() as p:
        browser = await launch_chromium(p)
        report = {}
        for name, vw, vh, mobile in (('mobile', 390, 844, True), ('desktop', 1366, 860, False)):
            ctx = await browser.new_context(viewport={'width': vw, 'height': vh}, is_mobile=mobile, has_touch=mobile, locale='ko-KR')
            page = await ctx.new_page()
            errors = []
            ignored_fonts = []
            page.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
            page.on('console', lambda m: collect_console(m, errors, ignored_fonts))
            await page.goto(url)
            await page.wait_for_timeout(300)
            overflow = []
            empty = []
            for c in DATA['cases']:
                await page.evaluate(f"location.hash = '#/{c.get('page', c['group'])}/{c['id']}'")
                await page.wait_for_timeout(60)
                tabs = await page.query_selector_all(TAB_SEL)
                for t in tabs[:6]:
                    try:
                        if await t.is_visible():
                            await t.click(timeout=800)
                            await page.wait_for_timeout(30)
                    except Exception:
                        pass
                sw = await page.evaluate('document.documentElement.scrollWidth')
                if sw > vw + 1:
                    overflow.append((c['id'], sw))
                txt = await page.evaluate('document.body.innerText.length')
                if txt < 200:
                    empty.append(c['id'])
            laws = {}
            try:
                await page.evaluate("location.hash = '#/laws/civil-code'")
                await page.wait_for_selector('.lw-art', timeout=15000)
                await page.wait_for_timeout(500)
                laws['civil_articles'] = await page.evaluate("document.querySelectorAll('.lw-art').length")
                laws['goto750'] = await page.evaluate("LawsModule.goto(document.querySelector('.lw-text'), '750')")
                await page.evaluate("location.hash = '#/laws/constitution/constitution-v1'")
                await page.wait_for_timeout(800)
                laws['const_v1_articles'] = await page.evaluate("document.querySelectorAll('.lw-art').length")
                laws['const_v1_old_banner'] = await page.evaluate("!!document.querySelector('.lw-head .old')")
                sw = await page.evaluate('document.documentElement.scrollWidth')
                if sw > vw + 1: overflow.append(('laws', sw))
            except Exception as e:
                laws['error'] = str(e)[:200]
            # 법률신문 주요판례: 연도 버튼을 모두 켜면 등록된 annual 사건이 모두 보이고, 필터·찾기가 오류 없이 동작해야 한다
            annual = {'expected': sum(1 for c in DATA['cases'] if c['group'] == 'annual')}
            try:
                await page.evaluate("location.hash = '#/annual'")
                await page.wait_for_selector('#years [data-year]', timeout=5000)
                for b in await page.query_selector_all('#years [data-year][aria-pressed=false]'):
                    await b.click()
                    await page.wait_for_timeout(30)
                annual['years'] = await page.evaluate("[...document.querySelectorAll('#years [data-year]')].map(b => b.dataset.year + (b.getAttribute('aria-pressed') === 'true' ? '' : '(off)')).join(' ')")
                annual['entries'] = await page.evaluate("document.querySelectorAll('#annualList .entry').length")
                annual['unfielded'] = await page.evaluate("[...document.querySelectorAll('#annualList details.lv1>summary')].some(s => s.innerText.includes('분야 미지정'))")
                await page.click('#btnAFilter')
                await page.wait_for_timeout(50)
                annual['filter_opens'] = await page.evaluate("!document.querySelector('#afilter').hidden")
                await page.click('#btnAFilter')
                if mobile:
                    await page.click('#btnAFind')
                await page.fill('#aq', '대법원')
                await page.wait_for_timeout(250)
                annual['search_hits'] = await page.evaluate("document.querySelectorAll('#annualList .entry').length")
                await page.fill('#aq', '')
                await page.wait_for_timeout(250)
                sw = await page.evaluate('document.documentElement.scrollWidth')
                if sw > vw + 1: overflow.append(('annual', sw))
            except Exception as e:
                annual['error'] = str(e)[:200]
            year_tabs = {pid: await check_year_tabs(page, pid, vw, overflow) for pid in YEAR_TAB_PAGES}
            report[name] = {'errors': errors[:20], 'overflow': overflow[:10], 'empty': empty[:10], 'ignored_google_fonts': len(ignored_fonts), 'laws': laws, 'annual': annual, **year_tabs}
            await ctx.close()
        await browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report_failed(report) else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(run(sys.argv[1])))
