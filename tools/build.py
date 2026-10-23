#!/usr/bin/env python3
"""Inject data into a template and write output/casebook.html.

Usage: python3 tools/build.py src/design-d.html [output/casebook.html]

Markers (each must appear exactly once in the template):
    <script id="case-data" type="application/json">__CASE_DATA_JSON__</script>
    <script id="laws-data" type="text/plain">__LAWS_DATA_B64__</script>   (optional: only if the template has it)
laws-data is gzip-compressed JSON, base64 encoded; the page decodes it with DecompressionStream('gzip').
"""
import json, os, sys, gzip, base64

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data', 'cases.json')
LAWS = os.path.join(ROOT, 'data', 'laws.json')



def inline_runtime(template):
    """Share one UI/runtime source between the downloadable and hosted edition."""
    for marker, filename in (('__DATA_PROVIDER_JS__', 'data-provider.js'),
                             ('__PERSONAL_DATA_JS__', 'personal-data.js')):
        if marker in template:
            if template.count(marker) != 1:
                raise ValueError(f'Expected one {marker}')
            source = open(os.path.join(ROOT, 'src', filename), encoding='utf-8').read()
            template = template.replace(marker, source.replace('</script', '<\\/script'))
    return template


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'output', 'casebook.html')
    tpl = inline_runtime(open(src, encoding='utf-8').read())
    if tpl.count('__CASE_DATA_JSON__') != 1:
        print('ERROR: template must contain exactly one __CASE_DATA_JSON__ marker'); sys.exit(2)
    data = json.load(open(DATA, encoding='utf-8'))
    js = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    js = js.replace('</', '<\\/').replace('<!--', '<\\!--')
    out = tpl.replace('__CASE_DATA_JSON__', js)
    if '__LAWS_DATA_B64__' in out:
        if out.count('__LAWS_DATA_B64__') != 1:
            print('ERROR: __LAWS_DATA_B64__ must appear exactly once'); sys.exit(2)
        raw = open(LAWS, 'rb').read()
        b64 = base64.b64encode(gzip.compress(raw, compresslevel=9)).decode('ascii')
        out = out.replace('__LAWS_DATA_B64__', b64)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, 'w', encoding='utf-8').write(out)
    print(f'wrote {dst} ({os.path.getsize(dst)/1024:.0f} KB)')


if __name__ == '__main__':
    main()
