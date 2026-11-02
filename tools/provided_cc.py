#!/usr/bin/env python3
"""헌법재판소 결정문 — 사용자가 제공한 판례 검색 사이트(케이스노트) 텍스트로 공식 수집본의 빠진 구역을 보충한다 (data/schema.md §3).

law.go.kr 의 어떤 헌법재판소 결정례 페이지는 판시사항·결정요지·조문만 있고 [주문]·[이유](전문)가 없다. 그런 사건의 본문을 사용자가
복사해 주면, 공식 수집본(data/fetched/<id>.json)은 그대로 두고 **빠진 구역만** data/fetched/<id>.supplement.json 에 보존한다.
build_data.py 가 공식 구역 뒤에 붙이고 출처를 구역별로 밝힌다(공식본에 같은 제목의 구역이 있으면 공식본을 쓴다).

  python -X utf8 tools/provided_cc.py attach --raw extra-folders/표준판례_헌법_미수집항목.txt [--dry-run] [--supplied-at 2026-11-02]

한 파일에 결정문 여러 건이 이어져 있어도 된다(머리글 "헌법재판소 2018. 8. 30. 선고 2016헌마263 전원재판부 결정 […]" 로 나눈다).
머리글의 선고일·사건번호가 등록부의 헌법재판소 표준판례(대표 사건번호·선고일)와 맞는 배치 중 공식 수집본이 있는 것에 붙인다.
- 판결 본문(판시사항·결정요지·심판대상조문·참조조문·참조판례·당사자 표·주문·이유·재판관 서명·별지)만 남기고,
  '많이 하이라이트된 문장 표시' 이하(소송경과·인용판례·유사판례·안내문·회사 정보)는 버린다.
- 글자는 바꾸지 않는다. 빈 줄·줄 끝 공백을 정리하고, 표로 줄바꿈된 재판관 서명을 한 사람 한 줄로 합치며, 쪽 나눔으로 끊긴 문장을
  이을 뿐이다. 원문과 정제본의 글자가 공백을 빼고 한 글자도 어긋나지 않는지 스스로 대조해 어긋나면 중단한다.
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REG = os.path.join(ROOT, 'data', 'registry.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')

HEADNOTE_HEADS = {'판시사항': '【판시사항】', '결정요지': '【결정요지】', '판결요지': '【판결요지】', '심판대상조문': '【심판대상조문】',
                  '심판대상조항': '【심판대상조문】', '참조조문': '【참조조문】', '참조판례': '【참조판례】'}
ROLES = {'재판장', '주심', '재판관'}
PARAGRAPH_HEADS = {'【판시사항】', '【결정요지】', '【판결요지】'}      # 문단 글: 쪽 나눔으로 끊긴 줄을 잇는다. 조문·판례 목록·표는 줄마다 따로 둔다
NAME_RE = re.compile(r'^[가-힣](?: ?[가-힣]){1,3}$')
HEADER_RE = re.compile(r'^헌법재판소 (?P<date>\d{4}\. \d{1,2}\. \d{1,2}\.) (?:선고|자) (?P<nums>.+?) (?:전원재판부|지정재판부)'
                       r'(?: (?:결정|판결))?(?: 〔[^〕]*〕)? (?P<tail>\[.*)$')
TAIL_RE = re.compile(r'^\[(?P<title>.*?)\](?: \[(?P<gong>[^\[\]]*)\])?$')
APPENDIX_RE = re.compile(r'^\s*(?:\[별지\s*(?P<a>\d*)\]|별지\s*(?P<b>\d*)\s{2,})\s*(?P<rest>.*)$')
END_MARK = '많이 하이라이트된 문장 표시'
CHROME = ('많이 하이라이트된 문장 표시', '주식회사 엘박스', '케이스노트', '인용판례', '유사판례', '주석서에서', '문헌에서 인용', '소송경과',
          '개인정보처리방침', '통신판매업신고', '사업자등록번호', 'Google API', '고객센터', '이용 가이드')
LABEL = '판례 검색 사이트(케이스노트) 수록본 · 사용자 제공 보충 자료'
END_RE = re.compile(r'[.)\]’”"\'?!。:;」』>]$')
HEADING_LIKE = re.compile(r'^(?:\d+\.|[가-힣]\.|\(\d+\)|\([가-힣]\)|[①-⑳]|[○ㅇ※]|\[|【|제\d+[조항호장절]|\d+\)|[가-힣]\))')
OPINION_TITLE = re.compile(r'(?:의견|견해)$')


def compact(text):
    return re.sub(r'\s+', '', text or '')


def loose(text):
    """공백·문장부호·가운뎃점·따옴표를 뺀 비교용 문자열(공식본과 제공본의 표기 차이를 무시하고 같은 본문인지 볼 때)."""
    return re.sub(r'[\s·ㆍ․⋅･,.，。:;\-_/~…‘’“”\'"()（）\[\]]', '', text or '')


def norm_heading(heading):
    return re.sub(r'[\s【】\[\]　]', '', heading or '')


def is_tab_label(line):
    """머리 표의 행 이름(예: '청구인 <탭>'): 탭 뒤가 비어 있는 짧은 줄. 표 안 칸(탭으로 시작하는 줄)은 해당하지 않는다."""
    if '\t' not in line:
        return False
    head, tail = line.split('\t', 1)
    return tail.strip() == '' and 0 < len(compact(head)) <= 12


def split_signature(lines):
    """끝의 재판부 서명(역할과 이름이 줄마다 갈라진 표)을 찾아 (본문 줄들, 서명 줄들)로 나눈다. 없으면 (lines, [])."""
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


def join_broken(lines, warnings, where):
    """쪽 나눔 등으로 문장 중간에서 끊긴 줄을 잇는다. 이전 줄이 문장 끝이 아니고, 이전 줄도 다음 줄도 제목·항목 표지로 보이지 않을 때만 잇는다."""
    merged = []
    for text in (x.strip() for x in lines if x.strip()):
        prev = merged[-1] if merged else ''
        if (prev and len(prev) >= 12 and not END_RE.search(prev) and not HEADING_LIKE.match(prev) and not OPINION_TITLE.search(prev)
                and not prev.startswith('재판관') and re.match(r'[가-힣“‘"\']', text) and not HEADING_LIKE.match(text)):
            warnings.append(f'JOIN {where}: 쪽 나눔으로 끊긴 줄을 이었음 — "{prev[-18:]}" + "{text[:18]}"')
            # 끊긴 자리가 낱말 끝(조사·어미)이면 띄어 잇고, 낱말 중간이면 붙여 잇는다(쪽 끝에서는 낱말 중간에서도 줄이 바뀐다)
            merged[-1] += (' ' if re.search(r'[을를은는이가의에도만와과로고며서면다]$', prev) else '') + text
        else:
            merged.append(text)
    return merged


def parse(raw):
    """-> (doc {sourceHeader, date, nums, pageTitle, sections}, cut {'pre': […], 'post': […]}, warnings)"""
    lines = [l for l in raw.replace('\r', '').split('\n') if not re.match(r'^\s*</?pasted_content\b', l)]
    h = next((i for i, l in enumerate(lines) if HEADER_RE.match(l.rstrip())), None)
    if h is None:
        raise ValueError('머리글("헌법재판소 2018. 8. 30. 선고 … 전원재판부 결정 […]")을 찾지 못했습니다')
    end = next((i for i, l in enumerate(lines) if END_MARK in l and i > h), None)
    if end is None:
        end = next((i for i, l in enumerate(lines) if l.strip() == '소송경과' and i > h), len(lines))
    head = HEADER_RE.match(lines[h].rstrip())
    tail = TAIL_RE.match(head['tail'])
    if not tail:
        raise ValueError('머리글의 사건명 괄호를 읽지 못했습니다: ' + head['tail'])
    body, warnings = lines[h + 1:end], []
    sections, cur, phase = [], None, 'head'
    consumed_marker = {}          # 본문 줄 번호 → 구역 제목으로 바뀌어 본문에서 빠지는 줄(값은 본문에 남는 나머지 글자)
    for i, line in enumerate(body):
        s, c = line.strip(), compact(line)
        heading = None
        if phase == 'head' and c in HEADNOTE_HEADS and s == c:
            heading = HEADNOTE_HEADS[c]
        elif phase == 'head' and is_tab_label(line):
            heading = '【%s】' % re.sub(r'\s+', ' ', line.split('\t', 1)[0].strip())
        elif phase == 'head' and c == '주문' and len(s) <= 8:
            heading, phase = '【주문】', 'order'
        elif phase in ('head', 'order') and c == '이유' and len(s) <= 6:
            heading, phase = '【이유】', 'reason'
        if heading:
            consumed_marker[i] = ''
            cur = [heading, []]
            sections.append(cur)
        elif cur is None:
            if s:
                raise ValueError('머리글 뒤 구역 제목 없는 줄이 있습니다: ' + s[:40])
        else:
            cur[1].append((i, line))
    out = []
    for heading, items in sections:
        ls = [l for _, l in items]
        if heading != '【이유】':
            joined = join_broken(ls, warnings, heading) if heading in PARAGRAPH_HEADS else [x.strip() for x in ls if x.strip()]
            out.append({'heading': heading, 'text': '\n'.join(joined)})
            continue
        # 이유: 재판관 서명 앞까지가 본문, 서명 뒤에 [별지] 가 이어질 수 있다.
        k = next((j for j, l in enumerate(ls) if APPENDIX_RE.match(l)), len(ls))
        reason, sig = split_signature(ls[:k])
        out.append({'heading': heading, 'text': '\n'.join(join_broken(reason, warnings, heading) + sig)})
        cursor = None
        for i, l in items[k:]:
            m = APPENDIX_RE.match(l)
            if m:
                consumed_marker[i] = m['rest']
                cursor = {'heading': '【별지%s】' % (m['a'] or m['b'] or ''), 'lines': [m['rest']] if m['rest'].strip() else []}
                out.append(cursor)
            else:
                cursor['lines'].append(l)
        for item in out:
            if 'lines' in item:       # 별지는 표·조문 목록이라 줄을 잇지 않는다
                item['text'] = '\n'.join(x.strip() for x in item.pop('lines') if x.strip())
    names = [norm_heading(s['heading']) for s in out]
    if '주문' not in names or '이유' not in names:
        warnings.append('주문 또는 이유 구역이 없습니다')
    # 원문 ↔ 정제본 글자 대조: 구역 제목으로 바뀐 줄을 뺀 원문과 정제본 본문이 공백을 빼면 같아야 한다
    consumed = ''.join(compact(consumed_marker[i]) if i in consumed_marker else compact(l) for i, l in enumerate(body))
    produced = ''.join(compact(s['text']) for s in out)
    if consumed != produced:
        first = next((i for i, (a, b) in enumerate(zip(consumed, produced)) if a != b), min(len(consumed), len(produced)))
        raise ValueError(f'원문과 정제본의 글자가 어긋납니다(공백 제외) — 위치 {first}: {consumed[first:first + 30]!r} / {produced[first:first + 30]!r}')
    doc = {'sourceHeader': lines[h].rstrip(), 'date': head['date'], 'nums': head['nums'], 'pageTitle': tail['title'], 'sections': out}
    return doc, {'pre': lines[:h], 'post': lines[end:]}, warnings


def split_documents(raw):
    """한 파일에 이어 붙은 결정문들을 머리글 줄에서 끊어 [(시작 줄 번호(1부터), 끝 줄 번호, 원문 문자열)] 로 나눈다."""
    lines = raw.replace('\r', '').split('\n')
    starts = [i for i, l in enumerate(lines) if HEADER_RE.match(l.rstrip())]
    if not starts:
        raise ValueError('결정문 머리글을 찾지 못했습니다')
    docs = []
    for k, st in enumerate(starts):
        en = starts[k + 1] if k + 1 < len(starts) else len(lines)
        docs.append((st + 1, en, '\n'.join(lines[st:en])))
    return docs


def read_json(path):
    with open(path, encoding='utf-8') as src:
        return json.load(src)


def write_json(path, value):
    with open(path, 'w', encoding='utf-8', newline='\n') as dst:
        json.dump(value, dst, ensure_ascii=False, indent=1)


def iso_date(text):
    m = re.fullmatch(r'(\d{4})\. (\d{1,2})\. (\d{1,2})\.', text)
    return f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}'


def docket_present(nums, key):
    return re.search(r'(?<![0-9])' + re.escape(key) + r'(?![0-9])', nums) is not None


def find_host(registry, doc):
    """머리글의 선고일·사건번호가 맞는 헌법재판소 표준판례 배치 중 공식 수집본(<id>.json)이 있는 것을 찾는다."""
    date = iso_date(doc['date'])
    matches = [c for c in registry if c.get('group') == 'standard' and c.get('court') == '헌법재판소'
               and c.get('decisionDate') == date and docket_present(doc['nums'], c.get('lookupKey') or c['caseNumber'])]
    hosts = [c for c in matches if os.path.isfile(os.path.join(FETCHED, c['id'] + '.json'))]
    return matches, hosts


def kept_note(added, skipped):
    text = ('law.go.kr 의 이 결정례 페이지에는 요지 부분만 있어, 빠진 구역(%s)을 사용자가 제공한 판례 검색 사이트(케이스노트) 수록 텍스트로 보충했다. '
            '국가법령정보센터 공식 원문이 아니다. 판결 본문만 보존하고 사이트의 부가정보(소송경과·인용판례·유사판례·안내문·이용자 정보)는 제외했다. '
            '빈 줄·줄바꿈·재판관 서명 줄 정리와 쪽 나눔으로 끊긴 문장 잇기 외에 글자는 바꾸지 않았다.') % '·'.join(norm_heading(h) for h in added)
    if skipped:
        text += ' 공식 수집본에 이미 있는 구역(%s)은 공식본을 그대로 쓰고 보충하지 않았다.' % '·'.join(norm_heading(h) for h in skipped)
    return text


def build_supplement(host, official, doc, raw_chunk, source_file, line_range, supplied_at):
    """공식 수집본에 없는 구역만 골라 보충 record 를 만든다 -> (record, 비교 보고)."""
    have = {norm_heading(s['heading']): s for s in official['sections']}
    added, skipped, report = [], [], []
    for section in doc['sections']:
        key = norm_heading(section['heading'])
        if key in have:
            same = compact(have[key].get('text')) == compact(section['text'])
            skipped.append(section['heading'])
            report.append({'heading': section['heading'], 'identicalToOfficial': same})
        else:
            added.append(section)
    if not any(norm_heading(s['heading']) == '이유' for s in added):
        raise ValueError('공식 수집본에 없는 【이유】 구역이 없어 보충할 것이 없습니다')
    reason = next(s for s in added if norm_heading(s['heading']) == '이유')
    probe = loose(reason['text'])[:300]
    if probe and probe in loose(''.join(s.get('text') or '' for s in official['sections'])):
        raise ValueError('공식 수집본에 같은 본문이 이미 있습니다(구역 제목만 다름) — 보충하지 않습니다')
    hits = [w for s in added for w in CHROME if w in s['text'] or w in s['heading']]
    if hits:
        raise ValueError('사이트 부가정보로 보이는 문구가 본문에 남아 있습니다: ' + ', '.join(sorted(set(hits))))
    record = {'id': host['id'], 'kind': 'supplement', 'provider': 'casenote', 'sourceLabel': LABEL, 'sourceHeader': doc['sourceHeader'],
              'sourceNote': kept_note([s['heading'] for s in added], skipped), 'suppliedAt': supplied_at,
              'retrieval': {'method': 'user-provided-text', 'sourceFile': source_file, 'sourceLineRange': list(line_range),
                            'sourceTextSha256': hashlib.sha256(raw_chunk.encode('utf-8')).hexdigest(),
                            'formattingOnly': ['빈 줄·줄 끝 공백 정리', '재판관 서명 표를 한 사람 한 줄로 합침', '쪽 나눔으로 끊긴 문장 잇기']},
              'sections': added}
    return record, report


def cmd_attach(a):
    with open(a.raw, encoding='utf-8', newline='') as src:
        raw = src.read()
    registry = read_json(REG)['cases']
    try:
        source_file = os.path.relpath(os.path.abspath(a.raw), ROOT).replace(os.sep, '/')
    except ValueError:       # 저장소와 다른 드라이브에 있는 파일은 절대 경로로 남긴다
        source_file = os.path.abspath(a.raw).replace(os.sep, '/')
    done = []
    for start, end, chunk in split_documents(raw):
        doc, cut, warnings = parse(chunk)
        matches, hosts = find_host(registry, doc)
        label = f"{doc['date']} {doc['nums'][:40]}"
        if len(hosts) != 1:
            sys.exit(f"{label}: 공식 수집본이 있는 대상 배치가 하나가 아닙니다 (같은 재판의 배치 {[c['id'] for c in matches]}, 수집본 있음 {[c['id'] for c in hosts]})")
        host = hosts[0]
        official = read_json(os.path.join(FETCHED, host['id'] + '.json'))
        try:
            record, report = build_supplement(host, official, doc, chunk, source_file, (start, end), a.supplied_at)
        except ValueError as exc:
            print(f'{host["id"]} {label}: 보충하지 않음 — {exc}')
            for w in warnings:
                print('  WARN', w)
            continue
        print(f"{host['id']} ({label}…): 보충 구역 {[s['heading'] + str(len(s['text'])) for s in record['sections']]}")
        for r in report:
            print(f"    공식본에 있어 건너뜀 {r['heading']}: " + ('공식본과 글자 같음(공백 제외)' if r['identicalToOfficial'] else '공식본과 글자가 다름'))
        for w in warnings:
            print('  WARN', w)
        if not a.dry_run:
            write_json(os.path.join(FETCHED, host['id'] + '.supplement.json'), record)
        done.append(host['id'])
    print(('--dry-run: 저장하지 않음; ' if a.dry_run else '저장: ') + ', '.join(done))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('attach')
    p.add_argument('--raw', required=True)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--supplied-at', default='2026-11-02')
    p.set_defaults(fn=cmd_attach)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
