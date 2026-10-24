#!/usr/bin/env python3
"""과목 간 겹침 재판(같은 decisionId 가 두 과목 PDF 에 실림)의 종합 입력 묶음을 만든다.

  python -X utf8 tools/overlap_prep.py [--dir data/standard-cases/_overlaps] [--worktrees .worktrees]

입력: _overlaps/overlaps.json(겹침 목록: decisionId, A/B 과목·seq), 각 과목 worktree 의 entries.jsonl·pages/, _overlaps/official/overlap-<decisionId>.json(law.go.kr 공식 텍스트)
출력: _overlaps/in/<decisionId>.json  — 두 책의 절 텍스트(쟁점·판시사항·판결요지·선정이유·검토메모)와 PDF 쪽 원문, 공식 판시사항·판결요지·참조조문·전문(이유 포함), 비교 요약
      _overlaps/in/PROMPT.md          — 종합 작성자(Fable 5.1) 지시문
      _overlaps/out/                  — 작성자가 <decisionId>.json 과 <decisionId>.md 를 쓰는 자리
설계: 종합문은 **두 PDF 에서 글자 그대로 옮긴 구절들의 합집합**이다(요약·의역·새 문장 금지 — CLAUDE.md 규칙 1). 공식 판결문은 구절의 순서·소속 재판 확인에 쓴다.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KO2ID = {'헌법': 'constitution', '행정법': 'administrative', '민법': 'civil', '형법': 'criminal', '상법': 'commercial'}
PROMPT = '''# 겹침 재판 종합 지시문 (Fable 5.1 · max)

한 재판이 두 과목의 표준판례 PDF 에 실려 있습니다. 두 책이 옮긴 판시사항(또는 쟁점)·판결요지는 같은 판결의 **서로 다른 부분**이거나 **같은 부분**입니다. 당신의 일은 두 책의 내용을 **모두 담은 하나의 표준판례 텍스트**를 만들고, 그것이 공식 판결문(국가법령정보센터)과 맞는지 검토하는 것입니다. 입력 묶음 `in/<decisionId>.json` 하나를 읽고 `out/<decisionId>.json` 과 `out/<decisionId>.md` 를 씁니다. 다른 파일은 읽거나 쓰지 않습니다.

## 절대 규칙 (CLAUDE.md 규칙 1·3)
1. **새 문장을 쓰지 않습니다.** 종합문의 모든 구절은 두 PDF 중 하나에서 **글자 그대로** 가져온 것이어야 합니다(공백·줄바꿈·괄호 모양 차이만 허용). 요약·의역·접속어 추가·오탈자 교정 금지. 공식 판결문의 문장을 끼워 넣지도 않습니다(공식 텍스트는 공식 자료 칸에 따로 표시됩니다).
2. **합집합 원칙.** 두 책이 같은 구절을 옮겼으면 한 번만, 한 책이 더 길게 옮겼으면 긴 쪽을, 서로 다른 부분을 옮겼으면 둘 다 넣습니다. 순서는 **공식 판결문(판시사항·판결요지·이유)에 나오는 순서**를 따릅니다. 공식 판결요지에 `[1]` `[2]` 번호가 있으면 그 번호를 각 항목의 `n` 으로 씁니다(두 책 모두 번호 없이 옮겼다면 공식 번호를 붙이되, 텍스트는 PDF 의 것).
3. **소속 확인.** 각 구절이 정말 이 재판의 것인지 공식 전문(이유 포함)에서 확인합니다. 공식 판결문 어디에도 없는 구절(다른 재판의 텍스트가 PDF 에 잘못 붙은 경우)은 종합문에서 **제외**하고 보고서에 적습니다. 공식 판시사항·요지가 PDF 보다 더 많은 항목을 담고 있으면 그 사실만 보고서에 적습니다(끼워 넣지 않음).
4. 판시사항 칸(`issues`): 두 책에 〈판시사항〉이 있으면 그 합집합, 없으면 〈쟁점〉의 합집합(사용자 결정). 쟁점은 책마다 다르게 쓴 문장이므로 둘 다 넣되 같은 뜻의 중복이면 한쪽만 — 어느 쪽을 택했는지 보고서에 적습니다.
5. 참조조문(`statutes`)은 두 책에 있는 것만 합집합. 없으면 생략.

## 출력 1 — out/<decisionId>.json
{
  "decisionId": "...",
  "issues": [{"n": "", "text": "<PDF 그대로>", "from": [{"subject": "헌법", "pages": [64]}]}],
  "holdings": [{"n": "[1]", "text": "<PDF 그대로>", "from": [{"subject": "헌법", "pages": [64]}, {"subject": "행정법", "pages": [75]}]}],
  "statutes": [{"text": "...", "from": [...]}],          ← 없으면 []
  "excluded": [{"subject": "...", "section": "판결요지", "text": "...", "why": "공식 전문에 없는 구절"}],
  "officialComparison": {"issuesCoverage": "공식 판시사항 3항목 중 PDF 가 다룬 것 2항목", "holdingsCoverage": "...", "discrepancies": ["..."]},
  "confidence": "high|medium|low",
  "note": "한두 문장"
}
- `text` 는 어느 한 PDF 의 절 텍스트(또는 그 안의 연속 구절)와 정규화 후 완전히 같아야 합니다. 검증 스크립트가 글자 단위로 확인하고, 틀리면 그 항목은 버려집니다.
- `from` 에는 그 구절을 옮긴 책(들)과 PDF 쪽을 적습니다.

## 출력 2 — out/<decisionId>.md (검토 보고, 사람이 읽음)
- 두 책이 각각 무엇을 옮겼는지(쪽·절), 겹치는 부분과 다른 부분, 종합 순서의 근거(공식 판결문의 어느 부분인지), 공식 판시사항·판결요지와 비교해 PDF 가 빠뜨린 것·공식에 없는 것, 제외한 구절과 이유, 두 책의 제목이 각자 과목 페이지에 그대로 쓰인다는 점.
'''


def load_entries(worktrees, ko):
    sid = KO2ID[ko]
    d = os.path.join(worktrees, f'pdf2md-{sid}', 'data', 'standard-cases', ko)
    ents = {e['seq']: e for e in L.read_jsonl(os.path.join(d, 'entries.jsonl'))}
    return d, ents


def pdf_text(d, pages):
    out = []
    for p in pages:
        path = L.page_path(d, p)
        if os.path.exists(path):
            lines = L.strip_furniture(open(path, encoding='utf-8').read().split('\n'))
            out.append({'page': p, 'text': '\n'.join(l for l in lines if l.strip())})
    return out


def official(dir_, did):
    path = os.path.join(dir_, 'official', f'overlap-{did}.json')
    if not os.path.exists(path):
        return {'available': False}
    f = json.load(open(path, encoding='utf-8'))
    secs = {}
    full = []
    for s in f.get('sections', []):
        h = (s.get('heading') or '').strip('【】[] ').replace(' ', '')
        t = (s.get('text') or '').strip()
        if h in ('판시사항', '판결요지', '결정요지', '참조조문', '참조판례', '심판대상조문'):
            secs[h] = t
        else:
            full.append({'heading': s.get('heading'), 'text': t})
    return {'available': True, 'sourceUrl': f.get('sourceUrl'), 'citation': f.get('citation'), 'pageTitle': f.get('pageTitle'), 'sections': secs, 'fullText': full}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default=os.path.join(ROOT, 'data', 'standard-cases', '_overlaps'))
    ap.add_argument('--worktrees', default=os.path.join(os.path.dirname(ROOT) if os.path.basename(os.path.dirname(ROOT)) == '.worktrees' else ROOT, '.worktrees'))
    a = ap.parse_args(argv)
    d = os.path.abspath(a.dir)
    wts = os.path.abspath(a.worktrees)
    ov = json.load(open(os.path.join(d, 'overlaps.json'), encoding='utf-8'))
    in_dir = os.path.join(d, 'in'); out_dir = os.path.join(d, 'out')
    os.makedirs(in_dir, exist_ok=True); os.makedirs(out_dir, exist_ok=True)
    L.write_text(os.path.join(in_dir, 'PROMPT.md'), PROMPT)
    cache = {}
    n_off = 0
    for r in ov:
        did = r['decisionId']
        books = []
        for side in ('A', 'B'):
            ko = r[side]['subject']
            if ko not in cache:
                cache[ko] = load_entries(wts, ko)
            sd, ents = cache[ko]
            sk = L.load_skeleton(sd)
            e = next(x for x in ents.values() if x['no'] == r[side]['no'] and (x.get('title') or '').startswith((r[side]['title'] or '')[:8]))
            books.append({'subject': ko, 'book': '표준판례', 'edition': '2023년 개정판', 'file': f'data/standard-cases/표준판례(2023년 개정판)_{ko}.pdf',
                          'no': e['no'], 'seq': e['seq'], 'title': e['title'], 'location': e.get('location'), 'pdfPages': e.get('pdfPages'),
                          'sections': {k: v for k, v in (e.get('sections') or {}).items() if v}, 'notes': e.get('notes') or [],
                          'verify': (e.get('verify') or {}).get('status'), 'pdfText': pdf_text(sd, e.get('pdfPages') or [])})
        off = official(d, did)
        n_off += bool(off.get('available'))
        bundle = {'decisionId': did, 'caseNumber': r['caseNumber'], 'date': r['date'], 'court': r['court'], 'books': books, 'official': off,
                  'fieldRelations': r.get('fields')}
        L.write_json(os.path.join(in_dir, f'{did}.json'), bundle)
    print(f'겹침 {len(ov)}건 → {in_dir} (공식 텍스트 있음 {n_off}건) · 출력 자리 {out_dir}')


if __name__ == '__main__':
    main()
