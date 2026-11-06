#!/usr/bin/env python3
"""Find collected decision texts whose line breaks were lost ("본문 한 줄").

The Korean-law API returns constitutional decision bodies with every line
break removed: 【당 사 자】, 【주 문】 and 【이 유】 then run on inside one
【전문】 block, numbered 판시사항 items are glued together ("…(적극)2. …") and
the screen cannot lay out paragraphs, the order or the outline. Official full
texts must come from the law.go.kr page (tools/fetch_lawgo.py), which keeps
those sections and paragraph breaks.

Checks, per data/fetched/<id>.json (constitutional `kind == "detc"` files by
default; `--kind all` adds precedents for information):
  one-line-body           the longest 이유/전문 block is long but has (almost) no line breaks
  inline-section-markers  a 【전문】 block carries 【주 문】/【이 유】 run on with other text
With --items it also notes (without failing) numbered 판시사항/요지 items that
run into the next ("…(소극)3. …"). Some law.go.kr pages print them that way
themselves, so a note is not by itself a collection error.

Usage:
  python tools/check_fulltext_lines.py [--fetched data/fetched] [--kind detc|prec|all] [--items] [--json]
Exit status 1 when any file has a problem. `add_cases.py validate` runs the
same check for detc files.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
FETCHED = ROOT / 'data' / 'fetched'

# Page-collected constitutional texts average at most ~400 characters per line
# (single paragraphs reach ~3,400); API imports have one line of up to 44,000.
MIN_BODY_CHARS = 600
MAX_AVERAGE_LINE = 1200
SECTION_MARKER = r'[【\[〔]\s*(?:주\s*문|이\s*유)\s*[】\]〕]'
INLINE_MARKER_RE = re.compile(r'[^\s][ \t]*' + SECTION_MARKER + r'|' + SECTION_MARKER + r'[ \t]*[^\s]')
GLUED_ITEM_RE = re.compile(r'\((?:적극|소극)\)[ \t]*(?:\d{1,2}|[가-하])\.[ \t]*\S')


def heading_name(heading):
    return re.sub(r'[\s【】〖〗\[\]]', '', heading or '')


def body_text(record):
    best = ''
    for section in record.get('sections') or []:
        text = section.get('text') or ''
        if heading_name(section.get('heading')) in ('이유', '전문') and len(text) > len(best):
            best = text
    return best


def flat_body(text):
    """Return a description when a long body has (almost) no line breaks."""
    text = (text or '').strip()
    breaks = text.count('\n')
    if len(text) >= MIN_BODY_CHARS and len(text) / (breaks + 1) >= MAX_AVERAGE_LINE:
        return f'{len(text)}자에 줄바꿈 {breaks}개'
    return None


def inline_section_markers(text):
    """Return the run-on order/reasons markers of a single 【전문】 block."""
    return [m.group(0).strip() for m in INLINE_MARKER_RE.finditer(text or '')]


PROBLEMS = ('one-line-body', 'inline-section-markers')
NOTES = ('glued-items',)


def inspect(record, notes=False):
    """Return [(code, message)] for one fetched record (glued-items only with notes=True)."""
    problems = []
    flat = flat_body(body_text(record))
    if flat:
        problems.append(('one-line-body', '전문·이유 본문이 한 줄: ' + flat))
    for section in record.get('sections') or []:
        name = heading_name(section.get('heading'))
        text = section.get('text') or ''
        if name == '전문':
            markers = inline_section_markers(text)
            if markers:
                problems.append(('inline-section-markers', '【전문】 안에 주문·이유 표지가 다른 글과 붙어 있음: '
                                 + ', '.join(sorted(set(markers)))[:80]))
        elif notes and name in ('판시사항', '결정요지', '판결요지') and GLUED_ITEM_RE.search(text):
            problems.append(('glued-items', f'{name} 항목이 줄바꿈 없이 이어짐: '
                             + GLUED_ITEM_RE.search(text).group(0)))
    return problems


def scan(fetched=FETCHED, kinds=('detc',), notes=False):
    """Return [{'id', 'file', 'kind', 'method', 'problems'}] for every flagged file."""
    found = []
    for path in sorted(Path(fetched).glob('*.json')):
        if path.name.endswith('.missing.json') or path.name.endswith('.supplement.json'):
            continue
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or (kinds and record.get('kind') not in kinds):
            continue
        problems = inspect(record, notes)
        if problems:
            found.append({'id': record.get('id') or path.stem, 'file': path.name, 'kind': record.get('kind'),
                          'method': (record.get('retrieval') or {}).get('method', 'law.go.kr page'),
                          'problems': [{'code': code, 'message': message} for code, message in problems]})
    return found


def validation_errors(fetched=FETCHED):
    """Messages for add_cases.py validate (constitutional detc files only)."""
    return [f"{item['id']}: 공식 전문 줄바꿈 없음({item['method']}) — "
            + '; '.join(p['message'] for p in item['problems'])
            + ' → law.go.kr 페이지로 다시 수집: python tools/fetch_lawgo.py --id ' + item['id'] + ' --force'
            for item in scan(fetched)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fetched', type=Path, default=FETCHED)
    ap.add_argument('--kind', choices=('detc', 'prec', 'all'), default='detc')
    ap.add_argument('--items', action='store_true', help='also note glued numbered 판시사항/요지 items (never fails)')
    ap.add_argument('--json', action='store_true', help='print the findings as JSON')
    a = ap.parse_args()
    kinds = None if a.kind == 'all' else (a.kind,)
    found = scan(a.fetched, kinds, a.items)
    if a.json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
    else:
        for item in found:
            print(f"{item['id']} [{item['kind']}, {item['method']}]")
            for problem in item['problems']:
                print(f"  {problem['code']}{'' if problem['code'] in PROBLEMS else ' (참고)'}: {problem['message']}")
    failing = [item for item in found if any(p['code'] in PROBLEMS for p in item['problems'])]
    if not a.json:
        print(f"줄바꿈 검사({a.kind}): 문제 {len(failing)}건" + (f", 참고 {len(found) - len(failing)}건" if a.items else ''))
    sys.exit(1 if failing else 0)


if __name__ == '__main__':
    main()
