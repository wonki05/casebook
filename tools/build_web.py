#!/usr/bin/env python3
"""Build versioned static web/PWA files; source PDFs are never published."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
from build import inline_runtime

ROOT = Path(__file__).resolve().parent.parent

def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def write_atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(raw)
    temp.replace(path)

def asset(out, kind, value):
    raw = encode(value)
    sha = digest(raw)
    url = f'data/{kind}.{sha}.json'
    target = out / url
    if not target.exists():
        write_atomic(target, raw)
    elif digest(target.read_bytes()) != sha:
        raise ValueError(f'Existing immutable data is corrupt: {target}')
    return {'url': url, 'sha256': sha, 'bytes': len(raw)}

def build(out=None):
    out = Path(out or ROOT / 'output' / 'web').resolve()
    data = json.loads((ROOT / 'data' / 'cases.json').read_text(encoding='utf-8'))
    laws = json.loads((ROOT / 'data' / 'laws.json').read_text(encoding='utf-8'))
    index = copy.deepcopy(data)
    for case in index['cases']:
        full = case.pop('fullText', None)
        if full:
            case['fullTextRef'] = asset(out, 'fulltext', full)
        case['fullText'] = None
    cases_ref = asset(out, 'cases', index)
    laws_ref = asset(out, 'laws', laws)
    version = digest(encode({'cases': cases_ref['sha256'], 'laws': laws_ref['sha256']}))[:20]
    manifest = {'schemaVersion': 1, 'version': version,
                'generatedAt': data.get('meta', {}).get('built'),
                'cases': cases_ref, 'laws': laws_ref,
                'caseCount': len(index['cases'])}
    template = inline_runtime((ROOT / 'src' / 'design-d.html').read_text(encoding='utf-8'))
    if template.count('__CASE_DATA_JSON__') != 1 or template.count('__LAWS_DATA_B64__') != 1:
        raise ValueError('Missing or duplicated data markers')
    html = template.replace('__CASE_DATA_JSON__', '{}').replace('__LAWS_DATA_B64__', '')
    head = ('<meta name="theme-color" content="#64523f">\n'
            '<meta name="apple-mobile-web-app-capable" content="yes">\n'
            '<link rel="manifest" href="./manifest.webmanifest">\n'
            '<link rel="icon" href="./icons/icon.svg" type="image/svg+xml">\n'
            '<link rel="apple-touch-icon" href="./icons/icon-192.png">\n'
            '<script>window.CASEBOOK_WEB=true;</script>\n')
    html = html.replace('</head>', head + '</head>', 1)
    html = html.replace('</body>', '''<script>
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js', {scope: './'}).catch(error => {
      console.warn('오프라인 화면 저장을 시작하지 못했습니다.', error);
    });
  });
}
</script>\n</body>''', 1)
    write_atomic(out / 'index.html', html.encode('utf-8'))
    static = ROOT / 'src' / 'pwa'
    static_assets = ('manifest.webmanifest', 'icons/icon.svg', 'icons/icon-192.png', 'icons/icon-512.png')
    for name in static_assets:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(static / name, target)
    # Include every cached asset so manifest/icon-only updates rotate the shell cache.
    shell_files = {'index.html': digest(html.encode('utf-8')),
                   'sw.js': digest((static / 'sw.js').read_bytes())}
    shell_files.update({name: digest((out / name).read_bytes()) for name in static_assets})
    shell_hash = digest(encode(shell_files))[:20]
    sw = (static / 'sw.js').read_text(encoding='utf-8').replace('__SHELL_VERSION__', shell_hash)
    write_atomic(out / 'sw.js', sw.encode('utf-8'))
    write_atomic(out / '.nojekyll', b'')
    write_atomic(out / 'data-manifest.json', encode(manifest))
    print(f'web: {out / "index.html"}; {len(index["cases"])} placements; data {version}; shell {len(html.encode("utf-8")):,} bytes')
    return manifest

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    build(parser.parse_args().output)
