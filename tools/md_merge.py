#!/usr/bin/env python3
"""entries.jsonl + skeleton.json + _review.jsonl → candidates-<subject>.json · _conflicts.json(stage3) · _review.jsonl(판정 대상 추가).

  python -X utf8 tools/md_merge.py --subject 상법 [--check] [--reviewer "script+claude-opus-5-5 sample 10%"] [--seed 20261024]
  옵션: --dir <과목폴더> --registry <registry.json> --toc <toc.json>
        (기본 등록부·목차: main 작업 폴더의 data/ — worktree 에서 실행해도 최신본과 비교한다)

규칙(spec/PIPELINE-pdf2md.md §3·§5, spec/TASK-pdf2md.md §3 단계 3·§6):
- 판정 대상을 _review.jsonl 에 verdict "pending" 으로 적는다(이미 있는 줄은 그대로 두고 새 줄만 덧붙인다):
  fail(대조 불합격) · conflict(법원 불명·한 항목 여러 재판·등록부와 텍스트 불일치) · warn(구조 경고·오류) · notes(검토메모) ·
  sample(pass 중 seed 난수 10%, 과목당 최소 20 — sampleKind "random"). 표본에 fix/reject 가 있으면 그 청크의 pass 전부
  (sampleKind "chunk"), 과목 표본 결함률 > 0.5% 면 과목의 pass 전부(sampleKind "subject")를 추가한다.
  제목이 20자를 넘으면 reason "title" 줄을 따로 적는다(title 에 축약안 → verdict ok). 이 줄은 제목에만 쓰이고 검증·상태에 영향이 없다.
- standardSource(verified) 는 ① pass 이고 표본 판정이 끝났고 그 청크 표본에 결함이 없고 과목 결함률 ≤ 0.5% 인 항목, 또는
  ② 판정 ok/fix 인 항목에만 붙는다. fix 는 fixedSections({절: 고친 원문})로 바꾼 뒤 다시 대조를 통과해야 한다. 그 밖에는 생략.
- 판정이 pending 이면 status "review". 같은 과목의 같은 decisionId 는 첫 항목만 남기고 나머지는 "skip"(첫 항목 memo 에 '함께 실린 곳').
  등록부에 같은 decisionId 가 있고 표준판례 텍스트가 다르면 "review" + _conflicts. tocPath 가 toc.json 에서 확인되지 않으면 "review".
- 판시사항이 없고 쟁점이 있으면 쟁점이 standardSource.issues 가 된다(대조 통과 조건). 판시사항이 있으면 쟁점은 memo('쟁점: …').
- md 의 판정 기록은 textSha256(md 텍스트 지문)과 묶인다. md 를 다시 만들면 이전 판정은 무효가 되고 새 pending 줄이 생긴다.
--check: 후보의 모든 standardSource 를 case_identity.validate_standard_source 로, status ok 후보의 재판 ID·목차를 add_cases 규칙으로
검사해 오류 수를 출력한다(오류가 있으면 종료코드 1). 입출력 오류는 종료코드 2.
"""
import argparse
import collections
import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402


def source_file(skel, sid):
    pdf = (skel.get('pdf') or '').replace('\\', '/')
    i = pdf.find('data/standard-cases/')
    if i >= 0:
        return pdf[i:]
    name = os.path.basename(pdf) or f'표준판례(2023년 개정판)_{L.BY_ID[sid]["folder"]}.pdf'
    return 'data/standard-cases/' + name


def toc_ids(toc, sid):
    out = {}

    def rec(nodes, path):
        for n in nodes or []:
            p = path + [n['id']]
            out[n['id']] = p
            rec(n.get('children'), p)
    rec((toc or {}).get(sid), [])
    return out


def decision_of(case):
    """(decisionId, decisionType, 오류)"""
    rec = {'court': case.get('court') or '', 'caseNumber': case.get('caseNumber') or '', 'lookupKey': case.get('lookupKey') or None,
           'decisionDate': case.get('date') or '', 'decisionType': case.get('decisionType')}
    try:
        ident = L.identity(rec)
        return ident['decisionId'], ident['decisionType'], None
    except (ValueError, KeyError, AttributeError) as exc:
        return None, None, str(exc)


def load_review(path, sid):
    meta, records = None, []
    if os.path.exists(path):
        for r in L.read_jsonl(path):
            if r.get('meta') is True and meta is None:
                meta = r
            else:
                records.append(r)
        if meta and meta.get('subject') not in (None, sid):
            raise ValueError(f'_review.jsonl 의 과목 {meta.get("subject")} ≠ {sid}')
    return meta, records


def rkey(r):
    return (r.get('seq'), r.get('decisionId') or r.get('caseNumber') or '')


def would_be_source(sections):
    """md 텍스트로 만든 표준판례 필드(등록부 비교용, 검증과 무관)."""
    out = {}
    for f in L.display_fields(sections):
        if sections.get(f):
            key = L.FIELD_TO_SOURCE[f]
            out[key] = L.split_items(sections[f]) if key in ('issues', 'holdings') else L.split_lines(sections[f])
    return out


def keywords_of(text):
    return [k.strip() for k in re.split(r'[\n,，;]', text or '') if k.strip()]


def placement(u):
    pg = u['row'].get('pdfPages') or []
    return f'{u["row"].get("title", "")} ({u["row"]["no"]}번, p.{pg[0] if pg else "?"})'


def run(a, sid, d):
    entries_path = os.path.join(d, 'entries.jsonl')
    rows = sorted(L.read_jsonl(entries_path), key=lambda r: r['seq'])
    skel = L.load_skeleton(d)
    reg_path = a.registry or L.data_file('registry.json')
    toc_path = a.toc or L.data_file('toc.json')
    reg = L.read_json(reg_path) if os.path.exists(reg_path) else {'cases': []}
    toc = L.read_json(toc_path) if os.path.exists(toc_path) else {}
    tids = toc_ids(toc, sid)
    review_path = os.path.join(d, '_review.jsonl')
    meta, records = load_review(review_path, sid)
    new_meta = None
    if meta is None:
        new_meta = meta = {'meta': True, 'subject': sid, 'seed': a.seed if a.seed is not None else L.SEED, 'sampleRate': L.SAMPLE_RATE,
                           'minSample': L.MIN_SAMPLE, 'defectTolerance': L.DEFECT_TOLERANCE, 'createdAt': L.now_iso()}
    elif a.seed is not None and a.seed != meta.get('seed'):
        print(f'WARN - --seed {a.seed} 무시: _review.jsonl 머리의 seed {meta.get("seed")} 를 유지')
    seed, rate = meta.get('seed', L.SEED), meta.get('sampleRate', L.SAMPLE_RATE)
    minimum, tol = meta.get('minSample', L.MIN_SAMPLE), meta.get('defectTolerance', L.DEFECT_TOLERANCE)
    pdf_file = source_file(skel, sid)
    entries_by_seq = skel['bySeq']
    seqs = [e['seq'] for e in skel['entries']]

    # ---- 등록부 decisionId 색인
    reg_by_did = collections.defaultdict(list)
    for c in reg.get('cases') or []:
        did = c.get('decisionId')
        if not did:
            try:
                did = L.identity(c)['decisionId']
            except (ValueError, KeyError):
                continue
        reg_by_did[did].append(c)

    # ---- 단위(항목 × 재판)
    units, conflicts = [], []
    for row in rows:
        cases = row.get('cases') or [{}]
        multi = len(cases) > 1
        for ci, case in enumerate(cases):
            did, dtype, err = decision_of(case)
            u = {'row': row, 'case': case, 'ci': ci, 'decisionId': did, 'decisionType': dtype or case.get('decisionType'),
                 'idError': err, 'multi': multi, 'reasons': [], 'notes': [], 'blockers': [], 'info': [],
                 'key': (row['seq'], did or case.get('caseNumber') or ''), 'textSha': L.text_sha256(row)}
            base = {'seq': row['seq'], 'no': row['no'], 'chunk': row.get('chunk'), 'decisionId': did, 'caseNumber': case.get('caseNumber')}
            if row.get('missing'):
                u['blockers'].append('md 에 항목 없음 — 전사 재실행 필요')
                conflicts.append(dict(base, kind='md-missing', note='md 에 항목 없음'))
            if err:
                u['reasons'].append('conflict')
                u['notes'].append('재판 ID 계산 불가: ' + err)
                u['blockers'].append('재판 ID 계산 불가(법원·사건번호·날짜·유형 확인)')
                conflicts.append(dict(base, kind='identity', note=err, court=case.get('court')))
            if multi:
                u['reasons'].append('conflict')
                u['notes'].append(f'한 항목에 재판 {len(cases)}건 — 본문이 이 재판의 요지일 때만 ok, 아니면 reject')
                conflicts.append(dict(base, kind='multi-case', note=' / '.join(c.get('caseNumber') or '?' for c in cases)))
            if not row.get('missing'):
                st = row['verify']['status']
                if st == 'fail':
                    u['reasons'].append('fail')
                    u['notes'].extend(f'〈{f}〉 {v.get("note") or v.get("ratio")}' for f, v in row['verify']['fields'].items() if v['status'] != 'pass')
                if row.get('level') in ('warn', 'error'):
                    u['reasons'].append('warn')
                    u['notes'].extend(row.get('reasons') or [])
                if row.get('notes'):
                    u['reasons'].append('notes')
            if did and did in reg_by_did:
                mine = would_be_source(row.get('sections') or {})
                diff, nosrc = [], []
                for rc in reg_by_did[did]:
                    src = rc.get('standardSource') or {}
                    if not src:
                        nosrc.append(rc['id'])
                    for k in L.STANDARD_FIELDS:
                        if k in src and k in mine and src[k] != mine[k]:
                            diff.append(f'{rc["id"]}.{k}')
                if diff:
                    u['reasons'].append('conflict')
                    u['notes'].append('등록부 표준판례 텍스트와 다름: ' + ', '.join(diff))
                    u['blockers'].append('등록부의 같은 재판과 표준판례 텍스트가 다름')
                    conflicts.append(dict(base, kind='registry-text', note=', '.join(diff), registryIds=[rc['id'] for rc in reg_by_did[did]]))
                elif nosrc and any(rc.get('group') == 'standard' for rc in reg_by_did[did]):
                    conflicts.append(dict(base, kind='registry-no-source', registryIds=nosrc,
                                          note='등록부에 standardSource 없이 있음 — add 는 "이미 있음"으로 건너뛰므로 검증 후 set --standard-source 로 붙인다'))
            u['reasons'] = [r for r in L.REVIEW_REASONS if r in u['reasons']]
            units.append(u)

    # ---- 같은 과목 안 같은 재판: 첫 항목만
    groups = collections.OrderedDict()
    for u in units:
        if u['decisionId']:
            groups.setdefault(u['decisionId'], []).append(u)
    for group in groups.values():
        if len(group) < 2:
            continue
        primary = next((x for x in group if not x['row'].get('missing')), group[0])   # md 가 있는 첫 항목
        for x in group:
            if x is not primary:
                x['dupOf'] = primary
                primary.setdefault('dups', []).append(x)
    for p in {id(u['dupOf']): u['dupOf'] for u in units if u.get('dupOf')}.values():
        conflicts.append({'seq': p['row']['seq'], 'no': p['row']['no'], 'chunk': p['row'].get('chunk'), 'decisionId': p['decisionId'],
                          'kind': 'duplicate', 'note': '같은 재판이 여러 항목에 실림: ' + ' / '.join(placement(x) for x in [p] + p['dups'])})

    # ---- 판정 기록
    by_key = collections.defaultdict(list)
    for r in records:
        by_key[rkey(r)].append(r)

    def current(u, title=False):
        rs = [r for r in by_key.get(u['key'], []) if (r.get('reason') == 'title') == title]
        if not title:
            rs = [r for r in rs if not r.get('textSha256') or r.get('textSha256') == u['textSha']]
        return rs[-1] if rs else None

    added = []

    def add_record(u, reason, note, kind=None, title=False):
        r = {'seq': u['row']['seq'], 'no': u['row']['no'], 'chunk': u['row'].get('chunk'), 'decisionId': u['decisionId'] or '',
             'caseNumber': u['case'].get('caseNumber'), 'reason': reason, 'reasons': [reason] if title else (u['reasons'] or [reason]),
             'verdict': 'pending', 'reviewer': '', 'reviewedAt': '', 'note': note, 'fixedSections': {}}
        if kind:
            r['sampleKind'] = kind
        if title:
            r['title'] = ''
            del r['fixedSections']
        else:
            r['textSha256'] = u['textSha']
            r['pages'] = u['row'].get('pdfPages') or []
        records.append(r)
        by_key[u['key']].append(r)
        added.append(r)
        return r

    live = [u for u in units if not u.get('dupOf') and not u['row'].get('missing')]
    for u in live:
        if u['reasons'] and current(u) is None:
            add_record(u, u['reasons'][0], '; '.join(dict.fromkeys(u['notes']))[:2000])

    population = [u for u in live if u['row']['verify']['status'] == 'pass' and not u['reasons'] and u['decisionId']]
    pop_keys = {u['key']: u for u in population}

    def random_records():
        out = []
        for k, u in pop_keys.items():
            r = current(u)
            if r and r.get('reason') == 'sample' and r.get('sampleKind', 'random') == 'random':
                out.append((u, r))
        return out

    target = L.sample_size(len(population), rate, minimum)
    have = {u['key'] for u, _ in random_records()}
    for k in L.pick_sample(list(pop_keys), have, target, seed):
        u = pop_keys[k]
        if current(u) is None:
            add_record(u, 'sample', f'pass 표본(seed {seed}, {int(rate * 100)}%, 최소 {minimum})', kind='random')
    rnd = random_records()
    verdicts = [r.get('verdict', 'pending') for _, r in rnd]
    defects = [(u, r) for u, r in rnd if r.get('verdict') in ('fix', 'reject')]
    complete = bool(rnd) and all(v in ('ok', 'fix', 'reject') for v in verdicts)
    drate = L.defect_rate(len(defects), len(rnd))
    bad_chunks = sorted({u['row'].get('chunk') for u, _ in defects})
    for u in population:
        if u['row'].get('chunk') in bad_chunks and current(u) is None:
            add_record(u, 'sample', f'청크 {u["row"].get("chunk")} 전수 재검토(표본 결함)', kind='chunk')
    subject_full = drate > tol
    if subject_full:
        for u in population:
            if current(u) is None:
                add_record(u, 'sample', f'과목 전수 재검토(표본 결함률 {drate:.2%} > {tol:.1%})', kind='subject')
    for u in live:
        title = u['row'].get('title') or ''
        if len(title) > L.TITLE_MAX and current(u, title=True) is None:
            add_record(u, 'title', f'제목 {len(title)}자 > {L.TITLE_MAX}자 — PDF 제목 그대로 두려면 verdict ok, 줄이려면 title 에 축약안', title=True)

    sample_reviewers = sorted({r.get('reviewer') for _, r in rnd if r.get('reviewer')})
    sample_dates = sorted(str(r.get('reviewedAt'))[:10] for _, r in rnd if re.match(r'\d{4}-\d{2}-\d{2}', str(r.get('reviewedAt') or '')))
    pct = f'{int(round(rate * 100))}%'
    sample_reviewer = a.reviewer or ('script+' + '/'.join(sample_reviewers) + f' sample {pct}' if sample_reviewers else f'script sample {pct}')
    sample_date = sample_dates[-1] if sample_dates else L.today()

    # ---- 후보
    candidates = []
    for u in units:
        row, case = u['row'], u['case']
        sections = row.get('sections') or {}
        sk = entries_by_seq.get(row['seq']) or {}
        blockers, info = list(u['blockers']), []
        src = None
        if not row.get('missing') and not u.get('dupOf'):
            rec = current(u)
            fields = [f for f in L.display_fields(sections) if sections.get(f)]
            verify = row['verify']
            use_sections, use_verify, reviewer, rdate = sections, verify, None, None
            if rec is not None:
                verdict = rec.get('verdict', 'pending')
                if verdict not in L.VERDICTS:
                    info.append(f'알 수 없는 verdict {verdict!r} → pending')
                    verdict = 'pending'
                if verdict == 'pending':
                    blockers.append(f'판정 대기({rec.get("reason")})')
                elif verdict == 'reject':
                    info.append('판정 reject — standardSource 생략')
                else:
                    reviewer = rec.get('reviewer') or a.reviewer or 'reviewer'
                    rdate = str(rec.get('reviewedAt') or '')[:10]
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', rdate):
                        rdate = L.today()
                    if verdict == 'fix':
                        fixed = dict(rec.get('fixedSections') or {})
                        if rec.get('fixedText') and not fixed:
                            fixed = {'판결요지': rec['fixedText']}
                        use_sections = copy.deepcopy(sections)
                        for k, v in fixed.items():
                            name = L.canon_section(k) or k
                            use_sections[name] = v if (v or '').strip() else None
                        idx = seqs.index(row['seq']) if row['seq'] in seqs else -1
                        nxt = entries_by_seq.get(seqs[idx + 1]) if 0 <= idx < len(seqs) - 1 else None
                        use_verify = L.verify_entry(d, use_sections, row.get('pdfPages') or [], sk, nxt, skel.get('pages'))
                        if use_verify['status'] != 'pass':
                            reviewer = None
                            blockers.append('fix 텍스트가 다시 대조를 통과하지 못함')
                            conflicts.append({'seq': row['seq'], 'no': row['no'], 'chunk': row.get('chunk'), 'decisionId': u['decisionId'],
                                              'kind': 'fix-failed', 'note': '; '.join(f'〈{f}〉 {v.get("note")}' for f, v in use_verify['fields'].items()
                                                                                       if v['status'] != 'pass') or use_verify.get('note', '')})
                        fields = [f for f in L.display_fields(use_sections) if use_sections.get(f)]
                    if reviewer:
                        src = L.standard_source_from_sections(use_sections, fields, file=pdf_file,
                                                              pages=use_verify.get('pages') or row.get('pdfPages') or [],
                                                              reviewer=reviewer, reviewed_at=rdate, sha256=use_verify.get('pagesSha256', ''))
            elif u['key'] in pop_keys:
                if not complete:
                    pend = sum(1 for v in verdicts if v not in ('ok', 'fix', 'reject'))
                    blockers.append(f'표본 판정 대기({pend}/{len(rnd)}건 미판정)')
                elif row.get('chunk') in bad_chunks or subject_full:
                    blockers.append('표본 결함 — 재검토 대기')
                else:
                    src = L.standard_source_from_sections(sections, [f for f in fields if verify['fields'].get(f, {}).get('status') == 'pass'],
                                                          file=pdf_file, pages=verify.get('pages') or row.get('pdfPages') or [],
                                                          reviewer=sample_reviewer, reviewed_at=sample_date, sha256=verify.get('pagesSha256', ''))
            elif verify['status'] == 'skip':
                info.append('표시 필드 없음 — standardSource 생략')
            if src is not None:
                errs = L.check_standard_source(src)
                if errs:
                    blockers.append('standardSource 형식 오류: ' + '; '.join(errs))
                    src = None
        # 제목
        title = row.get('title') or sk.get('title') or ''
        trec = current(u, title=True) if not u.get('dupOf') else None
        if trec and trec.get('verdict') in ('ok', 'fix') and (trec.get('title') or '').strip():
            title = trec['title'].strip()
        # 목차
        cand_toc = list(sk.get('tocPath') or [])
        tstatus = sk.get('tocPathStatus', 'resolved')
        if not cand_toc:
            blockers.append('tocPath 없음(목차 위치 미해결)')
        elif tstatus != 'resolved' or any(t not in tids for t in cand_toc):
            missing_ids = [t for t in cand_toc if t not in tids]
            blockers.append(f'tocPath {tstatus}' + (f' — toc.json 에 없는 id {missing_ids}' if missing_ids else '') + ' (toc.json 반영 후 다시 병합)')
        if not title:
            blockers.append('제목 없음')
        # memo
        memo = []
        if sections.get('판시사항') and sections.get('쟁점'):
            memo.append('쟁점: ' + ' '.join(sections['쟁점'].split('\n')))
        if u.get('dups'):
            memo.append('함께 실린 곳: ' + ', '.join(placement(x) for x in u['dups']))
        if u['multi']:
            others = [c.get('caseNumber') for i, c in enumerate(row.get('cases') or []) if i != u['ci']]
            memo.append('같은 항목의 다른 재판: ' + ', '.join(o or '?' for o in others))
        if u.get('dupOf'):
            status, reason = 'skip', f'같은 재판 중복 — 첫 항목 seq {u["dupOf"]["row"]["seq"]}({u["dupOf"]["row"]["no"]}번)에 등록'
        elif blockers:
            status, reason = 'review', '; '.join(dict.fromkeys(blockers))
        else:
            status = 'ok'
            reason = '검증된 standardSource' if src else ('standardSource 없음: ' + ('; '.join(info) if info else '검증 조건 미충족'))
        cand = {'caseNumber': case.get('caseNumber') or '', 'lookupKey': case.get('lookupKey') or '', 'court': case.get('court') or '',
                'decisionType': u['decisionType'], 'date': case.get('date') or '', 'enBanc': bool(case.get('enBanc')),
                'title': title, 'tocPath': cand_toc, 'tags': [], 'selectionReason': sections.get('선정이유') or '',
                'keywords': keywords_of(sections.get('주제')), 'memo': ' / '.join(memo), 'status': status, 'statusReason': reason,
                'seq': row['seq'], 'no': row['no'], 'chunk': row.get('chunk'), 'pdfPages': row.get('pdfPages') or [],
                'decisionId': u['decisionId'] or ''}
        if src is not None and status != 'skip':
            cand['standardSource'] = src
        candidates.append(cand)
    stats = {'records': len(records), 'added': len(added),
             'pending': sum(1 for u in live for r in [current(u)] if r and r.get('verdict', 'pending') == 'pending'),
             'sample': {'population': len(population), 'target': target, 'size': len(rnd),
                        'decided': sum(1 for v in verdicts if v in ('ok', 'fix', 'reject')), 'defects': len(defects),
                        'defectRate': round(drate, 4), 'complete': complete, 'defectChunks': bad_chunks, 'subjectFullReview': subject_full}}
    return {'candidates': candidates, 'conflicts': conflicts, 'added': added, 'new_meta': new_meta, 'stats': stats,
            'review_path': review_path, 'reg_path': reg_path, 'toc_path': toc_path, 'tids': tids, 'skel': skel}


def check(candidates, tids):
    """standardSource 형식 + status ok 후보의 add 사전 점검 → (standardSource 수, 오류 목록)."""
    errors, n = [], 0
    for c in candidates:
        tag = f'seq {c["seq"]} {c["caseNumber"]}'
        if 'standardSource' in c:
            n += 1
            for e in L.check_standard_source(c['standardSource']):
                errors.append(f'{tag}: standardSource {e}')
        if c['status'] != 'ok':
            continue
        rec = {'court': c['court'], 'caseNumber': c['caseNumber'], 'lookupKey': c['lookupKey'] or None,
               'decisionDate': c['date'], 'decisionType': c['decisionType']}
        try:
            did = L.identity(rec)['decisionId']
            if c.get('decisionId') and did != c['decisionId']:
                errors.append(f'{tag}: decisionId {c["decisionId"]} ≠ {did}')
        except (ValueError, KeyError) as exc:
            errors.append(f'{tag}: 재판 ID {exc}')
        if c['enBanc'] and c['court'] != '대법원':
            errors.append(f'{tag}: 전원합의체 표시는 대법원 사건에만')
        if not c['tocPath'] or any(t not in tids for t in c['tocPath']):
            errors.append(f'{tag}: tocPath {c["tocPath"]} 가 toc.json 에 없음')
        if not c['title']:
            errors.append(f'{tag}: 제목 없음')
    return n, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--subject', help='과목 id 또는 한글명')
    ap.add_argument('--dir', help='과목 폴더(기본: data/standard-cases/<한글과목명>)')
    ap.add_argument('--check', action='store_true', help='standardSource 와 add 사전 점검 결과를 출력(오류 있으면 종료코드 1)')
    ap.add_argument('--reviewer', help='표본 경로로 검증된 항목의 standardSource.reviewer (기본: script+<표본 판정자> sample 10%%)')
    ap.add_argument('--seed', type=int, help=f'표본 난수 시드(새 _review.jsonl 에만 적용, 기본 {L.SEED})')
    ap.add_argument('--registry', help='비교할 registry.json (기본: main 작업 폴더의 data/registry.json)')
    ap.add_argument('--toc', help='비교할 toc.json (기본: main 작업 폴더의 data/toc.json)')
    a = ap.parse_args(argv)
    try:
        sid, d = L.subject_dir(a.subject, a.dir)
    except ValueError as exc:
        print('ERROR -', exc)
        return 2
    if not os.path.exists(os.path.join(d, 'entries.jsonl')):
        print('ERROR - entries.jsonl 없음: 먼저 python -X utf8 tools/md_validate.py --subject', sid)
        return 2
    try:
        res = run(a, sid, d)
    except FileNotFoundError as exc:
        print('ERROR - 파일 없음:', exc)
        return 2
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print('ERROR - 입력을 읽지 못함:', exc)
        return 2
    cands = res['candidates']
    skel = res['skel']
    out = {'source': skel.get('pdf'), 'subject': sid, 'group': 'standard', 'generatedAt': L.now_iso(),
           'summary': {k: sum(1 for c in cands if c['status'] == k) for k in ('ok', 'review', 'skip')}, 'candidates': cands}
    out['summary']['standardSource'] = sum(1 for c in cands if 'standardSource' in c)
    cpath = os.path.join(d, '_conflicts.json')
    try:
        prev = L.read_json(cpath) if os.path.exists(cpath) else {}
        if not isinstance(prev, dict):
            prev = {'previous': prev}
        prev['stage3'] = res['conflicts']
        if res['new_meta']:
            L.write_jsonl(res['review_path'], [res['new_meta']] + res['added'])
        else:
            L.append_jsonl(res['review_path'], res['added'])
        L.write_json(os.path.join(d, f'candidates-{sid}.json'), out)
        L.write_json(cpath, prev)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print('ERROR - 쓰기 실패:', exc)
        return 2
    s = out['summary']
    st = res['stats']
    smp = st['sample']
    active = s['ok'] + s['review']
    print(f"[{sid}] 후보 {len(cands)}건 — ok {s['ok']} / review {s['review']} / skip {s['skip']} | standardSource {s['standardSource']}건"
          f" (skip 제외 {active}건 중 {s['standardSource'] / active:.1%})" if active else f"[{sid}] 후보 {len(cands)}건 — 없음")
    print(f"_review.jsonl: 기록 {st['records']}건(새 {st['added']}), 판정 대기 {st['pending']}건 | 표본 {smp['size']}/{smp['target']}"
          f" (모집단 {smp['population']}, 판정 {smp['decided']}, 결함 {smp['defects']}, 결함률 {smp['defectRate']:.2%}, "
          f"{'완료' if smp['complete'] else '미완료'})" + (f" | 결함 청크 {smp['defectChunks']}" if smp['defectChunks'] else '')
          + (' | 과목 전수 재검토' if smp['subjectFullReview'] else ''))
    kinds = collections.Counter(c['kind'] for c in res['conflicts'])
    print(f"_conflicts(stage3) {len(res['conflicts'])}건: {dict(kinds)}")
    reasons = collections.Counter(re.sub(r'\d+', 'n', c['statusReason'].split(';')[0])[:50] for c in cands if c['status'] == 'review')
    if reasons:
        print('review 사유 상위:', '; '.join(f'{k} {n}' for k, n in reasons.most_common(5)))
    print(f"비교 기준: 등록부 {res['reg_path']} · 목차 {res['toc_path']}")
    print('→', os.path.join(d, f'candidates-{sid}.json'), '·', cpath, '·', res['review_path'])
    if a.check:
        n, errors = check(cands, res['tids'])
        for e in errors[:50]:
            print('ERROR -', e)
        print(f'--check: standardSource {n}건, add 사전 점검 ok {s["ok"]}건 — 오류 {len(errors)}개')
        return 1 if errors else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
