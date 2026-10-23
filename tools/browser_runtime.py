"""Use Playwright Chromium, or an installed Edge when Chromium is not installed."""
import os
from pathlib import Path
from playwright.async_api import Error


async def launch_chromium(playwright):
    try:
        return await playwright.chromium.launch()
    except Error as error:
        if "Executable doesn't exist" not in str(error):
            raise
        # Windows PCs may already have Edge while the optional Playwright browser is absent.
        for base in (os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     os.environ.get('ProgramFiles', r'C:\Program Files'),
                     os.environ.get('LOCALAPPDATA')):
            if not base:
                continue
            executable = Path(base) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe'
            if executable.is_file():
                return await playwright.chromium.launch(executable_path=str(executable))
        raise
