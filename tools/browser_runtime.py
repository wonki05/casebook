"""Use Playwright Chromium, or an installed Edge when Chromium is not installed."""
import os
from pathlib import Path
from playwright.async_api import Error

# Chromium refuses to load pages from these ports (ERR_UNSAFE_PORT; net/base/port_util.cc). An OS-assigned
# ephemeral port can land on one of them on Windows, so test servers retry the bind until the port is usable.
UNSAFE_PORTS = frozenset([1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95, 101, 102,
                          103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161, 179, 389, 427, 465,
                          512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587, 601, 636, 989, 990, 993,
                          995, 1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669,
                          6697, 10080])


def bind_safe_server(make_server, attempts=25):
    """Call make_server() until it binds a port Chromium accepts; the rejected servers are closed."""
    for _ in range(attempts):
        server = make_server()
        if server.server_port not in UNSAFE_PORTS:
            return server
        server.server_close()
    raise RuntimeError('could not bind a port that the browser accepts')


async def launch_chromium(playwright):
    channel = os.environ.get("CASEBOOK_BROWSER_CHANNEL")
    if channel:
        return await playwright.chromium.launch(channel=channel)
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
