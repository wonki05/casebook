"""Run focused standard-edition UI checks with Node Playwright."""
import os
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    script = Path(__file__).with_suffix('.cjs')
    env = dict(os.environ, CASEBOOK_PYTHON=sys.executable)
    raise SystemExit(subprocess.call(['node', str(script), *sys.argv[1:]], env=env))
