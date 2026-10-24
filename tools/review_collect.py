#!/usr/bin/env python3
"""단계 3 판정 수거: _review_parts/*.jsonl 의 판정 줄을 검사해 _review.jsonl 에 덧붙인다(기존 줄은 지우지 않는다).

  python -X utf8 tools/review_collect.py --subject 상법 [--dir <과목폴더>] [--reviewer claude-opus-5-5]

검사: seq·decisionId·reason 이 pending 기록과 대응하는지, verdict 가 ok|fix|reject 인지, fix 면 fixedSections 가 비어 있지 않은지,
      textSha256 이 pending 기록과 같은지(다르면 md 가 바뀐 뒤의 판정이므로 버림). 통과한 줄만 덧붙이고 결과를 출력한다.
수거 후 `python -X utf8 tools/md_merge.py --subject <과목>` 을 다시 돌려 후보·표본 집계를 갱신한다.
"""
import argparse, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402
from review_prep import latest_reviews  # noqa: E402

VERDICTS = ('ok', 'fix', 'reject')


def matching_review(verdict, latest):
    """구형 ID 생략 판정은 후보가 정확히 하나일 때만 허용한다."""
    candidates = [(key, row) for key, row in latest.items()
                  if key[0] == verdict.get('seq') and key[2] == verdict.get('reason')]
    did, number = verdict.get('decisionId'), verdict.get('caseNumber')
    if did:
        exact = [(key, row) for key, row in candidates if row.get('decisionId') == did]
        if exact:
            candidates = exact
        else:
            # 명시된 다른 재판의 결과를 현재 재판에 붙이지 않는다.
            candidates = ([(key, row) for key, row in candidates if not row.get('decisionId')]
                          if number or len(candidates) == 1 else [])
    if number:
        candidates = [(key, row) for key, row in candidates if not row.get('caseNumber') or row['caseNumber'] == number]
    if len(candidates) != 1:
        raise ValueError('대응 재판 없음' if not candidates else 'decisionId 없는 판정의 대응 재판이 여러 개임')
    return candidates[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--subject', required=True)
    ap.add_argument('--dir')
    ap.add_argument('--reviewer', default='')
    a = ap.parse_args(argv)
    sid, d = L.subject_dir(a.subject, a.dir)
    rpath = os.path.join(d, '_review.jsonl')
    rows = L.read_jsonl(rpath)
    try:
        latest = latest_reviews(rows)
    except ValueError as exc:
        print(f'ERROR - {exc}'); return 1
    accepted, rejected, seen = [], [], set()
    for f in sorted(glob.glob(os.path.join(d, '_review_parts', '*.jsonl'))):
        with open(f, encoding='utf-8') as stream:
            lines = stream.readlines()
        for n, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except Exception as ex:
                rejected.append((f, n, f'JSON 오류 {ex}')); continue
            try:
                key, base = matching_review(v, latest)
            except ValueError as exc:
                rejected.append((f, n, f'{exc} {(v.get("seq"), v.get("decisionId"), v.get("reason"))}')); continue
            if base.get('verdict', 'pending') != 'pending' and key in seen:
                rejected.append((f, n, f'중복 판정 {key}')); continue
            if base.get('verdict', 'pending') != 'pending' and base.get('verdict') == v.get('verdict') and (base.get('note') or '') == (v.get('note') or '') \
                    and (base.get('fixedSections') or {}) == (v.get('fixedSections') or {}) and (base.get('title') or '') == (v.get('title') or ''):
                continue          # 이미 같은 판정이 수거되어 있음(재실행 시 중복 기록 방지)
            if v.get('verdict') not in VERDICTS:
                rejected.append((f, n, f'verdict 오류 {v.get("verdict")!r} {key}')); continue
            if v.get('reason') != 'title':
                if v.get('textSha256') and base.get('textSha256') and v['textSha256'] != base['textSha256']:
                    rejected.append((f, n, f'textSha256 불일치(md 가 바뀐 뒤의 판정) {key}')); continue
                if v['verdict'] == 'fix' and not (isinstance(v.get('fixedSections'), dict) and v['fixedSections']):
                    rejected.append((f, n, f'fix 인데 fixedSections 비어 있음 {key}')); continue
            out = dict(base)
            if not out.get('decisionId') and v.get('decisionId'):
                out['decisionId'] = v['decisionId']
            out.update({k: v.get(k) for k in ('verdict', 'note', 'fixedSections', 'title', 'reviewer', 'reviewedAt') if k in v})
            out['reviewer'] = v.get('reviewer') or a.reviewer or base.get('reviewer') or ''
            out['reviewedAt'] = v.get('reviewedAt') or L.today()
            if v.get('reason') == 'title':
                out.pop('fixedSections', None)
                out['title'] = (v.get('title') or '').strip()
            else:
                out.setdefault('fixedSections', {})
                if out['verdict'] != 'fix':
                    out['fixedSections'] = {}
            accepted.append(out); seen.add(key); latest[key] = out
    if accepted:
        L.append_jsonl(rpath, accepted)
    by = {}
    for r in accepted:
        by[(r.get('reason'), r['verdict'])] = by.get((r.get('reason'), r['verdict']), 0) + 1
    print(f'[{sid}] 판정 수거: 채택 {len(accepted)}줄, 거부 {len(rejected)}줄 → {rpath}')
    for k in sorted(by):
        print(f'  {k[0]}/{k[1]}: {by[k]}')
    for f, n, why in rejected[:20]:
        print(f'  거부 {os.path.basename(f)}:{n} {why}')
    print(json.dumps({'subject': sid, 'accepted': len(accepted), 'rejected': len(rejected)}, ensure_ascii=False))
    return 0 if not rejected else 1


if __name__ == '__main__':
    sys.exit(main())
