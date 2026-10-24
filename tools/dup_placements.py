#!/usr/bin/env python3
"""PDF 가 같은 재판을 여러 항목에 실었다는 이유로 등록하지 못한 항목(md_merge 의 "같은 재판 중복" skip)을
같은 과목의 다른 배치로 등록한다.

  python -X utf8 tools/dup_placements.py --subject 민법 [--dry-run]

- 배치 정보(제목·목차 경로·선정이유·키워드)만 등록하고 standardSource 는 붙이지 않는다. 재판의 표준판례 텍스트는 같은 decisionId 의 첫 배치에
  한 번만 있고, build_data 가 decisionId 로 모든 배치에 적용한다. 건너뛴 항목에만 있는 문구(쟁점 등)는 항목별 판정(검토메모 전수 판정 원칙)을
  거친 뒤 검증된 구절의 합집합으로 더한다.
- 같은 과목에 같은 제목의 배치가 이미 있으면 제목 뒤에 단원 이름을 붙여 구별한다("제목：단원"). 제목이 같지 않아야 add_cases.py 가 받는다.
- 첫 배치가 등록부에 없거나, 목차 경로가 확인되지 않거나, 항목이 여러 재판이거나, md 에 항목이 없으면 등록하지 않고 보고서에 남긴다.
- 등록은 add_cases.py add 를 통해서만 한다. 보고서: data/standard-cases/_reports/dup-placements-<과목id>.json
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402
import md_merge as M  # noqa: E402
import subjects  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REASON = '같은 재판 중복'


def toc_labels(toc, sid):
    out = {}

    def rec(nodes):
        for n in nodes or []:
            out[n['id']] = n['label']
            rec(n.get('children'))
    rec(toc.get(sid))
    return out


def unit_name(label):
    """'제6절 매매' → '매매' (장·절·관 번호는 떼고 이름만)."""
    return re.sub(r'^제\s*\d+\s*(?:편|장|절|관|款)\s*', '', label or '').strip() or (label or '')


def plan(subject, root=ROOT):
    sid = subject if subject in subjects.BY_ID else next(s['id'] for s in subjects.SUBJECTS if s['label'] == subject or s.get('folder') == subject)
    folder = subjects.BY_ID[sid]['folder']
    d = os.path.join(root, 'data', 'standard-cases', folder)
    reg = json.load(open(os.path.join(root, 'data', 'registry.json'), encoding='utf-8'))['cases']
    toc = json.load(open(os.path.join(root, 'data', 'toc.json'), encoding='utf-8'))
    tids, labels = M.toc_ids(toc, sid), toc_labels(toc, sid)
    rows = {r['seq']: r for r in L.read_jsonl(os.path.join(d, 'entries.jsonl'))}
    cands = json.load(open(os.path.join(d, f'candidates-{sid}.json'), encoding='utf-8'))['candidates']
    by_did = collections.defaultdict(list)
    for c in reg:
        if c['group'] == 'standard' and c['subject'] == sid:
            by_did[c['decisionId']].append(c)
    titles = collections.defaultdict(set)
    for did, xs in by_did.items():
        titles[did] = {x['title'].strip() for x in xs}
    todo, skipped = [], []
    for c in sorted(cands, key=lambda x: x['seq']):
        if c['status'] != 'skip' or not (c.get('statusReason') or '').startswith(REASON):
            continue
        row = rows.get(c['seq']) or {}
        why = None
        primary = by_did.get(c['decisionId'])
        if not primary:
            why = '같은 과목에 첫 배치가 등록부에 없음'
        elif row.get('missing'):
            why = 'md 에 항목 없음'
        elif len(row.get('cases') or []) > 1:
            why = '한 항목에 재판이 여럿(첫 재판만 후보)'
        elif not c.get('title'):
            why = '제목 없음'
        elif not M.valid_toc_path(c['tocPath'], tids):
            why = f"목차 경로 확인 불가 {c['tocPath']}"
        if why:
            skipped.append({'seq': c['seq'], 'no': c['no'], 'caseNumber': c['caseNumber'], 'title': c['title'], 'reason': why})
            continue
        title = c['title'].strip()
        if title in titles[c['decisionId']]:
            title = f"{title}：{unit_name(labels.get(c['tocPath'][-1]))}"
            if title in titles[c['decisionId']]:
                skipped.append({'seq': c['seq'], 'no': c['no'], 'caseNumber': c['caseNumber'], 'title': c['title'], 'reason': '단원 이름을 붙여도 제목이 같음'})
                continue
        titles[c['decisionId']].add(title)
        clean = row.get('verify', {}).get('status') == 'pass'
        first = primary[0]
        memo = [x for x in [c.get('memo') if clean else '', f"같은 재판의 다른 배치: {first['title']} ({first['id']}) — PDF {c['no']}번 항목, p.{(c.get('pdfPages') or ['?'])[0]}"] if x]
        entry = {k: c.get(k) for k in ('caseNumber', 'lookupKey', 'court', 'decisionType', 'date', 'enBanc', 'tocPath', 'tags')}
        entry.update(title=title, status='ok', memo=' / '.join(memo),
                     selectionReason=c.get('selectionReason', '') if clean else '', keywords=c.get('keywords', []) if clean else [])
        todo.append(dict(entry, _seq=c['seq'], _no=c['no'], _primary=[x['id'] for x in primary]))
    return sid, folder, todo, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--subject', required=True, help='과목 id 또는 한글명')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    sid, folder, todo, skipped = plan(a.subject)
    print(f"{folder}: 등록할 중복 배치 {len(todo)}건, 건너뜀 {len(skipped)}건")
    for s in skipped:
        print(f"  건너뜀 {s['no']}번 {s['caseNumber']} — {s['reason']}")
    if a.dry_run:
        for t in todo:
            print(f"  {t['_no']}번 {t['caseNumber']} 「{t['title']}」 {'/'.join(t['tocPath'])} ← {', '.join(t['_primary'])}")
        return
    reg_path = os.path.join(ROOT, 'data', 'registry.json')
    before = {c['id'] for c in json.load(open(reg_path, encoding='utf-8'))['cases']}
    src = os.path.join(ROOT, 'data', 'standard-cases', folder, 'candidates-dup-placements.json')
    json.dump({'group': 'standard', 'subject': sid, 'candidates': [{k: v for k, v in t.items() if not k.startswith('_')} for t in todo]},
              open(src, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'tools', 'add_cases.py'), 'add', '--from', src, '--group', 'standard', '--subject', sid],
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    print(r.stdout.strip()); print(r.stderr.strip())
    if r.returncode:
        sys.exit(r.returncode)
    after = json.load(open(reg_path, encoding='utf-8'))['cases']
    new = [c for c in after if c['id'] not in before]
    mapping = [{'id': c['id'], 'caseNumber': c['caseNumber'], 'title': c['title'], 'tocPath': c['tocPath'], 'decisionId': c['decisionId']} for c in new]
    rep = os.path.join(ROOT, 'data', 'standard-cases', '_reports', f'dup-placements-{sid}.json')
    json.dump({'subject': sid, 'registered': mapping, 'skipped': skipped,
               'note': '배치 정보만 등록(standardSource 없음). 표준판례 텍스트는 같은 decisionId 의 첫 배치 것을 build_data 가 적용한다. 건너뛴 항목에만 있는 문구는 판정 후 합집합으로 더한다.'},
              open(rep, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'등록 {len(new)}건 → {os.path.relpath(rep, ROOT)}')


if __name__ == '__main__':
    main()
