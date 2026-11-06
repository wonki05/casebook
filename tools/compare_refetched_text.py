#!/usr/bin/env python3
"""Compare official texts that were re-collected from law.go.kr pages with the
earlier Korean-law API imports of the same decisions.

The API (`korean-law:get_decision_text`) returned decision bodies with every
line break removed, so those records were re-collected with
`tools/fetch_lawgo.py --id <id> --force`. This script checks, per decision:

(a) identity — the re-collected page still names the registered court, case
    number, decision date and decision type (`fetch_lawgo.finish`), and its
    law.go.kr serial (`seq`) is the one the API record pointed to;
(b) text — 판시사항, 결정요지(판결요지), 심판대상조문, 참조조문, 참조판례 and the
    whole decision text (API 【전문】 versus the page's 【전문】 and every section
    after it, headings included) are identical character for character once
    spaces, tabs and line breaks are removed.

Nothing is rewritten: differences are only reported (CLAUDE.md rule 1).
The earlier API records are read from git (`--base-rev`, default 734618a) or
from a backup directory (`--backup`).

Usage:
  python tools/compare_refetched_text.py [--base-rev REV | --backup DIR]
      [--log fetch.log ...] [--json report.json] [--status spec/CCOURT-LINEBREAK-STATUS.md]
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from casenum import lookup_key  # noqa: E402
from fetch_lawgo import direct_url, finish  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FETCHED = ROOT / 'data' / 'fetched'
REGISTRY = ROOT / 'data' / 'registry.json'
API_METHOD = 'korean-law:get_decision_text'
FIELDS = ('판시사항', '결정요지', '심판대상조문', '참조조문', '참조판례')
FIELD_ALIASES = {'판결요지': '결정요지'}
MARKER_RE = re.compile(r'[【〖][^】〗\n]{1,20}[】〗]')
BEGIN, END = '<!-- BEGIN GENERATED: tools/compare_refetched_text.py -->', '<!-- END GENERATED -->'


def squash(text):
    return re.sub(r'\s+', '', text or '')


def heading_name(heading):
    return re.sub(r'[\s【】〖〗\[\]]', '', heading or '')


def split_fields(record):
    """Return {field: text} and the decision text (from 【전문】 to the end)."""
    fields, full, in_full = {}, [], False
    for section in record.get('sections') or []:
        name = heading_name(section.get('heading'))
        name = FIELD_ALIASES.get(name, name)
        text = section.get('text') or ''
        if name == '전문':
            in_full = True
            full.append(text)
        elif in_full or name not in FIELDS:
            in_full = True
            full.append((section.get('heading') or '') + text)
        else:
            fields[name] = fields.get(name, '') + text
    return fields, ''.join(full)


def first_difference(a, b):
    n = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return {'at': n, 'api': a[max(0, n - 25):n + 25], 'page': b[max(0, n - 25):n + 25],
            'apiLength': len(a), 'pageLength': len(b)}


# Known, explained differences between the API text and the page text. They are
# applied to both sides only to classify a difference; stored texts never change.
DOTS = str.maketrans({'·': 'ㆍ', '․': 'ㆍ', '‧': 'ㆍ', '・': 'ㆍ'})
NORMALIZERS = (
    ('entities', html.unescape),  # API: HTML character references (&#183; &nbsp; …)
    ('markers', lambda text: MARKER_RE.sub('', text)),  # 【당 사 자】 etc. as headings or inline labels
    ('middot', lambda text: text.translate(DOTS)),  # API: · (U+00B7) etc. where the page prints ㆍ (U+318D)
    # 참조판례 only: the API cites "대법원 2021. 1. 28. 2018도4708" where the page has "… 선고 2018도4708 판결"
    ('citation', lambda text: re.sub(r'(\d{2,4}[가-힣]{1,3}\d+(?:전원합의체)?)판결', r'\1',
                                     re.sub(r'선고(?=\d{2,4}[가-힣]{1,3}\d)', '', text))),
    ('tags', lambda text: re.sub(r'</?[A-Z]{2,10}>', '', text)),  # API: leftover markup such as <NOTE>
)
FIELD_ONLY = {'citation': {'참조판례'}}
NORMALIZER_NOTES = {'entities': 'API HTML 문자 참조', 'markers': '【…】 표지 위치',
                    'middot': '가운뎃점 API ·(U+00B7) / 페이지 ㆍ(U+318D)', 'citation': 'API 참조판례에서 "선고"·"판결" 빠짐',
                    'tags': 'API 본문에 남은 태그(<NOTE> 등)'}


def segment_diff(a, b, limit=12):
    """Differing (api, page) segments and their kinds; sentence alignment keeps long texts fast."""
    sa, sb = re.split(r'(?<=[.。])', a), re.split(r'(?<=[.。])', b)
    out, kinds = [], set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        x, y = ''.join(sa[i1:i2]), ''.join(sb[j1:j2])
        if len(x) + len(y) > 4000:
            out.append((x[:60] + '…', y[:60] + '…'))
            kinds.add(tag)
            continue
        for t, k1, k2, m1, m2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
            if t != 'equal':
                kinds.add(t)
                out.append((x[max(0, k1 - 12):k2 + 12], y[max(0, m1 - 12):m2 + 12]))
    return out[:limit], len(out), sorted(kinds)


def compare_text(api_text, page_text, field=None):
    """Classify the difference; the stored texts themselves are never changed."""
    a, b = squash(api_text), squash(page_text)
    if not a and not b:
        return {'status': 'absent'}
    if a and not b:
        return {'status': 'api-only', 'apiLength': len(a)}
    if b and not a:
        return {'status': 'page-only', 'pageLength': len(b)}
    if a == b:
        return {'status': 'equal', 'length': len(a)}
    used, na, nb = [], a, b
    for name, fn in NORMALIZERS:
        if name in FIELD_ONLY and field not in FIELD_ONLY[name]:
            continue
        ta, tb = squash(fn(na)), squash(fn(nb))
        if (ta, tb) != (na, nb):
            used.append(name)
            if name == 'entities':
                entities = sorted(set(re.findall(r'&#?\w+;', na)) | set(re.findall(r'&#?\w+;', nb)))
        na, nb = ta, tb
    result = {'normalized': used}
    if 'entities' in used:
        result['entities'] = entities
    if na == nb:
        return {'status': 'equal-after', 'length': len(na), **result}
    segments, count, kinds = segment_diff(na, nb)
    # 'insert' only: every remaining difference is text the page has and the API body lacks.
    return {'status': 'differ', **first_difference(na, nb), **result, 'segments': segments,
            'segmentCount': count, 'diffKinds': kinds, 'pageOnlyText': kinds == ['insert']}


def body_lines(record):
    """Line breaks of the longest reasons/full-text section (what the screen lays out)."""
    best = ''
    for section in record.get('sections') or []:
        if heading_name(section.get('heading')) in ('이유', '전문') and len(section.get('text') or '') > len(best):
            best = section.get('text') or ''
    return {'chars': len(best), 'newlines': best.count('\n')}


def registry_target(case):
    target = {key: case[key] for key in ('court', 'courtId', 'decisionDate', 'decisionType') if case.get(key)}
    target.update({'id': case['id'], 'caseNumber': case['caseNumber'],
                   'lookupKey': case.get('lookupKey') or lookup_key(case['caseNumber'])})
    return target


def load_base_from_git(rev):
    names = subprocess.run(['git', '-C', str(ROOT), 'ls-tree', '--name-only', rev, 'data/fetched/'],
                           check=True, capture_output=True, text=True, encoding='utf-8').stdout.split('\n')
    names = [n for n in names if re.fullmatch(r'data/fetched/[^/]+\.json', n) and not n.endswith('.missing.json')]
    proc = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '--batch'], input=''.join(f'{rev}:{n}\n' for n in names).encode('utf-8'),
                          check=True, capture_output=True)
    out, pos, records = proc.stdout, 0, {}
    for name in names:
        header_end = out.index(b'\n', pos)
        size = int(out[pos:header_end].split()[2])
        body = out[header_end + 1:header_end + 1 + size]
        pos = header_end + 1 + size + 1
        records[Path(name).stem] = json.loads(body.decode('utf-8'))
    return records


def load_base_from_dir(path):
    return {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in sorted(Path(path).glob('*.json'))
            if not p.name.endswith('.missing.json')}


def api_records(base, domain='constitutional'):
    return {key: rec for key, rec in base.items()
            if (rec.get('retrieval') or {}).get('method') == API_METHOD and (rec.get('retrieval') or {}).get('domain') == domain}


def parse_logs(paths):
    reasons = {}
    for path in paths or []:
        for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.match(r'\s*MISS\s+(\S+)\s+(.*)$', line)
            if match:
                reasons[match[1]] = match[2].strip()
    return reasons


def compare_one(rid, api, current, case, miss_reason=None):
    item = {'id': rid, 'caseNumber': (case or {}).get('caseNumber') or api.get('caseNumber'),
            'decisionDate': (case or {}).get('decisionDate'), 'seq': str(api.get('seq') or '')}
    if current is None:
        item.update(state='no-file', note='현재 수집본 파일이 없음')
        return item
    if (current.get('retrieval') or {}).get('method') == API_METHOD:
        item.update(state='not-refetched', note=miss_reason or '재수집되지 않음(기존 API 수집본 유지)',
                    lines=body_lines(current))
        return item
    item['state'] = 'refetched'
    item['lines'] = body_lines(current)
    problems = []
    if case is None:
        problems.append('등록부에 없는 id')
    else:
        kind, seq = current.get('kind'), str(current.get('seq') or '')
        result = finish(registry_target(case), kind, seq, direct_url(kind, seq), current, [])
        if not result['ok']:
            problems.append('식별 불일치: ' + result['reason'])
    if str(current.get('seq') or '') != item['seq']:
        problems.append(f"seq 변경 {item['seq']} → {current.get('seq')}")
    if current.get('sourceUrl') != api.get('sourceUrl'):
        problems.append('sourceUrl 변경')
    item['identity'] = 'ok' if not problems else 'problem'
    if problems:
        item['identityProblems'] = problems
    api_fields, api_full = split_fields(api)
    page_fields, page_full = split_fields(current)
    item['fields'] = {name: compare_text(api_fields.get(name, ''), page_fields.get(name, ''), name) for name in FIELDS}
    item['fields']['전문'] = compare_text(api_full, page_full, '전문')
    item['citation'] = {'api': api.get('citation'), 'page': current.get('citation')}
    return item


def run(base, fetched=FETCHED, registry=REGISTRY, reasons=None):
    cases = {c['id']: c for c in json.loads(Path(registry).read_text(encoding='utf-8'))['cases']}
    items = []
    for rid in sorted(base):
        path = Path(fetched) / (rid + '.json')
        current = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        items.append(compare_one(rid, base[rid], current, cases.get(rid), (reasons or {}).get(rid)))
    return items


SYMBOL = {'equal': '=', 'equal-after': '≈', 'differ': '**≠**', 'api-only': 'API만',
          'page-only': '페이지만', 'absent': '—'}
SHORT = {'entities': '참조', 'markers': '표지', 'middot': 'ㆍ', 'citation': '선고', 'tags': '태그'}


def summarize(items):
    total = len(items)
    refetched = [i for i in items if i['state'] == 'refetched']
    identity_ok = [i for i in refetched if i.get('identity') == 'ok']
    differ = [i for i in refetched if any(f['status'] == 'differ' for f in i['fields'].values())]
    one_line = [i for i in refetched if i['lines']['chars'] >= 1000 and i['lines']['newlines'] <= 2]
    return {'total': total, 'refetched': len(refetched), 'notRefetched': total - len(refetched),
            'identityOk': len(identity_ok), 'textDiffer': len(differ), 'stillOneLine': len(one_line)}


def cell(f):
    if f['status'] == 'equal-after':
        return '≈' + '·'.join(SHORT[n] for n in f['normalized'])
    return SYMBOL[f['status']]


def markdown(items):
    s = summarize(items)
    out = [BEGIN, '',
           f"대상 {s['total']}건 · 재수집 {s['refetched']}건 · 미재수집 {s['notRefetched']}건 · 식별 일치 {s['identityOk']}건 · "
           f"설명되지 않은 본문 차이가 남은 결정 {s['textDiffer']}건 · 재수집 후에도 한 줄 {s['stillOneLine']}건", '',
           '표기: `=` 공백·탭·줄바꿈을 빼면 글자 그대로 같음 · `≈…` 아래의 이미 설명된 차이만 있음(`참조` API 쪽 HTML 문자 참조 `&#183;` 등, '
           '`표지` 【…】 표지 위치, `ㆍ` API 가 가운뎃점 ㆍ(U+318D)를 ·(U+00B7) 등으로 바꿈, `선고` API 참조판례에서 "선고"·"판결" 빠짐, '
           '`태그` API 본문에 남은 `<NOTE>` 같은 태그) · '
           '`≠` 그 밖의 차이(아래 상세; "페이지에만 있는 구절"은 API 본문에서 빠진 글을 페이지가 담고 있다는 뜻) · '
           '`API만`/`페이지만` 한쪽에만 있음 · `—` 양쪽 모두 없음. '
           '전문 = API 【전문】 ↔ 페이지 【전문】부터 끝까지(소제목 포함). 줄바꿈 = 재수집본 이유(없으면 전문) 구역의 줄바꿈 수/글자 수. '
           '이 분류는 대조용 정규화일 뿐이며 저장된 글자는 바꾸지 않는다.', '']
    fields = FIELDS + ('전문',)
    out += ['### 필드별 집계', '', '| 필드 | ' + ' | '.join(['=', '≈', '≠', 'API만', '페이지만', '—']) + ' | ≈ 원인(건) |',
            '|---|---|---|---|---|---|---|---|']
    for name in fields:
        stats = [i['fields'][name] for i in items if i.get('fields')]
        counts = [sum(1 for f in stats if f['status'] == k) for k in ('equal', 'equal-after', 'differ', 'api-only', 'page-only', 'absent')]
        causes = {}
        for f in stats:
            for n in f.get('normalized', []) if f['status'] in ('equal-after', 'differ') else []:
                causes[n] = causes.get(n, 0) + 1
        out.append(f'| {name} | ' + ' | '.join(map(str, counts)) + ' | '
                   + ', '.join(f'{NORMALIZER_NOTES[n]} {v}' for n, v in causes.items()) + ' |')
    out.append('')
    problems = [i for i in items if i['state'] != 'refetched' or i.get('identity') != 'ok'
                or any(f['status'] in ('differ', 'api-only') for f in i['fields'].values())]
    out += ['### 확인 필요 (재수집 실패 · 식별 문제 · 설명되지 않은 차이 · API 에만 있는 필드)', '']
    if not problems:
        out.append('없음.')
    for i in problems:
        notes = []
        if i['state'] != 'refetched':
            notes.append(f"{i['state']}: {i.get('note')}")
        notes += i.get('identityProblems', [])
        for name, f in (i.get('fields') or {}).items():
            if f['status'] == 'differ':
                known = ('; 설명된 차이 ' + '·'.join(SHORT[n] for n in f['normalized'])) if f['normalized'] else ''
                clip = lambda text: (text[:70] + f'…(+{len(text) - 100}자)…' + text[-30:]) if len(text) > 110 else text
                segs = ' / '.join(f"API `{clip(x) or '∅'}` → 페이지 `{clip(y) or '∅'}`" for x, y in f['segments'])
                more = f" 외 {f['segmentCount'] - len(f['segments'])}곳" if f['segmentCount'] > len(f['segments']) else ''
                kind = '페이지에만 있는 구절(API 본문 누락) ' if f.get('pageOnlyText') else '글자 차이 '
                notes.append(f"{name} {kind}{f['segmentCount']}곳: {segs}{more}{known}")
            elif f['status'] == 'api-only':
                notes.append(f"{name}: API 에만 있음")
        out.append(f"- `{i['id']}` {i['caseNumber']} — " + '; '.join(notes))
    out += ['', '### 전체 표', '',
            '| id | 사건번호 | 선고일 | 재수집 | 식별 | 판시사항 | 결정요지 | 심판대상조문 | 참조조문 | 참조판례 | 전문 | 줄바꿈 |',
            '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for i in items:
        f = i.get('fields') or {}
        cells = [cell(f[n]) if n in f else '' for n in fields]
        lines = i.get('lines') or {}
        out.append(f"| `{i['id']}` | {i['caseNumber']} | {i.get('decisionDate') or ''} | "
                   f"{'성공' if i['state'] == 'refetched' else '실패'} | {i.get('identity', '—')} | " + ' | '.join(cells)
                   + f" | {lines.get('newlines', '')}/{lines.get('chars', '')} |")
    out += ['', END]
    return '\n'.join(out) + '\n'


def write_status(path, text):
    path = Path(path)
    if path.exists():
        old = path.read_text(encoding='utf-8')
        if BEGIN in old and END in old:
            text = old[:old.index(BEGIN)] + text.rstrip('\n') + old[old.index(END) + len(END):]
        else:
            text = old.rstrip('\n') + '\n\n' + text
    path.write_text(text, encoding='utf-8', newline='\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base-rev', default='734618a', help='git revision holding the API imports (default 734618a)')
    ap.add_argument('--backup', help='directory of API import backups instead of git')
    ap.add_argument('--domain', choices=('constitutional', 'precedent'), default='constitutional')
    ap.add_argument('--log', action='append', default=[], help='fetch_lawgo.py output to read MISS reasons from')
    ap.add_argument('--json', help='write the detailed JSON report here')
    ap.add_argument('--status', help='replace the generated block of this Markdown status file')
    a = ap.parse_args()
    base = load_base_from_dir(a.backup) if a.backup else load_base_from_git(a.base_rev)
    items = run(api_records(base, a.domain), reasons=parse_logs(a.log))
    if a.json:
        Path(a.json).write_text(json.dumps({'summary': summarize(items), 'items': items}, ensure_ascii=False, indent=1) + '\n',
                                encoding='utf-8', newline='\n')
    if a.status:
        write_status(a.status, markdown(items))
    print(json.dumps(summarize(items), ensure_ascii=False))
    for i in items:
        if i['state'] != 'refetched' or i.get('identity') != 'ok' or any(f['status'] == 'differ' for f in i['fields'].values()):
            print(' ', i['id'], i['state'], i.get('identityProblems') or i.get('note') or
                  {k: v['status'] for k, v in i['fields'].items() if v['status'] == 'differ'})


if __name__ == '__main__':
    main()
