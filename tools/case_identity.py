"""Stable project identifiers and verified standard-casebook source contracts.

Court IDs are internal, not official court codes. Placement IDs and fetched
filenames remain separate from a docket (caseId) and adjudication (decisionId).
Unknown courts fail closed; extend COURTS after verifying the complete name.
"""
import copy
import datetime
import re
import unicodedata


COURTS = {
    '대법원': 'sc', '헌법재판소': 'cc',
    '서울고등법원': 'hcseoul', '대전고등법원': 'hcdaejeon',
    '대구고등법원': 'hcdaegu', '부산고등법원': 'hcbusan',
    '광주고등법원': 'hcgwangju', '수원고등법원': 'hcsuwon',
    '특허법원': 'pc', '서울행정법원': 'acseoul',
    '서울가정법원': 'fcseoul', '인천가정법원': 'fcincheon',
    '수원가정법원': 'fcsuwon', '대전가정법원': 'fcdaejeon',
    '대구가정법원': 'fcdaegu', '부산가정법원': 'fcbusan',
    '울산가정법원': 'fculsan', '광주가정법원': 'fcgwangju',
    '서울중앙지방법원': 'dcseoulcentral', '서울동부지방법원': 'dcseouleast',
    '서울서부지방법원': 'dcseoulwest', '서울남부지방법원': 'dcseoulsouth',
    '서울북부지방법원': 'dcseoulnorth', '의정부지방법원': 'dcuijeongbu',
    '인천지방법원': 'dcincheon', '수원지방법원': 'dcsuwon',
    '춘천지방법원': 'dcchuncheon', '대전지방법원': 'dcdaejeon',
    '청주지방법원': 'dccheongju', '대구지방법원': 'dcdaegu',
    '부산지방법원': 'dcbusan', '울산지방법원': 'dculsan',
    '창원지방법원': 'dcchangwon', '광주지방법원': 'dcgwangju',
    '전주지방법원': 'dcjeonju', '제주지방법원': 'dcjeju',
    '서울회생법원': 'rcseoul', '수원회생법원': 'rcsuwon', '부산회생법원': 'rcbusan',
    '수원지방법원 성남지원': 'dcsuwonbseongnam',
    '수원지방법원 안양지원': 'dcsuwonbanyang',
    '수원지방법원 안산지원': 'dcsuwonbansan',
    '수원지방법원 평택지원': 'dcsuwonbpyeongtaek',
    '수원지방법원 여주지원': 'dcsuwonbyeoju',
    '인천지방법원 부천지원': 'dcincheonbbucheon',
    '의정부지방법원 고양지원': 'dcuijeongbubgoyang',
    '의정부지방법원 남양주지원': 'dcuijeongbubnamyangju',
}
CASE_SYMBOLS = {
    '다': 'da', '다카': 'daka', '도': 'do', '두': 'du', '누': 'nu',
    '마': 'ma', '므': 'meu', '그': 'geu', '스': 'seu', '라': 'ra',
    '가합': 'gahap', '가단': 'gadan', '가소': 'gaso', '나': 'na',
    '고합': 'gohap', '고단': 'godan', '고정': 'gojeong', '노': 'no',
    '구합': 'guhap', '구단': 'gudan', '모': 'mo', '오': 'o', '우': 'u',
    '후': 'hu', '허': 'heo', '카': 'ka', '자': 'ja', '재': 'jae',
    '헌가': 'heonga', '헌나': 'heonna', '헌다': 'heonda', '헌라': 'heonra',
    '헌마': 'heonma', '헌바': 'heonba', '헌사': 'heonsa', '헌아': 'heona',
    '헌자': 'heonja', '헌차': 'heoncha',
}
STANDARD_FIELDS = ('issues', 'holdings', 'statutes', 'precedents', 'subjectStatutes')
IDENTITY_FIELDS = ('courtId', 'caseNumberId', 'caseId', 'decisionType', 'decisionId')
_DOCKET = re.compile(r'^(\d{4}|\d{2})([가-힣]+)(\d+)$')


def court_id(court, declared=None):
    name = ' '.join(unicodedata.normalize('NFKC', court or '').split())
    matches = [(name_, cid) for name_, cid in COURTS.items()
               if name_.replace(' ', '') == name.replace(' ', '')]
    if not matches:
        raise ValueError(f'미등록 또는 불명확한 법원: {court!r}; 정식 법원명 확인 후 COURTS에 별도 ID를 등록하세요')
    cid = matches[0][1]
    if declared and declared != cid:
        raise ValueError(f'법원 ID 불일치: {court!r}={cid}, 등록값={declared}')
    return cid


def primary_case_number(number):
    """Keep the first complete docket number and historical year width."""
    compact = re.sub(r'\s+', '', unicodedata.normalize('NFKC', number or ''))
    primary = re.split(r'[·,;/]|등', compact, maxsplit=1)[0]
    if not _DOCKET.fullmatch(primary):
        raise ValueError(f'해석할 수 없는 대표 사건번호: {number!r}')
    return primary


def merged_display(number):
    return bool(re.search(r'\(병합\)$', re.sub(r'\s+', '', unicodedata.normalize('NFKC', number or ''))))


def case_number_list(number):
    """표시용 병합번호의 모든 사건번호. '2011헌바129,172(병합)' → ['2011헌바129', '2011헌바172']."""
    compact = re.sub(r'\s+', '', unicodedata.normalize('NFKC', number or ''))
    compact = re.sub(r'\(병합\)$', '', compact)
    compact = re.sub(r'등$', '', compact)
    out = []
    for part in re.split(r'[·,;/]', compact):
        if out and re.fullmatch(r'\d+', part):
            year, kind, _ = _DOCKET.fullmatch(out[0]).groups()
            part = f'{year}{kind}{part}'
        if _DOCKET.fullmatch(part):
            out.append(part)
    return out


def docket_parts(number):
    return _DOCKET.fullmatch(primary_case_number(number)).groups()


def encode_symbol(symbol):
    return CASE_SYMBOLS.get(symbol) or ('x' + ''.join(f'{ord(c):06x}' for c in symbol) + 'z')


def decode_symbol(encoded):
    inverse = {v: k for k, v in CASE_SYMBOLS.items()}
    if encoded in inverse:
        return inverse[encoded]
    if re.fullmatch(r'x(?:[0-9a-f]{6})+z', encoded):
        return ''.join(chr(int(encoded[i:i + 6], 16)) for i in range(1, len(encoded) - 1, 6))
    raise ValueError(f'알 수 없는 사건부호 ID: {encoded!r}')


def case_number_id(number):
    year, kind, serial = docket_parts(number)
    return year + encode_symbol(kind) + serial


def decode_case_number_id(value):
    match = re.fullmatch(r'(\d{4}|\d{2})(x(?:[0-9a-f]{6})+z|[a-z]+)(\d+)', value or '')
    if not match:
        raise ValueError(f'해석할 수 없는 사건번호 ID: {value!r}')
    year, symbol, serial = match.groups()
    return year + decode_symbol(symbol) + serial


def decision_type(record, citation=''):
    explicit = record.get('decisionType')
    if explicit not in (None, '', '판결', '결정'):
        raise ValueError(f'판결/결정 유형 오류: {explicit!r}')
    cited = None
    m = re.search(r'(판결|결정)\s*[\]】]?\s*$', citation or '')
    if m:
        cited = m.group(1)
    if explicit and cited and explicit != cited:
        raise ValueError(f'등록 유형 {explicit}과 공식 인용의 유형 {cited} 불일치')
    if record.get('court') == '헌법재판소' and (explicit == '판결' or cited == '판결'):
        raise ValueError('헌법재판소 재판 유형은 결정이어야 합니다')
    if explicit or cited:
        return explicit or cited
    if record.get('court') == '헌법재판소':
        return '결정'
    kind = docket_parts(record.get('lookupKey') or record['caseNumber'])[1]
    if kind in {'다', '다카', '도', '두', '누', '므', '후', '허', '가합', '가단', '가소', '나', '고합', '고단', '고정', '노', '구합', '구단'}:
        return '판결'
    if kind in {'마', '모', '스', '그', '라'}:
        return '결정'
    raise ValueError(f'재판 유형 확인 필요: {record["caseNumber"]}; decisionType을 판결/결정으로 지정하세요')


def identity(record, citation=''):
    cid = court_id(record.get('court'), record.get('courtId'))
    primary = primary_case_number(record['caseNumber'])
    lookup = primary_case_number(record.get('lookupKey') or primary)
    # 명시적 '(병합)' 표시번호가 대표 번호(lookupKey)를 포함하면 대표 번호가 첫 번호가 아니어도 허용한다(예: 2011헌바129,172(병합)).
    if lookup != primary and not (merged_display(record['caseNumber']) and lookup in case_number_list(record['caseNumber'])):
        raise ValueError(f'대표 사건번호 불일치: {primary} / lookupKey={lookup}')
    nid = record.get('caseNumberId') or case_number_id(lookup)
    if decode_case_number_id(nid) != lookup:
        raise ValueError(f'사건번호 ID 불일치: {lookup} / caseNumberId={nid}')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', record.get('decisionDate', '')):
        raise ValueError('decisionDate는 YYYY-MM-DD여야 합니다')
    dt = datetime.date.fromisoformat(record['decisionDate'])
    dtype = decision_type(record, citation)
    caseid = f'{cid}-{nid}'
    return {'courtId': cid, 'caseNumberId': nid, 'caseId': caseid,
            'decisionType': dtype,
            'decisionId': f'{caseid}-{dt:%Y%m%d}-' + ('judgment' if dtype == '판결' else 'decision')}


def validate_standard_source(source):
    """Check provenance structure. PDF comparison remains a human/agent review."""
    if source is None:
        return
    if not isinstance(source, dict) or source.get('verified') is not True:
        raise ValueError('standardSource는 PDF 원문 대조 후 verified:true여야 합니다')
    allowed = set(STANDARD_FIELDS) | {'verified', 'book', 'edition', 'file', 'pages', 'url', 'reviewedAt', 'reviewer', 'sha256'}
    unknown = set(source) - allowed
    if unknown:
        raise ValueError(f'standardSource의 미지원 필드: {sorted(unknown)}')
    for key in ('book', 'edition', 'file'):
        if not isinstance(source.get(key), str) or not source[key].strip():
            raise ValueError(f'standardSource.{key} 출처 정보가 필요합니다')
    pages = source.get('pages')
    if not isinstance(pages, list) or not pages or any(type(p) is not int or p < 1 for p in pages):
        raise ValueError('standardSource.pages는 PDF의 1부터 시작하는 실제 페이지 번호 배열이어야 합니다')
    if not any(k in source for k in STANDARD_FIELDS):
        raise ValueError('standardSource에 검토된 텍스트 필드가 없습니다')
    for key in STANDARD_FIELDS:
        if key not in source:
            continue
        values = source[key]
        if not isinstance(values, list):
            raise ValueError(f'standardSource.{key}는 배열이어야 합니다')
        if key in ('issues', 'holdings'):
            if any(not isinstance(x, dict) or not isinstance(x.get('n'), str)
                   or not isinstance(x.get('text'), str) or not x['text'].strip() for x in values):
                raise ValueError(f'standardSource.{key}는 {{n, text}} 배열이어야 합니다')
        elif any(not isinstance(x, str) or not x.strip() for x in values):
            raise ValueError(f'standardSource.{key}는 비어 있지 않은 문자열 배열이어야 합니다')


def standard_sources_by_decision(records, identities):
    """Share book fields among placements; conflicting verified texts are errors."""
    out = {}
    for record in records:
        source = record.get('standardSource')
        if source is None:
            continue
        validate_standard_source(source)
        decision_id = identities[record['id']]['decisionId']
        fields = out.setdefault(decision_id, {})
        provenance = {k: copy.deepcopy(v) for k, v in source.items() if k not in STANDARD_FIELDS}
        for key in STANDARD_FIELDS:
            if key not in source:
                continue
            if key in fields and fields[key]['value'] != source[key]:
                raise ValueError(f'{decision_id}: 서로 다른 표준판례 {key} 충돌 — 출처를 대조해 우선 판본을 명시하세요')
            item = fields.setdefault(key, {'value': copy.deepcopy(source[key]), 'sources': []})
            if provenance not in item['sources']:
                item['sources'].append(provenance)
    return out
