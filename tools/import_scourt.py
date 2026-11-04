#!/usr/bin/env python3
"""사법정보공개포털 전원합의체 수집분(data/scourt/, tools/fetch_scourt.py)을 등록부 후보와 공식 수집본(data/fetched/)으로 옮긴다.

등록은 add_cases.py 만 한다(이 도구는 후보 파일과 수집본만 만든다).

  python tools/import_scourt.py prepare --output <제목입력.json>        # 제목이 필요한 사건과 판시사항 발췌
  python tools/import_scourt.py candidates --titles <제목.json> --output <후보.json>
  python tools/add_cases.py add --from <후보.json> --group enbanc
  python tools/import_scourt.py fetched                                 # 같은 재판의 공식 텍스트가 없는 배치에 포털 전문을 저장

같은 재판(decisionId)이 포털에 일련번호 둘로 올라 있으면 큰 일련번호(나중에 올라온 판본)를 쓴다 — 비실명 처리와 서식이 더 나은 판본이다.
이미 표준판례·법률신문 등으로 등록된 재판은 그 배치의 제목·과목을 따르고 공식 텍스트도 새로 만들지 않는다(기존 수집본을 공유한다).
포털의 전문 HTML 에서 태그만 걷어낸 text 를 【…】 표제어 단위로 나눌 뿐 글자는 바꾸지 않는다.
"""
import argparse, json, os, re, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOURT = os.path.join(ROOT, 'data', 'scourt')
REG = os.path.join(ROOT, 'data', 'registry.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from case_identity import docket_parts, identity  # noqa: E402

PROVIDER, LABEL = '사법정보공개포털', '사법정보공개포털 종합법률정보'
GROUP_ORDER = {'standard': 0, 'annual': 1, 'research': 2, 'enbanc': 3, 'ccourt': 4}
PRE_HEADINGS = {'판시사항', '판결요지', '결정요지', '참조조문', '참조판례'}
HEAD = re.compile(r'^[ \t　]*【([^】\n]{1,40})】[ \t]*(.*)$', re.M)   # 오래된 판결은 표제어가 들여쓰기 되어 있다
CRIMINAL = {'도', '오', '감도', '재도', '초', '초기', '전도', '모', '노', '고합', '고단', '고정'}
ADMINISTRATIVE = {'누', '두', '추', '재누', '재두', '아', '구합', '구단'}
INTELLECTUAL = {'후', '허', '재후', '재허'}
COMMERCIAL_LAWS = ('상법', '어음법', '수표법', '독점규제 및 공정거래에 관한 법률', '보험업법', '자본시장')
INTELLECTUAL_LAWS = ('특허법', '실용신안법', '디자인보호법', '상표법', '저작권법', '부정경쟁방지')


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_json(path, obj, indent=None):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.write('\n')
    os.replace(tmp, path)


def norm_heading(h):
    return re.sub(r'[\s【】]', '', h or '')


def split_portal_text(text):
    """포털 text → (머리글, [{heading, text}]). 판시사항~참조판례 구역 안의 '【다수의견】' 같은 표제어는 앞 구역의 본문으로 둔다."""
    matches = list(HEAD.finditer(text))
    if not matches:
        return text.strip(), []
    header = text[:matches[0].start()].strip()
    parts, in_full = [], False
    for i, m in enumerate(matches):
        name = norm_heading(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if parts and not in_full and name not in PRE_HEADINGS and name != '전문' and ('의견' in name or name.startswith('대법관')):
            parts[-1][1].append(text[m.start():end])
            continue
        if name == '전문' or name not in PRE_HEADINGS:
            in_full = True
        parts.append(['【' + ' '.join(m.group(1).split()) + '】', [text[m.start(2):end]]])
    return header, [{'heading': h, 'text': ''.join(body).strip()} for h, body in parts]


def case_name(header, fallback):
    rest = header.split('\n', 1)[1] if '\n' in header else ''
    m = re.search(r'\[\s*([^\[\]]+?)\s*\]', rest)
    name = ' '.join(m.group(1).split()) if m else ''
    return fallback if not name or re.match(r'[공집]', name) else name


def display_number(title, fallback):
    m = re.search(r'(?:선고|자)\s+(.+?)\s*(?:전원합의체\s*)?(?:판결|결정)\s*$', title)
    return m.group(1) if m else fallback


def cites(statutes, laws):
    """참조조문에 법률명이 있는가. 앞이 한글이면 다른 법률명의 일부다('국가배상법' 속의 '상법' 등)."""
    return any(re.search(r'(?<![가-힣])' + re.escape(law), statutes) for law in laws)


def classify(case_number, statutes):
    kind = docket_parts(case_number)[1]
    if kind in INTELLECTUAL:
        return 'ip'
    if kind in CRIMINAL:
        return 'criminal'
    if kind in ADMINISTRATIVE:
        return 'administrative'
    if cites(statutes, INTELLECTUAL_LAWS):
        return 'ip'
    if cites(statutes, COMMERCIAL_LAWS):
        return 'commercial'
    return 'civil'


def load_decisions():
    """포털 기록을 재판(decisionId)별로 묶고 대표 판본(큰 일련번호)을 고른다 → (결정 목록, 식별 불가 기록)."""
    records = read_json(os.path.join(SCOURT, 'enbanc-list.json'))['records']
    groups, unidentified = defaultdict(list), []
    for r in records:
        (groups[r['decisionId']] if r.get('decisionId') else unidentified).append(r)
    decisions = []
    for did, rs in groups.items():
        best = max(rs, key=lambda r: int(r['srno']))
        doc = read_json(os.path.join(SCOURT, 'docs', best['srno'] + '.json'))
        header, sections = split_portal_text(doc['text'])
        statutes = next((s['text'] for s in sections if norm_heading(s['heading']) == '참조조문'), '')
        decisions.append({'decisionId': did, 'record': best, 'doc': doc, 'header': header, 'sections': sections,
                          'srnos': sorted(r['srno'] for r in rs), 'statutes': statutes,
                          'number': display_number(doc['title'], best['caseNumber'])})
    decisions.sort(key=lambda d: (d['record']['decisionDate'], d['record']['caseNumber']))
    return decisions, unidentified


def registry_by_decision():
    reg = read_json(REG)['cases']
    by = defaultdict(list)
    for c in reg:
        by[c.get('decisionId') or identity(c)['decisionId']].append(c)
    return by


def existing_title_and_subject(placements):
    best = sorted((c for c in placements if (c.get('title') or '').strip()),
                  key=lambda c: GROUP_ORDER.get(c['group'], 9))
    return (best[0]['title'].strip(), best[0]['subject']) if best else (None, None)


def issue_excerpt(sections, limit=450):
    for wanted in ('판시사항', '판결요지', '결정요지'):
        for s in sections:
            if norm_heading(s['heading']) == wanted and s['text']:
                return re.sub(r'\s+', ' ', s['text'])[:limit]
    return ''


def cmd_prepare(a):
    decisions, unidentified = load_decisions()
    by = registry_by_decision()
    need = []
    for d in decisions:
        if any(c['group'] == 'enbanc' for c in by.get(d['decisionId'], [])):
            continue
        title, _ = existing_title_and_subject(by.get(d['decisionId'], []))
        if title:
            continue
        r = d['record']
        need.append({'key': d['decisionId'], 'caseNumber': r['caseNumber'], 'date': r['decisionDate'], 'type': r['decisionType'],
                     'caseName': case_name(d['header'], r['caseName']), 'alias': r['caseAlias'].strip('〈〉 '),
                     'issues': issue_excerpt(d['sections'])})
    write_json(a.output, {'decisions': need}, indent=1)
    print(f'제목이 필요한 재판 {len(need)}건 → {a.output} (식별 불가로 제외 {[u["caseNumber"] for u in unidentified]})')


def cmd_candidates(a):
    decisions, unidentified = load_decisions()
    by = registry_by_decision()
    titles = read_json(a.titles)
    overrides = read_json(a.overrides) if a.overrides else {}
    items, skipped, subjects = [], Counter(), Counter()
    for d in decisions:
        r, placements = d['record'], by.get(d['decisionId'], [])
        if any(c['group'] == 'enbanc' for c in placements):
            skipped['이미 전원합의체 배치가 있음'] += 1
            continue
        title, subject = existing_title_and_subject(placements)
        title = title or (titles.get(d['decisionId']) or '').strip()
        if not title:
            raise SystemExit(f'제목이 없습니다: {r["caseNumber"]} {d["decisionId"]}')
        subject = overrides.get(d['decisionId']) or subject or classify(r['caseNumber'], d['statutes'])
        item = {'status': 'ok', 'caseNumber': d['number'], 'date': r['decisionDate'], 'title': title, 'subject': subject,
                'court': '대법원', 'decisionType': r['decisionType'], 'enBanc': True,
                'scourtSource': {'provider': PROVIDER, 'srno': r['srno'], 'grade': r['portalGrade'], 'discarded': r['discarded'],
                                 **({'discardedNote': r['discardNote']} if r.get('discardNote') else {})}}
        if identity({'court': '대법원', 'caseNumber': item['caseNumber'], 'decisionDate': item['date'],
                     'decisionType': item['decisionType']})['decisionId'] != d['decisionId']:
            raise SystemExit(f'표시 사건번호의 재판 식별이 목록과 다릅니다: {item["caseNumber"]}')
        items.append(item)
        subjects[subject] += 1
    write_json(a.output, {'group': 'enbanc', 'candidates': items}, indent=1)
    print(f'후보 {len(items)}건 → {a.output}; 과목 {dict(subjects)}; 제외 {dict(skipped)}; 식별 불가 {[u["caseNumber"] for u in unidentified]}')


def has_text(record):
    path = os.path.join(FETCHED, record['id'] + '.json')
    if not os.path.exists(path):
        return False
    try:
        return bool(read_json(path).get('sections'))
    except (OSError, ValueError):
        return False


def fetched_record(cid, d):
    r, doc = d['record'], d['doc']
    return {'id': cid, 'caseNumber': r['caseNumber'], 'lookupKey': r['caseNumber'], 'provider': PROVIDER,
            'sourceLabel': LABEL, 'sourceUrl': doc['source']['url'], 'portalSrno': r['srno'],
            'portalGrade': r['portalGrade'], 'portalDuplicateSrnos': [s for s in d['srnos'] if s != r['srno']],
            'pageTitle': case_name(d['header'], r['caseName']), 'citation': '[' + doc['title'] + ']',
            'header': d['header'], 'sections': d['sections'], 'portalFetchedAt': doc['fetchedAt']}


def cmd_fetched(a):
    decisions, _ = load_decisions()
    by_decision = {d['decisionId']: d for d in decisions}
    placements = defaultdict(list)
    for c in read_json(REG)['cases']:
        placements[c.get('decisionId') or identity(c)['decisionId']].append(c)
    written = skipped_text = skipped_exists = 0
    for did, cs in placements.items():
        d = by_decision.get(did)
        mine = [c for c in cs if c['group'] == 'enbanc' and (c.get('scourtSource') or {}).get('srno')]
        if not d or not mine:
            continue
        if any(has_text(c) for c in cs):
            skipped_text += 1
            continue
        target = mine[0]
        path = os.path.join(FETCHED, target['id'] + '.json')
        if os.path.exists(path):
            skipped_exists += 1
            continue
        write_json(path, fetched_record(target['id'], d), indent=1)
        written += 1
    print(f'포털 전문 저장 {written}건; 기존 텍스트가 있어 건너뜀 {skipped_text}건; 파일이 이미 있어 건너뜀 {skipped_exists}건')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--output', required=True)
    p = sub.add_parser('candidates')
    p.add_argument('--titles', required=True)
    p.add_argument('--overrides', help='decisionId → 과목 JSON(규칙 분류를 고칠 때)')
    p.add_argument('--output', required=True)
    sub.add_parser('fetched')
    a = ap.parse_args()
    {'prepare': cmd_prepare, 'candidates': cmd_candidates, 'fetched': cmd_fetched}[a.cmd](a)


if __name__ == '__main__':
    main()
