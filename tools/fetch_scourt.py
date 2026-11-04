#!/usr/bin/env python3
"""사법정보공개포털(portal.scourt.go.kr) 종합법률정보에서 대법원 전원합의체 판례의 목록·전문을 수집해 data/scourt/ 에 보존한다.

law.go.kr 수집(data/fetched/)과는 출처가 달라 별도 폴더에 둔다. registry.json·cases.json·fetched/ 는 건드리지 않는다.
포털 화면(WebSquare)이 쓰는 JSON 엔드포인트를 그대로 호출한다(쿠키·브라우저 불필요).

Usage:
  python tools/fetch_scourt.py list                 # 판례등급=전원합의체·대법원 목록 → data/scourt/enbanc-list.json
  python tools/fetch_scourt.py docs                 # 목록 중 전문이 없는 사건의 전문 → data/scourt/docs/<srno>.json
  python tools/fetch_scourt.py discarded            # 판례등급=폐기(변경) 중 제목에 '전원합의체'가 있는 사건을 찾아 전문까지 수집
  python tools/fetch_scourt.py annotate             # 전문 머리글의 폐기·변경 표시를 discardNote·discarded 로 기록
  python tools/fetch_scourt.py verify               # 건수·중복·전문 구조 점검 → data/scourt/collection-report.json
  옵션: --from 1978-01-01 --to <오늘> --delay 0.4 --force(이미 받은 전문도 다시)

저장 원칙: 포털 전문 HTML(orgdocXmlCtt)은 수정 없이 그대로 두고 text 는 거기서 태그만 걷어낸 파생값이다.
포털 판례등급은 한 값만 갖기 때문에 이후 판례 변경으로 폐기된 전원합의체는 '폐기(변경)' 등급에 들어 있고, 전원합의체 등급 검색에는 나오지 않는다.
그런 사건에는 discarded: true 를 기록한다(웹 화면 표시 방식은 미정이라 JSON 에만 둔다).
"""
import argparse, datetime, html, json, os, re, sys, time, urllib.error, urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'scourt')
DOCS = os.path.join(OUT, 'docs')
LIST = os.path.join(OUT, 'enbanc-list.json')
SCAN = os.path.join(OUT, 'discarded-scan.json')
REPORT = os.path.join(OUT, 'collection-report.json')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from case_identity import identity  # noqa: E402

BASE = 'https://portal.scourt.go.kr'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 lawbook-study/1.0'
GRADE_ENBANC, GRADE_DISCARDED = '01', '04'   # grpJdcpctGrCd (판례등급 검색 값)
SUBSET_ENBANC, SUBSET_DISCARDED = 'enbanc-grade', 'discarded-enbanc'


def post(path, body, pgmid, tries=4):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type': 'application/json;charset=UTF-8', 'Accept': 'application/json',
               'SC-Pgmid': pgmid, 'User-Agent': UA}
    for attempt in range(tries):
        try:
            req = urllib.request.Request(BASE + path, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=60) as r:
                j = json.loads(r.read().decode('utf-8'))
            if j.get('status') == 200 and j.get('data') is not None:
                return j
            raise RuntimeError(f'응답 오류: {j.get("status")} {j.get("message")}')
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt * 2)
            print(f'  재시도 {attempt + 1}: {e}', file=sys.stderr)


def search_body(grade, date_from, date_to, page_size, page_no=1):
    return {'dma_searchParam': {
        'srchwd': '', 'sort': 'jis_jdcpc_instn_dvs_cd_s asc, $relevance desc, prnjdg_ymd_o desc, jdcpct_gr_cd_s asc',
        'sortType': '정확도', 'searchRange': '', 'tpcJdcpctCsAlsYn': '', 'csNoLstCtt': '', 'csNmLstCtt': '',
        'prvsRefcCtt': '', 'searchScope': '', 'jisJdcpcInstnDvsCd': '01', 'jdcpctCdcsCd': '',
        'prnjdgYmdFrom': date_from.replace('-', ''), 'prnjdgYmdTo': date_to.replace('-', ''),
        'grpJdcpctGrCd': grade, 'cortNm': '', 'pageNo': str(page_no), 'jisJdcpcInstnDvsCdGrp': '',
        'grpJdcpctGrCdGrp': '', 'jdcpctCdcsCdGrp': '', 'adjdTypCdGrp': '', 'pageSize': str(page_size),
        'reSrchFlag': '', 'befSrchwd': '', 'preSrchConditions': '', 'initYn': 'N', 'totalCount': '',
        'jdcpctGrCd': '111|112|130|141|180|182|232|235', 'category': 'jdcpct', 'isKwdSearch': 'N'}}


def fetch_items(grade, date_from, date_to, delay):
    """한 요청으로 전체를 받는다(pageSize 700 확인). 총건수와 다르면 쪽을 넘기며 이어 받는다."""
    size = 700
    j = post('/pgp/pgp1011/selectJdcpctSrchRsltLst.on', search_body(grade, date_from, date_to, size), 'PGP1011M01')
    total = int(j['data']['totalCount'])
    items = list(j['data']['dlt_jdcpctRslt'])
    page = 1
    while len(items) < total:
        page += 1
        time.sleep(delay)
        j = post('/pgp/pgp1011/selectJdcpctSrchRsltLst.on', search_body(grade, date_from, date_to, size, page), 'PGP1011M01')
        got = j['data']['dlt_jdcpctRslt']
        if not got:
            break
        items.extend(got)
    return total, items


def iso(ymd):
    return f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'


def to_record(item, subset):
    rec = {
        'srno': str(item['jisCntntsSrno']), 'subset': subset,
        'court': item['cortNm'], 'caseNumber': item['csNoLstCtt'], 'caseName': item.get('csNmLstCtt', ''),
        'decisionDate': iso(item['prnjdgYmd']), 'decisionType': item['adjdTypNm'],
        'portalGrade': item['grpJdcpctGrNm'], 'discarded': item['grpJdcpctGrNm'] == '폐기(변경)',
        'publication': item.get('jdcpctPublcCtt', ''), 'caseAlias': item.get('jdcpctCsAlsNm', ''),
    }
    try:
        rec.update(identity({'court': rec['court'], 'caseNumber': rec['caseNumber'],
                             'decisionDate': rec['decisionDate'], 'decisionType': rec['decisionType']}))
    except ValueError as e:
        rec['identityError'] = str(e)
    return rec


def load_list():
    if not os.path.exists(LIST):
        return {'meta': {}, 'records': []}
    with open(LIST, encoding='utf-8') as f:
        return json.load(f)


def mark_duplicates(records):
    groups = defaultdict(list)
    for r in records:
        if r.get('decisionId'):
            groups[r['decisionId']].append(r['srno'])
    for r in records:
        r.pop('duplicateGroup', None)
        r.pop('duplicateSrnos', None)
        peers = groups.get(r.get('decisionId'), [])
        if len(peers) > 1:
            r['duplicateGroup'] = r['decisionId']
            r['duplicateSrnos'] = sorted(p for p in peers if p != r['srno'])


def write_json(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent, separators=(',', ': ') if indent else (',', ':'))
        f.write('\n')
    for attempt in range(5):   # Windows 에서 백신·인덱서가 파일을 잠시 잡고 있으면 교체가 거부될 수 있다
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def save_list(data, subset, records, meta):
    keep = [r for r in data.get('records', []) if r['subset'] != subset]
    allrec = keep + records
    allrec.sort(key=lambda r: (r['subset'], r['decisionDate'], r['caseNumber'], r['srno']), reverse=False)
    mark_duplicates(allrec)
    data['records'] = allrec
    data.setdefault('meta', {}).setdefault('queries', {})[subset] = meta
    write_json(LIST, data, indent=1)


def cmd_list(a):
    total, items = fetch_items(GRADE_ENBANC, a.date_from, a.date_to, a.delay)
    recs = [to_record(x, SUBSET_ENBANC) for x in items]
    if len({r['srno'] for r in recs}) != len(recs):
        raise SystemExit('일련번호 중복: 목록 응답이 이상합니다')
    meta = {'source': '사법정보공개포털 종합법률정보 판례 검색', 'court': '대법원', 'grade': '전원합의체',
            'from': a.date_from, 'to': a.date_to, 'portalTotal': total, 'collected': len(recs),
            'collectedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
    save_list(load_list(), SUBSET_ENBANC, recs, meta)
    print(f'목록 {len(recs)}건 (포털 총건수 {total}) → {os.path.relpath(LIST, ROOT)}')


def derive_text(h):
    t = re.sub(r'<(?:br\s*/?|/p|/div|/tr|/h\d|/li)>', '\n', h, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t).replace('\xa0', ' ')
    t = re.sub(r'[ \t]+\n', '\n', t)
    return re.sub(r'\n{3,}', '\n\n', t).strip()


def title_of(h):
    m = re.search(r'<h2>([\s\S]*?)</h2>', h)
    return ' '.join(html.unescape(m.group(1)).replace('\xa0', ' ').split()) if m else ''


def fetch_ctxt(rec):
    body = {'dma_searchParam': {
        'jisCntntsSrno': rec['srno'], 'srchwd': '*', 'csNoLstCtt': rec['caseNumber'], 'cortNm': rec['court'],
        'adjdTypNm': rec['decisionType'], 'jdcpctBrncNo': '', 'jdcpctGrCd': '', 'chnchrYn': '', 'systmNm': ''}}
    j = post('/pgp/pgp1011/selectJdcpctCtxt.on', body, 'PGP1011M04')
    d = j['data'].get('dma_jdcpctCtxt') or {}
    if str(d.get('jisCntntsSrno')) != rec['srno'] or not d.get('orgdocXmlCtt'):
        raise RuntimeError(f'전문 응답 불일치/비어 있음: {rec["srno"]} {rec["caseNumber"]}')
    return d


def doc_path(srno):
    return os.path.join(DOCS, f'{srno}.json')


def title_matches(rec, title):
    """제목 '대법원 2026. 7. 22. 선고 …' 또는 결정의 '…. 9. 2.자 …' 가 목록의 사건번호·선고일과 같은지."""
    m = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(?:선고|자)', title)
    title_date = f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''
    return {'caseNumber': rec['caseNumber'] in title, 'date': title_date == rec['decisionDate']}


def build_doc(rec, d):
    h = d['orgdocXmlCtt']
    title = title_of(h)
    return {
        'srno': rec['srno'], 'court': rec['court'], 'caseNumber': rec['caseNumber'],
        'decisionDate': rec['decisionDate'], 'decisionType': rec['decisionType'],
        'portalGrade': rec['portalGrade'], 'subset': rec['subset'], 'discarded': rec['discarded'],
        'source': {'site': '사법정보공개포털 종합법률정보', 'endpoint': '/pgp/pgp1011/selectJdcpctCtxt.on',
                   'url': f'{BASE}/pgp/main.on?w2xPath=PGP1011M04&jisCntntsSrno={rec["srno"]}&c=900',
                   'fileName': d.get('jisFileNm'), 'filePath': d.get('jisFilePathNm'),
                   'portalFirstInput': d.get('frstInptDt'), 'portalLastChanged': d.get('lastChgDt')},
        'fetchedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'title': title, 'enbancInTitle': '전원합의체' in title,
        'titleMatches': title_matches(rec, title),
        'orgdocXmlCtt': h, 'text': derive_text(h), 'textDerived': True,
    }


def cmd_docs(a, subset=None):
    data = load_list()
    recs = [r for r in data['records'] if subset is None or r['subset'] == subset]
    todo = [r for r in recs if a.force or not os.path.exists(doc_path(r['srno']))]
    print(f'전문 대상 {len(recs)}건 중 새로 받을 것 {len(todo)}건')
    failed = []
    for i, r in enumerate(todo, 1):
        try:
            write_json(doc_path(r['srno']), build_doc(r, fetch_ctxt(r)))
        except Exception as e:  # noqa: BLE001 - 사건별 실패를 모아 보고하고 계속한다
            failed.append((r['srno'], r['caseNumber'], str(e)))
            print(f'  실패 {r["srno"]} {r["caseNumber"]}: {e}', file=sys.stderr)
        if i % 50 == 0:
            print(f'  {i}/{len(todo)}', flush=True)
        time.sleep(a.delay)
    print(f'전문 수집 완료: 성공 {len(todo) - len(failed)}, 실패 {len(failed)}')
    for f in failed:
        print('  FAIL', *f)
    return failed


def discard_note(text):
    """전문 머리글의 '변경 : … 판결에 의하여 변경' · '폐기 : …' 줄(판례등급과 별개로 포털이 붙이는 표시)."""
    head = text.split('【', 1)[0]
    m = re.search(r'(?m)^[ \t]*((?:변경|폐기)[ \t]*[:：][ \t]*\S.*?)[ \t]*$', head)
    return ' '.join(m.group(1).split()) if m else ''


def cmd_annotate(a):
    """받아 둔 전문에서 폐기·변경 표시를 찾아 전문 파일과 목록 기록에 discardNote·discarded 로 남긴다(전문 원본은 그대로)."""
    data = load_list()
    changed = 0
    for r in data['records']:
        with open(doc_path(r['srno']), encoding='utf-8') as f:
            d = json.load(f)
        note = discard_note(d['text'])
        discarded = r['portalGrade'] == '폐기(변경)' or bool(note)
        if d.get('discardNote', '') != note or d.get('discarded') != discarded:
            d['discardNote'], d['discarded'] = note, discarded
            write_json(doc_path(r['srno']), d)
        if r.get('discardNote', '') != note or r['discarded'] != discarded:
            changed += 1
        r['discarded'], r['discardNote'] = discarded, note
        if not note:
            del r['discardNote']
    write_json(LIST, data, indent=1)
    flagged = [r['caseNumber'] for r in data['records'] if r['discarded']]
    print(f'폐기·변경 표시 {len(flagged)}건 (등급 폐기(변경) {sum(r["portalGrade"] == "폐기(변경)" for r in data["records"])}건 포함); 목록 기록 갱신 {changed}건')


def cmd_discarded(a):
    total, items = fetch_items(GRADE_DISCARDED, a.date_from, a.date_to, a.delay)
    print(f'폐기(변경) 등급 {total}건: 제목에 전원합의체가 있는지 확인합니다')
    scan = {}
    if os.path.exists(SCAN):
        with open(SCAN, encoding='utf-8') as f:
            scan = json.load(f).get('scanned', {})
    recs, failed = [], []
    for i, it in enumerate(items, 1):
        r = to_record(it, SUBSET_DISCARDED)
        s = scan.get(r['srno'])
        if s is None or a.force:
            try:
                doc = build_doc(r, fetch_ctxt(r))
            except Exception as e:  # noqa: BLE001
                failed.append((r['srno'], r['caseNumber'], str(e)))
                print(f'  실패 {r["srno"]} {r["caseNumber"]}: {e}', file=sys.stderr)
                continue
            s = {'caseNumber': r['caseNumber'], 'decisionDate': r['decisionDate'], 'title': doc['title'],
                 'enbanc': doc['enbancInTitle']}
            scan[r['srno']] = s
            if s['enbanc']:
                write_json(doc_path(r['srno']), doc)
            time.sleep(a.delay)
        if s['enbanc']:
            recs.append(r)
        if i % 50 == 0:
            print(f'  {i}/{len(items)}', flush=True)
            write_json(SCAN, {'scanned': scan}, indent=1)
    write_json(SCAN, {'scanned': scan}, indent=1)
    meta = {'source': '사법정보공개포털 종합법률정보 판례 검색', 'court': '대법원', 'grade': '폐기(변경)',
            'filter': '전문 제목에 전원합의체 포함', 'from': a.date_from, 'to': a.date_to, 'portalTotal': total,
            'scanned': len(scan), 'enbancFound': len(recs), 'failed': len(failed),
            'collectedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
    save_list(load_list(), SUBSET_DISCARDED, recs, meta)
    print(f'폐기(변경) {total}건 중 전원합의체 {len(recs)}건, 실패 {len(failed)}건')
    for f in failed:
        print('  FAIL', *f)


SECTIONS = ('판시사항', '판결요지|결정요지', '참조조문', '주\\s*문', '이\\s*유')


def cmd_verify(a):
    data = load_list()
    recs = data['records']
    rep = {'checkedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
           'records': len(recs), 'bySubset': dict(Counter(r['subset'] for r in recs))}
    rep['missingDocs'] = [r['srno'] for r in recs if not os.path.exists(doc_path(r['srno']))]
    rep['identityErrors'] = [(r['srno'], r['caseNumber'], r['identityError']) for r in recs if r.get('identityError')]
    dup = defaultdict(list)
    for r in recs:
        if r.get('duplicateGroup'):
            dup[r['duplicateGroup']].append(r['srno'])
    rep['duplicateGroups'] = dict(dup)
    same = {}
    for g, srnos in dup.items():
        texts = set()
        for s in srnos:
            if os.path.exists(doc_path(s)):
                with open(doc_path(s), encoding='utf-8') as f:
                    texts.add(json.load(f)['text'])
        same[g] = len(texts) == 1
    rep['duplicateTextIdentical'] = same
    rep['distinctDecisions'] = len({r.get('decisionId') or r['srno'] for r in recs})
    bad_title, no_enbanc_title, sec_missing, empty, sizes = [], [], defaultdict(list), [], []
    for r in recs:
        p = doc_path(r['srno'])
        if not os.path.exists(p):
            continue
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        sizes.append(len(d['orgdocXmlCtt']))
        if len(d['text']) < 500:
            empty.append(r['srno'])
        tm = title_matches(r, d['title'])
        if not (tm['caseNumber'] and tm['date']):
            bad_title.append((r['srno'], r['caseNumber'], d['title']))
        if not d['enbancInTitle']:
            no_enbanc_title.append((r['srno'], r['caseNumber'], d['title']))
        for name in SECTIONS:
            if not re.search(f'【(?:{name})】', d['text']):
                sec_missing[name].append(r['srno'])
    rep.update({'titleMismatch': bad_title, 'titleWithoutEnbanc': no_enbanc_title, 'shortText': empty,
                'sectionMissingCounts': {k: len(v) for k, v in sec_missing.items()},
                'sectionMissing': {k: v for k, v in sec_missing.items()},
                'totalHtmlBytes': sum(sizes), 'discardedCount': sum(1 for r in recs if r['discarded'])})
    by_decade = Counter(r['decisionDate'][:3] + '0s' for r in recs)
    rep['byDecade'] = dict(sorted(by_decade.items()))
    write_json(REPORT, rep, indent=1)
    show = {k: (v if not isinstance(v, (list, dict)) or len(v) <= 8 else f'{len(v)}건') for k, v in rep.items()}
    print(json.dumps(show, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', choices=['list', 'docs', 'discarded', 'annotate', 'verify'])
    ap.add_argument('--from', dest='date_from', default='1978-01-01')
    ap.add_argument('--to', dest='date_to', default=datetime.date.today().isoformat())
    ap.add_argument('--delay', type=float, default=0.4)
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    {'list': cmd_list, 'docs': lambda x: cmd_docs(x, SUBSET_ENBANC), 'discarded': cmd_discarded,
     'annotate': cmd_annotate, 'verify': cmd_verify}[a.command](a)


if __name__ == '__main__':
    main()
