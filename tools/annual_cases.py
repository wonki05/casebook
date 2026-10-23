#!/usr/bin/env python3
"""법률신문 「분야별 중요판례분석」 기사 본문(텍스트 파일)에서 사건번호를 뽑아 등록 후보를 만든다.

기사 텍스트는 브라우저에서 본문을 복사해 data/inbox/annual/<year>-<field>[-n].txt 로 저장한다(첫 줄: 기사 제목, 둘째 줄: URL 권장).
Usage:
  python3 tools/annual_cases.py data/inbox/annual/2025-civil-1.txt [--year 2025] [--field civil] [--out ...]
  --year 를 생략하면 제목의 "[2025년 분야별 중요판례분석]" 에서, --field 를 생략하면 제목의 분야명에서 추정한다.
분야(field, 화면의 분야 구분 = tools/subjects.py 의 ANNUAL_FIELDS):
  constitution 헌법 · administrative 행정법 · civil 민법(총칙·물권법·채권법) · family 민법(가족법)
  criminal-general 형법총칙 · criminal-special 형법각칙 · commercial 상법(회사법·보험·해상·공정거래법 포함) · ip 지식재산권법
  그 밖의 기사(민사소송법·형사소송법·노동법·조세법 등)는 대상이 아니다.
출력: {"article": 제목, "url": URL, "year": 2025, "field": "civil", "subject": "civil", "group": "annual",
       "candidates": [{caseNumber, court, date, enBanc, snippet, title:"", field:"civil", status:"review"}]}
  항목의 field 는 파일 field 로 미리 채워진다. 한 기사에 여러 분야(형법 총칙·각칙 등) 사건이 섞여 있으면 항목마다 고친다.
검토 후 tools/add_cases.py add --from <out> 로 등록(그룹 annual).
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from casenum import find_cases  # noqa: E402
from subjects import ANNUAL_BY_ID, ANNUAL_FIELD_IDS, resolve, resolve_field, guess_field, article_year  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('textfile')
    ap.add_argument('--year', type=int, help='연재 연도(생략하면 기사 제목에서 추정)')
    ap.add_argument('--field', type=resolve_field, help='분야 id 또는 이름 (' + ', '.join(ANNUAL_FIELD_IDS) + '). 생략하면 기사 제목에서 추정')
    ap.add_argument('--subject', type=resolve, help='(선택) 과목 — 분야에서 자동으로 정해진다. 주면 분야의 과목과 같은지 확인만 한다')
    ap.add_argument('--out')
    a = ap.parse_args()
    lines = open(a.textfile, encoding='utf-8').read().split('\n')
    title = lines[0].strip() if lines else ''
    url = lines[1].strip() if len(lines) > 1 and lines[1].strip().startswith('http') else ''
    body = '\n'.join(lines[2:] if url else lines[1:])
    year = a.year or article_year(title)
    if not year:
        raise SystemExit('--year 를 지정하세요 (기사 제목에서 연도를 찾지 못함)')
    field = a.field or guess_field(title, a.subject)
    if not field:
        raise SystemExit(f'분야를 정할 수 없습니다: {title!r} → --field 로 지정하세요 ({", ".join(ANNUAL_FIELD_IDS)}). '
                         '대상 분야(헌법·행정법·민법·형법·상법·지식재산권법)가 아닌 기사는 등록하지 않습니다.')
    subject = ANNUAL_BY_ID[field]['subject']
    if a.subject and a.subject != subject:
        raise SystemExit(f'--subject {a.subject} 와 분야 {field}(과목 {subject})가 맞지 않습니다')
    cands = []
    for c in find_cases(body, window=160):
        # field 는 항목마다 고칠 수 있다(한 기사에 형법 총칙·각칙 사건이 섞인 경우 등) — 항목 field > 파일 field
        cands.append({'caseNumber': c['caseNumber'], 'court': c['court'], 'date': c['date'], 'enBanc': c['enBanc'], 'snippet': c['snippet'], 'title': '', 'field': field, 'status': 'review'})
    out = a.out or os.path.splitext(a.textfile)[0] + '.candidates.json'
    json.dump({'article': title, 'url': url, 'year': year, 'field': field, 'subject': subject, 'group': 'annual', 'candidates': cands},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    f = ANNUAL_BY_ID[field]
    print(f'{out}: {year}년 {f["label"]}{" " + f["sub"] if f["sub"] else ""} — 후보 {len(cands)}건')


if __name__ == '__main__':
    main()
