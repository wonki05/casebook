"""Stable project identifiers and verified standard-casebook source contracts.

Court IDs are internal, not official court codes. Placement IDs and fetched
filenames remain separate from a docket (caseId) and adjudication (decisionId).
Unknown courts fail closed; extend COURTS after verifying the complete name.
"""
import copy
import datetime
import re
import unicodedata
from subjects import SUBJECTS


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
STANDARD_FIELDS = ('issues', 'holdings', 'facts', 'statutes', 'precedents', 'subjectStatutes')
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
    if lookup != primary:
        raise ValueError(f'대표 사건번호 불일치: {primary} / lookupKey={lookup}')
    nid = record.get('caseNumberId') or case_number_id(primary)
    if decode_case_number_id(nid) != primary:
        raise ValueError(f'사건번호 ID 불일치: {primary} / caseNumberId={nid}')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', record.get('decisionDate', '')):
        raise ValueError('decisionDate는 YYYY-MM-DD여야 합니다')
    dt = datetime.date.fromisoformat(record['decisionDate'])
    dtype = decision_type(record, citation)
    caseid = f'{cid}-{nid}'
    return {'courtId': cid, 'caseNumberId': nid, 'caseId': caseid,
            'decisionType': dtype,
            'decisionId': f'{caseid}-{dt:%Y%m%d}-' + ('judgment' if dtype == '판결' else 'decision')}


def validate_standard_source(source):
    """Check PDF/XLSX provenance; verification still requires the actual source."""
    if source is None:
        return
    if not isinstance(source, dict) or source.get('verified') is not True:
        raise ValueError('standardSource는 원문 대조 후 verified:true여야 합니다')
    allowed = set(STANDARD_FIELDS) | {'verified', 'book', 'edition', 'file', 'pages', 'url', 'reviewedAt', 'reviewer', 'sha256',
                                      'format', 'sheet', 'rows', 'preferred'}
    unknown = set(source) - allowed
    if unknown:
        raise ValueError(f'standardSource의 미지원 필드: {sorted(unknown)}')
    for key in ('book', 'edition', 'file'):
        if not isinstance(source.get(key), str) or not source[key].strip():
            raise ValueError(f'standardSource.{key} 출처 정보가 필요합니다')
    if 'preferred' in source and type(source['preferred']) is not bool:
        raise ValueError('standardSource.preferred는 명시적으로 선택한 판본 여부를 나타내는 불리언이어야 합니다')
    source_format = source.get('format', 'pdf')
    if source_format == 'xlsx':
        if not isinstance(source.get('sheet'), str) or not source['sheet'].strip():
            raise ValueError('standardSource.sheet에 원본 통합문서의 시트명이 필요합니다')
        rows = source.get('rows')
        if not isinstance(rows, list) or not rows or any(type(r) is not int or r < 1 for r in rows):
            raise ValueError('standardSource.rows는 시트의 1부터 시작하는 실제 행 번호 배열이어야 합니다')
        if 'pages' in source:
            raise ValueError('XLSX 출처는 PDF pages 대신 sheet와 rows를 사용해야 합니다')
    elif source_format == 'pdf':
        pages = source.get('pages')
        if not isinstance(pages, list) or not pages or any(type(p) is not int or p < 1 for p in pages):
            raise ValueError('standardSource.pages는 PDF의 1부터 시작하는 실제 페이지 번호 배열이어야 합니다')
        if 'sheet' in source or 'rows' in source:
            raise ValueError('PDF 출처에는 XLSX sheet/rows를 사용할 수 없습니다')
    else:
        raise ValueError(f'standardSource.format 미지원 형식: {source_format!r}')
    if not any(k in source for k in STANDARD_FIELDS):
        raise ValueError('standardSource에 검토된 텍스트 필드가 없습니다')
    for key in STANDARD_FIELDS:
        if key not in source:
            continue
        values = source[key]
        if not isinstance(values, list):
            raise ValueError(f'standardSource.{key}는 배열이어야 합니다')
        if key in ('issues', 'holdings', 'facts'):
            if any(not isinstance(x, dict) or not isinstance(x.get('n'), str)
                   or not isinstance(x.get('text'), str) or not x['text'].strip() for x in values):
                raise ValueError(f'standardSource.{key}는 {{n, text}} 배열이어야 합니다')
        elif any(not isinstance(x, str) or not x.strip() for x in values):
            raise ValueError(f'standardSource.{key}는 비어 있지 않은 문자열 배열이어야 합니다')


def standard_sources_by_decision(records, identities):
    """Share adjudication summaries while preserving independent placements.

    Explicitly preferred editions win per field. Within the same XLSX workbook,
    separate section rows are complementary excerpts and are combined verbatim.
    Conflicts between other verified sources still fail closed. Archived sources
    are retained and checked, but cannot silently override current selections.
    """
    collected = {}
    subject_order = {s['id']: i for i, s in enumerate(SUBJECTS)}
    for record in records:
        history = record.get('standardSourceHistory', [])
        if not isinstance(history, list):
            raise ValueError(f'{record["id"]}: standardSourceHistory는 출처 배열이어야 합니다')
        for archived in history:
            validate_standard_source(archived)
        source = record.get('standardSource')
        if source is None:
            continue
        validate_standard_source(source)
        decision_id = identities[record['id']]['decisionId']
        order = (subject_order.get(record.get('subject'), len(subject_order)),
                 source.get('sheet', ''), min(source.get('rows') or source.get('pages') or [0]),
                 str((record.get('standard') or {}).get('entryId', record['id'])))
        collected.setdefault(decision_id, []).append((order, source))

    out = {}
    for decision_id, rows in collected.items():
        fields = out.setdefault(decision_id, {})
        ordered = [source for _, source in sorted(rows, key=lambda row: row[0])]
        for key in STANDARD_FIELDS:
            candidates = [source for source in ordered if key in source]
            preferred = [source for source in candidates if source.get('preferred') is True]
            if preferred:
                candidates = preferred
            if not candidates:
                continue
            groups = {}
            for source in candidates:
                # Only explicit workbook rows are complementary. PDF excerpts
                # keep the strict, pre-existing equality requirement.
                group = (('xlsx', source['book'], source['edition'], source['file'], source.get('sha256'))
                         if source.get('format') == 'xlsx' else ('single', id(source)))
                if group not in groups:
                    groups[group] = {'value': copy.deepcopy(source[key]), 'sources': []}
                elif source.get('format') == 'xlsx':
                    for value in source[key]:
                        if value not in groups[group]['value']:
                            groups[group]['value'].append(copy.deepcopy(value))
                item = groups[group]
                provenance = {k: copy.deepcopy(v) for k, v in source.items() if k not in STANDARD_FIELDS}
                if provenance not in item['sources']:
                    item['sources'].append(provenance)
            chosen = None
            for item in groups.values():
                if chosen is None:
                    chosen = item
                elif chosen['value'] != item['value']:
                    raise ValueError(f'{decision_id}: 서로 다른 표준판례 {key} 충돌 — 출처를 대조해 우선 판본을 명시하세요')
                else:
                    chosen['sources'].extend(p for p in item['sources'] if p not in chosen['sources'])
            fields[key] = chosen
    return out
