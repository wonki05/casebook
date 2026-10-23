#!/usr/bin/env python3
"""표준판례 PDF(법학전문대학원협의회 배포본 등)에서 사건번호 후보와 주변 목차(대·중·소주제) 문맥을 뽑아
검토용 후보 파일을 만든다. 결과는 사람/에이전트가 확인한 뒤 tools/add_cases.py --from 으로 등록한다.

Usage:
  python3 tools/pdf_standard_cases.py "data/standard-cases/표준판례(2023년 개정판)_상법.pdf" [--subject commercial|상법] [--out data/standard-cases/candidates-commercial.json] [--pages 1-40]
  --subject 를 생략하면 파일명의 한글 과목명(헌법·행정법·민법·형법·상법)으로 추정한다. 과목 목록은 tools/subjects.py.

출력(JSON):
  {"source": "...pdf", "subject": "constitution", "pages": N,
   "headings": [{"page":3,"line":"제1편 헌법총론"}, ...],                  # 목차로 보이는 줄(제N편/장/절, 1. 2., 가. 나., 로마숫자 등)
   "candidates": [ {"caseNumber":"2004헌마554","court":"헌법재판소","date":"2004-10-21","enBanc":false,
                    "page":5, "context":["제1편 헌법총론","1. 헌법의 개념"], "snippet":"...",
                    "title":"", "tocPath":[], "status":"review"} ... ] }
- context 는 그 사건번호 앞에서 가장 최근에 나온 목차형 줄(최대 3단계)이다. 목차(toc.json)의 id 로 바꾸는 일은 검토 단계에서 한다.
- 표가 있는 PDF 는 pdfplumber 표 추출도 함께 시도해, 행 안에 사건번호가 있으면 그 행의 다른 칸을 row 로 넣는다.
"""
import argparse, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from casenum import find_cases  # noqa: E402
from subjects import STANDARD_IDS, resolve_standard, guess_from_filename  # noqa: E402

HEADING_RE = re.compile(r'^\s*(제\s?\d+\s?(편|장|절|관)\b.*|[IVXⅠ-Ⅻ]+\s*[.．]\s*\S.*|\d{1,2}\s*[.．]\s*\S.{0,60}|[가-힣]\s*[.．]\s*\S.{0,60}|\(\d{1,2}\)\s*\S.{0,60}|[①-⑳]\s*\S.{0,60}|[A-Z]\s*[.．]\s*\S.{0,60})\s*$')
SENT_END = re.compile(r'[다요음함됨임]\s*[.。]?\s*$')


def page_range(spec, n):
    if not spec:
        return range(n)
    out = []
    for part in spec.split(','):
        a, _, b = part.partition('-')
        a = int(a); b = int(b) if b else a
        out.extend(range(a - 1, min(b, n)))
    return out


def level_of(line):
    s = line.strip()
    if re.match(r'^제\s?\d+\s?편', s): return 1
    if re.match(r'^제\s?\d+\s?장', s): return 2
    if re.match(r'^제\s?\d+\s?절', s): return 3
    if re.match(r'^[IVXⅠ-Ⅻ]+\s*[.．]', s): return 1
    if re.match(r'^\d{1,2}\s*[.．]', s): return 2
    if re.match(r'^[가-힣]\s*[.．]', s): return 3
    if re.match(r'^\(\d{1,2}\)|^[①-⑳]', s): return 4
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('--subject', type=resolve_standard, help='과목 id 또는 한글명 (' + ', '.join(STANDARD_IDS) + '). 생략하면 파일명에서 추정')
    ap.add_argument('--out')
    ap.add_argument('--pages', help='예: 1-40 또는 3,5-9 (1부터)')
    a = ap.parse_args()
    if not a.subject:
        a.subject = guess_from_filename(a.pdf)
        if not a.subject:
            raise SystemExit('--subject 를 지정하세요 (파일명에서 과목을 알아낼 수 없음)')
    import logging; logging.getLogger('pdfminer').setLevel(logging.ERROR)
    import pdfplumber
    headings, candidates, seen = [], [], {}
    stack = []  # [(level, line)]
    with pdfplumber.open(a.pdf) as pdf:
        n = len(pdf.pages)
        for i in page_range(a.pages, n):
            page = pdf.pages[i]
            text = page.extract_text() or ''
            # 1) 줄 단위: 목차형 줄 추적 + 사건번호
            for raw in text.split('\n'):
                line = raw.strip()
                if not line:
                    continue
                if HEADING_RE.match(line) and len(line) <= 70 and not SENT_END.search(line) and not find_cases(line):
                    lv = level_of(line)
                    while stack and stack[-1][0] >= lv:
                        stack.pop()
                    stack.append((lv, line))
                    headings.append({'page': i + 1, 'level': lv, 'line': line})
                for c in find_cases(line):
                    cn = c['caseNumber']
                    if cn in seen:
                        continue
                    seen[cn] = True
                    candidates.append({'caseNumber': cn, 'court': c['court'], 'date': c['date'], 'enBanc': c['enBanc'], 'page': i + 1,
                                       'context': [s[1] for s in stack[-3:]], 'snippet': line[:200], 'title': '', 'tocPath': [], 'status': 'review'})
            # 2) 표 추출: 행 안의 사건번호 → 같은 행의 칸들을 row 로 보존
            try:
                for table in page.extract_tables() or []:
                    for row in table:
                        cells = [str(x).strip() if x else '' for x in row]
                        joined = ' | '.join(cells)
                        for c in find_cases(joined):
                            cn = c['caseNumber']
                            rec = next((x for x in candidates if x['caseNumber'] == cn), None)
                            if rec is None:
                                rec = {'caseNumber': cn, 'court': c['court'], 'date': c['date'], 'enBanc': c['enBanc'], 'page': i + 1,
                                       'context': [s[1] for s in stack[-3:]], 'snippet': joined[:200], 'title': '', 'tocPath': [], 'status': 'review'}
                                candidates.append(rec); seen[cn] = True
                            rec['row'] = cells
            except Exception:
                pass
    out = a.out or os.path.join(os.path.dirname(a.pdf), f'candidates-{a.subject}.json')
    json.dump({'source': os.path.abspath(a.pdf), 'subject': a.subject, 'pages': n, 'headings': headings, 'candidates': candidates},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{out}: 후보 {len(candidates)}건, 목차형 줄 {len(headings)}개 (검토 후 tools/add_cases.py --from {out})')


if __name__ == '__main__':
    main()
