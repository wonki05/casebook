#!/usr/bin/env python3
"""단계 4 보조: 후보 파일의 검증된 standardSource 를, 같은 재판(decisionId)이 이미 등록부에 있는 사건에 붙인다.

  python -X utf8 tools/standard_source_backfill.py --candidates data/standard-cases/상법/candidates-commercial.json [--dry-run]

- `add_cases.py add --from` 은 이미 등록된 재판을 건너뛰므로(시안 사건·전원합의체·헌법재판소 주요결정 등), 그 사건들의 표준판례 텍스트는
  이 스크립트가 `add_cases.py set <id> --standard-source <json>` 으로 붙인다(등록부 수정은 add_cases.py 를 거친다 — 규칙 4).
- status가 ok인 후보만 보충한다. review·skip 후보의 식별·출처 판정은 등록 전에 해결한다.
- 이미 standardSource 가 있는 사건은 텍스트가 같으면 건너뛰고, 다르면 바꾸지 않고 충돌로 보고한다(schema §1-3).
- 같은 decisionId 가 여러 사건(id)에 배치되어 있으면 모두에 같은 standardSource 를 붙인다(필드별 출처 공유).
"""
import argparse, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from case_identity import identity, STANDARD_FIELDS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--candidates', required=True)
    ap.add_argument('--registry', default=os.path.join(ROOT, 'data', 'registry.json'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    with open(a.candidates, encoding='utf-8') as f:
        cand = json.load(f)['candidates']
    with open(a.registry, encoding='utf-8') as f:
        reg = json.load(f)['cases']
    by_decision = {}
    for c in reg:
        try:
            did = c.get('decisionId') or identity(c)['decisionId']
        except Exception:
            continue
        by_decision.setdefault(did, []).append(c)
    applied, skipped, conflicts = [], [], []
    for x in cand:
        if x.get('status') != 'ok':
            continue
        src = x.get('standardSource')
        if not src:
            continue
        did = x.get('decisionId')
        if not did:
            try:
                did = identity({'court': x['court'], 'caseNumber': x['caseNumber'], 'lookupKey': x.get('lookupKey'), 'decisionDate': x['date'], 'decisionType': x.get('decisionType')})['decisionId']
            except Exception as ex:
                conflicts.append((x.get('caseNumber'), f'decisionId 계산 실패: {ex}')); continue
        for c in by_decision.get(did, []):
            cur = c.get('standardSource')
            if cur:
                same = all(cur.get(k) == src.get(k) for k in STANDARD_FIELDS if k in src or k in cur)
                (skipped if same else conflicts).append((c['id'], '이미 같은 standardSource' if same else '기존 standardSource 와 텍스트가 다름 — 수동 확인'))
                continue
            if a.dry_run:
                applied.append((c['id'], did))
                c['standardSource'] = src  # 뒤의 중복 후보도 예정된 결과와 비교한다.
                continue
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as tf:
                json.dump(src, tf, ensure_ascii=False); tmp = tf.name
            try:
                r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'tools', 'add_cases.py'), 'set', c['id'], '--standard-source', tmp], capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
                if r.returncode:
                    conflicts.append((c['id'], 'set 실패: ' + (r.stderr or r.stdout)[-200:]))
                else:
                    applied.append((c['id'], did))
                    c['standardSource'] = src  # 같은 id에 중복 적용하거나 덮어쓰지 않는다.
            except OSError as ex:
                conflicts.append((c['id'], f'set 실행 실패: {ex}'))
            finally:
                os.remove(tmp)
    print(f'standardSource 보충: 적용 {len(applied)}건, 이미 있음 {len(skipped)}건, 충돌 {len(conflicts)}건' + (' (dry-run)' if a.dry_run else ''))
    for cid, did in applied[:30]:
        print('  적용', cid, did)
    for cid, why in conflicts:
        print('  충돌', cid, why)
    return 0 if not conflicts else 1


if __name__ == '__main__':
    sys.exit(main())
