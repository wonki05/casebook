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
import argparse, copy, json, os, re, subprocess, sys
from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from subjects import resolve_standard, BY_ID  # noqa: E402
import md_merge  # noqa: E402
from pdf2md_lib import read_json  # noqa: E402

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


def report_candidates(cands, summary, new_reviews=0):
    counts = {status: sum(c['status'] == status for c in cands) for status in ('ok', 'review', 'skip')}
    summary['candidates'] = counts
    summary['review'] = [{'seq': c['seq'], 'decisionId': c.get('decisionId'), 'reason': c['statusReason']}
                         for c in cands if c['status'] == 'review']
    print(f'후보 ok {counts["ok"]} / review {counts["review"]} / skip {counts["skip"]}')
    for item in summary['review']:
        print(f'  등록 보류 seq {item["seq"]} {item["decisionId"]}: {item["reason"]}')
    if counts['review'] and not counts['ok']:
        raise SystemExit('등록 가능한 후보가 0건입니다 — 과목 전체를 건너뛰지 않고 중단합니다')
    if new_reviews:
        raise SystemExit(f'새 판정 대상 {new_reviews}건이 발견되었습니다 — 검토를 마친 뒤 등록하세요')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--subject', required=True)
    ap.add_argument('--overlap-final', default=os.path.join(ROOT, 'data', 'standard-cases', '_overlaps', 'final'))
    ap.add_argument('--skip-toc', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='제안 목차를 메모리에서 반영해 사전 검사; 어떤 데이터 파일도 저장하지 않음')
    a = ap.parse_args(argv)
    sid = resolve_standard(a.subject)
    ko = BY_ID[sid]['folder']
    d = os.path.join(ROOT, 'data', 'standard-cases', ko)
    for f in ('entries.jsonl', 'skeleton.json', '_review.jsonl'):
        if not os.path.exists(os.path.join(d, f)):
            raise SystemExit(f'{f} 없음 — 먼저 git merge pdf2md-{sid}')
    skel = read_json(os.path.join(d, 'skeleton.json'))
    proposed = sum(1 for e in skel['entries'] if e.get('tocPathStatus') == 'proposed')
    summary = {'subject': sid, 'tocReplaced': False, 'clearedCases': [], 'added': 0, 'backfilled': None, 'tocFixed': [], 'validate': None}
    add_cases = os.path.join(ROOT, 'tools', 'add_cases.py')

    # 등록부·목차를 바꾸기 전에 실제 실행과 동일한 입력으로 읽기 전용 사전 검사.
    # pages/ 는 git 병합에 포함되지 않으므로 fix 재대조가 가능해야 진행한다.
    reg_path = os.path.join(ROOT, 'data', 'registry.json')
    toc_path = os.path.join(ROOT, 'data', 'toc.json')
    toc = read_json(toc_path)
    replace_cmd = None
    summary['tocReplacementPlanned'] = bool(proposed and not a.skip_toc)
    if summary['tocReplacementPlanned']:
        tp = os.path.join(d, 'toc-proposed.json')
        replace_cmd = PY + [add_cases, 'toc', 'replace', '--subject', sid, '--from', tp]
        out = run(replace_cmd + ['--dry-run'])
        summary['clearedCases'] = re.findall(r'tocPath 비움 → (\S+) ', out)
        toc = copy.deepcopy(toc)
        toc[sid] = read_json(tp)['proposed']
    args = SimpleNamespace(registry=reg_path, toc=toc_path, overlap_final=a.overlap_final, seed=None, reviewer=None)
    try:
        preview = md_merge.run(args, sid, d, toc_override=toc)
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f'사전 검사 실패: {exc}') from exc
    _, errors = md_merge.check(preview['candidates'], preview['tids'])
    for error in errors:
        print('ERROR -', error)
    if errors:
        raise SystemExit(f'사전 검사 오류 {len(errors)}개 — 등록하지 않습니다')
    report_candidates(preview['candidates'], summary, len(preview['added']))
    if a.dry_run:
        print(json.dumps(summary, ensure_ascii=False)); return 0

    # 1) toc 교체
    if replace_cmd:
        out = run(replace_cmd)
        summary['tocReplaced'] = True
        summary['clearedCases'] = re.findall(r'tocPath 비움 → (\S+) ', out)
    # 2) md_merge 재생성 + check (--check 도 결과를 저장하므로 한 번만 실행)
    merge = [os.path.join(ROOT, 'tools', 'md_merge.py'), '--subject', sid, '--dir', d]
    if a.overlap_final and os.path.isdir(a.overlap_final):
        merge += ['--overlap-final', a.overlap_final]
    run(PY + merge + ['--check'])
    cand_path = os.path.join(d, f'candidates-{sid}.json')
    cands = read_json(cand_path)['candidates']
    report_candidates(cands, summary)
    # 3) 등록
    before = len(read_json(os.path.join(ROOT, 'data', 'registry.json'))['cases'])
    run(PY + [add_cases, 'add', '--from', cand_path])
    after = len(read_json(os.path.join(ROOT, 'data', 'registry.json'))['cases'])
    summary['added'] = after - before
    # 4) 기등록 재판에 표준판례 출처
    out = run(PY + [os.path.join(ROOT, 'tools', 'standard_source_backfill.py'), '--candidates', cand_path])
    summary['backfilled'] = out.strip().splitlines()[0] if out.strip() else ''
    # 5) 경로 잃은 사건의 tocPath 재지정
    if summary['clearedCases']:
        reg = read_json(os.path.join(ROOT, 'data', 'registry.json'))['cases']
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
    out = run(PY + [add_cases, 'validate'])
    m = re.search(r'오류 (\d+)개', out)
    summary['validate'] = int(m.group(1)) if m else None
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary['validate'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
