#!/usr/bin/env python3
"""Serve the generated PWA locally: python tools/serve_web.py [--port 8765]."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    target = ROOT / 'output' / 'web'
    if not (target / 'index.html').is_file():
        raise SystemExit('Run python tools/make.py data web first.')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(SimpleHTTPRequestHandler, directory=str(target)))
    print(f'판례집 웹앱: http://localhost:{args.port}/index.html', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
