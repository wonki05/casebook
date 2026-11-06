#!/usr/bin/env python3
"""헌법재판소 주요결정(또는 다른 최신판례 페이지) 배치의 판시사항·요지 표시 출처 점검.

  python tools/check_ccourt_page_summary.py                 # ccourt 페이지 요약 + 표 (data/cases.json 을 먼저 빌드: make data)
  python tools/check_ccourt_page_summary.py --page enbanc   # 다른 페이지(enbanc | annual | ccourt)
  python tools/check_ccourt_page_summary.py --all           # 표시 출처가 정상인 배치까지 표에 모두
  python tools/check_ccourt_page_summary.py --json out.json # 기계용 결과
  python tools/check_ccourt_page_summary.py --strict        # 아무것도 못 보여 주는 배치·근거 없는 편집 요약이 있으면 종료코드 1

배치마다 다음을 나열한다.
  shown              판시사항 / 결정요지에 실제로 쓰인 출처 (official | supplemental | standard | editorial | missing)
  standard           같은 재판의 표준판례 배치 id (isStandard)
  override           등록부의 summarySource (standard | official) — 페이지 기본값을 덮어쓴 배치
  표시(flag)         titleSameAsStandard  제목이 표준판례 배치 제목과 같음 (단원용 제목이 재판 전체를 나타내는지 확인)
                     titleIsCaseName      제목이 공식 사건명 그대로 (학습용 제목이 아님)
                     standardWithoutOfficial  표준판례와 겹치는데 공식 판시사항·요지가 없어 표준판례 발췌로 대신 보임
                     noSummary            공식·표준판례·편집 요약이 모두 없어 판시사항·요지가 비어 있음
                     editorialWithoutBasis  편집 요약에 근거 자료(basis)가 없음
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = os.path.join(ROOT, 'data', 'cases.json')
REG = os.path.join(ROOT, 'data', 'registry.json')
FLAGS = ('titleSameAsStandard', 'titleIsCaseName', 'standardWithoutOfficial', 'noSummary', 'editorialWithoutBasis')
STRICT_FLAGS = ('noSummary', 'editorialWithoutBasis')


def source_of(rec, field):
    info = (rec.get('fieldSources') or {}).get(field) or {}
    return info.get('type') or 'missing'


def inspect(page, cases, registry):
    by_id = {c['id']: c for c in cases}
    reg_by_id = {c['id']: c for c in registry}
    rows = []
    for rec in cases:
        if rec.get('page') != page:
            continue
        placements = rec.get('standardPlacements') or []
        std_titles = {p['title'] for p in placements}
        official = rec.get('officialSummary') or {}
        has_official = bool(official.get('issues') or official.get('holdings'))
        shown = {'issues': source_of(rec, 'issues'), 'holdings': source_of(rec, 'holdings')}
        editorial_basis = any((rec.get('fieldSources') or {}).get(f, {}).get('basis') for f in ('issues', 'holdings'))
        flags = {
            'titleSameAsStandard': bool(rec.get('title')) and rec['title'] in std_titles,
            'titleIsCaseName': bool(rec.get('caseName')) and rec.get('title') == rec.get('caseName'),
            'standardWithoutOfficial': bool(rec.get('isStandard')) and not has_official,
            'noSummary': shown['issues'] == 'missing' and shown['holdings'] == 'missing',
            'editorialWithoutBasis': 'editorial' in shown.values() and not editorial_basis,
        }
        rows.append({
            'id': rec['id'], 'caseNumber': rec.get('caseNumber'), 'decisionDate': rec.get('decisionDate'), 'title': rec.get('title'),
            'caseName': rec.get('caseName', ''), 'shown': shown, 'summaryType': rec.get('summaryType'),
            'precedence': rec.get('summaryPrecedence'), 'override': (reg_by_id.get(rec['id']) or {}).get('summarySource'),
            'isStandard': bool(rec.get('isStandard')), 'standard': [p['id'] for p in placements],
            'standardTitles': [p['title'] for p in placements], 'hasOfficialSummary': has_official,
            'flags': [name for name in FLAGS if flags[name]],
        })
    return rows


def summary(rows):
    counts = {'placements': len(rows), 'isStandard': sum(r['isStandard'] for r in rows), 'override': sum(1 for r in rows if r['override'])}
    for key in ('issues', 'holdings'):
        counts[f'shown.{key}'] = {}
        for r in rows:
            counts[f'shown.{key}'][r['shown'][key]] = counts[f'shown.{key}'].get(r['shown'][key], 0) + 1
    for name in FLAGS:
        counts[name] = sum(1 for r in rows if name in r['flags'])
    return counts


def markdown(rows, show_all):
    lines = ['| id | 사건번호 | 선고일 | 제목 | 판시사항 / 요지 출처 | 표준판례 배치 | 덮어쓰기 | 표시 |', '|---|---|---|---|---|---|---|---|']
    for r in rows:
        if not show_all and not r['flags']:
            continue
        lines.append('| {id} | {caseNumber} | {decisionDate} | {title} | {i} / {h} | {std} | {ov} | {flags} |'.format(
            id=r['id'], caseNumber=r['caseNumber'], decisionDate=r['decisionDate'], title=(r['title'] or '').replace('|', '｜'),
            i=r['shown']['issues'], h=r['shown']['holdings'], std=', '.join(r['standard']) or '-', ov=r['override'] or '-',
            flags=', '.join(r['flags']) or '-'))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--page', default='ccourt', help='점검할 페이지 id (기본 ccourt; enbanc, annual 도 가능)')
    ap.add_argument('--all', action='store_true', help='표시가 없는 배치도 표에 포함')
    ap.add_argument('--json', help='결과를 JSON 파일로 저장')
    ap.add_argument('--strict', action='store_true', help=f'{", ".join(STRICT_FLAGS)} 가 하나라도 있으면 종료코드 1')
    a = ap.parse_args(argv)
    if not os.path.exists(CASES):
        print('data/cases.json 이 없습니다 — 먼저 python tools/make.py data', file=sys.stderr)
        return 2
    cases = json.load(open(CASES, encoding='utf-8'))['cases']
    registry = json.load(open(REG, encoding='utf-8'))['cases']
    rows = inspect(a.page, cases, registry)
    counts = summary(rows)
    print(f"[{a.page}] 배치 {counts['placements']}건 · 표준판례와 같은 재판 {counts['isStandard']}건 · 출처 덮어쓰기 {counts['override']}건")
    print(f"  판시사항 출처: {counts['shown.issues']}")
    print(f"  결정요지 출처: {counts['shown.holdings']}")
    for name in FLAGS:
        ids = [r['id'] for r in rows if name in r['flags']]
        print(f"  {name}: {len(ids)}" + (f" — {', '.join(ids[:12])}{' …' if len(ids) > 12 else ''}" if ids else ''))
    print()
    print(markdown(rows, a.all))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as out:
            json.dump({'page': a.page, 'summary': counts, 'rows': rows}, out, ensure_ascii=False, indent=1)
        print(f'\nJSON: {a.json}')
    bad = [r['id'] for r in rows if any(f in r['flags'] for f in STRICT_FLAGS)]
    if a.strict and bad:
        print(f'\nSTRICT: {len(bad)}건 — {", ".join(bad[:20])}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
