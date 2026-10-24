#!/usr/bin/env python3
"""단계 4 과목 실행기 — main 작업 폴더에서 한 과목을 등록부에 반영한다(spec/STAGE4-pdf2md.md 의 1 절을 자동화).

  python -X utf8 tools/stage4_subject.py --subject 헌법 [--overlap-final data/standard-cases/_overlaps/final] [--dry-run] [--skip-toc]

전제: 과목 브랜치가 main 에 병합되어 data/standard-cases/<과목>/ 에 entries.jsonl·_review.jsonl·skeleton.json·toc-proposed.json 이 있다.
순서:
  1) toc 교체 — skeleton 의 tocPath 가 proposed 이면 `add_cases.py toc replace --subject … --from toc-proposed.json` (경로를 잃는 사건을 기록)
  2) md_merge 재생성(새 toc·등록부 기준, --overlap-final 적용) → --check 오류 0
  3) add_cases.py add --from candidates (status ok 만 등록; 같은 과목의 같은 재판은 add 가 거름)
  4) standard_source_backfill — 이미 등록돼 있던 같은 재판(시안·전원합의체·헌법재판소 등)에 표준판례 출처 붙이기
  5) 1) 에서 경로를 잃은 사건의 tocPath 를 같은 재판 후보의 tocPath 로 다시 지정(set --toc)
  6) validate — 오류 0 확인
결과 요약을 JSON 으로 출력한다. 실패하면 그 단계에서 멈추고 종료코드 1.
"""
import argparse, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from subjects import resolve_standard, BY_ID  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, '-X', 'utf8']


def run(cmd, check=True):
    print('$', ' '.join(os.path.relpath(c, ROOT) if os.path.isabs(c) and c.startswith(ROOT) else c for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    out = (r.stdout or '') + (r.stderr or '')
    print(out[-3000:])
    if check and r.returncode:
        raise SystemExit(f'실패(exit {r.returncode})')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--subject', required=True)
    ap.add_argument('--overlap-final', default=os.path.join(ROOT, 'data', 'standard-cases', '_overlaps', 'final'))
    ap.add_argument('--skip-toc', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='toc 교체·등록·set 을 실제로 하지 않고 명령만 출력')
    a = ap.parse_args(argv)
    sid = resolve_standard(a.subject)
    ko = BY_ID[sid]['folder']
    d = os.path.join(ROOT, 'data', 'standard-cases', ko)
    for f in ('entries.jsonl', 'skeleton.json', '_review.jsonl'):
        if not os.path.exists(os.path.join(d, f)):
            raise SystemExit(f'{f} 없음 — 먼저 git merge pdf2md-{sid}')
    skel = json.load(open(os.path.join(d, 'skeleton.json'), encoding='utf-8'))
    proposed = sum(1 for e in skel['entries'] if e.get('tocPathStatus') == 'proposed')
    summary = {'subject': sid, 'tocReplaced': False, 'clearedCases': [], 'added': 0, 'backfilled': None, 'tocFixed': [], 'validate': None}
    add_cases = os.path.join(ROOT, 'tools', 'add_cases.py')

    # 1) toc 교체
    if proposed and not a.skip_toc:
        tp = os.path.join(d, 'toc-proposed.json')
        out = run(PY + [add_cases, 'toc', 'replace', '--subject', sid, '--from', tp] + (['--dry-run'] if a.dry_run else []))
        summary['tocReplaced'] = not a.dry_run
        summary['clearedCases'] = re.findall(r'tocPath 비움 → (\S+) ', out)
    # 2) md_merge 재생성 + check
    merge = [os.path.join(ROOT, 'tools', 'md_merge.py'), '--subject', sid, '--dir', d]
    if a.overlap_final and os.path.isdir(a.overlap_final):
        merge += ['--overlap-final', a.overlap_final]
    run(PY + merge)
    run(PY + merge + ['--check'])
    cand_path = os.path.join(d, f'candidates-{sid}.json')
    cands = json.load(open(cand_path, encoding='utf-8'))['candidates']
    ok_cands = [c for c in cands if c['status'] == 'ok']
    print(f'후보 ok {len(ok_cands)} / review {sum(1 for c in cands if c["status"] == "review")} / skip {sum(1 for c in cands if c["status"] == "skip")}')
    if a.dry_run:
        print(json.dumps(summary, ensure_ascii=False)); return 0
    # 3) 등록
    before = len(json.load(open(os.path.join(ROOT, 'data', 'registry.json'), encoding='utf-8'))['cases'])
    run(PY + [add_cases, 'add', '--from', cand_path])
    after = len(json.load(open(os.path.join(ROOT, 'data', 'registry.json'), encoding='utf-8'))['cases'])
    summary['added'] = after - before
    # 4) 기등록 재판에 표준판례 출처
    out = run(PY + [os.path.join(ROOT, 'tools', 'standard_source_backfill.py'), '--candidates', cand_path], check=False)
    summary['backfilled'] = out.strip().splitlines()[0] if out.strip() else ''
    # 5) 경로 잃은 사건의 tocPath 재지정
    if summary['clearedCases']:
        reg = json.load(open(os.path.join(ROOT, 'data', 'registry.json'), encoding='utf-8'))['cases']
        by_did = {}
        for c in cands:
            if c.get('decisionId') and c.get('tocPath'):
                by_did.setdefault(c['decisionId'], c['tocPath'])
        for cid in summary['clearedCases']:
            rc = next((x for x in reg if x['id'] == cid), None)
            path = by_did.get(rc.get('decisionId')) if rc else None
            if path:
                run(PY + [add_cases, 'set', cid, '--toc', '/'.join(path)])
                summary['tocFixed'].append((cid, path))
            else:
                print(f'경로를 정하지 못함(수동): {cid}')
    # 6) validate
    out = run(PY + [add_cases, 'validate'], check=False)
    m = re.search(r'오류 (\d+)개', out)
    summary['validate'] = int(m.group(1)) if m else None
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary['validate'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
