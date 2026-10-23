#!/usr/bin/env python3
"""Screenshot a built HTML file at phone + desktop widths, light + dark, and optionally run a JS scenario.

Usage:
  python3 tools/shot.py output/casebook.html shots/a            # 4 screenshots: a-mobile-light.png, a-mobile-dark.png, a-desktop-light.png, a-desktop-dark.png
  python3 tools/shot.py output/casebook.html shots/a-case "document.querySelector('[data-case]')?.click()"   # run JS after load, then shoot
Prints console errors (if any) so templates can be checked for JS failures.
"""
import sys, os, asyncio
from playwright.async_api import async_playwright
from browser_runtime import launch_chromium

async def run(path, prefix, script):
    url = 'file://' + os.path.abspath(path)
    async with async_playwright() as p:
        browser = await launch_chromium(p)
        for name, vw, vh, mobile in (('mobile', 390, 844, True), ('desktop', 1366, 860, False)):
            for scheme in ('light', 'dark'):
                ctx = await browser.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=2 if mobile else 1,
                                                is_mobile=mobile, has_touch=mobile, color_scheme=scheme, locale='ko-KR')
                page = await ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('console', lambda m: errors.append('console.' + m.type + ': ' + m.text) if m.type in ('error',) else None)
                await page.goto(url)
                await page.wait_for_timeout(400)
                if script:
                    try:
                        await page.evaluate(script)
                    except Exception as e:
                        errors.append('script: ' + str(e))
                    await page.wait_for_timeout(400)
                out = f'{prefix}-{name}-{scheme}.png'
                os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
                await page.screenshot(path=out, full_page=False)
                print('wrote', out, ('ERRORS: ' + ' | '.join(errors)) if errors else '')
                await ctx.close()
        await browser.close()

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
