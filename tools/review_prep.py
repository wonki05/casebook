#!/usr/bin/env python3
"""단계 3 판정 준비: _review.jsonl 의 판정 대기(pending) 항목을 상위 모델(또는 사람)이 바로 볼 수 있게 묶음 파일로 만든다.

  python -X utf8 tools/review_prep.py --subject 상법 [--dir <과목폴더>] [--batch 6] [--only-reasons fail,warn,notes,sample,title]

산출물(과목 폴더):
  _review_in/PROMPT.md      판정자 지시문(공통)
  _review_in/bNNN.json      묶음: [{seq,no,chunk,decisionId,caseNumber,reason,reasons,note,textSha256,title,titleLen,
                                     md:{절:텍스트}, notes:[검토메모], verify:{필드:{status,ratio,note,diff}}, pdf:[{page,text}]}]
  _review_parts/            판정자가 bNNN.jsonl 을 쓰는 자리(비어 있음)
판정 결과는 tools/review_collect.py 로 _review.jsonl 에 합친다. 설계: spec/PIPELINE-pdf2md.md §3, spec/TASK-pdf2md.md 단계 3.
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402

PROMPT = '''# 표준판례 전사 판정 지시문 (상위 모델·사람 공통)

당신은 하위 모델이 PDF 에서 옮겨 적은 Markdown 전사를 **PDF 쪽 텍스트와 글자 단위로 대조해 판정**하는 검토자입니다. 입력 묶음(bNNN.json)의 항목마다 아래 규칙으로 판정하고, 결과를 지정된 `_review_parts/bNNN.jsonl` 에 **한 항목 한 줄(JSON)** 로 씁니다. 다른 파일은 읽거나 쓰지 않습니다.

## 판정 대상과 기준
- 비교 대상 절: 쟁점 · 판시사항 · 판결요지 · 참조조문 (화면에 표시될 텍스트). 주제·선정이유·기타는 참고만.
- **ok**: 각 절의 글자가 PDF 와 같다. 공백·줄바꿈·괄호 모양(【】〈〉[]·「」)·가운뎃점 변형(ㆍ·・)·전각/반각 차이는 같은 것으로 본다. 하위 모델이 줄바꿈으로 끊긴 어절을 붙인 것도 같은 것으로 본다.
- **fix**: 글자·숫자·조사·문장이 빠졌거나 더해졌거나 바뀌었다(오탈자 "교정"도 fix 대상 — PDF 가 틀려도 PDF 대로). `fixedSections` 에 **문제가 있는 절만** `{"절이름": "PDF 그대로의 전체 절 텍스트"}` 로 적는다. 절 텍스트는 요약하지 말고 PDF 에서 그대로 옮긴다(줄바꿈은 문단 경계에서만). 절이 PDF 에 없는데 md 에 있으면 `"(없음)"` 으로, PDF 에 있는데 md 가 `(없음)` 이면 PDF 텍스트로 채운다.
- **reject**: md 블록이 다른 항목의 텍스트이거나, 사건번호·선고일·법원이 PDF 와 다르거나, PDF 쪽 텍스트로는 바로잡을 수 없다(판독불가 등). note 에 이유.
- reason 별 초점: `fail`·`warn` 은 note 와 verify.diff 가 가리키는 곳을 먼저 확인하되 절 전체를 대조한다. `notes` 는 검토메모가 말하는 지점을 확인한다(참고판례 절을 기타로 옮긴 것, 헌재 약칭을 그대로 둔 것, 결정요지를 판결요지 절에 넣은 것은 **정상 — ok**). `sample` 은 무작위 표본이므로 절 전체를 꼼꼼히 대조한다.
- `title`(제목이 20자를 넘음): 다른 판정과 별개로, PDF 제목의 뜻을 보존하는 **20자 이하 학습용 제목**을 `title` 에 제안한다(새 사실·평가 추가 금지, 사건번호 금지). 줄일 수 없으면 PDF 제목 그대로 두고 `title` 을 빈 문자열로.
- 숫자(연월일·사건번호·조문·금액)는 한 자리라도 다르면 fix.

## 출력 형식 (bNNN.jsonl — 입력 항목 순서대로, 항목당 한 줄)
{"seq": 12, "no": 12, "chunk": "c001", "decisionId": "...", "reason": "fail", "verdict": "fix", "reviewer": "claude-opus-5-5", "reviewedAt": "YYYY-MM-DD", "note": "판결요지 둘째 문단 '제11조 제1항' 누락", "fixedSections": {"판결요지": "..."}, "textSha256": "<입력의 textSha256 그대로>"}
- `reason` 이 `title` 인 항목은 `{"seq","no","chunk","decisionId","reason":"title","verdict":"ok","reviewer","reviewedAt","note","title":"축약안 또는 빈 문자열"}`.
- verdict 가 ok 면 fixedSections 는 `{}`. 입력에 없는 항목을 만들지 않는다. 입력의 모든 항목에 대해 한 줄씩 쓴다.
'''


def entry_pdf_text(d, pages):
    out = []
    for p in pages:
        path = L.page_path(d, p)
        if not os.path.exists(path):
            continue
        raw = open(path, encoding='utf-8').read()
        lines = L.strip_furniture(raw.split('\n'))
        out.append({'page': p, 'text': '\n'.join(l for l in lines if l.strip())})
    return out


def latest_reviews(rows):
    """재판별 마지막 판정. 구형 ID 생략 기록은 하나의 재판으로 좁혀질 때만 연결한다."""
    rows = [r for r in rows if not r.get('meta')]
    known, legacy = {}, {}
    for r in rows:
        pair = (r['seq'], r.get('reason'))
        if r.get('decisionId'):
            known.setdefault(pair, {}).setdefault(r['decisionId'], set()).add(r.get('caseNumber') or '')
        else:
            legacy.setdefault(pair, set()).add(r.get('caseNumber') or '')
    latest = {}
    for r in rows:
        pair = (r['seq'], r.get('reason'))
        did, number = r.get('decisionId') or '', r.get('caseNumber') or ''
        if not did:
            choices = known.get(pair, {})
            matches = [d for d, numbers in choices.items() if not number or number in numbers or numbers == {''}]
            if len(matches) > 1 or (not choices and not number and len(legacy.get(pair, set())) > 1):
                raise ValueError(f'decisionId 없는 판정의 재판을 특정할 수 없음 {pair}')
            if matches:
                did = matches[0]
                r = dict(r, decisionId=did)
        key = (r['seq'], did or ('case:' + number if number else ''), r.get('reason'))
        latest[key] = r
    return latest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--subject', required=True)
    ap.add_argument('--dir')
    ap.add_argument('--batch', type=int, default=6)
    ap.add_argument('--only-reasons', default='fail,warn,notes,sample,conflict,title')
    a = ap.parse_args(argv)
    sid, d = L.subject_dir(a.subject, a.dir)
    reasons = set(x.strip() for x in a.only_reasons.split(',') if x.strip())
    rows = [r for r in L.read_jsonl(os.path.join(d, '_review.jsonl')) if not r.get('meta')]
    try:
        latest = latest_reviews(rows)
    except ValueError as exc:
        print(f'ERROR - {exc}'); return 1
    pending = [r for r in latest.values() if r.get('verdict', 'pending') == 'pending' and r.get('reason') in reasons]
    entries = {e['seq']: e for e in L.read_jsonl(os.path.join(d, 'entries.jsonl'))}
    skel = L.load_skeleton(d)
    skel_by = {e['seq']: e for e in skel['entries']}
    # 같은 seq에 재판이 여럿이어도 섞지 않는다. 동일 재판의 reason만 묶는다.
    by_seq = {}
    for r in sorted(pending, key=lambda r: (r['seq'], r.get('reason') != 'title')):
        key = (r['seq'], r.get('decisionId') or ('case:' + r['caseNumber'] if r.get('caseNumber') else ''))
        by_seq.setdefault(key, []).append(r)
    items = []
    for (seq, _), recs in sorted(by_seq.items()):
        e = entries.get(seq)
        if not e:
            continue
        sk = skel_by.get(seq) or {}
        pages = sorted(set(e.get('pdfPages') or sk.get('pdfPages') or []))
        main_rec = next((r for r in recs if r.get('reason') != 'title'), None)
        title_rec = next((r for r in recs if r.get('reason') == 'title'), None)
        verify = {}
        for f, v in ((e.get('verify') or {}).get('fields') or {}).items():
            verify[f] = {k: v.get(k) for k in ('status', 'method', 'ratio', 'digitsOk', 'note') if k in v}
        # 불합격 절의 차이 위치를 다시 계산해 넣는다(판정자용)
        if main_rec and main_rec.get('reason') in ('fail', 'warn'):
            try:
                nxt = skel_by.get(seq + 1)
                v2 = L.verify_entry(d, e.get('sections'), e.get('pdfPages'), sk, nxt, skel.get('pages'))
                for f, v in (v2.get('fields') or {}).items():
                    if v.get('diff'):
                        verify.setdefault(f, {})['diff'] = v['diff']
            except Exception as ex:  # 판정 준비가 멈추지 않게
                verify['_error'] = str(ex)[:120]
        items.append({
            'seq': seq, 'no': e.get('no'), 'chunk': e.get('chunk'), 'decisionId': (main_rec or title_rec).get('decisionId'),
            'caseNumber': (main_rec or title_rec).get('caseNumber'),
            'reason': main_rec.get('reason') if main_rec else 'title', 'reasons': sorted({r.get('reason') for r in recs}),
            'note': main_rec.get('note', '') if main_rec else '', 'textSha256': (main_rec or title_rec).get('textSha256', ''),
            'title': e.get('title') or sk.get('title'), 'titleLen': len(e.get('title') or sk.get('title') or ''), 'needsTitle': bool(title_rec),
            'citationRaw': e.get('citationRaw'), 'cases': e.get('cases'),
            'md': e.get('sections'), 'notes': e.get('notes') or [], 'verify': verify, 'pdf': entry_pdf_text(d, pages),
        })
    in_dir = os.path.join(d, '_review_in'); parts = os.path.join(d, '_review_parts')
    os.makedirs(in_dir, exist_ok=True); os.makedirs(parts, exist_ok=True)
    for old in os.listdir(in_dir):
        if old.startswith('b') and old.endswith('.json'):
            os.remove(os.path.join(in_dir, old))
    L.write_text(os.path.join(in_dir, 'PROMPT.md'), PROMPT)
    batches = [items[i:i + a.batch] for i in range(0, len(items), a.batch)]
    for i, b in enumerate(batches, 1):
        L.write_json(os.path.join(in_dir, f'b{i:03d}.json'), b)
    reasons_count = {}
    for it in items:
        for r in it['reasons']:
            reasons_count[r] = reasons_count.get(r, 0) + 1
    print(f'[{sid}] 판정 대기 항목 {len(items)}건(사유 {reasons_count}) → 묶음 {len(batches)}개 ({a.batch}건씩) → {in_dir}')
    print(json.dumps({'subject': sid, 'items': len(items), 'batches': len(batches), 'dir': in_dir, 'parts': parts}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
