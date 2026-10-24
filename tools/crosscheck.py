#!/usr/bin/env python3
"""표준판례 후보(standardSource) ↔ law.go.kr 공식 수집본 교차검증 (파이프라인 단계 5).

  python -X utf8 tools/crosscheck.py --subject 상법 [--candidates <path>] [--threshold 0.6]
         [--root <저장소>] [--registry <registry.json>] [--fetched-dir <fetched>] [--out <_crosscheck.json>]

후보 파일(data/standard-cases/<과목>/candidates-<subject>.json)에서 standardSource 가 있는 항목마다
  1) case_identity.identity 로 decisionId 를 계산해 등록부(data/registry.json)의 사건과 맞추고
     (identityAliases 를 거친 decisionId → 실패하면 대표 사건번호로 찾아 '메타 불일치' 후보로 본다),
  2) 등록부 id 의 공식 수집본 data/fetched/<id>.json 을 읽어
     【판결요지】/【결정요지】 ↔ standardSource.holdings, 【판시사항】 ↔ standardSource.issues 를
     정규화(pdf2md_lib.normalize 가 있으면 그것, 없으면 같은 규칙의 자체 구현) 뒤 difflib 비율과 부분 문자열 여부로 비교하고,
  3) 사건번호·선고일·법원·판결/결정·전원합의체를 후보 ↔ 등록부 ↔ 공식 인용문([대법원 2022. 5. 26. 선고 … 판결])으로 대조한다.
결과는 <과목폴더>/_crosscheck.json 과 콘솔 요약(flag 별 건수, low-similarity 하위 10건).

flag: ok | low-similarity(유사도 < 기준이고 부분 문자열도 아님) | meta-mismatch(사건번호·선고일·법원 등 불일치) | missing(미등록·미수집 — 건너뜀)
이 스크립트는 판정하지 않는다. low-similarity·meta-mismatch 는 상위 모델·사람이 판정해 _review.jsonl 에 남긴다.
등록부·fetched·후보 파일은 읽기만 한다. 종료코드는 입력 파일을 읽지 못할 때만 0 이 아니다.
"""
import argparse
import datetime
import difflib
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import case_identity as ci  # noqa: E402
from casenum import CASE_RE, DATE_RE, norm_date  # noqa: E402
import subjects  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_THRESHOLD = 0.6
FLAGS = ('ok', 'low-similarity', 'meta-mismatch', 'missing')
HOLDING_HEADINGS = {'판결요지', '결정요지'}
ISSUE_HEADINGS = {'판시사항'}

# ── 정규화 ───────────────────────────────────────────────────────────────
# 공통 계약: NFKC → 필러(U+FFA0·U+3164·NBSP 등)를 공백으로 → 모든 공백 제거 → 【】〖〗 는 [], 〈〉《》「」『』 는 제거
# → 전각 숫자·구두점 반각화(NFKC) → 하이픈류 통일. tools/pdf2md_lib.py 가 생기면 그 normalize 를 쓴다.
_FILLER_RE = re.compile('[ ᅟᅠㅤﾠ -​  　﻿]')
_WS_RE = re.compile(r'\s+')
_BRACKETS = str.maketrans({'【': '[', '】': ']', '〖': '[', '〗': ']',
                           '〈': None, '〉': None, '《': None, '》': None,
                           '「': None, '」': None, '『': None, '』': None})
_HYPHENS = str.maketrans({c: '-' for c in '‐‑‒–—―−﹘﹣－'})
# 교차검증 전용 추가 접기: 출처마다 다른 가운뎃점(공식 원문 'ㆍ' U+318D → NFKC 후 U+119E, PDF '·')과 굽은 따옴표.
# 대조 게이트(md_validate)가 아니라 서로 다른 두 출처의 유사도를 재는 단계이므로 표기 차이만 접는다.
_DOTS = str.maketrans({c: '·' for c in '·‧∙⋅・･ㆍᆞ'})
_QUOTES = str.maketrans({'‘': "'", '’': "'", '‚': "'", '‛': "'",
                         '“': '"', '”': '"', '„': '"', '‟': '"'})

try:  # 단계 2 공용 라이브러리가 있으면 같은 정규화를 쓴다
    from pdf2md_lib import normalize as _lib_normalize  # type: ignore
except Exception:  # noqa: BLE001 — 없거나 깨졌으면 자체 구현
    _lib_normalize = None


def base_normalize(text):
    """공통 계약 정규화(자체 구현)."""
    t = _FILLER_RE.sub(' ', text or '')
    t = unicodedata.normalize('NFKC', t)
    t = _FILLER_RE.sub(' ', t)
    t = _WS_RE.sub('', t)
    return t.translate(_BRACKETS).translate(_HYPHENS)


def normalizer_name():
    return 'pdf2md_lib' if _lib_normalize else 'crosscheck'


def normalize(text):
    """공통 정규화 + 교차검증용 가운뎃점·따옴표 접기."""
    base = None
    if _lib_normalize:
        try:
            base = _lib_normalize(text or '')
        except Exception:  # noqa: BLE001
            base = None
    if not isinstance(base, str):
        base = base_normalize(text)
    base = _WS_RE.sub('', _FILLER_RE.sub('', base))
    return base.translate(_DOTS).translate(_QUOTES)


def digits(norm_text):
    return re.findall(r'\d+', norm_text or '')


def heading_key(heading):
    """'【판결요지】'·'[판결 요지]'·'【주　　문】' → '판결요지'·'주문'."""
    t = unicodedata.normalize('NFKC', heading or '')
    t = _WS_RE.sub('', _FILLER_RE.sub('', t))
    return re.sub(r'[\[\]【】〖〗()<>〈〉]', '', t)


# ── 텍스트 비교 ──────────────────────────────────────────────────────────
_MARK_RE = re.compile(r'\[(\d{1,2})\]')


def split_numbered(norm_text):
    """정규화 텍스트를 [1] [2] … 표지(1부터 차례로 나오는 것만)에서 나눈다 → [(라벨, 조각)]. 표지가 둘 미만이면 []."""
    marks, expect = [], 1
    for m in _MARK_RE.finditer(norm_text):
        if int(m.group(1)) == expect:
            marks.append(m)
            expect += 1
    if len(marks) < 2:
        return []
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(norm_text)
        out.append((f'[{m.group(1)}]', norm_text[m.start():end]))
    return out


def best_window(std_norm, official_norm):
    """공식 텍스트 전체 또는 번호 항목의 연속 구간 중 표준 텍스트와 difflib 비율이 가장 높은 창 → (비율, 라벨, 창 텍스트).
    표준판례가 공식 요지의 일부 항목만 싣는 경우([2]만 등)를 공정하게 재기 위한 것."""
    windows = [('전체', official_norm)]
    segs = split_numbered(official_norm)
    for i in range(len(segs)):
        for j in range(i, len(segs)):
            text = ''.join(s for _, s in segs[i:j + 1])
            if text == official_norm:
                continue
            label = segs[i][0] if i == j else f'{segs[i][0]}-{segs[j][0]}'
            windows.append((label, text))
    for label, text in windows:   # 같은 글이면 difflib(긴 글에서 느림)을 돌리지 않는다
        if text == std_norm:
            return 1.0, label, text
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(std_norm)
    best = (-1.0, '전체', official_norm)
    for label, text in windows:
        sm.set_seq1(text)
        if sm.real_quick_ratio() <= best[0] or sm.quick_ratio() <= best[0]:
            continue
        r = sm.ratio()
        if r > best[0]:
            best = (r, label, text)
    return (max(best[0], 0.0),) + best[1:]


def joined_items(items):
    """standardSource 의 [{n, text}] → 번호를 앞에 붙여 이은 정규화 텍스트와 항목별 정규화 텍스트."""
    parts, texts = [], []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        n, text = normalize(it.get('n') or ''), normalize(it.get('text') or '')
        if not text:
            continue
        texts.append(text)
        parts.append(text if (not n or text.startswith(n)) else n + text)
    return ''.join(parts), texts


def official_text(fetched, headings):
    """fetched sections 중 해당 머리글의 비어 있지 않은 본문(중복 제거, 등장 순)을 이어 붙인 원문."""
    seen, out = set(), []
    for sec in (fetched or {}).get('sections') or []:
        if heading_key(sec.get('heading')) in headings:
            text = (sec.get('text') or '').strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return '\n'.join(out)


def compare_text(items, official_raw):
    """표준판례 항목 배열 vs 공식 원문 → 비교 결과 dict (공식 원문이나 표준 텍스트가 없으면 None)."""
    std_norm, item_texts = joined_items(items)
    off_norm = normalize(official_raw)
    if not std_norm or not off_norm:
        return None
    ratio, label, window = best_window(std_norm, off_norm)
    contained_items = sum(1 for t in item_texts if t in off_norm)
    return {
        'ratio': round(ratio, 4),
        'window': label,
        'contained': std_norm in off_norm,
        'itemsContained': f'{contained_items}/{len(item_texts)}',
        'allItemsContained': contained_items == len(item_texts),
        'digitsOk': digits(std_norm) == digits(window),
        'stdChars': len(std_norm),
        'officialChars': len(off_norm),
    }


def similar_enough(result, threshold):
    return result['contained'] or result['allItemsContained'] or result['ratio'] >= threshold


# ── 메타(사건번호·선고일·법원) ───────────────────────────────────────────
_CC_ALIASES = ('전원재판부', '지정재판부', '헌법재판소', '헌재')
_COURT_ALIASES = {'대판': '대법원', '대결': '대법원'}


def compact(s):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', s or ''))


def parse_citation(citation):
    """'[대법원 2022. 5. 26. 선고 2022다200249 판결]'·'[전원재판부 2020헌마1134, 2026. 7. 23.]' →
    {court, date, caseNumbers, decisionType, enBanc}. 해석하지 못한 칸은 None."""
    s = unicodedata.normalize('NFKC', citation or '').strip()
    s = re.sub(r'^[\[【(]\s*|\s*[\]】)]$', '', s)
    if not s:
        return None
    out = {'court': None, 'date': None, 'caseNumbers': [], 'decisionType': None, 'enBanc': '전원합의체' in s}
    d = DATE_RE.search(s)
    if d:
        try:
            out['date'] = datetime.date.fromisoformat(norm_date(*d.groups())).isoformat()
        except ValueError:
            out['date'] = None
    head = (s[:d.start()] if d else s).strip(' ,')
    if any(head.startswith(a) for a in _CC_ALIASES):
        out['court'] = '헌법재판소'
    elif head:
        name = _COURT_ALIASES.get(compact(head), head)
        known = [c for c in ci.COURTS if compact(c) == compact(name)]
        out['court'] = known[0] if known else None
        out['courtRaw'] = head
    out['caseNumbers'] = [f'{m.group(1)}{m.group(2)}{m.group(3)}' for m in CASE_RE.finditer(s)]
    tail = s[d.end():] if d else s
    if '결정' in tail:
        out['decisionType'] = '결정'
    elif '판결' in tail:
        out['decisionType'] = '판결'
    elif out['court'] == '헌법재판소':
        out['decisionType'] = '결정'
    return out


def primary(number):
    try:
        return ci.primary_case_number(number)
    except (ValueError, TypeError):
        return compact(re.split(r'[·,;/]|등', compact(number or ''), maxsplit=1)[0]) or None


def _field(cand, reg, off, required=True):
    vals = [v for v in (cand, reg, off) if v is not None]
    ok = all(v == vals[0] for v in vals) if len(vals) >= 2 else None
    if required and cand is None and (reg is not None or off is not None):
        ok = False
    return {'candidate': cand, 'registry': reg, 'official': off, 'ok': ok}


def meta_match(cand, cand_type, reg, citation):
    """후보 ↔ 등록부 ↔ 공식 인용문 대조. reg 가 None 이면 None."""
    if reg is None:
        return None
    off = parse_citation(citation) if citation else None
    cand_no, reg_no = primary(cand.get('lookupKey') or cand.get('caseNumber')), primary(reg.get('lookupKey') or reg.get('caseNumber'))
    case_ok = cand_no is not None and cand_no == reg_no
    if off and off['caseNumbers']:
        case_ok = case_ok and cand_no in off['caseNumbers']
    court = lambda v: compact(v) or None  # noqa: E731
    out = {
        'citation': citation or None,
        'caseNumber': {'candidate': cand_no, 'registry': reg_no, 'official': (off or {}).get('caseNumbers') or None, 'ok': case_ok},
        'date': _field(cand.get('date') or cand.get('decisionDate') or None, reg.get('decisionDate') or None, (off or {}).get('date')),
        'court': _field(court(cand.get('court')), court(reg.get('court')), court((off or {}).get('court'))),
        'decisionType': _field(cand_type, reg.get('decisionType') or None, (off or {}).get('decisionType'), required=False),
        'enBanc': _field(bool(cand.get('enBanc')), bool(reg.get('enBanc')), off['enBanc'] if off else None, required=False),
    }
    if off and off.get('court') is None and off.get('courtRaw'):
        out['court']['officialRaw'] = off['courtRaw']
    checks = [out[k]['ok'] for k in ('caseNumber', 'date', 'court', 'decisionType', 'enBanc')]
    out['ok'] = False if False in checks else True
    out['officialParsed'] = off is not None
    return out


# ── 입력 ────────────────────────────────────────────────────────────────
def read_json(path):
    with open(path, encoding='utf-8') as src:
        return json.load(src)


def candidate_identity(c):
    """후보 → (decisionId, decisionType, 오류문). 법원 불명 등으로 계산할 수 없으면 decisionId None."""
    dtype = c.get('decisionType') if c.get('decisionType') in ('판결', '결정') else None
    record = {'court': c.get('court'), 'caseNumber': c.get('caseNumber') or '', 'lookupKey': c.get('lookupKey'),
              'decisionDate': c.get('date') or c.get('decisionDate') or '', 'decisionType': dtype}
    if c.get('courtId'):
        record['courtId'] = c['courtId']
    try:
        ident = ci.identity(record)
        return ident['decisionId'], ident['decisionType'], None
    except (ValueError, KeyError, TypeError) as exc:
        return None, dtype, str(exc)


class Registry:
    def __init__(self, registry, fetched_dir):
        self.fetched_dir = fetched_dir
        self.cases = registry.get('cases') or []
        self.aliases = registry.get('identityAliases') or {}
        self.by_decision, self.by_number = {}, {}
        for c in self.cases:
            did = c.get('decisionId')
            if not did:
                try:
                    did = ci.identity(c, self.citation(c['id']))['decisionId']
                except (ValueError, KeyError, TypeError):
                    did = None
            if did:
                self.by_decision.setdefault(did, []).append(c)
            no = primary(c.get('lookupKey') or c.get('caseNumber'))
            if no:
                self.by_number.setdefault(no, []).append(c)

    def fetched_path(self, cid):
        return os.path.join(self.fetched_dir, cid + '.json')

    def fetched(self, cid):
        path = self.fetched_path(cid)
        if not os.path.isfile(path):
            return None
        try:
            return read_json(path)
        except (OSError, ValueError):
            return None

    def citation(self, cid):
        return (self.fetched(cid) or {}).get('citation') or ''

    def missing_reason(self, cid):
        path = os.path.join(self.fetched_dir, cid + '.missing.json')
        if not os.path.isfile(path):
            return ''
        try:
            return (read_json(path).get('reason') or '')[:120]
        except (OSError, ValueError):
            return '(.missing.json 읽기 실패)'

    def match(self, decision_id, number, subject):
        """→ (선택한 등록 사건, 같은 재판으로 본 등록 id 들, matchedBy)."""
        did = decision_id
        if did and did not in self.by_decision and isinstance(self.aliases.get(did), str):
            did = self.aliases[did]
        found, how = (self.by_decision.get(did) or [], 'decisionId' if did == decision_id else 'alias') if did else ([], None)
        if not found and number:
            found, how = self.by_number.get(number) or [], 'caseNumber'
        if not found:
            return None, [], None

        def rank(c):
            return (os.path.isfile(self.fetched_path(c['id'])) is False,
                    not (c.get('group') == 'standard' and c.get('subject') == subject))
        chosen = sorted(found, key=rank)[0]
        return chosen, [c['id'] for c in found], how


def load_issue_origins(folder):
    """entries.jsonl 이 있으면 seq → '판시사항'|'쟁점' (판시사항이 없고 쟁점이 있으면 issues 는 쟁점에서 온 것)."""
    path = os.path.join(folder, 'entries.jsonl')
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding='utf-8') as src:
        for line in src:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            secs = e.get('sections') or {}
            empty = lambda v: not (v or '').strip() or (v or '').strip() in ('(없음)', '없음')  # noqa: E731
            if e.get('seq') is not None:
                out[e['seq']] = '쟁점' if empty(secs.get('판시사항')) and not empty(secs.get('쟁점')) else '판시사항'
    return out


# ── 본체 ────────────────────────────────────────────────────────────────
def check_candidate(c, reg, subject, threshold, issue_origins):
    src = c.get('standardSource') or {}
    decision_id, cand_type, id_error = candidate_identity(c)
    number = primary(c.get('lookupKey') or c.get('caseNumber'))
    chosen, ids, how = reg.match(decision_id, number, subject)
    item = {'seq': c.get('seq'), 'no': c.get('no'), 'chunk': c.get('chunk'), 'caseNumber': c.get('caseNumber'),
            'status': c.get('status'), 'verified': src.get('verified') is True,
            'decisionId': decision_id, 'registryId': chosen['id'] if chosen else None, 'registryIds': ids, 'matchedBy': how,
            'registryDecisionId': (chosen or {}).get('decisionId'),
            'fetched': False, 'fetchedId': None,
            'holdingsRatio': None, 'holdingsContained': None, 'holdingsWindow': None, 'holdingsItemsContained': None, 'holdingsDigitsOk': None,
            'issuesRatio': None, 'issuesContained': None, 'issuesFrom': issue_origins.get(c.get('seq')),
            'metaMatch': None, 'textCompared': False, 'flag': None, 'reasons': []}
    reasons = item['reasons']
    if id_error:
        reasons.append(f'decisionId 계산 불가: {id_error}')
    if chosen is None:
        item['flag'] = 'missing'
        reasons.append('미등록: 등록부에 같은 decisionId·대표 사건번호가 없음')
        return item
    if how == 'caseNumber':
        reasons.append(f'decisionId 불일치: 후보 {decision_id} / 등록부 {chosen.get("decisionId")} ({chosen["id"]})')
    fetched_id = next((i for i in [chosen['id']] + ids if os.path.isfile(reg.fetched_path(i))), None)
    fetched = reg.fetched(fetched_id) if fetched_id else None
    item['metaMatch'] = meta_match(c, cand_type, chosen, (fetched or {}).get('citation'))
    if fetched is None:
        item['flag'] = 'missing'
        why = reg.missing_reason(chosen['id'])
        reasons.append(f'미수집: fetched/{chosen["id"]}.json 없음' + (f' (.missing: {why})' if why else ''))
        return item
    item['fetched'], item['fetchedId'] = True, fetched_id

    meta = item['metaMatch']
    if not meta['officialParsed']:
        reasons.append('공식 인용문 해석 불가 — 등록부와만 대조')
    if meta['court'].get('officialRaw'):
        reasons.append(f'공식 인용문의 법원명 해석 불가: {meta["court"]["officialRaw"]} — 등록부와만 대조')
    for key in ('caseNumber', 'date', 'court', 'decisionType', 'enBanc'):
        f = meta[key]
        if f['ok'] is False:
            reasons.append(f'{key} 불일치: 후보 {f["candidate"]} / 등록부 {f["registry"]} / 공식 {f["official"]}')
    meta_bad = meta['ok'] is False or how == 'caseNumber'

    holdings = compare_text(src.get('holdings'), official_text(fetched, HOLDING_HEADINGS))
    issues = compare_text(src.get('issues'), official_text(fetched, ISSUE_HEADINGS))
    if holdings:
        item.update({'holdingsRatio': holdings['ratio'], 'holdingsContained': holdings['contained'], 'holdingsWindow': holdings['window'],
                     'holdingsItemsContained': holdings['itemsContained'], 'holdingsDigitsOk': holdings['digitsOk']})
        if not holdings['digitsOk'] and not holdings['contained']:
            reasons.append(f'판결요지 숫자열 다름(창 {holdings["window"]})')
    elif src.get('holdings'):
        reasons.append('공식 판결요지·결정요지 없음 — 판결요지 비교 불가')
    if issues:
        item.update({'issuesRatio': issues['ratio'], 'issuesContained': issues['contained']})
    elif src.get('issues'):
        reasons.append('공식 판시사항 없음 — 판시사항 비교 불가')

    # 판결요지가 있으면 그것으로, 없으면 판시사항으로 판단(issues 가 쟁점에서 온 것이면 공식 판시사항과 다른 글이므로 판단 근거로 쓰지 않음)
    basis = holdings or (issues if item['issuesFrom'] != '쟁점' else None)
    low = False
    if basis:
        item['textCompared'] = True
        low = not similar_enough(basis, threshold)
        name = '판결요지' if holdings else '판시사항'
        if low:
            reasons.append(f'{name} 유사도 {basis["ratio"]:.3f} < {threshold} (창 {basis["window"]}, 부분 문자열 아님)')
    else:
        reasons.append('텍스트 비교 불가 — 메타만 대조' + (' (issues 가 쟁점에서 옴)' if issues else ''))
    if holdings and issues and not similar_enough(issues, threshold):
        origin = item['issuesFrom']
        reasons.append(f'판시사항 유사도 {issues["ratio"]:.3f} 낮음' + (' (issues 가 쟁점에서 옴 — 차이 예상)' if origin == '쟁점'
                                                                    else ' (issues 가 쟁점에서 왔을 수 있음)' if origin is None else ''))
    item['flag'] = 'meta-mismatch' if meta_bad else ('low-similarity' if low else 'ok')
    return item


def run(subject, candidates_path, registry_path, fetched_dir, out_path, threshold=DEFAULT_THRESHOLD, folder=None, root=ROOT):
    """교차검증을 수행하고 결과 dict 를 out_path 에 쓴 뒤 반환한다."""
    sid = subjects.resolve_standard(subject)
    data = read_json(candidates_path)
    reg = Registry(read_json(registry_path), fetched_dir)
    origins = load_issue_origins(folder or os.path.dirname(os.path.abspath(candidates_path)))
    cands = data.get('candidates') or []
    items = [check_candidate(c, reg, sid, threshold, origins) for c in cands if c.get('standardSource')]
    counts = {f: sum(1 for it in items if it['flag'] == f) for f in FLAGS}
    result = {
        'subject': sid,
        'generatedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'threshold': threshold,
        'normalizer': normalizer_name(),
        'inputs': {'candidates': rel(candidates_path, root), 'registry': rel(registry_path, root), 'fetchedDir': rel(fetched_dir, root)},
        'items': items,
        'totals': {'candidates': len(cands), 'withStandardSource': len(items), **counts,
                   'textNotCompared': sum(1 for it in items if it['fetched'] and not it['textCompared'])},
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as dst:
        json.dump(result, dst, ensure_ascii=False, indent=1)
        dst.write('\n')
    os.replace(tmp, out_path)
    return result


def rel(path, root=ROOT):
    try:
        return os.path.relpath(path, root).replace(os.sep, '/')
    except ValueError:
        return path


def summary(result, out_path, limit=10):
    t = result['totals']
    lines = [f'[crosscheck] {subjects.label_of(result["subject"])}({result["subject"]}) — 후보 {t["candidates"]}건 중 '
             f'standardSource {t["withStandardSource"]}건, 기준 {result["threshold"]}, 정규화 {result["normalizer"]}',
             '  ' + ' · '.join(f'{f} {t[f]}' for f in FLAGS) + f' (수집됐으나 텍스트 비교 불가 {t["textNotCompared"]})']
    low = sorted((it for it in result['items'] if it['flag'] == 'low-similarity'),
                 key=lambda it: (it['holdingsRatio'] if it['holdingsRatio'] is not None else it['issuesRatio'] or 0))
    if low:
        lines.append(f'  low-similarity 하위 {min(limit, len(low))}건(유사도 낮은 순):')
        for it in low[:limit]:
            r = it['holdingsRatio'] if it['holdingsRatio'] is not None else it['issuesRatio']
            lines.append(f'    seq {it["seq"]} no {it["no"]} {it["caseNumber"]}  유사도 {r:.3f} 창 {it["holdingsWindow"] or "-"}  등록부 {it["registryId"]}')
    meta = [it for it in result['items'] if it['flag'] == 'meta-mismatch']
    if meta:
        lines.append(f'  meta-mismatch {len(meta)}건' + (f'(앞 {limit}건)' if len(meta) > limit else '') + ':')
        for it in meta[:limit]:
            why = next((r for r in it['reasons'] if '불일치' in r), it['reasons'][0] if it['reasons'] else '')
            lines.append(f'    seq {it["seq"]} no {it["no"]} {it["caseNumber"]}  {why}')
    lines.append(f'  → {out_path}')
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='표준판례 standardSource ↔ 공식 수집본 교차검증 → _crosscheck.json')
    ap.add_argument('--subject', required=True, help='과목 id 또는 한글명(헌법·행정법·민법·형법·상법)')
    ap.add_argument('--candidates', help='후보 파일(기본: data/standard-cases/<과목>/candidates-<subject>.json)')
    ap.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD, help='low-similarity 기준 difflib 비율(기본 0.6)')
    ap.add_argument('--root', default=ROOT, help='저장소 루트(기본: 이 스크립트의 상위 폴더)')
    ap.add_argument('--registry', help='등록부(기본: <root>/data/registry.json)')
    ap.add_argument('--fetched-dir', help='공식 수집본 폴더(기본: <root>/data/fetched)')
    ap.add_argument('--out', help='출력(기본: <과목폴더>/_crosscheck.json)')
    a = ap.parse_args(argv)
    try:
        sid = subjects.resolve_standard(a.subject)
    except ValueError as exc:
        ap.error(str(exc))
    if not 0 < a.threshold <= 1:
        ap.error('--threshold 는 0 초과 1 이하')
    folder = os.path.join(a.root, 'data', 'standard-cases', subjects.BY_ID[sid]['folder'])
    cand_path = a.candidates or os.path.join(folder, f'candidates-{sid}.json')
    reg_path = a.registry or os.path.join(a.root, 'data', 'registry.json')
    fetched_dir = a.fetched_dir or os.path.join(a.root, 'data', 'fetched')
    out_path = a.out or os.path.join(folder, '_crosscheck.json')
    for path, what in ((cand_path, '후보 파일'), (reg_path, '등록부')):
        if not os.path.isfile(path):
            print(f'[crosscheck] {what}이 없습니다: {path}', file=sys.stderr)
            return 2
    if not os.path.isdir(fetched_dir):
        print(f'[crosscheck] 경고: 공식 수집본 폴더가 없습니다(모두 missing 처리): {fetched_dir}', file=sys.stderr)
    try:
        result = run(sid, cand_path, reg_path, fetched_dir, out_path, a.threshold, folder, a.root)
    except (OSError, ValueError) as exc:
        print(f'[crosscheck] 입력을 읽지 못했습니다: {exc}', file=sys.stderr)
        return 2
    print(summary(result, out_path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
