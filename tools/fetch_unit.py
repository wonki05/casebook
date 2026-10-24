#!/usr/bin/env python3
"""표준판례 공식 전문 수집을 단원(unit) 단위로 나누어 계획·실행·검사·커밋하는 보조 도구.

수집 자체는 tools/fetch_lawgo.py 가 하고(law.go.kr 에서 추출한 원문만 data/fetched 에 저장), 이 도구는
  - plan : 목차 노드별로 사건 id 를 단원으로 나눈 계획(JSON)을 만든다.
  - run  : 한 단원을 청크 단위로 수집하고, 실패 건을 한 번 더 시도한 뒤, 결과를 검사해 보고서를 남기고 (--commit 이면) 커밋한다.
  - resolve: 한글주소 조회에 실패한 건을 law.go.kr 검색(사건번호)으로 다시 찾는다. 사건번호와 선고일이 등록부와 모두 일치하는 결과가
             하나일 때만 그 판례의 공식 페이지를 같은 방식으로 추출한다(선고일이 다르거나 후보가 여럿이면 수집하지 않고 보고서에 남긴다).
  - audit: 단원(또는 계획 전체)의 수집 결과를 읽기 전용으로 검사한다.
단원마다 별도 git worktree 에서 `run` 을 돌리면 서로 다른 파일만 만들므로 병합 충돌이 없다.

  python -X utf8 tools/fetch_unit.py plan --subject civil --spec <units-spec.json> --out spec/fetch-units-civil.json
  python -X utf8 tools/fetch_unit.py run  --plan spec/fetch-units-civil.json --unit u01-general [--chunk 15] [--delay 1.5] [--commit]
  python -X utf8 tools/fetch_unit.py resolve --plan spec/fetch-units-civil.json --unit u01-general [--commit]
  python -X utf8 tools/fetch_unit.py audit --plan spec/fetch-units-civil.json [--unit u01-general]

spec 파일: {"units": [{"name": "u01-general", "label": "총칙 통칙·인·법인·물건", "nodes": ["mb-1-1", "mb-1-2"]}, ...]}
  nodes 는 toc.json 의 노드 id 이며, 사건의 tocPath 에 그 id 가 있으면 그 단원에 속한다(한 사건이 두 단원에 걸리면 오류).
보고서는 spec/fetch-reports/<subject>-<unit>.json. 공식 수집 파일·등록부는 수정하지 않는다(새 파일만 만든다).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import subjects  # noqa: E402

REG = os.path.join(ROOT, 'data', 'registry.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')
REPORTS = os.path.join(ROOT, 'spec', 'fetch-reports')
FETCH = os.path.join(ROOT, 'tools', 'fetch_lawgo.py')
TRAILER = 'Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>'
SEARCH_URL = 'https://www.law.go.kr/precSc.do?menuId=7&subMenuId=47&tabMenuId=213&query='
RESULT_JS = r"""() => Array.from(document.querySelectorAll("a[onclick*='precView']")).map(a => ({
  text: a.innerText.replace(/\s+/g, ' ').trim(), seq: ((/precView\('(\d+)'/.exec(a.getAttribute('onclick')) || [])[1]) || ''}))"""

# 공식 인용문: [대법원 2003. 7. 24. 선고 2001다48781 전원합의체 판결] / [대법원 2008. 3. 14. 자 2007마123 결정]
CITE_RE = re.compile(r'\[\s*(?P<court>\S+(?:\s\S+?법원)?)\s+(?P<y>\d{4})\.\s*(?P<m>\d{1,2})\.\s*(?P<d>\d{1,2})\.\s*(?P<kind>선고|자)\s+(?P<num>\S+?)(?P<eb>\s+전원합의체)?\s+(?P<type>판결|결정|명령)\s*\]')


def load_registry():
    return json.load(open(REG, encoding='utf-8'))['cases']


def fetched_path(cid):
    return os.path.join(FETCHED, cid + '.json')


def missing_path(cid):
    return os.path.join(FETCHED, cid + '.missing.json')


def load_toc(subject):
    toc = json.load(open(os.path.join(ROOT, 'data', 'toc.json'), encoding='utf-8'))[subject]
    labels = {}

    def walk(n):
        labels[n['id']] = n['label']
        for c in n.get('children', []):
            walk(c)
    for n in toc:
        walk(n)
    return labels


def cmd_plan(a):
    subj = subjects.BY_ID[a.subject]
    spec = json.load(open(a.spec, encoding='utf-8'))
    labels = load_toc(a.subject)
    cases = [c for c in load_registry() if c['subject'] == a.subject and c['group'] == 'standard']
    owner, units = {}, []
    for u in spec['units']:
        nodes = u['nodes']
        for n in nodes:
            if n not in labels:
                sys.exit(f'목차에 없는 노드: {n}')
        ids = []
        for c in cases:
            if any(n in (c.get('tocPath') or []) for n in nodes):
                if c['id'] in owner:
                    sys.exit(f"{c['id']} 가 단원 {owner[c['id']]} 와 {u['name']} 에 모두 속함")
                owner[c['id']] = u['name']
                ids.append(c['id'])
        units.append({'name': u['name'], 'label': u['label'], 'nodes': nodes, 'nodeLabels': [labels[n] for n in nodes], 'ids': ids})
    rest = [c['id'] for c in cases if c['id'] not in owner]
    if rest:
        sys.exit(f'어느 단원에도 속하지 않은 사건 {len(rest)}건: {rest[:10]}')
    plan = {'subject': a.subject, 'subjectLabel': subj['label'], 'total': len(cases), 'units': units}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(plan, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"{subj['label']} 표준판례 {len(cases)}건 → 단원 {len(units)}개 ({a.out})")
    for u in units:
        todo = sum(1 for i in u['ids'] if not os.path.exists(fetched_path(i)) and not os.path.exists(missing_path(i)))
        print(f"  {u['name']:<28} 전체 {len(u['ids']):>3} / 미수집 {todo:>3}  {' · '.join(u['nodeLabels'])}")


def load_plan(path):
    return json.load(open(path, encoding='utf-8'))


def pick_units(plan, name):
    us = [u for u in plan['units'] if name in (None, u['name'])]
    if not us:
        sys.exit(f'단원 없음: {name}')
    return us


def run_fetch(ids, delay, timeout):
    """fetch_lawgo.py 를 한 번 실행한다(브라우저 한 번 기동). 시간 초과·비정상 종료여도 이미 저장된 건은 남는다."""
    cmd = [sys.executable, '-X', 'utf8', FETCH, '--delay', str(delay)]
    for i in ids:
        cmd += ['--id', i]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
        tail = (p.stdout or '').strip().splitlines()[-1:] + (p.stderr or '').strip().splitlines()[-2:]
        return p.returncode, ' | '.join(tail)
    except subprocess.TimeoutExpired:
        return -9, f'시간 초과({timeout}s)'


def fetch_pass(ids, chunk, delay, label):
    for k in range(0, len(ids), chunk):
        part = ids[k:k + chunk]
        t0 = time.time()
        rc, note = run_fetch(part, delay, timeout=int(len(part) * (delay + 25)) + 180)
        done = sum(1 for i in part if os.path.exists(fetched_path(i)))
        print(f'[{label}] {k + len(part)}/{len(ids)} 청크 성공 {done}/{len(part)} rc={rc} {time.time() - t0:.0f}s {note}', flush=True)


def classify(reason):
    if reason.startswith('한글주소 조회 실패'):
        return 'not-listed'
    if '일치하지 않음' in reason:
        return 'number-mismatch'
    return 'error'


def check_record(c, rec):
    """공식 인용문과 등록부의 메타(법원·선고일·판결/결정·전원합의체·사건번호)를 대조한다. 불일치만 돌려준다(판정·수정은 하지 않는다)."""
    flags = []
    if rec.get('id') != c['id']:
        flags.append(f"id 불일치: {rec.get('id')}")
    if not rec.get('sections') or sum(len(s.get('text', '')) for s in rec['sections']) < 200:
        flags.append('본문이 너무 짧음')
    m = CITE_RE.search(rec.get('citation') or '')
    if not m:
        flags.append(f"인용문 해석 실패: {rec.get('citation')!r}")
        return flags
    date = f"{int(m['y']):04d}-{int(m['m']):02d}-{int(m['d']):02d}"
    if date != c.get('decisionDate'):
        flags.append(f"선고일 {c.get('decisionDate')} ≠ 공식 {date}")
    if m['court'] != c.get('court'):
        flags.append(f"법원 {c.get('court')} ≠ 공식 {m['court']}")
    if m['type'] != c.get('decisionType'):
        flags.append(f"유형 {c.get('decisionType')} ≠ 공식 {m['type']}")
    if bool(m['eb']) != bool(c.get('enBanc')):
        flags.append(f"전원합의체 {bool(c.get('enBanc'))} ≠ 공식 {bool(m['eb'])}")
    if m['num'] != (c.get('lookupKey') or c['caseNumber']):
        flags.append(f"사건번호 {c.get('lookupKey')} ≠ 공식 {m['num']}")
    return flags


def audit_unit(plan, u):
    by_id = {c['id']: c for c in load_registry()}
    ok, miss, flagged, waiting = [], [], [], []
    for cid in u['ids']:
        if os.path.exists(fetched_path(cid)):
            rec = json.load(open(fetched_path(cid), encoding='utf-8'))
            ok.append(cid)
            fl = check_record(by_id[cid], rec)
            if fl:
                flagged.append({'id': cid, 'caseNumber': by_id[cid]['caseNumber'], 'flags': fl})
        elif os.path.exists(missing_path(cid)):
            m = json.load(open(missing_path(cid), encoding='utf-8'))
            miss.append({'id': cid, 'caseNumber': by_id[cid]['caseNumber'], 'decisionDate': by_id[cid].get('decisionDate'),
                         'class': classify(m.get('reason', '')), 'reason': m.get('reason', '')[:160]})
        else:
            waiting.append(cid)
    return {'unit': u['name'], 'label': u['label'], 'total': len(u['ids']), 'ok': len(ok), 'missing': miss, 'flagged': flagged, 'waiting': waiting}


def cmd_audit(a):
    plan = load_plan(a.plan)
    tot = {'total': 0, 'ok': 0, 'missing': 0, 'flagged': 0, 'waiting': 0}
    for u in pick_units(plan, a.unit):
        r = audit_unit(plan, u)
        print(f"{r['unit']:<28} 전체 {r['total']:>3} 성공 {r['ok']:>3} 미게재·실패 {len(r['missing']):>2} 메타 불일치 {len(r['flagged']):>2} 대기 {len(r['waiting']):>3}")
        for m in r['missing']:
            print(f"    MISS {m['id']} {m['caseNumber']} [{m['class']}] {m['reason'][:60]}")
        for f in r['flagged']:
            print(f"    FLAG {f['id']} {f['caseNumber']}: {'; '.join(f['flags'])}")
        tot['total'] += r['total']; tot['ok'] += r['ok']; tot['missing'] += len(r['missing']); tot['flagged'] += len(r['flagged']); tot['waiting'] += len(r['waiting'])
    print('합계', tot)


def git(*args, input_text=None):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', input=input_text)


def cmd_run(a):
    plan = load_plan(a.plan)
    u = pick_units(plan, a.unit)[0]
    t0 = time.time()
    os.makedirs(FETCHED, exist_ok=True)
    pending = [i for i in u['ids'] if not os.path.exists(fetched_path(i))]
    print(f"{plan['subjectLabel']} {u['name']} ({u['label']}): 전체 {len(u['ids'])}건, 수집할 것 {len(pending)}건", flush=True)
    fetch_pass(pending, a.chunk, a.delay, '1차')
    retry = [i for i in u['ids'] if not os.path.exists(fetched_path(i))]
    if retry:
        print(f'1차 실패 {len(retry)}건 — 한 번 더 시도(간격 {a.delay * 2:g}s)', flush=True)
        fetch_pass(retry, a.chunk, a.delay * 2, '2차')
    r = audit_unit(plan, u)
    r['retried'] = retry
    r['elapsedSec'] = round(time.time() - t0)
    os.makedirs(REPORTS, exist_ok=True)
    rep = os.path.join(REPORTS, f"{plan['subject']}-{u['name']}.json")
    json.dump(r, open(rep, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"완료 {u['name']}: 성공 {r['ok']} / 미게재·실패 {len(r['missing'])} / 메타 불일치 {len(r['flagged'])} / 대기 {len(r['waiting'])} ({r['elapsedSec']}s)")
    for m in r['missing']:
        print(f"  MISS {m['id']} {m['caseNumber']} [{m['class']}]")
    for f in r['flagged']:
        print(f"  FLAG {f['id']} {f['caseNumber']}: {'; '.join(f['flags'])}")
    if a.commit:
        commit_unit(plan, u, r, rep, f"{plan['subjectLabel']} 표준판례 공식 전문 수집: {u['name']} (성공 {r['ok']}건, 미게재 {len(r['missing'])}건)")


def commit_unit(plan, u, r, rep, msg):
    if r['waiting']:
        sys.exit(f"수집이 끝나지 않은 건이 있어 커밋하지 않습니다: {r['waiting'][:5]}")
    paths = [os.path.relpath(p, ROOT).replace(os.sep, '/') for i in u['ids'] for p in (fetched_path(i), missing_path(i)) if os.path.exists(p)]
    paths.append(os.path.relpath(rep, ROOT).replace(os.sep, '/'))
    add = git('add', '--pathspec-from-file=-', input_text='\n'.join(paths) + '\n')
    if add.returncode:
        sys.exit('git add 실패: ' + add.stderr)
    body = 'law.go.kr 에서 tools/fetch_lawgo.py 로 추출한 원문만 data/fetched 에 보존.'
    if r['flagged']:
        body += f"\n공식 인용문과 등록부 메타가 다른 {len(r['flagged'])}건은 보고서(spec/fetch-reports)에 기록, 판정 대기."
    cm = git('commit', '-m', msg, '-m', body, '-m', TRAILER)
    print(cm.stdout.strip() or cm.stderr.strip())
    if cm.returncode:
        sys.exit(1)


BRACKET_RE = re.compile(r'\[([^\[\]]+)\]\s*$')
DATE_IN_RE = re.compile(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.')


def parse_result(text, key):
    """검색 결과 한 줄('제목 [대법원 2017. 3. 15. 선고 2013다79887 판결]')에서 법원·선고일과 사건번호 일치 여부를 읽는다."""
    m = BRACKET_RE.search(text)
    if not m:
        return None
    cite = m.group(1)
    d = DATE_IN_RE.search(cite)
    if not d:
        return None
    parts = re.split(r'\s(?:선고|자)\s', cite, maxsplit=1)
    nums = parts[1] if len(parts) > 1 else ''
    return {'court': cite.split()[0], 'date': f"{int(d[1]):04d}-{int(d[2]):02d}-{int(d[3]):02d}", 'cite': '[' + cite + ']',
            'numberMatch': bool(re.search(r'(?<![0-9])' + re.escape(key) + r'(?![0-9])', nums))}


def resolve_by_search(page, c):
    """검색 결과에서 사건번호·선고일이 등록부와 모두 같은 판례의 precSeq 를 찾는다. -> (seq 또는 None, 결과 설명)"""
    from urllib.parse import quote
    key = c.get('lookupKey') or c['caseNumber']
    page.goto(SEARCH_URL + quote(key, safe=''), wait_until='domcontentloaded', timeout=60000)
    try:
        page.wait_for_selector("a[onclick*='precView']", timeout=15000)
    except Exception:
        page.wait_for_timeout(1500)
    hits = []
    for r in page.evaluate(RESULT_JS):
        pr = parse_result(r['text'], key)
        if pr and pr['numberMatch'] and r['seq']:
            hits.append({**pr, 'seq': r['seq']})
    exact = [h for h in hits if h['date'] == c.get('decisionDate')]
    if len(exact) == 1:
        return exact[0]['seq'], {'outcome': 'found', 'cite': exact[0]['cite']}
    if len(exact) > 1:
        return None, {'outcome': 'ambiguous', 'candidates': exact}
    if hits:
        return None, {'outcome': 'date-conflict', 'registryDate': c.get('decisionDate'), 'candidates': hits}
    return None, {'outcome': 'no-result'}


def cmd_resolve(a):
    import fetch_lawgo
    from playwright.sync_api import sync_playwright
    plan = load_plan(a.plan)
    u = pick_units(plan, a.unit)[0]
    by_id = {c['id']: c for c in load_registry()}
    todo = [i for i in u['ids'] if not os.path.exists(fetched_path(i)) and os.path.exists(missing_path(i))]
    print(f"{u['name']}: 검색으로 다시 찾을 미게재 {len(todo)}건", flush=True)
    outcomes = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=fetch_lawgo.UA)
        for cid in todo:
            c = by_id[cid]
            try:
                seq, info = resolve_by_search(page, c)
                if seq:
                    t = {'id': cid, 'caseNumber': c['caseNumber'], 'lookupKey': c.get('lookupKey') or c['caseNumber'], 'kind': 'prec', 'seq': seq}
                    res = fetch_lawgo.fetch_one_pw(page, t)
                    if res['ok']:
                        json.dump(res['rec'], open(fetched_path(cid), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                        os.remove(missing_path(cid))
                        info['outcome'] = 'fetched'
                        info['seq'] = seq
                    else:
                        info = {'outcome': 'fetch-failed', 'seq': seq, 'reason': res['reason'][:160]}
            except Exception as e:
                info = {'outcome': 'error', 'reason': f'{type(e).__name__}: {e}'[:160]}
            outcomes[cid] = info
            print(f"  {info['outcome']:<13} {cid} {c['caseNumber']}", flush=True)
            time.sleep(a.delay)
        browser.close()
    rep = os.path.join(REPORTS, f"{plan['subject']}-{u['name']}.json")
    old = json.load(open(rep, encoding='utf-8')) if os.path.exists(rep) else {}
    r = audit_unit(plan, u)
    r['retried'] = old.get('retried', [])
    r['elapsedSec'] = old.get('elapsedSec')
    r['search'] = outcomes
    os.makedirs(REPORTS, exist_ok=True)
    json.dump(r, open(rep, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    n = sum(1 for v in outcomes.values() if v['outcome'] == 'fetched')
    print(f"완료 {u['name']}: 검색으로 {n}건 추가 수집 → 성공 {r['ok']} / 미게재·실패 {len(r['missing'])} / 메타 불일치 {len(r['flagged'])} / 대기 {len(r['waiting'])}")
    for f in r['flagged']:
        print(f"  FLAG {f['id']} {f['caseNumber']}: {'; '.join(f['flags'])}")
    if a.commit:
        commit_unit(plan, u, r, rep, f"{plan['subjectLabel']} 표준판례 공식 전문 수집: {u['name']} 검색 보완 (추가 {n}건, 성공 {r['ok']}건, 미게재 {len(r['missing'])}건)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('plan'); p.add_argument('--subject', required=True, choices=subjects.STANDARD_IDS); p.add_argument('--spec', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('run'); p.add_argument('--plan', required=True); p.add_argument('--unit', required=True)
    p.add_argument('--chunk', type=int, default=15); p.add_argument('--delay', type=float, default=1.5); p.add_argument('--commit', action='store_true')
    p = sub.add_parser('resolve'); p.add_argument('--plan', required=True); p.add_argument('--unit', required=True); p.add_argument('--delay', type=float, default=1.5); p.add_argument('--commit', action='store_true')
    p = sub.add_parser('audit'); p.add_argument('--plan', required=True); p.add_argument('--unit')
    a = ap.parse_args()
    {'plan': cmd_plan, 'run': cmd_run, 'resolve': cmd_resolve, 'audit': cmd_audit}[a.cmd](a)


if __name__ == '__main__':
    main()
