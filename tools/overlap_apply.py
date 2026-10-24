#!/usr/bin/env python3
"""겹침 재판 종합 결과(_overlaps/final/<decisionId>.json)를 등록부의 두 과목 배치에 똑같이 붙인다(add_cases.py set 경유).

  python -X utf8 tools/overlap_apply.py [--final data/standard-cases/_overlaps/final] [--dry-run]

- 배치는 등록부에서 (decisionId, group=standard, subject) 로 찾는다. 없는 배치는 보고만 한다(아직 등록 전).
- 종합이 없는 재판(text=null)은 두 배치의 standardSource 를 비워 공식 자료만 표시되게 한다(`set --clear-standard-source` 가 없으므로 그런 경우는 보고만 하고 사람이 처리).
"""
import argparse, glob, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from subjects import resolve  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--final', default=os.path.join(ROOT, 'data', 'standard-cases', '_overlaps', 'final'))
    ap.add_argument('--registry', default=os.path.join(ROOT, 'data', 'registry.json'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    reg = json.load(open(a.registry, encoding='utf-8'))['cases']
    by = {}
    for c in reg:
        if c.get('group') == 'standard' and c.get('decisionId'):
            by.setdefault((c['decisionId'], c.get('subject')), []).append(c)
    applied, missing, cleared, failed, unchanged = [], [], [], [], []
    for p in sorted(glob.glob(os.path.join(a.final, '*.json'))):
        f = json.load(open(p, encoding='utf-8'))
        did = f['decisionId']
        if not f.get('placements'):
            cleared.append(did)
            continue
        for pl in f['placements']:
            sid = resolve(pl['subject'])
            targets = by.get((did, sid), [])
            if not targets:
                missing.append((did, pl['subject']))
                continue
            for c in targets:
                if c.get('standardSource') == pl['standardSource']:
                    unchanged.append(c['id'])
                    continue
                applied.append((c['id'], did, pl['subject']))
                if a.dry_run:
                    continue
                with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as tf:
                    json.dump(pl['standardSource'], tf, ensure_ascii=False); tmp = tf.name
                try:
                    r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'tools', 'add_cases.py'), 'set', c['id'], '--standard-source', tmp],
                                       capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
                    if r.returncode:
                        failed.append((c['id'], (r.stderr or r.stdout)[-200:]))
                finally:
                    os.remove(tmp)
    print(f'겹침 종합 적용: {len(applied)}건 적용, 동일 {len(unchanged)}건, 배치 미등록 {len(missing)}건, 종합 없음 {len(cleared)}건, 실패 {len(failed)}건' + (' (dry-run)' if a.dry_run else ''))
    for x in applied[:50]: print('  적용', *x)
    for x in missing: print('  미등록', *x)
    for x in cleared: print('  종합 없음(표준판례 텍스트 없이 표시)', x)
    for x in failed: print('  실패', *x)
    return 0 if not (failed or missing or cleared) else 1


if __name__ == '__main__':
    sys.exit(main())
