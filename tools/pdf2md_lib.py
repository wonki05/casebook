"""표준판례 PDF → Markdown 파이프라인 공용 함수 (md_validate.py · md_merge.py · test_pdf2md.py 가 공유). 단독 실행 없음.

설계·계약: spec/PIPELINE-pdf2md.md §2~§5, spec/TASK-pdf2md.md §2·§3·§6. 하위 모델 산출 형식: tools/prompts/pdf2md.md.

- normalize / digit_seq     대조·유사도 공통 정규화와 숫자열
- parse_md / parse_case_line md/cNNN.md 파싱(H2 블록 = 항목 1개)
- Haystack / verify_sections pages/pNNNN.txt 와 문자 대조(절 경계 포함) — 대조 게이트
- load_skeleton / load_pages / pages_sha256 / read_jsonl / write_json …  입출력
- standard_source_from_sections / check_standard_source / sample_size / pick_sample  병합 규칙
"""
import datetime
import difflib
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import unicodedata

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
from casenum import CASE_RE, DATE_RE, norm_date  # noqa: E402
from case_identity import COURTS, STANDARD_FIELDS, identity, primary_case_number, validate_standard_source  # noqa: E402,F401
from subjects import BY_ID, resolve_standard  # noqa: E402

ROOT = os.path.dirname(TOOLS)

BOOK = '표준판례'
EDITION = '2023년 개정판'
PASS_RATIO = 0.995            # 부분 문자열이 아닐 때 통과 하한(SequenceMatcher 비율)
SEED = 20261024               # 표본 난수 시드 기본값(_review.jsonl 머리에 기록)
SAMPLE_RATE = 0.1             # pass 의 10%
MIN_SAMPLE = 20               # 과목당 최소 20건
DEFECT_TOLERANCE = 0.005      # 결함 허용 0.5%
TITLE_MAX = 20                # 이보다 긴 제목은 _review 에 축약 판정 기록

# md 의 ### 절 이름(정규) — 순서는 지시문 틀과 같다
SECTIONS = ('주제', '쟁점', '판시사항', '판결요지', '참조조문', '선정이유', '기타')
NOTE_SECTION = '검토메모'
SECTION_ALIASES = {'결정요지': '판결요지', '판례선정이유': '선정이유', '검토메모': '검토메모', '기타': '기타'}
# PDF 꺾쇠 제목 → 정규 이름(그 밖의 제목은 'other:<이름>' 으로 절 경계로만 쓴다)
PDF_SECTION_CANON = {'주제': '주제', '쟁점': '쟁점', '판시사항': '판시사항', '판결요지': '판결요지', '결정요지': '판결요지',
                     '참조조문': '참조조문', '선정이유': '선정이유', '판례선정이유': '선정이유'}
# 대조 게이트의 표시 필드 → standardSource 키 (판시사항이 없으면 쟁점이 issues 자리를 채운다: 사용자 결정 §6-1)
FIELD_TO_SOURCE = {'판시사항': 'issues', '쟁점': 'issues', '판결요지': 'holdings', '참조조문': 'statutes'}
SOURCE_KEYS = frozenset(STANDARD_FIELDS) | {'verified', 'book', 'edition', 'file', 'pages', 'url', 'reviewedAt', 'reviewer', 'sha256'}
REVIEW_REASONS = ('fail', 'conflict', 'warn', 'notes', 'sample')   # 우선순위 순
VERDICTS = ('ok', 'fix', 'reject', 'pending')

# ---------------------------------------------------------------- 정규화
_PRE = str.maketrans({
    'ㆍ': '·', 'ᆞ': '·', '・': '·', '･': '·', '∙': '·', '‧': '·', '·': '·', '·': '·',
    'ﺠ': ' ', 'ﾠ': ' ', 'ㅤ': ' ', 'ᅠ': ' ', 'ᅟ': ' ',
})
_POST = str.maketrans({
    # 필러(NFKC 가 U+FFA0·U+3164 를 U+1160 으로 바꾼다)·폭 없는 문자
    'ᅠ': ' ', 'ᅟ': ' ', 'ᆞ': '·', '・': '·', '​': '', '‌': '', '‍': '', '⁠': '', '﻿': '', '­': '',
    # 괄호 통일: 【】〖〗 → [], 〈〉《》「」『』<> → 제거
    '【': '[', '】': ']', '〖': '[', '〗': ']',
    '〈': '', '〉': '', '《': '', '》': '', '「': '', '」': '', '『': '', '』': '', '<': '', '>': '',
    # 하이픈류·물결표 통일
    '‐': '-', '‑': '-', '‒': '-', '–': '-', '—': '-', '―': '-', '−': '-', '﹣': '-', '⁃': '-',
    '∼': '~', '〜': '~', '˜': '~',
})
_WS = re.compile(r'\s+')
_DIGITS = re.compile(r'[0-9]+')


def light_clean(text):
    """줄 단위 판정용: NFKC + 필러를 공백으로, 앞뒤 공백 제거(공백 자체는 남긴다)."""
    t = unicodedata.normalize('NFKC', (text or '').translate(_PRE))
    return t.translate({0x1160: ' ', 0x115f: ' ', 0x200b: '', 0xfeff: ''}).strip()


def normalize(text):
    """대조·유사도 공통 정규화: NFKC → 필러 → 공백·줄바꿈 제거 → 괄호 통일 → 전각 반각화(NFKC) → 하이픈류 통일."""
    t = unicodedata.normalize('NFKC', (text or '').translate(_PRE))
    return _WS.sub('', t.translate(_POST))


def digit_seq(text):
    """정규화한 텍스트의 숫자열 목록(사건번호·연월일·조문·금액 대조용)."""
    return _DIGITS.findall(normalize(text))


def similarity(a, b):
    """정규화 문자열 두 개의 SequenceMatcher 비율(autojunk 끔)."""
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def norm_label(s):
    """목차 라벨 비교용(공백·가운뎃점·구두점 무시)."""
    return re.sub(r'[\s·,.()\[\]]', '', normalize(s))


# ---------------------------------------------------------------- md 파싱
_H2 = re.compile(r'^##(?!#)\s*(.*?)\s*$')
_H3 = re.compile(r'^###(?!#)\s*(.*?)\s*$')
_HEAD = re.compile(r'^(\(\s*이어짐\s*\)\s*)?(\d{1,4})\s*[.．]\s*(.*)$')
_META = re.compile(r'^\s*[-*]\s*(출처|사건|위치|쪽)\s*[:：]\s*(.*?)\s*$')
_FENCE = re.compile(r'^\s*```')
_ILLEGIBLE = re.compile(r'\[\s*판독\s*불가[^\]]*\]')


def _is_none(text):
    t = re.sub(r'\s+', '', text or '')
    return t in ('', '(없음)', '-(없음)', '없음')


def canon_section(name):
    n = re.sub(r'\s+', '', name or '')
    if n in SECTIONS:
        return n
    return SECTION_ALIASES.get(n)


def parse_pages_spec(spec):
    """'49-50' → [49, 50], '49' → [49], '49, 51~52' → [49, 51, 52]. 해석 불가면 []."""
    s = normalize(spec).replace('p.', '').replace('P.', '').replace('쪽', '')
    out = []
    for part in re.split(r'[,;]', s):
        if not part:
            continue
        m = re.fullmatch(r'(\d{1,4})(?:[-~](\d{1,4}))?', part)
        if not m:
            return []
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if b < a or b - a > 60 or a < 1:
            return []
        out.extend(range(a, b + 1))
    return sorted(set(out))


def court_name(raw):
    """COURTS 의 정식 이름(공백 차이 허용). 없으면 None."""
    name = ' '.join(unicodedata.normalize('NFKC', raw or '').split())
    for known in COURTS:
        if known.replace(' ', '') == name.replace(' ', ''):
            return known
    return None


def parse_case_line(line):
    """'- 사건: 2022다200249 | 2022-05-26 | 대법원 | 판결 | 전원합의체 아니오' →
    {caseNumber, lookupKey, date, court, decisionType, enBanc, errors[], warnings[]}.
    decisionType 은 '판결'|'결정'|None(판결? 등 불확실), enBanc 은 True|False|None."""
    text = re.sub(r'^\s*[-*]\s*사건\s*[:：]\s*', '', line or '').strip()
    parts = [p.strip() for p in text.split('|')]
    out = {'caseNumber': '', 'lookupKey': '', 'date': None, 'court': '', 'decisionType': None, 'enBanc': None,
           'errors': [], 'warnings': []}
    if len(parts) != 5:
        out['errors'].append(f'사건 줄 칸 수 {len(parts)} (5칸 필요): {text[:80]}')
        parts = (parts + [''] * 5)[:5]
    number = re.sub(r'\s+', '', unicodedata.normalize('NFKC', parts[0]))
    out['caseNumber'] = number
    try:
        primary = primary_case_number(number)
        out['lookupKey'] = primary
        if not CASE_RE.fullmatch(primary):
            out['warnings'].append(f'사건부호가 casenum.CASE_RE 에 없음: {primary}')
    except ValueError:
        out['errors'].append(f'사건번호 해석 불가: {parts[0]!r}')
    raw_date = unicodedata.normalize('NFKC', parts[1])
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date):
        try:
            datetime.date.fromisoformat(raw_date)
            out['date'] = raw_date
        except ValueError:
            out['errors'].append(f'날짜 오류: {raw_date}')
    elif DATE_RE.fullmatch(raw_date.strip()):
        try:
            iso = norm_date(*DATE_RE.fullmatch(raw_date.strip()).groups())
            datetime.date.fromisoformat(iso)
            out['date'] = iso
            out['warnings'].append(f'날짜 표기 정규화: {raw_date} → {iso}')
        except ValueError:
            out['errors'].append(f'날짜 오류: {raw_date}')
    else:
        out['errors'].append(f'날짜 없음/형식 오류: {raw_date or "(빈칸)"}')
    court = ' '.join(unicodedata.normalize('NFKC', parts[2]).split())
    known = court_name(court)
    out['court'] = known or court
    if not court:
        out['errors'].append('법원 칸이 비어 있음')
    elif not known:
        out['warnings'].append(f'COURTS 에 없는 법원: {court}')
    dtype = re.sub(r'\s+', '', parts[3])
    if dtype in ('판결', '결정'):
        out['decisionType'] = dtype
    else:
        out['warnings'].append(f'판결/결정 불확실: {parts[3] or "(빈칸)"}')
    eb = re.sub(r'\s+', '', parts[4])
    if '아니' in eb:
        out['enBanc'] = False
    elif eb.endswith('예'):
        out['enBanc'] = True
    else:
        out['errors'].append(f'전원합의체 칸 해석 불가: {parts[4]!r}')
    if out['enBanc'] and out['court'] != '대법원':
        out['warnings'].append('전원합의체 표시가 대법원이 아닌 사건에 있음')
    return out


def _finish_section(block, name, lines):
    if name is None:
        return
    text = '\n'.join(lines).strip('\n')
    text = '\n'.join(l.rstrip() for l in text.split('\n')).strip()
    if name == NOTE_SECTION:
        notes = []
        for l in text.split('\n'):
            s = re.sub(r'^\s*[-*]\s*', '', l).strip()
            if s and not _is_none(s):
                notes.append(s)
        block['notes'].extend(notes)
        return
    value = None if _is_none(text) else text
    if name in block['sections']:
        if block['sections'][name] is not None and value is not None:
            block['warnings'].append(f'### {name} 절이 두 번 나옴(이어 붙임)')
            value = block['sections'][name] + '\n' + value
        elif value is None:
            value = block['sections'][name]
        else:
            block['warnings'].append(f'### {name} 절이 두 번 나옴')
    block['sections'][name] = value


def parse_md(text):
    """md 파일 내용 → 항목 블록 목록. 블록:
    {no, title, continued, header, line, citationRaw, cases[], location, pages[], pagesRaw, sections{절: 텍스트|None},
     notes[], unknownSections{}, illegible, errors[], warnings[]}
    첫 H2 앞에 내용이 있으면 no=None 인 'preamble' 블록을 맨 앞에 둔다."""
    lines = (text or '').replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if lines and lines[0].startswith('﻿'):
        lines[0] = lines[0][1:]
    fences = {i for i, l in enumerate(lines) if _FENCE.match(l)}
    lines = [l for i, l in enumerate(lines) if i not in fences]
    blocks, block, sec, buf, pre = [], None, None, [], []
    for lineno, raw in enumerate(lines, 1):
        h2 = _H2.match(raw)
        if h2:
            if block is not None:
                _finish_section(block, sec, buf)
            sec, buf = None, []
            header = h2.group(1)
            m = _HEAD.match(header)
            block = {'no': int(m.group(2)) if m else None, 'title': (m.group(3).strip() if m else header), 'continued': bool(m and m.group(1)),
                     'header': header, 'line': lineno, 'citationRaw': None, 'cases': [], 'location': None, 'pages': [], 'pagesRaw': None,
                     'sections': {}, 'notes': [], 'unknownSections': {}, 'illegible': 0, 'errors': [], 'warnings': []}
            if not m:
                block['errors'].append(f'H2 머리를 해석할 수 없음: {header[:60]}')
            blocks.append(block)
            continue
        if block is None:
            if raw.strip():
                pre.append(raw)
            continue
        h3 = _H3.match(raw)
        if h3:
            _finish_section(block, sec, buf)
            buf = []
            name = canon_section(h3.group(1))
            if name is None:
                block['warnings'].append(f'알 수 없는 절: ### {h3.group(1)}')
                sec = '?' + h3.group(1)
            else:
                sec = name
            continue
        if sec is None:
            mm = _META.match(raw)
            if mm:
                key, val = mm.group(1), mm.group(2)
                if key == '출처':
                    block['citationRaw'] = val
                elif key == '사건':
                    block['cases'].append(parse_case_line(val))
                elif key == '위치':
                    block['location'] = val
                elif key == '쪽':
                    block['pagesRaw'] = val
                    block['pages'] = parse_pages_spec(val)
                    if not block['pages']:
                        block['errors'].append(f'쪽 표기 해석 불가: {val!r}')
            elif raw.strip():
                block['warnings'].append(f'머리 줄 형식 밖 내용: {raw.strip()[:60]}')
            continue
        buf.append(raw)
    if block is not None:
        _finish_section(block, sec, buf)
    for b in blocks:
        for name in [k for k in b['sections'] if k.startswith('?')]:
            b['unknownSections'][name[1:]] = b['sections'].pop(name)
        b['illegible'] = sum(len(_ILLEGIBLE.findall(v or '')) for v in b['sections'].values()) + \
            sum(len(_ILLEGIBLE.findall(v or '')) for v in b['unknownSections'].values())
        if not b['continued']:
            if b['citationRaw'] is None:
                b['errors'].append('- 출처: 줄 없음')
            if not b['cases']:
                b['errors'].append('- 사건: 줄 없음')
            if b['pagesRaw'] is None:
                b['warnings'].append('- 쪽: 줄 없음')
    if pre:
        blocks.insert(0, {'no': None, 'title': '', 'continued': False, 'header': '(preamble)', 'line': 1, 'citationRaw': None, 'cases': [],
                          'location': None, 'pages': [], 'pagesRaw': None, 'sections': {}, 'notes': [], 'unknownSections': {},
                          'illegible': 0, 'errors': [f'첫 H2 앞에 내용 {len(pre)}줄'], 'warnings': [], 'preamble': True})
    if fences:
        (blocks[0] if blocks else {'warnings': []})['warnings'].append(f'코드펜스 {len(fences)}줄 제거')
    return blocks


def location_parts(location):
    parts = [p.strip() for p in re.split(r'\s*[>›»]\s*', location or '') if p.strip()]
    return [p for p in parts if not re.fullmatch(r'\(?\s*(절\s*)?없음\s*\)?', p)]


def location_compatible(location, labels, chunk_location=None):
    """md 의 '- 위치:' 와 skeleton 의 tocLabels(또는 청크 위치) 가 서로의 부분집합이면 호환."""
    md = {norm_label(p) for p in location_parts(location)}
    if not md:
        return False
    for ref in (labels or [], location_parts(chunk_location)):
        sk = {norm_label(p) for p in ref if p}
        if sk and (md <= sk or sk <= md):
            return True
    return False


# ---------------------------------------------------------------- 쪽 텍스트와 대조
# 꺾쇠 절 제목: <판결요지> 〈쟁점〉 <판결요지(다수의견)> — 괄호 표기는 절 본문 첫머리로 둔다(md 가 빼거나 [ ] 로 써도 통과)
_SECTION_HEAD = re.compile(r'^\s*[<〈]\s*((?:[가-힣]\s*){2,12}?)\s*(\(\s*[^()<>〈〉]{1,20}?\s*\))?\s*[>〉]\s*(.*)$')
_HEADING = re.compile(r'^(제\s*\d+\s*(편|장|절|관))(\s+\S.*)?$|^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+)\s*[.．]\s*\S')
_ENTRY_LINE = re.compile(r'^\s*(\d{1,3})\s*[.．]\s*(.*)$')   # 'N.' 만 있는 줄(제목이 앞뒤 줄로 갈린 경우)도 항목 머리
_RUNHEAD = re.compile(r'^제\s*\d+\s*편(\s*제\s*\d+\s*장)?(\s+\S.*)?$')
_PAGENO = re.compile(r'^[-–—\s]*\d{1,4}[-–—\s]*$|^-\s*[ivxlcIVXLC]+\s*-$')
_SENT_END = re.compile(r'(다|요|음|함|됨|임)\s*[.。]?\s*$')
_COURT_WORD = re.compile(r'대법원|헌재|헌법재판소|대판|대결|법원')


def strip_furniture(raw_lines):
    """쪽 머리글(첫 줄: '…표준판례연구' 또는 '제N편 제N장 …')과 쪽 번호(끝 줄)를 뺀 원문 줄 목록."""
    out = [l for l in raw_lines]
    while out and not out[0].strip():
        out.pop(0)
    if out:
        first = light_clean(out[0])
        if '표준판례' in first.replace(' ', '') or (_RUNHEAD.match(first) and len(first) <= 40 and not _SENT_END.search(first)
                                                   and not re.search(r'[,.]', first)):
            out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    if out and _PAGENO.match(light_clean(out[-1])):
        out.pop()
    return out


def _is_heading(line):
    return len(line) <= 30 and bool(_HEADING.match(line)) and not _SENT_END.search(line) and not re.search(r'[,]', line)


def _is_citation_line(line):
    if not (line.startswith('(') or line.startswith('（')) or len(line) > 90:
        return False
    compact = line.replace(' ', '')
    return bool(_COURT_WORD.search(compact) and CASE_RE.search(compact))


def _citation_follows(flat, i):
    head = flat[i][1]
    m = re.search(r'[(（](.*)$', head)
    if m and (_COURT_WORD.search(m.group(1)) or CASE_RE.search(m.group(1).replace(' ', ''))):
        return True
    for j in range(i + 1, min(i + 4, len(flat))):
        l = flat[j][1]
        if l.startswith('(') or l.startswith('（'):
            compact = l.replace(' ', '')
            return bool(_COURT_WORD.search(compact) or CASE_RE.search(compact))
        if _SECTION_HEAD.match(l):
            return False
    return False


class Haystack:
    """여러 쪽의 원문을 머리글·쪽번호를 빼고 정규화해 이은 문자열과 경계(cut) 목록.
    cut: {'offset', 'kind': section|heading|entry, 'name', 'no', 'title'} — 꺾쇠 절 제목은 문자열에서 빠지고 경계로만 남는다."""

    def __init__(self, pages_text):
        flat = []
        for p in sorted(pages_text):
            for raw in strip_furniture((pages_text[p] or '').split('\n')):
                line = light_clean(raw)
                if line:
                    flat.append((p, line))
        parts, cuts, page_spans = [], [], []
        pos, cur, start = 0, None, 0
        for i, (p, line) in enumerate(flat):
            if p != cur:
                if cur is not None:
                    page_spans.append((cur, start, pos))
                cur, start = p, pos
            m = _SECTION_HEAD.match(line)
            if m:
                name = re.sub(r'\s+', '', m.group(1))
                qual = normalize(m.group(2) or '')
                cuts.append({'offset': pos, 'kind': 'section', 'name': PDF_SECTION_CANON.get(name, 'other:' + name), 'raw': name, 'page': p,
                             'qual': qual})
                seg = qual + normalize(m.group(3))
            else:
                seg = normalize(line)
                em = _ENTRY_LINE.match(line)
                if _is_heading(line):
                    cuts.append({'offset': pos, 'kind': 'heading', 'name': line, 'page': p})
                elif em and _citation_follows(flat, i):
                    title = em.group(2) or (flat[i + 1][1] if i + 1 < len(flat) else '')
                    cuts.append({'offset': pos, 'kind': 'entry', 'no': int(em.group(1)), 'title': normalize(title), 'page': p})
                elif _is_citation_line(line) and i + 1 < len(flat) and _SECTION_HEAD.match(flat[i + 1][1]):
                    # 한 항목에 재판이 여럿이면 '(대법원 … 판결)' 줄 뒤에 절이 다시 시작된다 — 앞 절의 끝
                    cuts.append({'offset': pos, 'kind': 'citation', 'name': line, 'page': p})
            parts.append(seg)
            pos += len(seg)
        if cur is not None:
            page_spans.append((cur, start, pos))
        self.text = ''.join(parts)
        self.cuts = cuts
        self.page_spans = page_spans
        self.qual = {c['offset']: c['qual'] for c in cuts if c['kind'] == 'section' and c.get('qual')}

    def pages_of(self, start, end):
        if end <= start:
            return [p for p, s, e in self.page_spans if s <= start < e][:1]
        return [p for p, s, e in self.page_spans if s < end and e > start]

    def page_of(self, offset):
        for p, s, e in self.page_spans:
            if s <= offset < e or (offset == e and s == e):
                return p
        return self.page_spans[-1][0] if self.page_spans else None

    def _entry_cuts(self, no, title):
        cands = [c for c in self.cuts if c['kind'] == 'entry' and c['no'] == no]
        t = normalize(title)[:6]
        titled = [c for c in cands if t and (c['title'].startswith(t) or t.startswith(c['title'][:6]))]
        return titled or cands

    def region(self, no, title, start_page=None, next_entry=None):
        """항목 머리(번호+제목)부터 다음 항목 머리 전까지 (start, end, note). 머리를 못 찾으면 전체 범위와 note."""
        cands = self._entry_cuts(no, title) if no is not None else []
        if start_page is not None:
            cands = sorted(cands, key=lambda c: (c['page'] != start_page, abs((c['page'] or 0) - start_page), c['offset']))
        if not cands:
            return 0, len(self.text), '항목 머리 위치 미확인(쪽 범위 전체와 대조)'
        start = cands[0]['offset']
        end = None
        if next_entry:
            nxt = [c for c in self._entry_cuts(next_entry.get('no'), next_entry.get('title') or '') if c['offset'] > start]
            if nxt:
                end = nxt[0]['offset']
        later = [c['offset'] for c in self.cuts if c['kind'] == 'entry' and c['offset'] > start]
        if later:   # skeleton 이 놓친 항목 머리('N.' 줄)가 사이에 있으면 거기서 끊는다
            end = min(end, later[0]) if end is not None else later[0]
        return start, end if end is not None else len(self.text), ''

    def section_spans(self, start, end):
        """구간 안의 꺾쇠 절 → {정규 이름: [(s, e), …]} (절 끝 = 다음 경계)."""
        out = {}
        for i, c in enumerate(self.cuts):   # cuts 는 줄 순서(= offset 오름차순)
            if c['kind'] != 'section' or not (start <= c['offset'] < end):
                continue
            e = self.cuts[i + 1]['offset'] if i + 1 < len(self.cuts) else len(self.text)
            out.setdefault(c['name'], []).append((c['offset'], max(c['offset'], min(e, end))))
        return out


def _compare(needle, hay, spans):
    """needle(정규화) 과 PDF 절 구간들(한 항목에 같은 절이 여럿이면 그 이음도) 중 가장 가까운 것의 비교 결과."""
    best = None
    options = []
    for sp in spans:
        target = hay.text[sp[0]:sp[1]]
        options.append(([sp], target, ''))
        q = hay.qual.get(sp[0])
        if q and target.startswith(q):
            options.append(([sp], target[len(q):], f'절 제목의 {q} 표기 없이 일치'))
            options.append(([sp], '[' + q[1:-1] + ']' + target[len(q):], f'절 제목의 {q} 를 [ ] 로 적은 것과 일치'))
    if len(spans) > 1:
        options.append((list(spans), ''.join(hay.text[s:e] for s, e in spans), f'PDF 의 같은 절 {len(spans)}개를 이은 것과 일치'))
    for used, target, note in options:
        if needle == target:
            return {'status': 'pass', 'method': 'substring', 'ratio': 1.0, 'digitsOk': True, 'note': note, 'spans': used}
        ratio = similarity(needle, target)
        digits_ok = _DIGITS.findall(needle) == _DIGITS.findall(target)
        cand = {'ratio': ratio, 'digitsOk': digits_ok, 'spans': used, 'target': target}
        if best is None or ratio > best['ratio']:
            best = cand
    ratio, digits_ok, target = best['ratio'], best['digitsOk'], best['target']
    notes = []
    if needle and needle in target:
        i = target.find(needle)
        notes.append(f'절 경계 불일치: md 가 PDF 절의 일부(앞 {i}자·뒤 {len(target) - i - len(needle)}자 빠짐)')
    elif target and target in needle:
        notes.append(f'절 경계 불일치: md 에 PDF 절 밖 내용 {len(needle) - len(target)}자')
    if not digits_ok:
        notes.append('숫자열 불일치')
    ok = ratio >= PASS_RATIO and digits_ok and not notes
    if not ok and ratio < PASS_RATIO and not notes:
        notes.append(f'유사도 {ratio:.4f} < {PASS_RATIO}')
    return {'status': 'pass' if ok else 'fail', 'method': 'lcs', 'ratio': round(ratio, 4), 'digitsOk': digits_ok,
            'note': '; '.join(notes), 'diff': diff_snippets(target, needle), 'spans': best['spans']}


def diff_snippets(pdf, md, limit=3, width=12):
    """정규화 PDF 절과 md 의 차이 위치(판정자용): ['…앞뒤[PDF→md]…', …]."""
    if len(pdf) * len(md) > 4_000_000:
        return []
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, pdf, md, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        out.append(f'…{pdf[max(0, i1 - width):i1]}[{pdf[i1:i2][:40]}→{md[j1:j2][:40]}]{pdf[i2:i2 + width]}…')
        if len(out) >= limit:
            break
    return out


def display_fields(sections, pdf_names=()):
    """대조할 표시 필드 이름 목록. 판시사항이 md·PDF 어디에도 없고 쟁점이 있으면 쟁점이 issues 자리(§6-1)."""
    sections = sections or {}
    names = set(pdf_names or ())
    if sections.get('판시사항') or '판시사항' in names:
        issues = '판시사항'
    elif sections.get('쟁점') or '쟁점' in names:
        issues = '쟁점'
    else:
        issues = None
    return [f for f in (issues, '판결요지', '참조조문') if f]


def verify_sections(sections, pages_text, no=None, title='', start_page=None, next_entry=None):
    """대조 게이트(PIPELINE §3-1). sections: md 절 {이름: 텍스트|None}, pages_text: {쪽: 원문}.
    반환 {'status': pass|fail|skip, 'fields': {필드: {status, method, ratio, digitsOk, note}}, 'pages': [...], 'note': str}
    - PDF 절 구간과 정규화 문자열이 같으면 pass(substring). 아니면 SequenceMatcher 비율 ≥ 0.995 이고 숫자열이 같아야 pass(lcs).
    - PDF 에 있는 절이 md 에 (없음) 이면 fail(절 누락). md 에만 있고 PDF 항목 안에 그 절 제목이 없으면 fail.
    - 표시 필드가 md·PDF 모두 없으면 skip."""
    hay = Haystack(pages_text)
    start, end, rnote = hay.region(no, title, start_page, next_entry)
    spans = hay.section_spans(start, end)
    present = {n for n, ss in spans.items() if any(e > s for s, e in ss)}
    fields, used = {}, []
    for f in display_fields(sections, present):
        md_text = (sections or {}).get(f)
        pdf = [(s, e) for s, e in spans.get(f, []) if e > s]
        if md_text is None and not pdf:
            continue
        if md_text is None:
            fields[f] = {'status': 'fail', 'method': 'absent', 'ratio': 0.0, 'digitsOk': False,
                         'note': f'PDF 에 있는 〈{f}〉 절이 md 에 (없음)'}
            used.extend(pdf)
            continue
        needle = normalize(md_text)
        if not pdf:
            where = ''
            idx = hay.text.find(needle, start, end) if needle else -1
            if idx >= 0:
                owner = [c for c in hay.cuts if c['kind'] == 'section' and c['offset'] <= idx]
                where = f' (md 텍스트는 PDF 〈{owner[-1]["raw"]}〉 절 안에 있음)' if owner else ''
            fields[f] = {'status': 'fail', 'method': 'absent', 'ratio': 0.0, 'digitsOk': False,
                         'note': f'PDF 항목 안에서 〈{f}〉 절 제목을 찾지 못함{where}'}
            continue
        r = _compare(needle, hay, pdf)
        used.extend(r.pop('spans'))
        fields[f] = r
    pages = sorted({p for s, e in used for p in hay.pages_of(s, e)})
    if not fields:
        status = 'skip'
    else:
        status = 'pass' if all(v['status'] == 'pass' for v in fields.values()) else 'fail'
    # 한 항목 안의 '(법원 … 판결)' 인용 줄 수와 같은 절이 여러 번 나오는 절 — 여러 재판이 실린 항목 표시(md_validate 가 warn)
    inside = [c for c in hay.cuts if start <= c['offset'] < end]
    cites = sum(1 for c in inside if c['kind'] == 'citation')
    if not rnote and len(inside) > 1 and inside[0]['kind'] == 'entry' and inside[1]['kind'] == 'citation':
        cites -= 1   # 제목 바로 아래 인용 줄은 그 항목 자신의 것
    cites += 1
    repeated = sorted(n for n, ss in spans.items() if len(ss) > 1 and not n.startswith('other:'))
    return {'status': status, 'fields': fields, 'pages': pages, 'note': rnote, 'citations': cites, 'repeatedSections': repeated}


def haystack_pages(pdf_pages, skeleton_pages, total=None, last=False):
    """대조할 쪽 범위: skeleton 쪽 ∪ (그 근처의) md 쪽, 앞뒤 1쪽 허용. 마지막 항목(last)은 PDF 끝(최대 +3쪽)까지."""
    base = set(skeleton_pages or [])
    if pdf_pages:
        if base:
            lo, hi = min(base) - 2, max(base) + 2
            base |= {p for p in pdf_pages if lo <= p <= hi}
        else:
            base = set(pdf_pages)
    if not base:
        return []
    lo, hi = max(1, min(base) - 1), max(base) + (3 if last else 1)
    if total:
        hi = min(hi, int(total))
    return list(range(lo, hi + 1))


def verify_entry(subject_dir, sections, pdf_pages, skel_entry, next_entry=None, total_pages=None):
    """verify_sections + 쪽 파일 읽기 + pagesSha256. skel_entry/next_entry 는 skeleton 항목(dict) 또는 None."""
    skel_pages = (skel_entry or {}).get('pdfPages') or []
    pages = haystack_pages(pdf_pages, skel_pages, total_pages, last=next_entry is None)
    text = load_pages(subject_dir, pages)
    if not text:
        return {'status': 'skip' if not any((sections or {}).get(f) for f in FIELD_TO_SOURCE) else 'fail',
                'fields': {}, 'pages': [], 'note': 'pages/ 쪽 파일 없음', 'pagesSha256': ''}
    start_page = skel_pages[0] if skel_pages else (pdf_pages[0] if pdf_pages else None)
    v = verify_sections(sections, text, (skel_entry or {}).get('no'), (skel_entry or {}).get('title', ''), start_page, next_entry)
    sha_pages = v['pages'] or sorted(set(pdf_pages or skel_pages))
    v['pagesSha256'] = pages_sha256(subject_dir, sha_pages)
    return v


# ---------------------------------------------------------------- 입출력
def main_root():
    """worktree 안에서도 main 작업 폴더(등록부·목차의 최신본)를 찾는다."""
    try:
        common = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, capture_output=True, text=True,
                                timeout=10).stdout.strip()
        if common:
            path = common if os.path.isabs(common) else os.path.join(ROOT, common)
            return os.path.abspath(os.path.join(path, '..'))
    except (OSError, subprocess.SubprocessError):
        pass
    return ROOT


def data_file(name):
    """data/<name> — main 작업 폴더에 있으면 그것(최신 등록부·목차), 없으면 이 작업 폴더의 것."""
    for base in (main_root(), ROOT):
        path = os.path.join(base, 'data', name)
        if os.path.exists(path):
            return path
    return os.path.join(ROOT, 'data', name)


def subject_dir(subject=None, directory=None):
    """(과목 id, 과목 폴더). --dir 만 주면 skeleton.json 의 subject 를 쓴다."""
    sid = resolve_standard(subject) if subject else None
    if directory:
        path = os.path.abspath(directory)
        if not sid:
            skel = os.path.join(path, 'skeleton.json')
            if os.path.exists(skel):
                sid = resolve_standard(read_json(skel).get('subject') or '')
        if not sid:
            raise ValueError('--subject 를 지정하세요(skeleton.json 에 subject 없음)')
        return sid, path
    if not sid:
        raise ValueError('--subject 또는 --dir 가 필요합니다')
    return sid, os.path.join(ROOT, 'data', 'standard-cases', BY_ID[sid]['folder'])


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1) + '\n')


def read_jsonl(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f'{path}:{i}: JSON 오류 {exc}') from exc
    return rows


def write_jsonl(path, rows):
    write_text(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def append_jsonl(path, rows):
    if not rows:
        return
    prefix = ''
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, 'rb') as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b'\n':
                prefix = '\n'
    with open(path, 'a', encoding='utf-8', newline='\n') as f:
        f.write(prefix + ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def load_skeleton(directory):
    """skeleton.json → dict (+ 'bySeq', 'byChunk' 색인). 없으면 FileNotFoundError."""
    skel = read_json(os.path.join(directory, 'skeleton.json'))
    entries = sorted(skel.get('entries') or [], key=lambda e: e['seq'])
    skel['entries'] = entries
    skel['bySeq'] = {e['seq']: e for e in entries}
    by_chunk = {}
    for e in entries:
        by_chunk.setdefault(e.get('chunk'), []).append(e)
    skel['byChunk'] = by_chunk
    skel['chunkById'] = {c['id']: c for c in skel.get('chunks') or []}
    return skel


def page_path(directory, page):
    return os.path.join(directory, 'pages', f'p{int(page):04d}.txt')


def load_pages(directory, pages):
    """{쪽: 원문} — 파일이 있는 쪽만."""
    out = {}
    for p in pages or []:
        path = page_path(directory, p)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                out[int(p)] = f.read()
    return out


def pages_sha256(directory, pages):
    """대조에 쓴 pages/ 파일 내용(쪽 순서대로 이은 바이트)의 sha256. 파일이 하나도 없으면 ''."""
    h, n = hashlib.sha256(), 0
    for p in sorted({int(x) for x in pages or []}):
        path = page_path(directory, p)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                h.update(f.read())
            n += 1
    return h.hexdigest() if n else ''


def text_sha256(entry):
    """판정 기록이 가리키는 md 텍스트의 지문(md 가 다시 만들어지면 판정을 다시 받는다)."""
    payload = json.dumps({'sections': entry.get('sections') or {}, 'cases': [
        {k: c.get(k) for k in ('caseNumber', 'date', 'court', 'decisionType', 'enBanc')} for c in entry.get('cases') or []]},
        ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def now_iso():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def today():
    return datetime.date.today().isoformat()


# ---------------------------------------------------------------- 병합 규칙
def split_items(text):
    from build_data import split_items as _split   # 공식 판시사항·판결요지와 같은 번호 분리 규칙
    return _split(text)


def split_lines(text):
    return [l.strip() for l in (text or '').replace('\r', '').split('\n') if l.strip()]


def standard_source_from_sections(sections, verified_fields, *, file, pages, reviewer, reviewed_at, sha256):
    """대조(또는 판정)를 통과한 표시 필드만 standardSource 로. 통과 필드가 없으면 None.
    판시사항이 있으면 그것이, 없고 쟁점이 통과했으면 쟁점이 issues 가 된다(§6-1)."""
    src = {'verified': True, 'book': BOOK, 'edition': EDITION, 'file': file, 'pages': sorted({int(p) for p in pages})}
    fields = [f for f in verified_fields if sections.get(f)]
    if '판시사항' in fields and '쟁점' in fields:
        fields.remove('쟁점')
    for f in fields:
        key = FIELD_TO_SOURCE[f]
        if key in ('issues', 'holdings'):
            items = split_items(sections[f])
            if items:
                src[key] = items
        else:
            lines = split_lines(sections[f])
            if lines:
                src[key] = lines
    if not any(k in src for k in STANDARD_FIELDS) or not src['pages']:
        return None
    src.update({'reviewer': reviewer, 'reviewedAt': reviewed_at})
    if sha256:
        src['sha256'] = sha256
    return src


def check_standard_source(src):
    """validate_standard_source + 허용 키 검사 → 오류 문자열 목록(빈 목록 = 통과)."""
    errors = []
    if not isinstance(src, dict):
        return ['standardSource 가 객체가 아님']
    unknown = set(src) - SOURCE_KEYS
    if unknown:
        errors.append(f'허용되지 않는 키: {sorted(unknown)}')
    try:
        validate_standard_source(src)
    except ValueError as exc:
        errors.append(str(exc))
    if 'reviewedAt' in src and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(src['reviewedAt'])):
        errors.append(f'reviewedAt 은 YYYY-MM-DD: {src["reviewedAt"]!r}')
    return errors


def sample_size(population, rate=SAMPLE_RATE, minimum=MIN_SAMPLE):
    """표본 크기: ceil(rate × N), 최소 minimum, 최대 N."""
    if population <= 0:
        return 0
    return min(population, max(minimum, math.ceil(rate * population)))


def pick_sample(keys, already, target, seed=SEED):
    """keys 를 seed 로 섞은 순서대로, 이미 뽑힌 것(already)을 포함해 target 개가 될 때까지 추가로 뽑는다 → 새로 뽑은 키 목록."""
    order = sorted(keys, key=lambda k: json.dumps(k, ensure_ascii=False))
    random.Random(seed).shuffle(order)
    pool = set(order)
    have = sum(1 for k in already or () if k in pool)
    already = set(already or ())
    picked = []
    for k in order:
        if have + len(picked) >= target:
            break
        if k not in already:
            picked.append(k)
    return picked


def defect_rate(defects, size):
    return (defects / size) if size else 0.0
