#!/usr/bin/env python3
"""표준판례 PDF → 뼈대(skeleton.json)·쪽 텍스트(pages/)·청크(chunks/)·목차 대응표(00_toc.md) 생성. 모델 토큰 0.

  python -X utf8 tools/pdf_chunks.py 상법                                  # 과목 id/한글명 → main 작업 폴더의 PDF 를 찾는다
  python -X utf8 tools/pdf_chunks.py "data/standard-cases/표준판례(2023년 개정판)_상법.pdf" [--subject commercial]
  옵션: --out <과목폴더> --chunk-pages 15 --max-pages 20 --toc-json data/toc.json --body-start N(자동 감지 대신 지정)

산출물(과목 폴더 data/standard-cases/<한글과목명>/):
  pages/pNNNN.txt   쪽별 pdfplumber 원문(대조 기준, 수정 금지)
  skeleton.json     {subject, pdf, pages, bodyStart, entries:[{seq,no,title,citationRaw,cases,tocLabels,tocPath,tocPathStatus,pdfPages,chunk}], chunks:[...]}
  chunks/cNNN_pAAAA-pBBBB.txt   머리 2줄(현재 위치 / 기대 항목) + "----- PDF p.N -----" 로 나뉜 쪽 텍스트
  00_toc.md         PDF 머리글 트리 ↔ toc.json id 대응표 (resolved / proposed)
  toc-proposed.json 기존 toc.json 과 맞지 않는 과목의 제안 목차(편›장›절) — 단계 4 승인 후 반영
  _conflicts.json   사건번호·날짜·법원·유형·목차 미해결, 번호 이상 등 사람이 볼 것
설계·계약: spec/PIPELINE-pdf2md.md §2, spec/TASK-pdf2md.md §2.
"""
import argparse, json, os, re, subprocess, sys, unicodedata, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from casenum import CASE_RE, DATE_RE, norm_date, lookup_key  # noqa: E402
from subjects import BY_ID, resolve_standard, guess_from_filename  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILLERS = dict.fromkeys(map(ord, 'ﺠﾠㅤ   　   '), ' ')
FILLERS.update({0x318d: '·', 0x119e: '·', 0x30fb: '·'})

HEAD_RE = re.compile(r'^제\s*(\d+)\s*(편|장|절|관)\s*(.*)$')
ROMAN_RE = re.compile(r'^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|X{0,1}(?:IX|IV|V?I{0,3}))\s*[.．]\s*(\S.*)$')
RUNHEAD_RE = re.compile(r'^제\s*\d+\s*편\s+제\s*\d+\s*장\b')
RUNHEAD2_RE = re.compile(r'^[가-힣]{2,6}(?:\s[가-힣]{1,4}){0,3}\s+제\s*\d+\s*편(\s*제\s*\d+\s*장)?(\s+\S.*)?$')
ENTRY_RE = re.compile(r'^(\d{1,3})\s*[.．]\s+(\S.*)$')
ENTRY_NODOT_RE = re.compile(r'^(\d{1,3})\s+([가-힣][^\d]{1,70})$')
PAGENO_RE = re.compile(r'^(-\s*)?\d{1,4}(\s*-)?$|^-\s*[ivxlc]+\s*-$')
OLD_CASE_RE = re.compile(r'(?<![0-9])(\d{4}|\d{2})\s?(민상|민재|형상|민항|행상|특항|행항|민특|형비|재도|재다|재두|재노|재마|재가|재나|재초|재항|추|무|부|드|르|브|즈|느|과|수|쿠|푸|루|토|주|흐)\s?(\d{1,7})(?![0-9])')
DATE2_RE = re.compile(r'(\d{4})\s*[.년]?\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*[.일]?')
MERGED_RE = re.compile(r'((?:\d{2}|\d{4})(?:헌[가-힣]|다카|다|도|두|마|므|누|라|바|카|그|재|스|자|노|모|보|오|우|후|히|초|허|민상|형상)\d{1,7})((?:\s*[,·・]\s*\d{1,7}(?![가-힣0-9]))+)')
COURT_RE = re.compile(r'(헌법재판소|헌재|대법원|대판|대결|[가-힣]+(?:고등|지방|가정|행정|회생)법원(?:\s*[가-힣]+지원)?|특허법원)')
LEADER_RE = re.compile(r'[·.]{6,}')
SENT_END = re.compile(r'[다요음함됨임]\s*[.。]?\s*$')
PART_WORDS = {'총칙·상행위': '총칙·상행위', '회 사': '회사', '회사': '회사', '어음·수표': '어음·수표', '보 험': '보험', '보험': '보험', '해 상': '해상', '해상': '해상',
              '형법총론': '형법총론', '형 법 총 론': '형법총론', '형법각론': '형법각론', '형 법 각 론': '형법각론'}
PART_KEYS = {k.replace(' ', ''): v for k, v in PART_WORDS.items()}


def clean(s):
    return unicodedata.normalize('NFKC', s or '').translate(FILLERS).strip()


def main_root():
    """worktree 안에서 실행해도 PDF 는 main 작업 폴더(data/standard-cases/)에서 찾는다."""
    try:
        common = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if common:
            cand = os.path.abspath(os.path.join(ROOT, common, '..')) if not os.path.isabs(common) else os.path.abspath(os.path.join(common, '..'))
            return cand
    except Exception:
        pass
    return ROOT


def find_pdf(arg, subject):
    if os.path.exists(arg) and arg.lower().endswith('.pdf'):
        return os.path.abspath(arg)
    folder = BY_ID[subject]['folder']
    for base in (ROOT, main_root()):
        p = os.path.join(base, 'data', 'standard-cases', f'표준판례(2023년 개정판)_{folder}.pdf')
        if os.path.exists(p):
            return p
    raise SystemExit(f'PDF 를 찾을 수 없습니다: {arg} (data/standard-cases/표준판례(2023년 개정판)_{folder}.pdf)')


def extract_pages(pdf):
    import logging; logging.getLogger('pdfminer').setLevel(logging.ERROR)
    import pdfplumber
    out = []
    with pdfplumber.open(pdf) as doc:
        for pg in doc.pages:
            out.append(pg.extract_text() or '')
    return out


def page_lines(text, book_word):
    """쪽 텍스트 → 머리글·쪽번호 제거한 줄 목록."""
    lines = [clean(l) for l in text.split('\n')]
    lines = [l for l in lines if l]
    while lines and (RUNHEAD_RE.match(lines[0]) or '표준판례연구' in lines[0] or lines[0] == book_word
                     or (RUNHEAD2_RE.match(lines[0]) and len(lines[0]) <= 60 and not SENT_END.search(lines[0]))):
        lines.pop(0)
    while lines and (PAGENO_RE.match(lines[-1]) or '표준판례연구' in lines[-1]):
        lines.pop()
    return lines


def is_toc_page(lines):
    return sum(1 for l in lines if LEADER_RE.search(l)) >= 3 or any(l == '목 차' or l == '목차' for l in lines[:3])


def _balanced(text, lines, j, max_extra=4):
    """text 는 '(' 다음부터. 괄호가 닫힐 때까지 다음 줄을 이어 붙여 (안쪽 텍스트, 추가로 소비한 줄 수) 반환."""
    depth, buf, extra = 1, '', 0
    while True:
        for ch in text:
            if ch in '(（':
                depth += 1
            elif ch in ')）':
                depth -= 1
                if depth == 0:
                    return buf.strip(), extra
            buf += ch
        if j + 1 >= len(lines) or extra >= max_extra:
            return buf.strip(), extra
        j += 1
        extra += 1
        text = ' ' + lines[j]


def looks_citation(text):
    t = text.replace(' ', '')
    return bool(COURT_RE.search(text) or CASE_RE.search(t) or OLD_CASE_RE.search(t))


def citation_in(lines, k):
    """lines[k] 가 항목 머리줄일 때, 같은 줄 또는 다음 3줄 안의 괄호 인용을 찾아 (citationRaw, 소비한 줄 수) 반환."""
    head = lines[k]
    m = re.search(r'[\(（](.*)$', head)
    if m and looks_citation(m.group(1)):
        text, extra = _balanced(m.group(1), lines, k)
        return text, extra
    j = k + 1
    while j < len(lines) and j <= k + 3:
        l = lines[j]
        if l.startswith('(') or l.startswith('（'):
            text, extra = _balanced(l[1:], lines, j)
            if looks_citation(text):
                return text, (j - k) + extra
            return None, 0
        if COURT_RE.match(l) and (CASE_RE.search(l.replace(' ', '')) or OLD_CASE_RE.search(l.replace(' ', ''))) and len(l) <= 90:
            return l.rstrip(')）').strip(), j - k      # 괄호 없이 적힌 인용 줄(행정법 일부)
        if HEAD_RE.match(l) or ENTRY_RE.match(l):
            return None, 0
        j += 1
    return None, 0


def parse_citation(cit):
    """괄호 인용 → cases 목록 [{caseNumber, lookupKey, date, court, decisionType, enBanc}]."""
    cit = clean(cit)
    compact = cit.replace(' ', '')
    out = []
    # 재판별로 ';' 로 나뉘기도 한다(형법). 그 외에는 사건번호 단위.
    parts = [p for p in re.split(r'[;；]', cit) if p.strip()] or [cit]
    for part in parts:
        pc = part.replace(' ', '')
        court = None
        cm = COURT_RE.search(part)
        if cm:
            c = cm.group(1).replace(' ', '')
            court = '헌법재판소' if c in ('헌재', '헌법재판소') else '대법원' if c in ('대법원', '대판', '대결') else cm.group(1).strip()
        nums = [m.group(1) + m.group(2) + m.group(3) for m in CASE_RE.finditer(pc)] or [m.group(1) + m.group(2) + m.group(3) for m in OLD_CASE_RE.finditer(pc)]
        # 병합사건: "2010다78135,78142" 처럼 뒤 번호가 숫자만(부호 없이) 이어지면 가운뎃점으로 잇는다
        merged = None
        mm = MERGED_RE.search(pc)
        if mm:
            merged = mm.group(1) + re.sub(r'\s*[,·・]\s*', '·', mm.group(2))
        dm = list(DATE_RE.finditer(part)) or list(DATE2_RE.finditer(part))
        date = norm_date(*dm[0].groups()) if dm else ''
        dtype = None
        if court == '헌법재판소' or '결정' in pc or re.search(r'\d\.자', pc) or re.search(r'\.\s*자\s', part):
            dtype = '결정'
        if '판결' in pc:
            dtype = '판결'
        if court == '헌법재판소':
            dtype = '결정'
        inferred = False
        if not dtype and '선고' in pc:
            dtype, inferred = '판결', True      # '선고'는 판결 표기 — 추정 표시
        if not nums:
            out.append({'caseNumber': '', 'lookupKey': '', 'date': date, 'court': court, 'decisionType': dtype, 'enBanc': '전원합의체' in pc, 'raw': part.strip()})
            continue
        first = True
        for n in nums:
            cn = merged if (first and merged and merged.startswith(n)) else n
            rec = {'caseNumber': cn, 'lookupKey': lookup_key(cn), 'date': date, 'court': court, 'decisionType': dtype, 'enBanc': '전원합의체' in pc}
            if inferred:
                rec['decisionTypeInferred'] = True
            out.append(rec)
            first = False
    return out


def heading_of(line):
    """편·장·절·관 또는 로마숫자 절 머리글이면 (level, label) — 1=편, 2=장, 3=절/관/로마, 아니면 None."""
    l = clean(line)
    if len(l) > 48 or SENT_END.search(l) and not HEAD_RE.match(l):
        return None
    if RUNHEAD_RE.match(l) or '참조' in l:
        return None
    m = HEAD_RE.match(l)
    if m:
        n, kind, rest = m.groups()
        rest = re.sub(r'\s+', ' ', rest).strip()
        if kind in ('편',):
            return 1, f'제{n}편 {rest}'.strip()
        if kind == '장':
            return 2, f'제{n}장 {rest}'.strip()
        return 3, f'제{n}{kind} {rest}'.strip()
    m = ROMAN_RE.match(l)
    if m and m.group(1) and m.group(2) and len(m.group(2)) <= 30 and not re.match(r'^\d', m.group(2)):
        return 3, f'{m.group(1)}. {m.group(2).strip()}'
    return None


def tidy_label(label):
    """'제 1 편 총 칙' → '제1편 총칙' 처럼 글자 사이 공백을 없앤다(목차 라벨 비교용)."""
    m = HEAD_RE.match(label)
    if m:
        n, kind, rest = m.groups()
        rest = re.sub(r'\s+', '', rest) if re.fullmatch(r'(\S\s)+\S', rest or '') else rest
        return f'제{n}{kind} {rest}'.strip()
    return label


def norm_label(s):
    return re.sub(r'[\s·ㆍ・,.()（）\[\]]', '', unicodedata.normalize('NFKC', s or ''))


def build_toc_index(toc, subject):
    idx = {}
    def rec(nodes, path, labels):
        for n in nodes:
            p = path + [n['id']]; lb = labels + [n['label']]
            idx[tuple(norm_label(x) for x in lb)] = p
            rec(n.get('children') or [], p, lb)
    rec(toc.get(subject, []), [], [])
    return idx


def ordinal(label):
    m = re.match(r'^(제\d+(?:편|장|절|관))', norm_label(label))
    return m.group(1) if m else None


def resolve_toc(labels, toc_index):
    """[분야?, 편, 장, 절?] 라벨 경로를 toc.json 경로로. 라벨 완전 일치 → 같은 부모 아래 서수(제N편/장) 일치 순으로, 깊이 3까지."""
    keys = [norm_label(x) for x in labels][:3]
    path, matched = [], ()
    for depth, k in enumerate(keys):
        cand = matched + (k,)
        if cand in toc_index:
            matched = cand
            path = toc_index[cand]
            continue
        o = ordinal(labels[depth])
        alt = [kk for kk in toc_index if len(kk) == depth + 1 and kk[:depth] == matched and o and kk[-1].startswith(o)]
        if len(alt) == 1:
            matched = alt[0]
            path = toc_index[alt[0]]
            continue
        break
    if not path:
        return None, 'unresolved'
    return path, ('resolved' if len(matched) >= min(3, len(keys)) else 'partial')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pdf_or_subject')
    ap.add_argument('--subject')
    ap.add_argument('--out')
    ap.add_argument('--chunk-pages', type=int, default=15)
    ap.add_argument('--max-pages', type=int, default=20)
    ap.add_argument('--toc-json', default=os.path.join(ROOT, 'data', 'toc.json'))
    ap.add_argument('--body-start', type=int, help='본문 시작 PDF 쪽(1부터). 생략하면 자동 감지')
    ap.add_argument('--reuse-pages', action='store_true', help='pages/ 가 이미 있으면 PDF 를 다시 읽지 않고 그 텍스트를 쓴다(재실행용)')
    a = ap.parse_args()

    subject = resolve_standard(a.subject) if a.subject else None
    if not subject:
        subject = guess_from_filename(a.pdf_or_subject) if a.pdf_or_subject.lower().endswith('.pdf') else resolve_standard(a.pdf_or_subject)
    if not subject:
        raise SystemExit('--subject 를 지정하세요')
    sdef = BY_ID[subject]
    pdf = find_pdf(a.pdf_or_subject, subject)
    out_dir = os.path.abspath(a.out or os.path.join(ROOT, 'data', 'standard-cases', sdef['folder']))
    os.makedirs(os.path.join(out_dir, 'pages'), exist_ok=True)
    os.makedirs(os.path.join(out_dir, 'chunks'), exist_ok=True)
    toc = json.load(open(a.toc_json, encoding='utf-8'))
    toc_index = build_toc_index(toc, subject)
    book_word = f'{sdef["folder"]}표준판례연구'

    print(f'[{subject}] {pdf}')
    import glob as _glob
    existing = sorted(_glob.glob(os.path.join(out_dir, 'pages', 'p*.txt')))
    if a.reuse_pages and existing:
        raw_pages = [open(f, encoding='utf-8').read() for f in existing]
        print(f'pages/ 재사용: {len(raw_pages)}쪽')
    else:
        raw_pages = extract_pages(pdf)
        for i, t in enumerate(raw_pages, 1):
            with open(os.path.join(out_dir, 'pages', f'p{i:04d}.txt'), 'w', encoding='utf-8', newline='\n') as f:
                f.write(t)
    npages = len(raw_pages)
    lines_by_page = [page_lines(t, book_word) for t in raw_pages]

    # ---- 본문 시작 쪽 감지: 목차형 쪽이 아니면서 "항목 머리 + 인용" 이 처음 나오는 쪽
    body_start = a.body_start
    if not body_start:
        for i, lines in enumerate(lines_by_page, 1):
            if is_toc_page(lines):
                continue
            for k, l in enumerate(lines):
                if ENTRY_RE.match(l) and citation_in(lines, k)[0]:
                    body_start = i; break
            if body_start:
                break
    if not body_start:
        raise SystemExit('본문 시작 쪽을 찾지 못했습니다(--body-start 로 지정)')

    # ---- 본문 순회: 머리글 추적 + 항목 추출
    entries, headings_log = [], []
    ctx = {'part': None, 1: None, 2: None, 3: None}
    conflicts = []
    last_no = 0
    heading_since_entry = True   # 마지막 항목 이후 편·장 머리글이 나왔는가(번호가 1로 재시작할 수 있는 조건)
    page_first_heading = {}   # 청크 분할 힌트: 새 편·장이 시작되는 쪽
    scan_start = body_start
    def part_like(lines):
        hs = sum(1 for l in lines if heading_of(l))
        return hs >= 2 and (len(lines) - hs) <= 2 and not any(LEADER_RE.search(l) for l in lines)
    while scan_start > 1:
        prev = lines_by_page[scan_start - 2]
        if prev and not part_like(prev):
            break
        scan_start -= 1     # 빈 쪽·부(部) 표지(머리글만 있는 쪽)만 지나 본문 바로 앞까지 거슬러 올라간다
    for pno in range(scan_start, npages + 1):
        lines = lines_by_page[pno - 1]
        if not lines:
            continue
        if is_toc_page(lines) or any(re.fullmatch(r'(판례\s*)?(색\s*인|차\s*례)', l) for l in lines[:3]):
            continue          # 끝의 판례 색인·차례 같은 목차형 쪽
        # 부(部) 표지: 짧은 쪽에 편 목록만 있는 경우 → 첫 줄을 분야명으로
        heads_here = [heading_of(l) for l in lines]
        nhead = sum(1 for h in heads_here if h)
        if nhead >= 2 and (len(lines) - nhead) <= 2 and not any(ENTRY_RE.match(l) for l in lines):
            first = [l for l, h in zip(lines, heads_here) if not h]
            if first:
                ctx['part'] = PART_KEYS.get(first[0].replace(' ', ''), first[0])
                ctx[1] = ctx[2] = ctx[3] = None
                headings_log.append((pno, 0, ctx['part']))
                page_first_heading[pno] = 1
            continue
        k = 0
        while k < len(lines):
            l = lines[k]
            if l.replace(' ', '') in PART_KEYS and not ENTRY_RE.match(l):
                ctx['part'] = PART_KEYS[l.replace(' ', '')]; ctx[1] = ctx[2] = ctx[3] = None
                heading_since_entry = True
                headings_log.append((pno, 0, ctx['part'])); page_first_heading.setdefault(pno, 1)
                k += 1; continue
            h = heading_of(l)
            if h and not ENTRY_RE.match(l):
                lv, label = h
                # '제1편 제1장 통 칙' 같은 머리글 잔재는 page_lines 에서 제거됨. 같은 라벨 반복은 무시
                label = tidy_label(label)
                if ctx.get(lv) != label:
                    ctx[lv] = label
                    if lv <= 2:
                        heading_since_entry = True
                    for deeper in range(lv + 1, 4):
                        ctx[deeper] = None
                    headings_log.append((pno, lv, label))
                    if lv <= 2:
                        page_first_heading.setdefault(pno, lv)
                k += 1; continue
            m = ENTRY_RE.match(l)
            split_head = 0
            if not m:
                m0 = re.match(r'^\d\s+((\d{1,3})\s*[.．]\s+\S.*)$', l)       # 각주 번호가 앞에 붙은 머리('4 496. 제목')
                if m0 and k + 1 < len(lines) and looks_citation(lines[k + 1]):
                    m = ENTRY_RE.match(m0.group(1))
            if not m:
                m2 = ENTRY_NODOT_RE.match(l)
                if m2 and k + 1 < len(lines) and lines[k + 1].startswith(('(', '（')) and looks_citation(lines[k + 1]):
                    m = m2
            if not m and re.match(r'^\d{1,3}\s*[.．]\s*$', l) and k + 1 < len(lines) and not ENTRY_RE.match(lines[k + 1]):
                nxt = lines[k + 1]
                if nxt.startswith(('(', '（')) and looks_citation(nxt):
                    m = None                                   # 제목 없이 바로 인용이면 항목 머리로 보지 않는다
                else:
                    m = ENTRY_RE.match(l.strip() + ' ' + nxt.strip('(（)）'))
                    if m:
                        split_head = 1
            if m:
                cit, used = citation_in(lines[:k + 1] + lines[k + 1 + split_head:], k)
                no = int(m.group(1))
                plausible = last_no == 0 or no in (last_no + 1, last_no + 2, last_no + 3) or (no == 1 and heading_since_entry)
                head_ok = not re.match(r'^(선고\s+\d|판결[)）]|결정[)）]|자\s+\d|\d{4}\.)', m.group(2)) and len(re.findall(r'[가-힣]', m.group(2))) >= 2   # '선고유예'·'판결의 효력' 같은 제목은 통과
                if not cit and m and k + 1 < len(lines) and '참조' in lines[k + 1 + split_head] and (last_no == 0 or no in (last_no + 1, last_no + 2, last_no + 3)):
                    conflicts.append({'seq': len(entries) + 1, 'no': no, 'page': pno, 'kind': 'reference', 'note': f'{m.group(2)[:40]} → {lines[k + 1 + split_head][:40]} (다른 편 참조, 사건 아님)'})
                    last_no = no
                if cit and not (plausible and head_ok):
                    conflicts.append({'seq': len(entries) + 1, 'no': no, 'page': pno, 'kind': 'numbering-skip', 'note': f'항목으로 보이지 않아 건너뜀(이전 {last_no}): ' + m.group(2)[:60]})
                    cit = None
                if cit:
                    title = m.group(2)
                    title = re.sub(r'\s*[\(（].*$', '', title).strip() if re.search(r'[\(（]\s*(대법원|헌재|헌법재판소|대판|대결|[가-힣]+법원)', title) else title
                    labels = [x for x in (ctx['part'], ctx[1], ctx[2], ctx[3]) if x]
                    path, status = resolve_toc(labels, toc_index)
                    e = {'seq': len(entries) + 1, 'no': no, 'title': title, 'citationRaw': cit, 'cases': parse_citation(cit),
                         'tocLabels': labels, 'tocPath': path, 'tocPathStatus': status, 'pdfPages': [pno], 'printedPage': None, 'chunk': None}
                    if last_no and no not in (last_no + 1, 1):
                        conflicts.append({'seq': e['seq'], 'no': no, 'page': pno, 'kind': 'numbering', 'note': f'이전 번호 {last_no} → {no}'})
                    last_no = no
                    heading_since_entry = False
                    entries.append(e)
                    k += used + 1 + split_head
                    continue
            k += 1
    if not entries:
        raise SystemExit('항목을 하나도 찾지 못했습니다')
    # 항목 쪽 범위: 다음 항목 시작 쪽까지(같은 쪽이면 한 쪽)
    def body_end_after(start):
        end = start
        for q in range(start + 1, min(npages, start + 6) + 1):
            lines_q = lines_by_page[q - 1]
            if not lines_q or is_toc_page(lines_q) or any(re.fullmatch(r'(판례\s*)?(색\s*인|차\s*례)', l) for l in lines_q[:3]):
                break
            end = q
        return end
    for i, e in enumerate(entries):
        start = e['pdfPages'][0]
        end = entries[i + 1]['pdfPages'][0] if i + 1 < len(entries) else body_end_after(start)
        e['pdfPages'] = list(range(start, max(start, end) + 1))

    # ---- 제안 목차(기존 toc.json 과 안 맞는 과목용): 머리글 로그에서 편›장›절 트리
    prefix = sdef['tocPrefix']
    proposed, counters = [], {}
    node_by_path = {}
    cur = []
    for pno, lv, label in headings_log:
        if lv == 0:
            cur = [label]; lv_eff = 1
        else:
            depth = (2 if any(x[1] == 0 for x in headings_log) else 1) if lv == 1 else (lv + (1 if any(x[1] == 0 for x in headings_log) else 0))
            cur = cur[:depth - 1] + [label]
            lv_eff = depth
        if lv_eff > 3:
            continue
        key = tuple(cur[:lv_eff])
        if key in node_by_path:
            continue
        parent = node_by_path.get(key[:-1]) if len(key) > 1 else None
        siblings = parent['children'] if parent else proposed
        nid = (parent['id'] + '-' if parent else f'{prefix}-') + str(len(siblings) + 1)
        node = {'id': nid, 'label': key[-1], 'children': []}
        siblings.append(node); node_by_path[key] = node
    # 유령 노드 가지치기: 어떤 항목의 tocLabels 접두어도 아닌 노드(편 표지에 나열된 장 목록 등)는 제거하고 id 를 다시 매긴다
    used_paths = set()
    for e in entries:
        for cut in range(1, min(3, len(e['tocLabels'])) + 1):
            used_paths.add(tuple(e['tocLabels'][:cut]))
    def prune(nodes, path):
        kept = []
        for n in nodes:
            my = path + (n['label'],)
            n['children'] = prune(n.get('children') or [], my)
            if my in used_paths or n['children']:
                kept.append(n)
        return kept
    proposed = prune(proposed, ())
    node_by_path = {}
    def renumber(nodes, parent_id, path):
        for i, n in enumerate(nodes, 1):
            n['id'] = f'{parent_id}-{i}' if parent_id else f'{prefix}-{i}'
            my = path + (n['label'],)
            node_by_path[my] = n
            renumber(n['children'], n['id'], my)
    renumber(proposed, '', ())
    # 제안 id 로 tocPath 보충(기존 toc.json 에서 못 찾은 항목)
    def proposed_path(labels):
        path = []
        for cut in range(1, min(3, len(labels)) + 1):
            n = node_by_path.get(tuple(labels[:cut]))
            if not n: break
            path.append(n['id'])
        return path
    n_resolved = 0
    for e in entries:
        if e['tocPathStatus'] == 'resolved':
            n_resolved += 1
        elif e['tocLabels']:
            pp = proposed_path(e['tocLabels'])
            if pp:
                e['tocPath'] = pp; e['tocPathStatus'] = 'proposed'
        if not e['tocPath']:
            conflicts.append({'seq': e['seq'], 'no': e['no'], 'page': e['pdfPages'][0], 'kind': 'toc', 'note': '목차 위치를 정하지 못함 ' + ' › '.join(e['tocLabels'])})
        for c in e['cases']:
            if not c.get('caseNumber'):
                conflicts.append({'seq': e['seq'], 'no': e['no'], 'page': e['pdfPages'][0], 'kind': 'case', 'note': '사건번호 없음: ' + e['citationRaw']})
            if not c.get('date'):
                conflicts.append({'seq': e['seq'], 'no': e['no'], 'page': e['pdfPages'][0], 'kind': 'date', 'note': '선고일 없음: ' + e['citationRaw']})
            if not c.get('court'):
                conflicts.append({'seq': e['seq'], 'no': e['no'], 'page': e['pdfPages'][0], 'kind': 'court', 'note': '법원 불명: ' + e['citationRaw']})
            if not c.get('decisionType'):
                conflicts.append({'seq': e['seq'], 'no': e['no'], 'page': e['pdfPages'][0], 'kind': 'decisionType', 'note': '판결/결정 불명: ' + e['citationRaw']})

    # ---- 청크 분할: 장 경계 우선, chunk_pages 안팎, max_pages 초과 금지
    starts = sorted({e['pdfPages'][0] for e in entries})
    last_page = max(e['pdfPages'][-1] for e in entries)
    chunks = []
    p = body_start
    while p <= last_page:
        target = p + a.chunk_pages - 1
        hard = min(p + a.max_pages - 1, last_page)
        cut = min(target, last_page)
        # target±3 범위에서 새 장/편이 시작되는 쪽 직전으로 자른다
        best = None
        for q in range(max(p + 5, target - 3), min(hard, target + 5) + 1):
            if (q + 1) in page_first_heading:
                best = q; break
        if best:
            cut = best
        chunks.append([p, cut]); p = cut + 1
    import glob as _g
    for stale in _g.glob(os.path.join(out_dir, 'chunks', 'c*.txt')):
        os.remove(stale)        # 이전 실행의 청크 파일(쪽 범위가 달라진 것)을 치운다
    for i, (s, e) in enumerate(chunks, 1):
        cid = f'c{i:03d}'
        exp = [x for x in entries if s <= x['pdfPages'][0] <= e]
        for x in exp:
            x['chunk'] = cid
        cont = next((x['no'] for x in reversed(entries) if x['pdfPages'][0] < s), None) if any(x['pdfPages'][0] < s and x['pdfPages'][-1] >= s for x in entries) else None
        # 청크 시작 시점의 위치: 그 쪽 이전의 마지막 머리글 문맥
        loc = []
        ctx2 = {'part': None, 1: None, 2: None, 3: None}
        for pno, lv, label in headings_log:
            if pno > s or (pno == s and lv != 0):
                break           # 청크 첫 쪽의 머리글은 본문에 그대로 보이므로 '현재 위치'는 그 직전 문맥으로 둔다
            if lv == 0:
                ctx2 = {'part': label, 1: None, 2: None, 3: None}
            else:
                ctx2[lv] = label
                for d in range(lv + 1, 4): ctx2[d] = None
        loc = [x for x in (ctx2['part'], ctx2[1], ctx2[2]) if x]
        fname = f'{cid}_p{s:04d}-p{e:04d}.txt'
        head = f"현재 위치: {' › '.join(loc) if loc else '(없음)'}\n기대 항목: {exp[0]['no'] if exp else '-'} ~ {exp[-1]['no'] if exp else '-'}" + (f"  (앞 청크에서 이어진 항목: {cont})" if cont else '') + '\n'
        with open(os.path.join(out_dir, 'chunks', fname), 'w', encoding='utf-8', newline='\n') as f:
            f.write(head)
            for pno in range(s, e + 1):
                f.write(f'\n----- PDF p.{pno} -----\n' + raw_pages[pno - 1].rstrip() + '\n')
        chunks[i - 1] = {'id': cid, 'file': f'chunks/{fname}', 'pages': [s, e], 'expected': [exp[0]['no'], exp[-1]['no']] if exp else [], 'expectedSeq': [exp[0]['seq'], exp[-1]['seq']] if exp else [], 'continued': cont, 'location': ' › '.join(loc)}

    # ---- 산출물
    skel = {'subject': subject, 'pdf': os.path.relpath(pdf, main_root()).replace('\\', '/'), 'pages': npages, 'bodyStart': body_start,
            'generatedAt': datetime.date.today().isoformat(), 'entries': entries, 'chunks': chunks}
    json.dump(skel, open(os.path.join(out_dir, 'skeleton.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    json.dump({'subject': subject, 'proposed': proposed}, open(os.path.join(out_dir, 'toc-proposed.json'), 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    cpath = os.path.join(out_dir, '_conflicts.json')
    prev = json.load(open(cpath, encoding='utf-8')) if os.path.exists(cpath) else {}
    prev['stage0'] = conflicts
    json.dump(prev, open(cpath, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, '00_toc.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'# {sdef["label"]} 표준판례 PDF 머리글 트리 ↔ toc.json 대응 (본문 {body_start}~{npages}쪽, 항목 {len(entries)}건)\n\n')
        f.write('| PDF 쪽 | 수준 | 머리글 | toc.json id | 상태 | 항목 수 |\n|---|---|---|---|---|---|\n')
        for pno, lv, label in headings_log:
            labels_here = None
            cnt = sum(1 for e in entries if label in e['tocLabels'])
            path, status = resolve_toc([label], toc_index) if lv == 1 and not any(x[1] == 0 for x in headings_log) else (None, '')
            f.write(f'| {pno} | {"분야" if lv == 0 else {1: "편", 2: "장", 3: "절"}[lv]} | {label} | | | {cnt} |\n')
        f.write('\n항목별 대응은 skeleton.json 의 tocPath/tocPathStatus(resolved=기존 toc.json, proposed=toc-proposed.json 의 id) 를 본다.\n')

    # ---- 요약
    n_case = sum(1 for e in entries if all(c.get('caseNumber') for c in e['cases']))
    n_date = sum(1 for e in entries if all(c.get('date') for c in e['cases']))
    n_prop = sum(1 for e in entries if e['tocPathStatus'] == 'proposed')
    n_unres = sum(1 for e in entries if not e['tocPath'])
    covered = sum(len([x for x in entries if c['pages'][0] <= x['pdfPages'][0] <= c['pages'][1]]) for c in chunks)
    print(f'본문 {body_start}~{npages}쪽, 항목 {len(entries)}건(인쇄 번호 최대 {max(e["no"] for e in entries)}), 사건번호 있음 {n_case}, 선고일 있음 {n_date}')
    print(f'tocPath: 기존 toc.json 일치 {n_resolved}, 제안 목차 {n_prop}, 미해결 {n_unres} | 머리글 {len(headings_log)}개 | 청크 {len(chunks)}개(쪽 {a.chunk_pages}±, 최대 {a.max_pages}) | 청크 기대 항목 합계 {covered}/{len(entries)}')
    kinds = {}
    for c in conflicts: kinds[c['kind']] = kinds.get(c['kind'], 0) + 1
    print(f'_conflicts(stage0): {kinds}')
    print(f'→ {out_dir}')


if __name__ == '__main__':
    main()
