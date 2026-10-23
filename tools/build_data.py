#!/usr/bin/env python3
"""Build data/cases.json (normalized) from data/registry.json + data/toc.json + data/fetched/*.json.

Usage: python3 tools/build_data.py
  registry.json : 사건 등록부 (메타·목차 경로·편집 요약 대체문·법률신문 기사 정보)   ← 사람/에이전트가 편집
  toc.json      : 표준판례 목차 트리 (과목별, 깊이 1~3)                               ← 사람/에이전트가 편집
  fetched/      : 국가법령정보센터에서 그대로 추출한 공식 텍스트 (tools/fetch_lawgo.py) ← 자동
"""
import copy, json, re, glob, os, sys, datetime
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from case_identity import identity, decision_type, standard_sources_by_decision, STANDARD_FIELDS
from subjects import SUBJECTS as SUBJECT_DEFS, STANDARD_SUBJECTS, ANNUAL_FIELDS, ANNUAL_BY_ID, ANNUAL_YEARS, CCOURT_YEARS, ENBANC_YEARS, ENBANC_FROM, guess_field  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, 'data', 'registry.json')
TOC_FILE = os.path.join(ROOT, 'data', 'toc.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')
OUT = os.path.join(ROOT, 'data', 'cases.json')

GROUP_MAP = {'standard': 'standard', 'annual': 'annual', 'enbanc': 'enbanc', 'constitutional_court': 'ccourt'}

SUBJECTS = [{"id": s["id"], "label": s["label"], "standard": s["standard"]} for s in SUBJECT_DEFS]      # tools/subjects.py 가 단일 출처
SUBJECT_NAMES = '·'.join(s["label"] for s in STANDARD_SUBJECTS)
FIELD_NAMES = '·'.join(dict.fromkeys(f["label"] for f in ANNUAL_FIELDS))
GROUPS = [
    {"id": "standard", "label": "표준판례", "short": "표준판례",
     "desc": f"법학전문대학원협의회 표준판례 — 과목({SUBJECT_NAMES})별 목차 구성"},
    {"id": "annual", "label": "법률신문 주요판례", "short": "주요판례",
     "desc": f"법률신문 「분야별 중요판례분석」 — 연도별 · 분야({FIELD_NAMES})별"},
    {"id": "enbanc", "label": "대법원 전원합의체", "short": "전원합의체",
     "desc": "대법원 전원합의체 판결"},
    {"id": "ccourt", "label": "헌법재판소 주요결정", "short": "헌법재판소",
     "desc": "헌법재판소 주요결정"},
]
PAGES = [  # 표준판례는 과목마다 한 페이지(std-<subject>); 과목 순서 = tools/subjects.py 순서 (standard 과목만)
    {"id": f"std-{s['id']}", "label": f"{s['label']} 표준판례", "short": s["label"], "section": "표준판례", "group": "standard", "subject": s["id"]}
    for s in STANDARD_SUBJECTS
] + [
    {"id": "annual", "label": "법률신문 주요판례", "short": "주요판례", "section": "최신판례", "group": "annual", "subject": None},
    {"id": "enbanc", "label": "대법원 전원합의체", "short": "전원합의체", "section": "최신판례", "group": "enbanc", "subject": None},
    {"id": "ccourt", "label": "헌법재판소 주요결정", "short": "헌법재판소", "section": "최신판례", "group": "ccourt", "subject": None},
    {"id": "laws", "label": "주요법령", "short": "주요법령", "section": "법령", "group": None, "subject": None},
]
def make_year_tabs(years_in, single, decades_from=None):
    """선고연도 탭 [{id, label, from, to}] (최신 → 과거). single=(처음, 끝) 해는 한 해씩 두고,
    그 앞은 decades_from 이 있으면 그 해가 든 연대까지 10년 단위('2010년대'), 없으면 처음 해에서 끝낸다.
    등록부의 선고연도(years_in)가 범위 밖이면 그쪽으로 넓힌다(연대 탭이 있으면 과거 쪽은 연대로)."""
    first, last = single[0], max([single[1]] + years_in)
    if decades_from is None:
        first = min([first] + years_in)
    tabs = [{"id": str(y), "label": str(y), "from": y, "to": y} for y in range(last, first - 1, -1)]
    if decades_from is not None:
        low = min([decades_from] + years_in) // 10 * 10
        tabs += [{"id": f"{d}s", "label": f"{d}년대", "from": d, "to": min(d + 9, first - 1)}
                 for d in range((first - 1) // 10 * 10, low - 1, -10)]
    return tabs


def load_toc():
    return json.loads(Path(TOC_FILE).read_text(encoding='utf-8'))


MARKER_TYPES = [
    ('bracket', re.compile(r'^\s*(\[\d+\])\s*')),
    ('number', re.compile(r'^\s*(\d{1,2}\.)(?:\s+|$)')),
    ('hangul', re.compile(r'^\s*([가나다라마바사아자차카타파하]\.)(?:\s+|$)')),
]
OPINION_HEAD_RE = re.compile(r'^\s*(재판관|대법관|대법원장)\s.{0,80}(의견|意見)\s*$')


def split_items(text):
    """Split an official 판시사항/판결요지 block into numbered items.
    The marker style ([n] / n. / 가.) is taken from the first non-empty line and only that
    style splits items, so sub-numbering (가. 나. inside 1.) stays inside the item.
    Returns list of {"n": label, "text": body}. Body keeps internal line breaks."""
    if not text:
        return []
    lines = [l.rstrip() for l in text.replace('\r', '').split('\n')]
    first = next((l for l in lines if l.strip()), '')
    item_re = None
    for _, rx in MARKER_TYPES:
        if rx.match(first):
            item_re = rx
            break
    if item_re is None:
        body = '\n'.join(l.strip() for l in lines).strip()
        body = re.sub(r'\n{3,}', '\n\n', body)
        return [{"n": "", "text": body}] if body else []
    items = []
    cur = None
    for l in lines:
        m = item_re.match(l)
        if OPINION_HEAD_RE.match(l):
            # e.g. "재판관 김영일의 별개의견" — keep as its own unnumbered line between items
            cur = {"n": "", "text": l.strip()}
            items.append(cur)
            cur = None
            continue
        if m:
            cur = {"n": m.group(1), "text": l[m.end():].strip()}
            items.append(cur)
        else:
            s = l.strip()
            if cur is None:
                if s:
                    cur = {"n": "", "text": s}
                    items.append(cur)
            else:
                cur["text"] += ('\n' + s) if s else '\n'
    for it in items:
        it["text"] = re.sub(r'\n{3,}', '\n\n', it["text"]).strip()
    return [it for it in items if it["text"]]


def split_lines(text):
    return [l.strip() for l in (text or '').replace('\r', '').split('\n') if l.strip()]


def fmt_date(iso):
    y, m, d = iso.split('-')
    return f"{int(y)}. {int(m)}. {int(d)}."


def parse_citation(cit, court, iso_date, case_number, is_enbanc, explicit_type=None):
    """Keep a court's complete name; only Supreme Court uses 대판/대결."""
    cit = (cit or '').strip('[] ')
    dtype = decision_type({'court': court, 'caseNumber': case_number,
                           'decisionType': explicit_type}, cit)
    bench = ''
    if court == '헌법재판소':
        bench = '지정재판부' if '지정재판부' in cit else ('전원재판부' if '전원재판부' in cit or not cit else '')
        citation = f"헌법재판소 {fmt_date(iso_date)} 선고 {case_number} {bench + ' ' if bench else ''}결정"
        short = f"헌결 {case_number}"
    else:
        if court == '대법원' and ('전원합의체' in cit or is_enbanc):
            bench = '전원합의체'
        when = f"{fmt_date(iso_date)}자" if dtype == '결정' else f"{fmt_date(iso_date)} 선고"
        citation = f"{court} {when} {case_number} {bench + ' ' if bench else ''}{dtype}"
        label = ('대결' if dtype == '결정' else '대판') if court == '대법원' else f'{court} {dtype}'
        short = f"{label} {case_number}"
    return bench, dtype, citation.replace('  ', ' '), short


def brackets(blocks):
    """【주 문】 → [주 문] : block headings and heading-like lines (【…】 / 〖…〗 alone on a line) use square brackets."""
    out = []
    for b in blocks:
        h = (b.get("heading") or "").replace("【", "[").replace("】", "]").replace("〖", "[").replace("〗", "]")
        t = b.get("text") or ""
        t = re.sub(r'^(\s*)[【〖]([^】〗\n]{1,30})[】〗](\s*)$', r'\1[\2]\3', t, flags=re.M)
        out.append({"heading": h, "text": t})
    return out


def load_fetched(cid):
    paths = sorted(glob.glob(os.path.join(FETCHED, cid + '.json')) + glob.glob(os.path.join(FETCHED, cid + '.part*.json')))
    if not paths:
        return None
    merged = None
    for p in paths:
        try:
            d = json.loads(Path(p).read_text(encoding='utf-8'))
        except Exception as e:
            print('WARN bad json', p, e, file=sys.stderr)
            continue
        if merged is None:
            merged = d
            merged['sections'] = list(d.get('sections') or [])
        else:
            merged['sections'].extend(d.get('sections') or [])
    return merged


def norm_heading(h):
    return re.sub(r'[\s【】\[\]\u3000]', '', h or '')


def textify(v):
    if v is None:
        return ''
    if isinstance(v, list):
        return '\n'.join(str(x) for x in v)
    return str(v)


def editorial_items(v):
    """Original editorial issues/holding: string (maybe '[1] ...' or '* 1. ...') or list."""
    if isinstance(v, list):
        return [{"n": "", "text": str(x).strip()} for x in v if str(x).strip()]
    s = textify(v).strip()
    s = re.sub(r'^\*\s*', '', s)
    return split_items(s)


def derive_result(fetched, orig):
    r = orig.get('result') or orig.get('outcome') or ''
    if r:
        return r
    if not fetched:
        return ''
    t = ''
    for s in fetched.get('sections', []):
        if norm_heading(s.get('heading')) == '주문':
            t = s.get('text', '')
            break
    if not t:
        return ''
    if '파기' in t:
        if '환송' in t:
            return '파기환송'
        if '이송' in t:
            return '파기이송'
        return '파기자판' if '자판' in t or '무죄' in t else '파기'
    if '상고를 모두 기각' in t or '상고를 기각' in t:
        return '상고기각'
    tags = []
    if '헌법에 합치되지 아니한다' in t or '헌법불합치' in t:
        tags.append('헌법불합치')
    uncon = '헌법에 위반된다' in t
    con = '헌법에 위반되지 아니한다' in t
    if uncon and con:
        tags.append('일부 위헌')
    elif uncon:
        tags.append('위헌')
    elif con:
        tags.append('합헌')
    if '침해한 것' in t or '침해하였' in t or '인용' in t:
        tags.append('인용')
    if '기각' in t:
        tags.append('기각')
    if '각하' in t:
        tags.append('각하')
    return '·'.join(dict.fromkeys(tags))


def apply_source_precedence(rec, standard_fields, official_fields, editorial):
    """Select each study field without modifying official or book source text."""
    sources = {}
    official_source = rec.get('source') or {}
    standard_provenance = []
    for field in STANDARD_FIELDS:
        if field in standard_fields:
            choice = standard_fields[field]
            rec[field] = copy.deepcopy(choice['value'])
            sources[field] = {'type': 'standard', 'sources': copy.deepcopy(choice['sources'])}
            for source in choice['sources']:
                if source not in standard_provenance:
                    standard_provenance.append(copy.deepcopy(source))
        elif official_fields.get(field):
            rec[field] = copy.deepcopy(official_fields[field])
            sources[field] = {'type': 'official', 'label': '국가법령정보센터',
                              'url': official_source.get('url', '')}
        else:
            raw = editorial.get('holding' if field == 'holdings' else field)
            if field in ('issues', 'holdings'):
                rec[field] = editorial_items(raw)
            else:
                rec[field] = [str(x).strip() for x in (raw or []) if str(x).strip()]
            sources[field] = ({'type': 'editorial', 'label': '편집 요약'}
                              if rec[field] else {'type': 'missing'})
    types = {sources[f]['type'] for f in ('issues', 'holdings')}
    rec['summaryType'] = ('standard' if types == {'standard'} else
                          'official' if types == {'official'} else
                          'editorial' if types <= {'editorial', 'missing'} else 'mixed')
    rec['fieldSources'] = sources
    rec['standardSource'] = standard_provenance[0] if standard_provenance else None
    rec['standardSources'] = standard_provenance
    # Keep the official counterpart available for comparison without relabeling it.
    rec['officialSummary'] = copy.deepcopy(official_fields)


def build():
    reg = json.loads(Path(REG).read_text(encoding='utf-8'))
    TOC = load_toc()
    cases = []
    stats = {"official": 0, "editorial": 0, "standard": 0, "mixed": 0, "fullText": 0}
    fetched_by_id = {c['id']: load_fetched(c['id']) for c in reg['cases']}
    identities = {c['id']: identity(c, (fetched_by_id[c['id']] or {}).get('citation', '')) for c in reg['cases']}
    standard_by_decision = standard_sources_by_decision(reg['cases'], identities)
    for c in reg['cases']:
        cid = c['id']
        group = c['group']
        court = c['court']
        is_enbanc = bool(c.get('enBanc')) or group == 'enbanc'
        case_number = c['caseNumber']
        ed = c.get('editorial') or {}
        fetched = fetched_by_id[cid]
        rec = {
            "id": cid,
            "group": group,
            "page": ('std-' + (c.get('subject') or 'constitution')) if group == 'standard' else group,
            "subject": c.get('subject') or 'constitution',
            "tocPath": c.get('tocPath') or [],
            "title": (c.get('title') or '').strip(),
            "caseName": (c.get('officialTitle') or '').strip(),
            "court": court,
            "bench": "",
            "caseNumber": case_number,
            "decisionDate": c['decisionDate'],
            "decisionType": "",
            "citation": "",
            "citeShort": "",
            "result": "",
            "summaryType": "editorial",
            "holdingLabel": "결정요지" if court == '헌법재판소' else "판결요지",
            "issues": [],
            "holdings": [],
            "subjectStatutes": [],
            "statutes": [],
            "precedents": [],
            "fullText": None,
            "source": None,
            "annual": None,
            "tags": c.get('tags') or [],
        }
        rec.update(identities[cid])
        for k in ('selectionReason', 'keywords', 'difficulty', 'memo'):
            if c.get(k):
                rec[k] = c[k]
        if group == 'annual':
            a = c.get('annual') or {}
            # 분야: 등록부의 annual.field → 없으면 기사 제목·과목으로 추정 (화면에는 연재 순번 "(3)" 없이 분야 이름만 쓴다)
            field = a.get('field') if a.get('field') in ANNUAL_BY_ID else guess_field(a.get('article'), c.get('subject'))
            if not field:
                print(f"WARN {cid}: 법률신문 분야를 정할 수 없음 → '분야 미지정' 으로 표시 (add_cases.py set {cid} --field …)", file=sys.stderr)
            rec["annual"] = {"year": a.get('year'), "field": field or '', "series": f"법률신문 {a.get('year') or ''}년 분야별 중요판례분석".replace('  ', ' '),
                             "article": a.get('article', ''), "url": a.get('url', '')}

        if fetched and fetched.get('sections'):
            rec["summaryType"] = "official"
            rec["caseName"] = (fetched.get('pageTitle') or rec["caseName"]).strip()
            secs = fetched['sections']
            full = []
            in_full = False
            for s in secs:
                h = norm_heading(s.get('heading'))
                t = (s.get('text') or '').strip()
                if h == '판시사항':
                    rec["issues"] = split_items(t)
                elif h in ('판결요지', '결정요지'):
                    rec["holdings"] = split_items(t)
                    rec["holdingLabel"] = '결정요지' if h == '결정요지' else '판결요지'
                elif h == '심판대상조문':
                    rec["subjectStatutes"] = split_lines(t)
                elif h == '참조조문':
                    rec["statutes"] = split_lines(t)
                elif h == '참조판례':
                    rec["precedents"] = split_lines(t)
                elif h == '전문':
                    in_full = True
                    if t:
                        full.append({"heading": "[전문]", "text": t})
                else:
                    in_full = True
                    full.append({"heading": (s.get('heading') or '').strip(), "text": t})
            rec["fullText"] = brackets(full) if full else None
            bench, dtype, citation, short = parse_citation(fetched.get('citation'), court, rec["decisionDate"], case_number, is_enbanc, rec['decisionType'])
            rec["bench"], rec["decisionType"], rec["citation"], rec["citeShort"] = bench, dtype, citation, short
            rec["source"] = {"label": "국가법령정보센터", "url": fetched.get('sourceUrl') or fetched.get('url') or ''}
        else:
            rec["summaryType"] = "editorial"
            bench, dtype, citation, short = parse_citation('', court, rec["decisionDate"], case_number, is_enbanc, rec['decisionType'])
            rec["bench"], rec["decisionType"], rec["citation"], rec["citeShort"] = bench, dtype, citation, short
            lg = c.get('lawgo') or {}
            if lg.get('seq'):
                rec["source"] = {"label": "국가법령정보센터", "url": f"https://www.law.go.kr/LSW/{'precInfoP' if lg.get('kind') == 'prec' else 'detcInfoP'}.do?{'precSeq' if lg.get('kind') == 'prec' else 'detcSeq'}={lg['seq']}"}
        official_fields = {key: copy.deepcopy(rec[key]) for key in STANDARD_FIELDS}
        apply_source_precedence(rec, standard_by_decision.get(rec['decisionId'], {}), official_fields, ed)
        stats[rec['summaryType']] += 1
        rec["result"] = derive_result(fetched, {'result': c.get('result', '')})
        if rec["fullText"]:
            stats["fullText"] += 1
        cases.append(rec)

    # order: by group order, then subject order, then tocPath, then date
    gi = {g["id"]: i for i, g in enumerate(GROUPS)}
    si = {s["id"]: i for i, s in enumerate(SUBJECTS)}
    cases.sort(key=lambda r: (gi[r["group"]], si.get(r["subject"], 9), r["tocPath"], r["decisionDate"]))

    # 법률신문 주요판례 페이지: 연도 버튼(최신 → 과거)과 분야 구분(tools/subjects.py 의 ANNUAL_FIELDS 순서)
    years_in = [r["annual"]["year"] for r in cases if r["annual"] and isinstance(r["annual"].get("year"), int)]
    y_from, y_to = min([ANNUAL_YEARS[0]] + years_in), max([ANNUAL_YEARS[1]] + years_in)
    annual = {"years": list(range(y_to, y_from - 1, -1)),
              "fields": [{"id": f["id"], "label": f["label"], "sub": f["sub"], "subject": f["subject"]} for f in ANNUAL_FIELDS]}
    # 헌법재판소 주요결정·대법원 전원합의체 페이지: 과목 칩 아래 선고연도 탭(최신 → 과거; 범위는 tools/subjects.py)
    page_years = lambda page: [int(r["decisionDate"][:4]) for r in cases if r["page"] == page and r["decisionDate"][:4].isdigit()]  # noqa: E731
    year_tabs = {"ccourt": make_year_tabs(page_years('ccourt'), CCOURT_YEARS),
                 "enbanc": make_year_tabs(page_years('enbanc'), ENBANC_YEARS, ENBANC_FROM)}

    data = {
        "meta": {
            "title": "판례집",
            "built": datetime.date.today().isoformat(),
            "note": "학습용 항목은 검증된 표준판례를 우선합니다. 공식 전문과 출처별 원문은 별도로 보존합니다.",
            "schemaVersion": 2,
            "count": len(cases),
            "stats": stats,
        },
        "pages": PAGES,
        "groups": GROUPS,
        "subjects": SUBJECTS,
        "annual": annual,
        "yearTabs": year_tabs,
        "toc": TOC,
        "cases": cases,
        "identityAliases": {**(reg.get('identityAliases') or {}),
                            **{c['id']: c['decisionId'] for c in cases}},
    }
    Path(OUT).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    size = os.path.getsize(OUT)
    print(f"wrote {OUT}: {len(cases)} cases, {size/1024:.0f} KB, stats={stats}")


if __name__ == '__main__':
    build()
