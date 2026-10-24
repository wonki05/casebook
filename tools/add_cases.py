#!/usr/bin/env python3
"""사건 등록부(data/registry.json)와 표준판례 목차(data/toc.json)를 다루는 CLI.

  # 후보 파일(pdf_standard_cases.py / annual_cases.py 산출물)에서 status 가 "ok" 인 항목을 등록
  python3 tools/add_cases.py add --from data/standard-cases/candidates-commercial.json [--group standard] [--subject commercial]
  # 사건 하나를 직접 등록
  python3 tools/add_cases.py add --group enbanc --subject civil --case 2023다275578 --date 2026-09-29 --title "채권가압류 후 원인계약의 합의해제" [--toc mb-3/mb-3-1] [--tags a,b]
  python3 tools/add_cases.py add --group standard --subject commercial --case 2015다45451 --date 2021-02-18 --enbanc --title "대표이사의 전단적 대표행위" --toc sb-2/sb-2-4/sb-2-4-2
  python3 tools/add_cases.py add --group annual --field family --year 2024 --case 2023므12345 --date 2024-05-30 --title "..." [--article "[2024년 분야별 중요판례분석] (5) 가족법" --url https://...]
  # 필드 수정
  python3 tools/add_cases.py set std-civil-04 --title "..." --toc mb-1/mb-1-4 --result 파기환송 --tags "소멸시효,판례변경"
  python3 tools/add_cases.py set annual-2025-07 --field criminal-special [--year 2025 --article "..." --url https://...]
  # 목차
  python3 tools/add_cases.py toc list --subject civil
  python3 tools/add_cases.py toc add --subject civil --parent mb-3 --id mb-3-4 --label "사무관리"      (parent 생략 = 최상위)
  python3 tools/add_cases.py toc rename --id mb-3-4 --label "사무관리·부당이득"
  # 점검
  python3 tools/add_cases.py validate

후보 파일 항목 필드: caseNumber(필수) court date enBanc title tocPath(목차 id 배열) tags status(ok 만 등록) editorial{issues,holding,statutes} (annual 은 field 도 항목별로 덮어쓸 수 있음)
id 는 관례대로 자동 생성: std-<subject>-NN · annual-<year>-NN · enbanc-<romanized> · cc-<romanized>
법률신문(annual) 사건은 annual.field(분야: tools/subjects.py 의 ANNUAL_FIELDS)를 가진다. --field 를 생략하면 기사 제목에서 추정하고,
과목(subject)은 분야에서 정해진다(가족법 → civil, 형법각칙 → criminal, 지식재산권법 → ip …).
"""
import argparse, json, os, re, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from case_identity import identity, IDENTITY_FIELDS, validate_standard_source, standard_sources_by_decision, primary_case_number, docket_parts
from casenum import romanize, lookup_key, is_cc  # noqa: E402
from subjects import SUBJECT_IDS, STANDARD_IDS, ANNUAL_BY_ID, ANNUAL_FIELD_IDS, resolve_field, guess_field, article_year  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, 'data', 'registry.json')
TOC = os.path.join(ROOT, 'data', 'toc.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')
SUBJECTS = SUBJECT_IDS   # tools/subjects.py 가 단일 출처 (지식재산권법 ip 는 표준판례 과목이 아님 → STANDARD_IDS)
GROUPS = ['standard', 'annual', 'enbanc', 'ccourt']


def annual_field(field, subject, article):
    """annual 사건의 분야를 정하고 과목과 맞춘다 → (field, subject)."""
    field = field or guess_field(article, subject)
    if not field:
        raise SystemExit(f'법률신문 분야를 정할 수 없습니다(기사 제목 {article!r}) → --field 또는 후보 파일의 "field" 로 지정하세요 ({", ".join(ANNUAL_FIELD_IDS)})')
    if field not in ANNUAL_BY_ID:
        raise SystemExit(f'알 수 없는 분야: {field} (가능: {", ".join(ANNUAL_FIELD_IDS)})')
    fs = ANNUAL_BY_ID[field]['subject']
    if subject and subject != fs:
        raise SystemExit(f'분야 {field} 의 과목은 {fs} 입니다(지정한 과목: {subject})')
    return field, fs


_loaded_bytes = {}


def read_json(path):
    with open(path, encoding='utf-8') as src:
        return json.load(src)


def load():
    for path in (REG, TOC):
        _loaded_bytes[path] = Path(path).read_bytes()
    return json.loads(_loaded_bytes[REG]), json.loads(_loaded_bytes[TOC])


def save(reg=None, toc=None):
    for path, value in ((REG, reg), (TOC, toc)):
        if value is None:
            continue
        if path in _loaded_bytes and Path(path).read_bytes() != _loaded_bytes[path]:
            raise SystemExit(f'다른 세션이 {path}를 변경했습니다. 최신 파일을 읽고 다시 실행하세요.')
        raw = json.dumps(value, ensure_ascii=False, indent=1).encode('utf-8')
        # Keep the existing file permissions on managed Windows workspaces.
        # Refuse a stale snapshot rather than overwriting another session's work.
        Path(path).write_bytes(raw)
        _loaded_bytes[path] = raw


def toc_index(toc):
    """id -> (subject, path[list of ids], node)"""
    out = {}
    def rec(subject, nodes, path):
        for n in nodes:
            p = path + [n['id']]
            out[n['id']] = (subject, p, n)
            rec(subject, n.get('children') or [], p)
    for subject, nodes in toc.items():
        rec(subject, nodes, [])
    return out


def next_id(reg, group, subject, case_number, year=None):
    ids = {c['id'] for c in reg['cases']}
    if group == 'standard':
        n = 1
        while f'std-{subject}-{n:02d}' in ids: n += 1
        return f'std-{subject}-{n:02d}'
    if group == 'annual':
        n = 1
        while f'annual-{year}-{n:02d}' in ids: n += 1
        return f'annual-{year}-{n:02d}'
    base = ('cc-' if group == 'ccourt' else 'enbanc-') + romanize(lookup_key(case_number))
    cid, n = base, 2
    while cid in ids:
        cid = f'{base}-{n}'; n += 1
    return cid


def make_entry(reg, toc, group, subject, case_number, date, title, toc_path=None, tags=None, court=None, en_banc=None, year=None, article=None, url=None, editorial=None, extra=None, field=None, decision_type=None):
    key = primary_case_number(case_number)
    if not court:
        if is_cc(key):
            court = '헌법재판소'
        elif group == 'enbanc' or docket_parts(key)[1] in {'다', '다카', '도', '두', '마', '므', '그', '스', '모', '후'}:
            court = '대법원'
        else:
            raise SystemExit(f'하급심 또는 법원 불명확 사건은 정식 법원명이 필요합니다: {case_number} (--court)')
    if group == 'enbanc' and court != '대법원':
        raise SystemExit('전원합의체 그룹에는 대법원 사건만 등록할 수 있습니다')
    if en_banc and court != '대법원':
        raise SystemExit('전원합의체 표시는 대법원 사건에만 사용할 수 있습니다')
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date or ''):
        raise SystemExit(f'선고일은 YYYY-MM-DD 형식이어야 합니다: {case_number} {date!r}')
    if group == 'annual':
        field, subject = annual_field(field, subject, article)
        year = year or article_year(article)
        if not year:
            raise SystemExit(f'법률신문 연재 연도가 필요합니다(--year 또는 후보 파일의 "year"): {case_number}')
    elif group == 'standard' and subject not in STANDARD_IDS:
        raise SystemExit(f'표준판례 과목이 아닙니다: {subject} (가능: {", ".join(STANDARD_IDS)})')
    if subject not in SUBJECTS:
        raise SystemExit(f'과목이 필요합니다: {case_number} (가능: {", ".join(SUBJECTS)})')
    e = {'id': next_id(reg, group, subject, case_number, year), 'group': group, 'subject': subject, 'title': title or '', 'court': court,
         'caseNumber': case_number, 'lookupKey': key, 'decisionDate': date, 'enBanc': bool(en_banc) if en_banc is not None else group == 'enbanc',
         'tocPath': toc_path or [], 'tags': tags or [], 'result': '', 'editorial': editorial or {}}
    if group == 'annual':
        e['annual'] = {'year': year, 'field': field, 'article': article or '', 'url': url or ''}
    if extra:
        e.update({k: v for k, v in extra.items() if v is not None})
    if decision_type:
        e['decisionType'] = decision_type
    try:
        validate_standard_source(e.get('standardSource'))
        e.update(identity(e))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if e['tocPath']:
        idx = toc_index(toc)
        for tid in e['tocPath']:
            if tid not in idx:
                raise SystemExit(f'toc.json 에 없는 목차 id: {tid} (사건 {case_number}). 먼저 `toc add` 로 만드세요.')
    return e


def duplicate(reg, e):
    """같은 그룹에 같은 사건이 이미 있는가. annual 은 같은 연도·분야일 때만, standard 는 같은 과목일 때만 중복
    (한 판례가 두 분야 기사에, 또는 두 과목의 표준판례 PDF 에 실릴 수 있다 — 과목마다 그 책의 제목으로 배치된다)."""
    for x in reg['cases']:
        if x['group'] != e['group']:
            continue
        if identity(x, fetched_citation(x['id']))['decisionId'] != identity(e)['decisionId']:
            continue
        if e['group'] == 'standard':
            if x.get('subject') == e.get('subject'):
                return True
            continue
        if e['group'] != 'annual':
            return True
        xa, ea = x.get('annual') or {}, e['annual']
        if xa.get('year') == ea['year'] and (xa.get('field') or guess_field(xa.get('article'), x.get('subject'))) == ea['field']:
            return True
    return False


def cmd_add(a):
    reg, toc = load()
    added = []
    if a.from_file:
        src = read_json(a.from_file)
        group = a.group or src.get('group') or 'standard'
        subject = a.subject or src.get('subject')
        year = a.year or src.get('year')   # annual: 명령줄 --year/--field 가 파일 값보다 우선(분야는 --field > 항목 field > 파일 field)
        for c in src.get('candidates', []):
            if c.get('status') != 'ok':
                continue
            e = make_entry(reg, toc, group, c.get('subject') or subject, c['caseNumber'], c.get('date'), c.get('title'), c.get('tocPath'), c.get('tags'), c.get('court'), c.get('enBanc'),
                           year, src.get('article'), src.get('url'), c.get('editorial'), {k: c.get(k) for k in ('selectionReason', 'keywords', 'difficulty', 'memo', 'lawgo', 'decisionType', 'courtId', 'standardSource')},
                           a.field or c.get('field') or src.get('field'))
            if duplicate(reg, e):
                print('이미 있음:', c['caseNumber']); continue
            reg['cases'].append(e); added.append(e['id'])
    else:
        if not (a.group and (a.subject or a.field) and a.case and a.date):
            raise SystemExit('--group --subject --case --date 가 필요합니다 (annual 은 --subject 대신 --field 가능; 또는 --from)')
        e = make_entry(reg, toc, a.group, a.subject, a.case, a.date, a.title, a.toc.split('/') if a.toc else None, a.tags.split(',') if a.tags else None, a.court, True if a.enbanc else None, a.year, a.article, a.url,
                       field=a.field, decision_type=a.decision_type)
        if duplicate(reg, e):
            raise SystemExit('이미 있음: ' + a.case)
        reg['cases'].append(e); added.append(e['id'])
    save(reg=reg)
    print('등록:', ', '.join(added) if added else '(없음)')
    if added:
        print('다음: python3 tools/fetch_lawgo.py --all-missing  →  python3 tools/build_data.py  →  make build check')


def cmd_set(a):
    reg, toc = load()
    c = next((x for x in reg['cases'] if x['id'] == a.id), None)
    if not c:
        raise SystemExit('없는 id: ' + a.id)
    requested_subject = getattr(a, 'subject', None)
    old_subject = c['subject']
    if a.title: c['title'] = a.title
    if a.toc is not None:
        path = [p for p in a.toc.split('/') if p]
        idx = toc_index(toc)
        for tid in path:
            if tid not in idx: raise SystemExit('toc.json 에 없는 목차 id: ' + tid)
        c['tocPath'] = path
    if a.result is not None: c['result'] = a.result
    if a.tags is not None: c['tags'] = [t for t in a.tags.split(',') if t]
    if a.date: c['decisionDate'] = a.date
    if a.court:
        c['court'] = a.court
        c.pop('courtId', None)
    if a.decision_type: c['decisionType'] = a.decision_type
    if a.standard_source:
        c['standardSource'] = read_json(a.standard_source)
        validate_standard_source(c['standardSource'])
    if a.enbanc is not None: c['enBanc'] = a.enbanc == 'yes'
    for k in ('selectionReason', 'keywords', 'difficulty', 'memo'):
        v = getattr(a, k, None)
        if v is not None:
            c[k] = v.split(',') if k == 'keywords' else v
    if any(getattr(a, k) is not None for k in ('field', 'year', 'article', 'url')):
        if c['group'] != 'annual':
            raise SystemExit('--field/--year/--article/--url 은 법률신문(annual) 사건에만 씁니다: ' + a.id)
        an = c.setdefault('annual', {})
        if a.year is not None: an['year'] = a.year
        if a.article is not None: an['article'] = a.article
        if a.url is not None: an['url'] = a.url
        if a.field is not None:
            an['field'], c['subject'] = annual_field(a.field, None, an.get('article'))
    if requested_subject is not None:
        if requested_subject not in SUBJECTS:
            raise SystemExit('알 수 없는 과목: ' + requested_subject)
        if c['group'] == 'annual':
            an = c.get('annual') or {}
            if not an.get('field'):
                raise SystemExit('법률신문 과목 변경에는 --field 또는 기존 annual.field가 필요합니다')
            _, subject = annual_field(an['field'], requested_subject, an.get('article'))
            c['subject'] = subject
        else:
            c['subject'] = requested_subject
        if c['group'] == 'standard':
            if requested_subject not in STANDARD_IDS:
                raise SystemExit('표준판례 과목이 아닙니다: ' + requested_subject)
            if requested_subject != old_subject and a.toc is None:
                raise SystemExit('표준판례 과목 변경에는 새 과목의 --toc 경로가 필요합니다')
    if requested_subject is not None or a.toc is not None:
        path = c.get('tocPath') or []
        if c['group'] == 'standard' and not path:
            raise SystemExit('표준판례는 비어 있지 않은 --toc 경로가 필요합니다')
        idx = toc_index(toc)
        for tid in path:
            if tid not in idx or idx[tid][0] != c['subject']:
                raise SystemExit('대상 과목과 맞지 않는 목차 id: ' + tid)
        if path and idx[path[-1]][1] != path:
            raise SystemExit('--toc는 상위부터 하위까지 이어지는 전체 경로여야 합니다')
    previous = c.get('decisionId')
    c.update(identity(c, fetched_citation(c['id'])))
    aliases = reg.setdefault('identityAliases', {})
    aliases[c['id']] = c['decisionId']
    if previous and previous != c['decisionId']:
        aliases[previous] = c['decisionId']
    save(reg=reg); print('수정:', a.id)


def cmd_toc(a):
    reg, toc = load()
    if a.toc_cmd == 'list':
        def rec(nodes, d=0):
            for n in nodes:
                print('  ' * d + f"{n['id']}  {n['label']}")
                rec(n.get('children') or [], d + 1)
        for s in ([a.subject] if a.subject else STANDARD_IDS):
            print(f'== {s}'); rec(toc.get(s, []))
        return
    idx = toc_index(toc)
    if a.toc_cmd == 'add':
        if a.id in idx: raise SystemExit('이미 있는 id: ' + a.id)
        node = {'id': a.id, 'label': a.label, 'children': []}
        if a.parent:
            if a.parent not in idx: raise SystemExit('없는 parent: ' + a.parent)
            idx[a.parent][2].setdefault('children', []).append(node)
        else:
            toc.setdefault(a.subject, []).append(node)
        save(toc=toc); print('목차 추가:', a.id)
    elif a.toc_cmd == 'rename':
        if a.id not in idx: raise SystemExit('없는 id: ' + a.id)
        idx[a.id][2]['label'] = a.label; save(toc=toc); print('이름 변경:', a.id)
    elif a.toc_cmd == 'replace':
        if not (a.subject and a.from_file):
            raise SystemExit('toc replace 에는 --subject 와 --from 이 필요합니다')
        src = read_json(a.from_file)
        tree = src.get('proposed') if isinstance(src, dict) else src
        if not isinstance(tree, list) or not tree:
            raise SystemExit('--from 파일에 proposed 배열이 없습니다')
        from subjects import BY_ID as _BY
        prefix = _BY[a.subject]['tocPrefix'] + '-'
        ids = []
        def walk(nodes, depth):
            for n in nodes:
                if not isinstance(n, dict) or not n.get('id') or not n.get('label'):
                    raise SystemExit(f'노드 형식 오류: {n!r}')
                if not n['id'].startswith(prefix):
                    raise SystemExit(f'id 접두어가 과목({prefix})과 다릅니다: {n["id"]}')
                if depth > 3:
                    raise SystemExit(f'목차 깊이는 3까지입니다: {n["id"]}')
                ids.append(n['id'])
                walk(n.get('children') or [], depth + 1)
        walk(tree, 1)
        if len(ids) != len(set(ids)):
            raise SystemExit('제안 목차에 중복 id 가 있습니다')
        new_ids = set(ids)
        cleared = []
        for c in reg['cases']:
            if c.get('subject') == a.subject and c.get('tocPath') and not all(t in new_ids for t in c['tocPath']):
                cleared.append((c['id'], c['tocPath']))
        old_n = len(toc_index({a.subject: toc.get(a.subject, [])}))
        print(f'[{a.subject}] 목차 교체: 기존 {old_n}개 노드 → 새 {len(ids)}개 노드; 경로를 잃는 사건 {len(cleared)}건')
        for cid, path in cleared:
            print('  tocPath 비움 →', cid, path, '(set --toc 로 다시 지정)')
        if a.dry_run:
            print('(--dry-run: 저장하지 않음)'); return
        toc[a.subject] = tree
        for c in reg['cases']:
            if c.get('subject') == a.subject and c.get('tocPath') and not all(t in new_ids for t in c['tocPath']):
                c['tocPath'] = []
        save(reg=reg, toc=toc)
        print('저장:', TOC, '및', REG)


def fetched_citation(cid):
    path = os.path.join(FETCHED, cid + '.json')
    if not os.path.isfile(path):
        return ''
    with open(path, encoding='utf-8') as src:
        return json.load(src).get('citation') or ''


def cmd_migrate_identities(a):
    reg, _ = load()
    changed = 0
    aliases = dict(reg.get('identityAliases') or {})
    for c in reg['cases']:
        fields = identity(c, fetched_citation(c['id']))
        if any(c.get(k) != v for k, v in fields.items()):
            previous = c.get('decisionId')
            c.update(fields)
            if previous and previous != fields['decisionId']:
                aliases[previous] = fields['decisionId']
            changed += 1
        aliases[c['id']] = fields['decisionId']
    reg['identityAliases'] = aliases
    save(reg=reg)
    print(f'식별자 보완: {changed}건 (배치 id·공식 원문 파일명 보존)')


def cmd_validate(a):
    reg, toc = load()
    idx = toc_index(toc)
    ids, errs, warnings, identities = set(), [], [], {}
    for c in reg['cases']:
        try:
            fields = identity(c, fetched_citation(c['id']))
            identities[c['id']] = fields
            for key in IDENTITY_FIELDS:
                if key in c and c[key] != fields[key]:
                    errs.append(f"{c['id']}: {key} 불일치 {c[key]!r} != {fields[key]!r}")
            validate_standard_source(c.get('standardSource'))
            if c.get('enBanc') and c.get('court') != '대법원':
                errs.append(f"{c['id']}: 전원합의체는 대법원 사건에만 표시")
            if c['group'] == 'enbanc' and c.get('court') != '대법원':
                errs.append(f"{c['id']}: enbanc 그룹에 대법원이 아닌 사건")
        except (ValueError, KeyError) as exc:
            errs.append(f"{c['id']}: {exc}")
        if c['id'] in ids: errs.append(f"중복 id {c['id']}")
        ids.add(c['id'])
        if c['group'] not in GROUPS: errs.append(f"{c['id']}: group {c['group']}")
        if c['subject'] not in SUBJECTS: errs.append(f"{c['id']}: subject {c['subject']}")
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', c.get('decisionDate', '')): errs.append(f"{c['id']}: decisionDate {c.get('decisionDate')!r}")
        if c['group'] == 'standard' and not c.get('tocPath'): errs.append(f"{c['id']}: 표준판례인데 tocPath 없음")
        if c['group'] == 'standard' and c['subject'] not in STANDARD_IDS: errs.append(f"{c['id']}: 표준판례 과목이 아님 {c['subject']}")
        if c['group'] == 'annual':
            an = c.get('annual') or {}
            f = an.get('field')
            if not f: errs.append(f"{c['id']}: annual.field 없음 (추정값 {guess_field(an.get('article'), c['subject'])}; `set {c['id']} --field …`)")
            elif f not in ANNUAL_BY_ID: errs.append(f"{c['id']}: 알 수 없는 분야 {f}")
            elif ANNUAL_BY_ID[f]['subject'] != c['subject']: errs.append(f"{c['id']}: 분야 {f} 의 과목은 {ANNUAL_BY_ID[f]['subject']} (등록 과목 {c['subject']})")
        for t in c.get('tocPath') or []:
            if t not in idx: errs.append(f"{c['id']}: 없는 목차 id {t}")
            elif idx[t][0] != c['subject']: errs.append(f"{c['id']}: 목차 {t} 는 {idx[t][0]} 과목")
        if c['group'] == 'annual' and not (c.get('annual') or {}).get('year'): errs.append(f"{c['id']}: annual.year 없음")
        if not c.get('title'): errs.append(f"{c['id']}: title 비어 있음")
        has = os.path.exists(os.path.join(FETCHED, c['id'] + '.json'))
        miss = os.path.exists(os.path.join(FETCHED, c['id'] + '.missing.json'))
        if not has: warnings.append(f"{c['id']}: 공식 텍스트 미수집" + (' (.missing: ' + read_json(os.path.join(FETCHED, c['id'] + '.missing.json')).get('reason', '')[:60] + ')' if miss else ''))
    if len(identities) == len(reg['cases']):
        try:
            standard_sources_by_decision(reg['cases'], identities)
        except ValueError as exc:
            errs.append(str(exc))
    for e in errs: print('ERROR -', e)
    for warning in warnings: print('WARN -', warning)
    print(f'{len(reg["cases"])}건 점검, 오류 {len(errs)}개 / 경고 {len(warnings)}개')
    if errs:
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('add'); p.add_argument('--from', dest='from_file'); p.add_argument('--group', choices=GROUPS); p.add_argument('--subject', choices=SUBJECTS)
    p.add_argument('--case'); p.add_argument('--date'); p.add_argument('--title'); p.add_argument('--toc'); p.add_argument('--tags'); p.add_argument('--year', type=int); p.add_argument('--article'); p.add_argument('--url')
    p.add_argument('--field', type=resolve_field, help='법률신문 분야 (' + ', '.join(ANNUAL_FIELD_IDS) + '); 생략하면 --article 제목에서 추정')
    p.add_argument('--enbanc', action='store_true', help='대법원 전원합의체 판결(표준판례 등 enbanc 그룹이 아닌 사건에 표시)')
    p.add_argument('--court', help='정식 선고법원명 (하급심은 반드시 지정)')
    p.add_argument('--decision-type', choices=['판결', '결정'])
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser('set'); p.add_argument('id'); p.add_argument('--title'); p.add_argument('--toc'); p.add_argument('--result'); p.add_argument('--tags'); p.add_argument('--date'); p.add_argument('--enbanc', choices=['yes', 'no'])
    p.add_argument('--subject', choices=SUBJECTS, help='과목 변경 (표준판례는 새 --toc, 법률신문은 일치하는 --field 필요)')
    p.add_argument('--court'); p.add_argument('--decision-type', choices=['판결', '결정'])
    p.add_argument('--standard-source', help='PDF 원문과 대조한 표준판례 발췌 JSON 파일')
    p.add_argument('--selectionReason'); p.add_argument('--keywords'); p.add_argument('--difficulty'); p.add_argument('--memo')
    p.add_argument('--field', type=resolve_field, help='법률신문 분야 (' + ', '.join(ANNUAL_FIELD_IDS) + ') — 과목도 함께 맞춘다')
    p.add_argument('--year', type=int); p.add_argument('--article'); p.add_argument('--url'); p.set_defaults(fn=cmd_set)
    p = sub.add_parser('toc'); p.add_argument('toc_cmd', choices=['list', 'add', 'rename', 'replace']); p.add_argument('--from', dest='from_file', help='replace: 제안 목차 JSON({"proposed": [...]} 또는 배열)'); p.add_argument('--dry-run', action='store_true'); p.add_argument('--subject', choices=STANDARD_IDS); p.add_argument('--parent'); p.add_argument('--id'); p.add_argument('--label'); p.set_defaults(fn=cmd_toc)
    p = sub.add_parser('validate'); p.set_defaults(fn=cmd_validate)
    p = sub.add_parser('migrate-identities'); p.set_defaults(fn=cmd_migrate_identities)
    a = ap.parse_args(); a.fn(a)


if __name__ == '__main__':
    main()
