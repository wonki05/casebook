#!/usr/bin/env python3
"""표준판례 하위 모델 전사(md/cNNN.md) 파싱 + 구조 검사 + PDF 쪽 텍스트 대조 게이트 → entries.jsonl · _report.json.

  python -X utf8 tools/md_validate.py --subject 상법                 # data/standard-cases/상법/
  python -X utf8 tools/md_validate.py --dir <과목폴더> [--subject commercial]

입력(과목 폴더): skeleton.json(tools/pdf_chunks.py) · pages/pNNNN.txt(대조 기준, 수정 금지) · md/cNNN.md(tools/prompts/pdf2md.md 형식)
출력(과목 폴더): entries.jsonl(skeleton 항목마다 1행, seq 순) · _report.json(청크별 집계·항목별 ok/warn/error·totals)

구조 검사: 번호 연속·skeleton 청크 배정과 일치(누락 missing/추가 extra), 사건 줄(casenum.CASE_RE·ISO 날짜·COURTS 법원명),
위치 문자열 ↔ skeleton tocLabels, 청크 간 중복, 필수 절(판결요지), [판독불가] 개수, '(이어짐)' 블록 병합.
대조 게이트(PIPELINE §3-1): 표시 필드(판시사항 또는 그 대체인 쟁점 · 판결요지 · 참조조문)를 pdfPages ±1쪽의 정규화 텍스트에서
항목·절 경계로 자른 PDF 절과 비교 — 같으면 pass(substring), 아니면 SequenceMatcher 비율 ≥ 0.995 이고 숫자열이 같아야 pass(lcs).
PDF 에 있는 절이 md 에 없거나, md 의 절이 PDF 항목에 없으면 fail. 표시 필드가 모두 (없음)이면 skip.
level(ok|warn|error)은 구조 검사 결과이고 대조 결과는 verify.status 로 따로 둔다. 단 lcs 로만 통과한 필드(완전 일치가 아님 —
1000자 안의 '된다'→'되지 않는다' 같은 차이도 비율 0.995 를 넘을 수 있다)는 차이 위치(diff)와 함께 warn 으로 올려 판정을 받게 한다.
종료코드: 입출력 오류(skeleton.json 없음·읽기/쓰기 실패)일 때만 2, 그 밖에는 검사 결과와 관계없이 0.
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402

MD_NAME = re.compile(r'^(c\d{3,4})\.md$')
LEVELS = ('ok', 'warn', 'error')


def _case_out(c):
    return {k: c.get(k) for k in ('caseNumber', 'lookupKey', 'date', 'court', 'decisionType', 'enBanc')}


def _primary(number):
    try:
        return L.primary_case_number(number)
    except ValueError:
        return re.sub(r'\s+', '', number or '')


def _title_matches(md_title, skel_title):
    a, b = L.normalize(md_title), L.normalize(skel_title)
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def map_chunk(cid, blocks, expected, chunk_meta, prev_chunk_entries):
    """한 청크의 md 블록 → ({seq: 본 블록}, {seq: [이어짐 블록]}, 청크 문제 목록, missing, extra 블록)."""
    assigned, conts, problems, extra = {}, {}, [], []
    order = []
    for b in blocks:
        if b.get('preamble') or b['no'] is None:
            problems.append({'level': 'error', 'reason': f'{cid}:{b["line"]} ' + '; '.join(b['errors'] or ['해석 불가 블록']), 'no': b['no']})
            continue
        if b['continued']:
            want = (chunk_meta or {}).get('continued')
            if want is None:
                problems.append({'level': 'error', 'no': b['no'], 'reason': f'{cid}: 예상하지 않은 (이어짐) {b["no"]} 블록'})
                continue
            if b['no'] != want:
                problems.append({'level': 'error', 'no': b['no'], 'reason': f'{cid}: (이어짐) 번호 {b["no"]} ≠ skeleton 의 이어진 항목 {want}'})
                continue
            owner = [e for e in prev_chunk_entries if e['no'] == want]
            if not owner:
                problems.append({'level': 'error', 'no': b['no'], 'reason': f'{cid}: 앞 청크에서 이어진 항목 {want} 를 skeleton 에서 찾지 못함'})
                continue
            conts.setdefault(owner[-1]['seq'], []).append(b)
            continue
        cands = [e for e in expected if e['no'] == b['no'] and e['seq'] not in assigned]
        if cands:
            titled = [e for e in cands if _title_matches(b['title'], e['title'])]
            e = (titled or cands)[0]
            assigned[e['seq']] = b
            order.append(e['seq'])
        else:
            dup = any(e['no'] == b['no'] for e in expected)
            b['_extraReason'] = '같은 번호 블록 중복' if dup else '이 청크의 skeleton 기대 항목이 아님'
            extra.append(b)
    if order != sorted(order):
        problems.append({'level': 'error', 'no': None, 'reason': f'{cid}: 항목 순서가 skeleton 과 다름 ({[assigned[s]["no"] for s in order]})'})
    missing = [e['no'] for e in expected if e['seq'] not in assigned]
    return assigned, conts, problems, missing, extra


def build_entry(sid, d, skel, e, block, conts, next_e, expect_cont):
    errors, warns, info = [], [], []
    labels = e.get('tocLabels') or []
    chunk_loc = (skel['chunkById'].get(e.get('chunk')) or {}).get('location')
    sections = {k: None for k in L.SECTIONS}
    notes, unknown, illegible = [], {}, 0
    if block is None and not conts:
        row = {'seq': e['seq'], 'no': e['no'], 'chunk': e.get('chunk'), 'continued': False, 'missing': True, 'title': e.get('title', ''),
               'citationRaw': e.get('citationRaw'), 'cases': [_case_out(c) for c in e.get('cases') or []],
               'location': ' › '.join(labels), 'pdfPages': e.get('pdfPages') or [], 'skeletonPages': e.get('pdfPages') or [],
               'sections': sections, 'notes': [], 'illegible': 0, 'level': 'error', 'reasons': ['md 에 항목 없음(전사 누락)'],
               'verify': {'status': 'skip', 'fields': {}, 'pages': [], 'note': 'md 없음',
                          'pagesSha256': L.pages_sha256(d, e.get('pdfPages') or [])}}
        return row
    base = block or conts[0]
    if block is None:
        errors.append('본 블록 없이 (이어짐) 블록만 있음')
    for b in ([block] if block else []) + list(conts or []):
        errors.extend(b['errors'])
        warns.extend(b['warnings'])
        for k, v in b['sections'].items():
            if v is None:
                continue
            if sections.get(k):
                warns.append(f'(이어짐) 병합: 〈{k}〉 이음 확인')
                sections[k] = sections[k] + '\n' + v
            else:
                sections[k] = v
        notes.extend(b['notes'])
        unknown.update(b['unknownSections'])
        illegible += b['illegible']
    if expect_cont and not conts:
        warns.append(f'다음 청크({expect_cont})에 (이어짐) 블록 없음')
    pages = sorted({p for b in ([block] if block else []) + list(conts or []) for p in b['pages']})
    skel_pages = e.get('pdfPages') or []
    if pages and skel_pages and (min(pages) > max(skel_pages) + 1 or max(pages) < min(skel_pages) - 1):
        warns.append(f'- 쪽: {pages} 이 skeleton 쪽 {skel_pages} 과 떨어져 있음')
    cases = base['cases'] if block else []
    for c in cases:
        errors.extend(c['errors'])
        warns.extend(c['warnings'])
    sk_cases = e.get('cases') or []
    if block:
        if len(cases) != len(sk_cases):
            warns.append(f'사건 수 {len(cases)} ≠ skeleton {len(sk_cases)}')
        for c, s in zip(cases, sk_cases):
            if _primary(c['caseNumber']) != _primary(s.get('caseNumber')):
                warns.append(f'사건번호 {c["caseNumber"]} ≠ skeleton {s.get("caseNumber")}')
            if c['date'] and s.get('date') and c['date'] != s['date']:
                warns.append(f'선고일 {c["date"]} ≠ skeleton {s["date"]}')
            if c['court'] and s.get('court') and c['court'] != s['court']:
                warns.append(f'법원 {c["court"]} ≠ skeleton {s["court"]}')
        if not _title_matches(block['title'], e.get('title', '')):
            warns.append(f'제목이 skeleton 과 다름: {block["title"][:30]!r} / {e.get("title", "")[:30]!r}')
        if block['location'] is None:
            warns.append('- 위치: 줄 없음')
        elif not L.location_compatible(block['location'], labels, chunk_loc):
            warns.append(f'위치 불일치: {block["location"]!r} / skeleton {" › ".join(labels)!r}')
    if not sections.get('판결요지'):
        errors.append('필수 절 〈판결요지〉 없음')
    if illegible:
        warns.append(f'[판독불가] {illegible}곳')
    for name in unknown:
        warns.append(f'알 수 없는 절 ### {name}')
    if notes:
        info.append(f'검토메모 {len(notes)}줄')
    v = L.verify_entry(d, sections, pages, e, next_e, skel.get('pages'))
    for f, r in v['fields'].items():
        if r['status'] != 'pass':
            info.append(f'대조 fail 〈{f}〉: ' + (r.get('note') or f'ratio {r.get("ratio")}'))
        elif r.get('method') == 'lcs':
            # 비율 기준(≥0.995)으로는 통과했지만 글자가 완전히 같지는 않다 — 뜻이 바뀌는 한두 글자 차이도 여기 든다 → 판정 대상
            warns.append(f'〈{f}〉 lcs 통과(ratio {r["ratio"]}, 완전 일치 아님): ' + ' '.join(r.get('diff') or []))
    if v.get('note'):
        info.append(v['note'])
    if block and v.get('citations', 0) > max(1, len(cases)):
        warns.append(f'PDF 항목 안 인용 줄 {v["citations"]}개 > md 사건 {len(cases)}건(재판 여러 건 확인)')
    if v.get('repeatedSections'):
        warns.append('PDF 항목 안에 같은 절이 여러 번: ' + ', '.join(v['repeatedSections']))
    level = 'error' if errors else 'warn' if warns else 'ok'
    row = {'seq': e['seq'], 'no': e['no'], 'chunk': e.get('chunk'), 'continued': bool(conts), 'title': (block or {}).get('title') or e.get('title', ''),
           'citationRaw': (block or {}).get('citationRaw') or e.get('citationRaw'),
           'cases': [_case_out(c) for c in cases] if cases else [_case_out(c) for c in sk_cases],
           'location': (block or {}).get('location') or ' › '.join(labels), 'pdfPages': pages or skel_pages, 'skeletonPages': skel_pages,
           'sections': sections, 'notes': notes, 'illegible': illegible, 'level': level,
           'reasons': list(dict.fromkeys(errors + warns + info)), 'verify': v}
    if unknown:
        row['unknownSections'] = unknown
    if not cases:
        row['casesFrom'] = 'skeleton'
    return row


def run(sid, d):
    skel = L.load_skeleton(d)
    entries = skel['entries']
    chunks = skel.get('chunks') or []
    md_dir = os.path.join(d, 'md')
    parsed = {}
    if os.path.isdir(md_dir):
        for name in sorted(os.listdir(md_dir)):
            m = MD_NAME.match(name)
            if m:
                with open(os.path.join(md_dir, name), encoding='utf-8') as f:
                    parsed[m.group(1)] = L.parse_md(f.read())
    chunk_ids = [c['id'] for c in chunks]
    stray = sorted(set(parsed) - set(chunk_ids))
    block_of, conts_of, chunk_rep, problems, extras = {}, {}, {}, [], []
    for i, c in enumerate(chunks):
        cid = c['id']
        expected = skel['byChunk'].get(cid, [])
        prev_entries = skel['byChunk'].get(chunk_ids[i - 1], []) if i else []
        blocks = parsed.get(cid)
        if blocks is None:
            chunk_rep[cid] = {'md': False, 'entries': 0, 'missing': [e['no'] for e in expected], 'extra': [], 'continued': c.get('continued')}
            continue
        assigned, conts, probs, missing, extra = map_chunk(cid, blocks, expected, c, prev_entries)
        block_of.update(assigned)
        for seq, bl in conts.items():
            conts_of.setdefault(seq, []).extend(bl)
        for p in probs:
            problems.append(dict(p, chunk=cid))
        for b in extra:
            twin = [e for e in entries if e['no'] == b['no'] and e.get('chunk') != cid and _title_matches(b['title'], e['title'])]
            reason = b['_extraReason'] + (f' — 다른 청크 {twin[0]["chunk"]} 의 항목(seq {twin[0]["seq"]})과 중복' if twin else '')
            extras.append({'seq': None, 'no': b['no'], 'chunk': cid, 'level': 'error', 'reasons': [reason, f'{cid}.md:{b["line"]} {b["header"][:40]}']})
        chunk_rep[cid] = {'md': True, 'entries': len(assigned), 'missing': missing, 'extra': [b['no'] for b in extra], 'continued': c.get('continued')}
    rows = []
    for idx, e in enumerate(entries):
        nxt = entries[idx + 1] if idx + 1 < len(entries) else None
        cid = e.get('chunk')
        pos = chunk_ids.index(cid) if cid in chunk_ids else -1
        expect_cont = None
        if 0 <= pos < len(chunks) - 1:
            nc = chunks[pos + 1]
            last = (skel['byChunk'].get(cid) or [None])[-1]
            if nc.get('continued') is not None and last is not None and last['seq'] == e['seq'] and nc.get('continued') == e['no'] and nc['id'] in parsed:
                expect_cont = nc['id']
        rows.append(build_entry(sid, d, skel, e, block_of.get(e['seq']), conts_of.get(e['seq'], []), nxt, expect_cont))
    by_chunk = collections.defaultdict(list)
    for r in rows:
        by_chunk[r['chunk']].append(r)
    for cid, rep in chunk_rep.items():
        rs = by_chunk.get(cid, [])
        for k in ('pass', 'fail', 'skip'):
            rep[k] = sum(1 for r in rs if r['verify']['status'] == k and not r.get('missing'))
        rep['notes'] = sum(1 for r in rs if r['notes'])
        rep['pages'] = (skel['chunkById'].get(cid) or {}).get('pages')
    items = [{'seq': r['seq'], 'no': r['no'], 'chunk': r['chunk'], 'level': r['level'], 'reasons': r['reasons']} for r in rows]
    for p in problems:
        items.append({'seq': None, 'no': p.get('no'), 'chunk': p['chunk'], 'level': p['level'], 'reasons': [p['reason']]})
    items.extend(extras)
    for s in stray:
        items.append({'seq': None, 'no': None, 'chunk': s, 'level': 'error', 'reasons': [f'md/{s}.md 는 skeleton 청크가 아님']})
    present = [r for r in rows if not r.get('missing')]
    totals = {'entries': len(rows), 'md': len(present),
              'pass': sum(1 for r in present if r['verify']['status'] == 'pass'),
              'fail': sum(1 for r in present if r['verify']['status'] == 'fail'),
              'skip': sum(1 for r in present if r['verify']['status'] == 'skip'),
              'ok': sum(1 for i in items if i['level'] == 'ok'),
              'warn': sum(1 for i in items if i['level'] == 'warn'),
              'error': sum(1 for i in items if i['level'] == 'error'),
              'notes': sum(1 for r in rows if r['notes']), 'noteLines': sum(len(r['notes']) for r in rows),
              'illegible': sum(r['illegible'] for r in rows),
              'missing': sum(len(c['missing']) for c in chunk_rep.values()),
              'extra': sum(len(c['extra']) for c in chunk_rep.values()),
              'chunks': len(chunks), 'mdFiles': len(parsed)}
    report = {'subject': sid, 'generatedAt': L.now_iso(), 'chunks': chunk_rep, 'items': items, 'totals': totals}
    return rows, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--subject', help='과목 id 또는 한글명(헌법·행정법·민법·형법·상법)')
    ap.add_argument('--dir', help='과목 폴더(기본: data/standard-cases/<한글과목명>)')
    ap.add_argument('--quiet', action='store_true', help='청크별 줄을 출력하지 않음')
    a = ap.parse_args(argv)
    try:
        sid, d = L.subject_dir(a.subject, a.dir)
    except ValueError as exc:
        print('ERROR -', exc)
        return 2
    try:
        rows, report = run(sid, d)
    except FileNotFoundError as exc:
        print('ERROR - 파일 없음:', exc)
        return 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print('ERROR - 입력을 읽지 못함:', exc)
        return 2
    try:
        L.write_jsonl(os.path.join(d, 'entries.jsonl'), rows)
        L.write_json(os.path.join(d, '_report.json'), report)
    except OSError as exc:
        print('ERROR - 쓰기 실패:', exc)
        return 2
    t = report['totals']
    if not a.quiet:
        for cid, c in report['chunks'].items():
            pg = c.get('pages') or ['?', '?']
            print(f"{cid} p{pg[0]}-{pg[1]}  md {'있음' if c['md'] else '없음'}  항목 {c['entries']}  pass {c.get('pass', 0)} fail {c.get('fail', 0)} "
                  f"skip {c.get('skip', 0)}  검토메모 {c.get('notes', 0)}  missing {c['missing'] or '-'}  extra {c['extra'] or '-'}"
                  + (f"  이어짐 {c['continued']}" if c.get('continued') is not None else ''))
    reasons = collections.Counter()
    for r in rows:
        for f, v in r['verify']['fields'].items():
            if v['status'] != 'pass':
                reasons[f'〈{f}〉 ' + re.sub(r'\d+', 'n', (v.get('note') or 'fail').split(';')[0])] += 1
    print(f"[{sid}] 항목 {t['entries']} (md {t['md']}, 누락 {t['missing']}, 추가 {t['extra']}) | pass {t['pass']} fail {t['fail']} skip {t['skip']} | "
          f"ok {t['ok']} warn {t['warn']} error {t['error']} | 검토메모 {t['notes']}항목 {t['noteLines']}줄 | 판독불가 {t['illegible']} | md 파일 {t['mdFiles']}/{t['chunks']}")
    if reasons:
        print('fail 사유 상위:', '; '.join(f'{k} {n}' for k, n in reasons.most_common(5)))
    print('→', os.path.join(d, 'entries.jsonl'), '·', os.path.join(d, '_report.json'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
