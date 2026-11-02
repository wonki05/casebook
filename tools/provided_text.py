#!/usr/bin/env python3
"""law.go.kr 미게재 사건의 사용자 제공 판결문 텍스트를 data/fetched/<id>.json 으로 보존한다 (data/schema.md §3 의 예외 규정).

  python -X utf8 tools/provided_text.py parse  --raw raw.txt --out spec.json [--mode casenote|plain] [--cut cut.txt]
         [--citation "[대법원 1970. 3. 10. 선고 69도2285 판결]" --title 사건명]   (plain 은 머리글이 없어 둘 다 필요)
  python -X utf8 tools/provided_text.py import --id std-criminal-91 --spec spec.json [--force]

parse : 판례 검색 사이트(케이스노트)에서 복사한 텍스트(casenote) 또는 표 없는 판결문 텍스트(plain)에서 판결 본문
        (판시사항·판결요지·참조조문·참조판례·사건 표·주문·이유·재판부 서명)만 골라 spec 을 만든다. 머리글 앞의 안내·이용자 정보와
        '많이 하이라이트된 문장 표시' 이하(소송경과·인용판례·유사판례·주석서·인용 문헌·회사 정보)는 버리고 --cut 파일에 남긴다.
        글자는 바꾸지 않는다 — 빈 줄·줄 끝 공백을 정리하고, 표로 줄바꿈된 재판부 서명을 한 사람 한 줄로 합칠 뿐이다.
        원문과 spec 의 글자가 한 글자도 어긋나지 않는지(공백 제외) 스스로 대조해 어긋나면 중단한다.
import: spec 을 검증(등록부의 법원·선고일·유형·사건번호·전원합의체와 인용문 일치, 사이트 부가정보 문구 없음, 출처 필드 기록)한 뒤
        fetched/<id>.json 으로 쓰고 .missing.json 을 지운다. law.go.kr 공식 수집본이 있으면 --force 없이는 덮어쓰지 않는다.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fetch_unit  # noqa: E402  (check_record: 인용문 ↔ 등록부 메타 대조)

REG = os.path.join(ROOT, 'data', 'registry.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')

SECTION_HEADS = {'판시사항': '【판시사항】', '판결요지': '【판결요지】', '결정요지': '【결정요지】', '참조조문': '【참조조문】', '참조판례': '【참조판례】'}
PLAIN_LABELS = {'사건', '피고인', '상고인', '변호인', '원판결', '원심판결', '판결선고'}
ROLES = {'재판장', '주심', '대법관', '대법원장'}
NAME_RE = re.compile(r'^[가-힣]{2,4}$')
HEADER_RE = re.compile(r'^(?P<court>\S+) (?P<date>\d{4}\. \d{1,2}\. \d{1,2}\.) 선고 (?P<nums>.+?) (?:(?P<bench>전원합의체) )?(?P<type>판결|결정) (?P<tail>\[.*)$')
TAIL_RE = re.compile(r'^\[(?P<title>.*?)\](?: \[(?P<gong>[^\[\]]*)\])?$')
CHROME = ('많이 하이라이트된 문장 표시', '주식회사 엘박스', '케이스노트', '인용판례', '유사판례', '주석서에서', '문헌에서 인용', '소송경과',
          '개인정보처리방침', '통신판매업신고', '사업자등록번호', '기관:', 'help@', '영리목적으로 이용', '인터넷열람 사이트에서 열람')
CASENOTE_LABEL = '판례 검색 사이트(케이스노트) 수록본 · 사용자 제공'
BREAK_RE = re.compile(r'^[고며서면로을를은는와과] ')  # 쪽 나눔 등으로 낱말 중간에서 끊긴 줄의 시작(문단 첫머리가 될 수 없는 조사·어미)
END_RE = re.compile(r'[.)\]’”"\'?!。:;]$')


def compact(s):
    return re.sub(r'\s+', '', s or '')


def norm_text(s):
    return re.sub(r'\s+', '', s or '')


def is_row_label(line):
    c = compact(line)
    return '\t' in line and 0 < len(c) <= 12


def is_body_head(line):
    s = line.strip()
    return compact(s) in ('주문', '이유') and len(s) <= 4


def split_signature(lines):
    """끝의 재판부 서명(역할어와 이름이 줄마다 갈라진 표)을 찾아 (본문 줄들, 서명 줄들) 로 나눈다. 없으면 (lines, [])."""
    toks = [(i, l.strip()) for i, l in enumerate(lines) if l.strip()]
    start = len(toks)
    while start > 0 and (toks[start - 1][1] in ROLES or NAME_RE.match(toks[start - 1][1])):
        start -= 1
    while start < len(toks) and toks[start][1] not in ROLES:
        start += 1
    if start >= len(toks):
        return lines, []
    entries, roles = [], []
    for _, t in toks[start:]:
        if t in ROLES:
            roles.append(t)
        else:
            if not roles:
                return lines, []
            entries.append(' '.join(roles + [t]))
            roles = []
    if roles:
        return lines, []
    return lines[:toks[start][0]], entries


def parse(raw, mode='casenote'):
    """-> (spec 조각 {citation,pageTitle,sourceHeader,sections}, cut {'pre':[…],'post':[…]}, warnings)"""
    lines = [l for l in raw.replace('\r', '').split('\n') if not re.match(r'^\s*</?pasted_content\b', l)]
    warnings, head, header_line = [], None, ''
    if mode == 'casenote':
        h = next((i for i, l in enumerate(lines) if HEADER_RE.match(l.strip())), None)
        if h is None:
            raise ValueError('머리글("대법원 2012. 8. 17. 선고 … 판결 […]")을 찾지 못했습니다')
        e = next((i for i, l in enumerate(lines) if '많이 하이라이트된 문장 표시' in l), len(lines))
        head, header_line = HEADER_RE.match(lines[h].strip()), lines[h].strip()
        pre, body, post = lines[:h], lines[h + 1:e], lines[e:]
    else:
        pre, body, post = [], lines, []
    sections, cur = [], None
    for l in body:
        s, c = l.strip(), compact(l)
        heading = None
        if mode == 'casenote':
            if is_row_label(l):
                heading = '【%s】' % c
            elif c in SECTION_HEADS and s == c:
                heading = SECTION_HEADS[c]
            elif is_body_head(l):
                heading = '【%s】' % compact(s)
        elif c in PLAIN_LABELS | {'주문', '이유'} and len(s) <= 6:
            heading = '【%s】' % c
        if heading:
            cur = [heading, []]
            sections.append(cur)
        elif cur is None:
            if s:
                cur = ['【전문】', [l]]
                sections.append(cur)
        else:
            cur[1].append(l)
    out = []
    for heading, ls in sections:
        if heading == '【이유】':
            ls, sig = split_signature(ls)
        else:
            sig = []
        merged = []
        for x in (x.strip() for x in ls if x.strip()):
            if merged and BREAK_RE.match(x) and not END_RE.search(merged[-1]):
                warnings.append(f'JOIN {heading}: 쪽 나눔으로 끊긴 낱말을 이었음 — "{merged[-1][-16:]}" + "{x[:16]}"')
                merged[-1] += x
            else:
                merged.append(x)
        out.append({'heading': heading, 'text': '\n'.join(merged + sig)})
    names = [s['heading'] for s in out]
    if '【주문】' not in names or '【이유】' not in names:
        warnings.append('주문 또는 이유 구역이 없습니다')
    # 원문 ↔ spec 글자 대조: 표 머리·구역 제목을 뺀 원문 줄과 spec 본문이 공백을 빼면 같아야 한다
    kept = ''.join(norm_text(l) for l in body if l.strip() and not (mode == 'casenote' and (is_row_label(l) or compact(l) in SECTION_HEADS and l.strip() == compact(l)))
                   and not (compact(l) in ('주문', '이유') and len(l.strip()) <= 4)
                   and not (mode == 'plain' and compact(l) in PLAIN_LABELS and len(l.strip()) <= 6))
    if kept != ''.join(norm_text(s['text']) for s in out):
        raise ValueError('원문과 정제본의 글자가 어긋납니다(공백 제외) — 구역 나누기를 확인하세요')
    spec = {'sourceHeader': header_line, 'sections': out}
    if head:
        tail = TAIL_RE.match(head['tail'])
        if not tail:
            raise ValueError('머리글의 사건명 괄호를 읽지 못했습니다: ' + head['tail'])
        spec['citation'] = '[%s %s 선고 %s %s%s]' % (head['court'], head['date'], head['nums'], (head['bench'] + ' ') if head['bench'] else '', head['type'])
        spec['pageTitle'] = tail['title']
    return spec, {'pre': pre, 'post': post}, warnings


def kept_note(sections, extra=''):
    names = [s['heading'].strip('【】') for s in sections if s['text'] and s['heading'] != '【전문】']
    return ('law.go.kr 미게재 사건. 사용자가 제공한 텍스트이며 국가법령정보센터 공식 원문이 아니다. 판결 본문(' + '·'.join(names) +
            ')만 보존하고 사이트의 부가정보(소송경과·인용판례·유사판례·주석서 인용·인용 문헌·안내문·이용자 정보)는 제외했다. '
            '빈 줄·줄바꿈·재판부 서명 줄 정리 외에 글자는 바꾸지 않았다.' + extra)


def read_json(path):
    with open(path, encoding='utf-8') as src:
        return json.load(src)


def write_json(path, value):
    with open(path, 'w', encoding='utf-8') as dst:
        json.dump(value, dst, ensure_ascii=False, indent=1)


def load_registry():
    return {c['id']: c for c in read_json(REG)['cases']}


def build_record(case_id, spec, case):
    for key in ('citation', 'pageTitle', 'provider', 'sourceLabel', 'sourceHeader', 'sourceNote', 'suppliedAt', 'sections'):
        if key not in spec or (key != 'sourceHeader' and not spec[key]):
            raise ValueError(f'spec 에 {key} 가 없습니다')
    rec = {'id': case_id, 'caseNumber': case['caseNumber'], 'lookupKey': case.get('lookupKey') or case['caseNumber'], 'kind': 'prec', 'seq': '',
           'sourceUrl': spec.get('sourceUrl', ''), 'pageTitle': spec['pageTitle'], 'citation': spec['citation'], 'provider': spec['provider'],
           'sourceLabel': spec['sourceLabel'], 'sourceHeader': spec['sourceHeader'], 'sourceNote': spec['sourceNote'], 'suppliedAt': spec['suppliedAt'],
           'sections': spec['sections']}
    for s in rec['sections']:
        if not re.fullmatch(r'【[^【】]+】', s.get('heading', '')) or not isinstance(s.get('text'), str):
            raise ValueError('구역 제목은 【…】 형식이어야 합니다: %r' % s.get('heading'))
    hits = [w for s in rec['sections'] for w in CHROME if w in s['text'] or w in s['heading']]
    if hits:
        raise ValueError('사이트 부가정보로 보이는 문구가 본문에 남아 있습니다: ' + ', '.join(sorted(set(hits))))
    if not any(s['heading'] == '【이유】' and s['text'] for s in rec['sections']):
        raise ValueError('【이유】 본문이 없습니다')
    flags = fetch_unit.check_record(case, rec)
    if flags:
        raise ValueError('등록부와 인용문이 맞지 않습니다: ' + '; '.join(flags))
    return rec


def cmd_import(a):
    reg = load_registry()
    if a.id not in reg:
        sys.exit(f'등록부에 없는 id: {a.id}')
    spec = read_json(a.spec)
    path = os.path.join(FETCHED, a.id + '.json')
    if os.path.isfile(path) and not a.force and 'sourceLabel' not in read_json(path):
        sys.exit(f'{a.id} 에는 law.go.kr 공식 수집본이 있습니다 — 덮어쓰려면 --force')
    try:
        rec = build_record(a.id, spec, reg[a.id])
    except ValueError as exc:
        sys.exit(f'{a.id}: {exc}')
    write_json(path, rec)
    missing = os.path.join(FETCHED, a.id + '.missing.json')
    if os.path.isfile(missing):
        os.remove(missing)
    print(f"저장: {path} ({len(rec['sections'])}개 구역, {sum(len(s['text']) for s in rec['sections'])}자) {rec['citation']}")


def cmd_parse(a):
    with open(a.raw, encoding='utf-8', newline='') as src:
        raw = src.read()
    spec, cut, warnings = parse(raw, a.mode)
    if a.citation:
        spec['citation'] = a.citation
    if a.title:
        spec['pageTitle'] = a.title
    spec.setdefault('citation', '')
    spec.setdefault('pageTitle', '')
    spec['provider'] = a.provider or ('casenote' if a.mode == 'casenote' else 'user-text')
    spec['sourceLabel'] = a.source_label or (CASENOTE_LABEL if a.mode == 'casenote' else '사용자 제공 판결문 텍스트 (출처 사이트 미표기)')
    spec['sourceNote'] = a.source_note or kept_note(spec['sections'])
    spec['suppliedAt'] = a.supplied_at
    write_json(a.out, spec)
    if a.cut:
        with open(a.cut, 'w', encoding='utf-8', newline='') as dst:
            dst.write('=== 머리글 앞 ===\n' + '\n'.join(cut['pre']) + '\n=== 버린 뒷부분 ===\n' + '\n'.join(cut['post']))
    print(f"{a.out}: {len(spec['sections'])}개 구역 " + ' '.join(f"{s['heading']}{len(s['text'])}" for s in spec['sections']))
    for w in warnings:
        print('  WARN', w)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('parse')
    p.add_argument('--raw', required=True); p.add_argument('--out', required=True); p.add_argument('--cut')
    p.add_argument('--mode', choices=['casenote', 'plain'], default='casenote')
    p.add_argument('--citation'); p.add_argument('--title'); p.add_argument('--provider'); p.add_argument('--source-label'); p.add_argument('--source-note')
    p.add_argument('--supplied-at', default='2026-10-28')
    p.set_defaults(fn=cmd_parse)
    p = sub.add_parser('import')
    p.add_argument('--id', required=True); p.add_argument('--spec', required=True); p.add_argument('--force', action='store_true')
    p.set_defaults(fn=cmd_import)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
