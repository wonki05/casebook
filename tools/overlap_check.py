#!/usr/bin/env python3
"""겹침 재판 종합 결과(out/<decisionId>.json)를 검증하고, 두 과목 배치에 붙일 standardSource JSON 을 만든다.

  python -X utf8 tools/overlap_check.py [--dir data/standard-cases/_overlaps]

검증: 각 issues/holdings/statutes 항목의 text 가 두 PDF 중 적어도 한 책의 해당 절(또는 그 쪽 텍스트)에 정규화 후 **연속 부분 문자열**로 존재해야 한다(글자 그대로 규칙).
      통과하지 못한 항목은 버리고 보고한다. 하나도 남지 않으면 그 재판은 종합 없음(각 과목 배치는 standardSource 없이 등록).
출력: _overlaps/final/<decisionId>.json = {"decisionId", "text": {issues, holdings, statutes}, "placements": [{"subject", "standardSource": {...validate_standard_source 통과...}}], "report": {...}}
      두 배치의 standardSource 는 텍스트가 같고(build 가 출처를 합친다) book/file/pages 만 각자 것이다. reviewer 에 종합 출처를 적는다.
"""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402
from case_identity import validate_standard_source  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def haystacks(bundle):
    """책별 정규화 텍스트: 절 텍스트들 + 쪽 원문(머리글 제거) 연결."""
    hs = {}
    for b in bundle['books']:
        parts = [L.normalize(v) for v in (b.get('sections') or {}).values() if v]
        parts.append(L.normalize('\n'.join(p['text'] for p in b.get('pdfText') or [])))
        hs[b['subject']] = parts
    return hs


def verbatim(text, hs):
    n = L.normalize(text or '')
    if not n:
        return []
    return [subj for subj, parts in hs.items() if any(n in p for p in parts)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default=os.path.join(ROOT, 'data', 'standard-cases', '_overlaps'))
    ap.add_argument('--reviewer', help='실제 종합 검토자; 생략하면 출력 또는 기존 검증본 기록 유지')
    ap.add_argument('--only', action='append', default=[], help='지정 decisionId만 검증')
    ap.add_argument('--require-complete', action='store_true', help='모든 입력에 출력이 있는지 확인')
    a = ap.parse_args(argv)
    d = os.path.abspath(a.dir)
    fin = os.path.join(d, 'final'); os.makedirs(fin, exist_ok=True)
    ok_n = drop_n = none_n = errors = 0
    inputs = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(d, 'in', '*.json'))}
    outputs = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(d, 'out', '*.json'))}
    missing = (inputs - outputs) if a.require_complete else (set(a.only) - outputs)
    for did in sorted(missing):
        print('종합 출력 없음:', did)
        errors += 1
    for p in sorted(glob.glob(os.path.join(d, 'out', '*.json'))):
        did = os.path.basename(p)[:-5]
        if a.only and did not in a.only:
            continue
        bundle_path = os.path.join(d, 'in', f'{did}.json')
        if not os.path.exists(bundle_path):
            print('입력 묶음 없음:', did); errors += 1; continue
        bundle = json.load(open(bundle_path, encoding='utf-8'))
        out = json.load(open(p, encoding='utf-8'))
        if bundle.get('decisionId') != did or out.get('decisionId') != did:
            print('decisionId 불일치:', did); errors += 1; continue
        reviewer = a.reviewer or out.get('reviewer')
        existing = os.path.join(fin, f'{did}.json')
        if not reviewer and os.path.exists(existing):
            prior = json.load(open(existing, encoding='utf-8'))
            placements = prior.get('placements') or []
            if placements:
                reviewer = (placements[0].get('standardSource', {}).get('reviewer') or '').split('; 종합 출처:')[0]
        reviewer = reviewer or 'reviewer unspecified + script verbatim check'
        hs = haystacks(bundle)
        kept, dropped = {}, []
        for field in ('issues', 'holdings', 'statutes'):
            items = out.get(field) or []
            keep = []
            for it in items:
                text = it.get('text') if isinstance(it, dict) else it
                srcs = verbatim(text, hs)
                if srcs:
                    keep.append({'n': (it.get('n') if isinstance(it, dict) else '') or '', 'text': text.strip(), 'from': srcs})
                else:
                    dropped.append({'field': field, 'text': (text or '')[:80]})
            kept[field] = keep
        if not (kept['issues'] or kept['holdings']):
            none_n += 1
            drop_n += len(dropped)
            L.write_json(os.path.join(fin, f'{did}.json'), {'decisionId': did, 'text': None, 'placements': [], 'report': {'dropped': dropped, 'note': '검증 통과 항목 없음 — standardSource 없이 등록'}})
            print(f'{did}: 종합 없음 (버린 항목 {len(dropped)})'); continue
        placements = []
        used_pages = {b['subject']: sorted(set(b.get('pdfPages') or [])) for b in bundle['books']}
        srcs_desc = ' + '.join(f"{b['subject']} p.{','.join(map(str, used_pages[b['subject']]))}" for b in bundle['books'])
        for b in bundle['books']:
            src = {'verified': True, 'book': b['book'], 'edition': b['edition'], 'file': b['file'], 'pages': used_pages[b['subject']],
                   'holdings': [{'n': x['n'], 'text': x['text']} for x in kept['holdings']] if kept['holdings'] else None,
                   'issues': [{'n': x['n'], 'text': x['text']} for x in kept['issues']] if kept['issues'] else None,
                   'statutes': [x['text'] for x in kept['statutes']] if kept['statutes'] else None,
                   'reviewer': f"{reviewer}; 종합 출처: {srcs_desc}", 'reviewedAt': L.today()}
            src = {k: v for k, v in src.items() if v is not None}
            validate_standard_source(src)
            placements.append({'subject': b['subject'], 'seq': b['seq'], 'no': b['no'], 'title': b['title'], 'standardSource': src})
        drop_n += len(dropped); ok_n += 1
        L.write_json(os.path.join(fin, f'{did}.json'), {'decisionId': did, 'text': kept, 'placements': placements,
                                                        'report': {'dropped': dropped, 'excluded': out.get('excluded'), 'officialComparison': out.get('officialComparison'), 'confidence': out.get('confidence'), 'note': out.get('note')}})
        print(f"{did}: issues {len(kept['issues'])} holdings {len(kept['holdings'])} statutes {len(kept['statutes'])} | 버림 {len(dropped)} | {out.get('confidence')}")
    print(f'종합 완료 {ok_n}건, 종합 없음 {none_n}건, 버린 항목 {drop_n}개 → {fin}')

    return 1 if errors or drop_n or none_n else 0


if __name__ == '__main__':
    sys.exit(main())
