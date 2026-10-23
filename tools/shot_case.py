#!/usr/bin/env python3
"""Screenshot a case in a built design: summary tab and full-text tab, mobile + desktop (light).
Usage: python3 tools/shot_case.py output/casebook.html <group> <caseId> shots/prefix [scrollY]
"""
import sys, os, asyncio
from playwright.async_api import async_playwright
from browser_runtime import launch_chromium

TAB_SEL = "[role=tab], [data-tab], .tab, .tabs button, .reader-tabs button"

async def run(path, group, cid, prefix, scroll):
    url = 'file://' + os.path.abspath(path) + f'#/{group}/{cid}'
    async with async_playwright() as p:
        b = await launch_chromium(p)
        for name, vw, vh, mobile in (('m', 390, 844, True), ('d', 1366, 860, False)):
            ctx = await b.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile, locale='ko-KR')
            page = await ctx.new_page()
            await page.goto(url); await page.wait_for_timeout(500)
            if scroll:
                await page.evaluate(f"(document.scrollingElement||document.body).scrollTop={scroll}; document.querySelectorAll('main,.reader,.sheet,.panel,[data-scroll]').forEach(e=>e.scrollTop={scroll})")
                await page.wait_for_timeout(150)
            await page.screenshot(path=f'{prefix}-{name}-summary.png')
            tabs = [t for t in await page.query_selector_all(TAB_SEL) if await t.is_visible()]
            # click the tab whose text contains 전문
            for t in tabs:
                txt = (await t.inner_text()).strip()
                if '전문' in txt:
                    await t.click(); break
            await page.wait_for_timeout(400)
            if scroll:
                await page.evaluate(f"(document.scrollingElement||document.body).scrollTop={scroll}; document.querySelectorAll('main,.reader,.sheet,.panel,[data-scroll]').forEach(e=>e.scrollTop={scroll})")
                await page.wait_for_timeout(150)
            await page.screenshot(path=f'{prefix}-{name}-full.png')
            await ctx.close()
        await b.close()
    print('ok', prefix)

if __name__ == '__main__':
    a = sys.argv
    asyncio.run(run(a[1], a[2], a[3], a[4], int(a[5]) if len(a) > 5 else 0))
