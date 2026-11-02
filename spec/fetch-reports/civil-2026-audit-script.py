#!/usr/bin/env python3
"""민법 2026 개정판 추가 59배치 스크립트 감사(읽기 전용).

  python -X utf8 civ26_audit.py --root <통합 worktree> --out <audit.json> [--xlsx <xlsx>]

배치마다: 공식 수집본 위치(own/shared) · 완전성 · 공식 인용문 ↔ 등록부 메타 · 엑셀 원본 셀 ↔ 등록부 텍스트 ·
엑셀(제목·쟁점·요지·선정이유) 문장을 공식 본문에 정렬했을 때 글자 차이 · 공식 본문/엑셀의 서식·글자 깨짐 휴리스틱.
판정하지 않는다 — 차이 목록은 검수 에이전트가 읽고 반증자가 확인한다.
"""
import argparse, collections, difflib, json, os, re, sys, unicodedata

ap = argparse.ArgumentParser()
ap.add_argument('--root', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--xlsx', default='E:/Casebook_workspace/casebook-buildspace/data/standard-cases/2026_표준판례_2차_배포용.xlsx')
a = ap.parse_args()
ROOT = a.root
sys.path.insert(0, os.path.join(ROOT, 'tools'))
os.chdir(ROOT)
import build_data as B  # noqa: E402
import fetch_unit as FU  # noqa: E402
from case_identity import identity  # noqa: E402
import openpyxl  # noqa: E402

reg = json.load(open('data/registry.json', encoding='utf-8'))['cases']
by = {c['id']: c for c in reg}
civ = [c for c in reg if c['group'] == 'standard' and c['subject'] == 'civil']
new = [c for c in civ if 'standardPrevious' not in c]

fetched_by_id = B.load_fetched_records(reg)
identities = {c['id']: identity(c, (fetched_by_id[c['id']] or {}).get('citation', '')) for c in reg}
shared = B.shared_fetched_by_decision(reg, identities, fetched_by_id)

wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
ws = list(wb['민법'].iter_rows(values_only=True))

DOTS = str.maketrans({'・': '·', 'ᆞ': '·', '‧': '·', '∙': '·', '･': '·', '•': '·', '⋅': '·', 'ㆍ': '·', '·': '·'})
N = lambda t: re.sub(r'\s+', '', unicodedata.normalize('NFKC', t or '')).translate(DOTS)


def sec(f, *names):
    out = []
    for s in f['sections']:
        if any(n in s['heading'] for n in names):
            out.append(s['text'])
    return '\n'.join(out)


def clauses(text):
    parts = re.split(r'(?<=[.?!])\s+|\n+', text or '')
    return [p.strip() for p in parts if len(N(p)) >= 12]


def align(clause, official_norm):
    """clause(정규화) 를 공식 본문에 정렬 → (coverage, diffs). diffs: [(xlsx조각, 공식조각)]"""
    c = N(clause)
    sm = difflib.SequenceMatcher(None, c, official_norm, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 4]
    if not blocks:
        return 0.0, []
    cov = sum(b.size for b in blocks) / len(c)
    lo, hi = blocks[0].b, blocks[-1].b + blocks[-1].size
    span = official_norm[lo:hi]
    sm2 = difflib.SequenceMatcher(None, c[blocks[0].a:blocks[-1].a + blocks[-1].size], span, autojunk=False)
    diffs = []
    for tag, i1, i2, j1, j2 in sm2.get_opcodes():
        if tag == 'equal':
            continue
        ctxc = c[blocks[0].a:][max(0, i1 - 10):i2 + 10]
        ctxo = span[max(0, j1 - 10):j2 + 10]
        if max(i2 - i1, j2 - j1) > 12:
            continue   # 정렬 범위가 어긋난 큰 덩어리(발췌·생략)는 글자 오류 후보가 아니다
        diffs.append({'op': tag, 'xlsx': c[blocks[0].a:][i1:i2], 'official': span[j1:j2], 'xlsxCtx': ctxc, 'officialCtx': ctxo})
    return cov, diffs


XL_HEUR = [
    ('서식잔재(꺾쇠 표지)', re.compile(r'(쟁점|판결요지|판시사항|선정이유)>|<\s*(쟁점|판결요지|판시사항)\s*>')),
    ('마침표 뒤 공백 누락', re.compile(r'[가-힣]다\.[가-힣]')),
    ('같은 낱말 반복', re.compile(r'(?<![가-힣])([가-힣]{2,6})\s+\1(?![가-힣])')),
    ('장 제목 잔재', re.compile(r'\s(?:제\s*\d+\s*(?:편|장|절|관)|[IVXⅠ-Ⅹ]+\.)\s*[가-힣 ]{2,12}$')),
    ('글자 깨짐', re.compile(r'[\ufffd]|\?(?=[가-힣])|(?<=[가-힣])\?(?=[가-힣])')),
    ('이중 공백', re.compile(r'[가-힣]  +[가-힣]')),
]
OF_HEUR = [
    ('가운뎃점이 ? 로 깨짐', re.compile(r'(?<=[가-힣])\?(?=[가-힣])')),
    ('글자 깨짐(U+FFFD)', re.compile('\ufffd')),
    ('같은 낱말 반복', re.compile(r'(?<![가-힣])([가-힣]{2,6}) \1(?![가-힣])')),
    ('HTML 잔재', re.compile(r'&[a-z]+;|<br|</?p>|&#\d+;')),
    ('빈 괄호', re.compile(r'\(\s*\)|\[\s*\]')),
]


def heur(text, rules):
    hits = []
    for name, rx in rules:
        for m in rx.finditer(text or ''):
            s = max(0, m.start() - 15)
            hits.append({'rule': name, 'match': m.group(0)[:30], 'ctx': (text[s:m.end() + 15]).replace('\n', ' ')})
            if len(hits) > 40:
                return hits
    return hits


def bal(text):
    out = []
    for o, c in (('(', ')'), ('[', ']'), ('‘', '’'), ('“', '”'), ('「', '」')):
        if (text or '').count(o) != (text or '').count(c):
            out.append(f'{o}{c} 짝 불일치({text.count(o)}/{text.count(c)})')
    return out


results = []
for c in new:
    sid = c['id']
    did = identities[sid]['decisionId']
    own = fetched_by_id.get(sid)
    src_id, f = (sid, own) if own and own.get('sections') else (shared.get(did) or (None, None))
    row = c['standard'].get('row')
    r = {'id': sid, 'caseNumber': c['caseNumber'], 'date': c['decisionDate'], 'decisionType': c['decisionType'], 'enBanc': c['enBanc'], 'title': c['title'],
         'row': row, 'tocPath': c['tocPath'], 'officialFrom': src_id, 'officialFile': f'data/fetched/{src_id}.json' if src_id else None, 'flags': []}
    ss = c.get('standardSource') or {}
    xl = {'title': c['title'], 'issues': [i['text'] for i in ss.get('issues', [])], 'holdings': [h['text'] for h in ss.get('holdings', [])],
          'selectionReason': c.get('selectionReason', ''), 'keywords': c.get('keywords'), 'memo': c.get('memo')}
    # 엑셀 셀 ↔ 등록부
    cells = ws[row - 1] if row else None
    if cells:
        cell_title, cell_info, cell_issue, cell_reason, cell_hold = (cells[1], cells[2], cells[3], cells[4], cells[5])
        r['cell'] = {'title': str(cell_title or ''), 'info': str(cell_info or '')}
        chk = []
        if N(cell_title) != N(c['title']):
            chk.append('제목')
        if N(cell_reason) != N(c.get('selectionReason', '')):
            chk.append('선정이유')
        if N(cell_issue) != N(''.join(xl['issues'])) and N(cell_issue) and not N(''.join(xl['issues'])) == '':
            chk.append('쟁점')
        if N(cell_hold) != N(''.join(xl['holdings'])):
            chk.append('요지')
        r['cellMismatch'] = chk
        r['cellInfo'] = str(cell_info or '')
        r['cellIssue'] = str(cell_issue or '')
        r['cellHoldingLen'] = len(str(cell_hold or ''))
    r['xlsxHeuristics'] = {k: heur(v if isinstance(v, str) else '\n'.join(v or []), XL_HEUR) for k, v in xl.items() if k in ('title', 'selectionReason') or k in ('issues', 'holdings')}
    r['xlsxBalance'] = {k: bal(v if isinstance(v, str) else '\n'.join(v or [])) for k, v in xl.items() if k in ('title', 'selectionReason', 'issues', 'holdings')}
    r['xlsx'] = xl
    if not f:
        r['flags'].append('공식 수집본 없음')
        results.append(r)
        continue
    r['citation'] = f.get('citation')
    r['officialHeadings'] = [(s['heading'], len(s['text'])) for s in f['sections']]
    # 완전성
    reasons = sec(f, '이 유', '이유')
    order = sec(f, '주 문', '주문')
    summary = sec(f, '판결요지', '결정요지')
    r['completeness'] = {'reasonsChars': len(reasons), 'orderChars': len(order), 'summaryChars': len(summary), 'issuesChars': len(sec(f, '판시사항'))}
    if len(reasons) < 300:
        r['flags'].append('이유 부분이 없거나 매우 짧음(전문 누락 의심)')
    if not order:
        r['flags'].append('주문 없음')
    # 메타
    fl = FU.check_record(c, dict(f, id=src_id if src_id != sid else sid)) if f else []
    fl = [x for x in fl if not x.startswith('id 불일치')]
    r['metaFlags'] = fl
    # 정렬
    off_all = N(sec(f, '판시사항') + sec(f, '판결요지', '결정요지') + reasons)
    items = []
    for field, texts in (('쟁점', xl['issues']), ('요지', xl['holdings']), ('선정이유', [xl['selectionReason']]), ('제목', [xl['title']])):
        for t in texts:
            for cl in clauses(t) if field != '제목' else ([t] if len(N(t)) >= 8 else []):
                cov, diffs = align(cl, off_all)
                items.append({'field': field, 'clause': cl[:160], 'coverage': round(cov, 3), 'diffs': diffs[:6]})
    r['alignment'] = items
    r['lowCoverage'] = [i for i in items if i['coverage'] < 0.6 and i['field'] in ('쟁점', '요지')]
    r['diffItems'] = [i for i in items if i['coverage'] >= 0.6 and i['diffs']]
    # 이슈 유사도(식별 오류 판별): 엑셀 쟁점+요지 가 공식 판시사항+판결요지+이유 에 얼마나 들어있나
    xl_all = N(''.join(xl['issues']) + ''.join(xl['holdings']))
    if xl_all:
        sm = difflib.SequenceMatcher(None, xl_all[:1500], off_all[:60000], autojunk=False)
        r['contentCoverage'] = round(sum(b.size for b in sm.get_matching_blocks()) / len(xl_all[:1500]), 3)
    r['officialHeuristics'] = heur('\n'.join(s['text'] for s in f['sections']), OF_HEUR)
    results.append(r)

json.dump({'count': len(results), 'items': results}, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('audited', len(results))
low = [r for r in results if r.get('contentCoverage', 1) < 0.6]
print('low contentCoverage:', [(r['id'], r['contentCoverage']) for r in low])
print('meta flags:', [(r['id'], r['metaFlags']) for r in results if r.get('metaFlags')])
print('no official:', [r['id'] for r in results if not r['officialFile']])
print('cell mismatch:', [(r['id'], r['cellMismatch']) for r in results if r.get('cellMismatch')])
