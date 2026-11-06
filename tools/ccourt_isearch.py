#!/usr/bin/env python3
"""헌법재판소 판례검색(isearch.ccourt.go.kr)에 수록된 결정문으로 law.go.kr 에 없는 헌법재판소 결정을 채운다 (data/schema.md §3).

law.go.kr 에 아직 게재되지 않았거나(최근 선고) 요지만 있고 전문이 없는 결정례는, 같은 재판의 헌법재판소 공식 판례검색 수록본으로 둘 수 있다.
사용자 PC(한국 네트워크)에서 Playwright 로 실행한다. 이 도구는 등록부·템플릿을 고치지 않고 data/fetched/ 의 파일만 만든다.

  python -X utf8 tools/ccourt_isearch.py fetch --id cc-2024heolma569 [--id …] [--dry-run] [--mode auto|full|supplement]

- auto: 공식 수집본(<id>.json)이 있고 【이 유】가 없으면 supplement, 공식 수집본이 없으면 full.
- full: data/fetched/<id>.json 으로 저장(provider·sourceLabel·sourceHeader·sourceNote·suppliedAt·retrieval 기록).
- supplement: 공식본에 없는 구역(당사자·주문·이유)만 data/fetched/<id>.supplement.json 으로 저장. 공식본의 판시사항·결정요지와
  판례검색의 같은 구역 글자가 (공백·가운뎃점 표기 차이를 빼고) 일치해야 한다.
- 저장 전에 판례검색 머리 줄의 선고일·사건번호가 등록부와 맞는지, 구역으로 나눈 글자가 원문과 공백을 빼고 한 글자도 어긋나지 않는지 검사한다.
- 글자는 바꾸지 않는다. 줄 끝 공백·빈 줄 정리와 줄 안 연속 공백 줄임만 한다(사이트 화면 장식·검색 안내는 제외).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from casenum import lookup_key  # noqa: E402
from case_identity import case_number_list  # noqa: E402

REG = os.path.join(ROOT, 'data', 'registry.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 lawbook-study/1.0'
SEARCH_URL = 'https://isearch.ccourt.go.kr/search.do?category=99'
LABEL = '헌법재판소 판례검색'
PROVIDER = 'ccourt-isearch'

HEADNOTE_HEADS = {'판시사항': '【판시사항】', '결정요지': '【결정요지】', '판결요지': '【판결요지】', '심판대상조문': '【심판대상조문】',
                  '심판대상조항': '【심판대상조문】', '참조조문': '【참조조문】', '참조판례': '【참조판례】'}
BODY_HEADS = {'당사자': '【당 사 자】', '주문': '【주 문】', '이유': '【이 유】'}
HEAD_LINE = re.compile(r'^\s*【\s*([^】\n]+?)\s*】\s*$')
META_LINE = re.compile(r'^헌재 (?P<date>\d{4}\. \d{1,2}\. \d{1,2}\.) (?P<nums>.+?), (?P<kind>결정문|판례집.*|공보.*)\s*$')
END_LINE = re.compile(r'^종국일자 (?P<date>\d{4}\. \d{1,2}\. \d{1,2}\.) 종국결과 (?P<result>.*)$')
DOTS = '·ㆍ․⋅•∙・‧∘'
IDENTITY_HEADS = ('판시사항', '결정요지', '판결요지')


def compact(text):
    return re.sub(r'\s+', '', text or '')


def loose(text):
    """공백·가운뎃점 표기 차이를 뺀 비교용 문자열."""
    return re.sub('[' + DOTS + ']', '·', compact(text))


def dotless(text):
    """공백과 가운뎃점류를 모두 뺀 비교용 문자열(law.go.kr 요지 페이지가 일부 가운뎃점을 빠뜨리는 경우를 허용한다)."""
    return re.sub('[' + DOTS + ']', '', compact(text))


def clean_text(text):
    """줄 끝 공백을 없애고 세 줄 이상의 빈 줄을 한 줄로, 줄 안 연속 공백(표 정렬용)을 한 칸으로 줄인다."""
    lines = [re.sub(r'[ \t 　]+', ' ', line).strip() for line in text.replace('\r', '').split('\n')]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def iso_date(text):
    m = re.fullmatch(r'(\d{4})\. (\d{1,2})\. (\d{1,2})\.', text)
    return f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}'


def heading_key(heading):
    return re.sub(r'[\s【】\[\]]', '', heading or '')


def parse_view(text):
    """판례검색 상세(팝업) innerText -> dict(kind, title, date, numbers, result, metaLine, sections).

    kind 'casebook': 판례집·공보 수록본(【판시사항】…【이 유】 구역). kind 'decision': 결정문 원본(머리표·주문·이유)."""
    lines = text.replace('\r', '').split('\n')
    meta = next(((i, META_LINE.match(l.strip())) for i, l in enumerate(lines) if META_LINE.match(l.strip())), None)
    if meta is None:
        raise ValueError('판례검색 머리 줄("헌재 2026. 10. 22. 2024헌마990등, 결정문")을 찾지 못했습니다')
    meta_at, mm = meta
    end = next((END_LINE.match(l.strip()) for l in lines[:meta_at + 1] if END_LINE.match(l.strip())), None)
    out = {'metaLine': lines[meta_at].strip(), 'date': iso_date(mm['date']), 'result': (end['result'].strip() if end else ''),
           'catalog': mm['kind'], 'numbers': case_number_list(re.sub(r'등$', '', mm['nums'].strip()))}
    start = meta_at + 1
    if mm['kind'] == '결정문':
        # 머리표: '헌 법 재 판 소 / 결 정 / 사 건 … / 선 고 일 …' 다음에 '주 문', '이 유'
        h = next((i for i in range(start, len(lines)) if compact(lines[i]) == '헌법재판소'), None)
        if h is None:
            raise ValueError('결정문 머리("헌 법 재 판 소")를 찾지 못했습니다')
        order = next((i for i in range(h, len(lines)) if compact(lines[i]) == '주문'), None)
        reason = next((i for i in range(h, len(lines)) if compact(lines[i]) == '이유'), None)
        if order is None or reason is None or order > reason:
            raise ValueError('결정문에서 주문·이유를 찾지 못했습니다')
        title = None
        for line in lines[h:order]:
            m = re.match(r'^\s*사\s*건\s+\S+\s+(.+?)\s*$', line)
            if m:
                title = m.group(1)
                break
        out.update(kind='decision', title=title or '',
                   sections=[{'heading': '【전문】', 'text': clean_text('\n'.join(lines[h:order]))},
                             {'heading': '【주 문】', 'text': clean_text('\n'.join(lines[order + 1:reason]))},
                             {'heading': '【이 유】', 'text': clean_text('\n'.join(lines[reason + 1:]))}])
        consumed = compact(''.join(lines[h:order]) + ''.join(lines[order + 1:reason]) + ''.join(lines[reason + 1:]))
    else:
        first = next((i for i in range(start, len(lines)) if HEAD_LINE.match(lines[i])), None)
        if first is None:
            raise ValueError('판례집 수록본의 구역 제목(【판시사항】 등)을 찾지 못했습니다')
        dated = next((i for i in range(start, first) if re.match(r'^\[\d{4}\. \d{1,2}\. \d{1,2}\.', lines[i].strip())), first)
        out['title'] = next((lines[i].strip() for i in range(dated - 1, start - 1, -1) if lines[i].strip()), '')
        bodies, current = [], None
        for line in lines[first:]:
            m = HEAD_LINE.match(line)
            if m:
                key = heading_key(m.group(1))
                heading = HEADNOTE_HEADS.get(key) or BODY_HEADS.get(key) or '【%s】' % re.sub(r'\s+', ' ', m.group(1))
                current = [heading, []]
                bodies.append(current)
            else:
                current[1].append(line)
        out.update(kind='casebook', sections=[{'heading': h, 'text': clean_text('\n'.join(ls))} for h, ls in bodies])
        consumed = compact(''.join(''.join(ls) for _, ls in bodies))
    produced = compact(''.join(s['text'] for s in out['sections']))
    if out['kind'] == 'decision':
        produced = compact(''.join(s['text'] for s in out['sections']))
    if consumed != produced:
        first = next((i for i, (a, b) in enumerate(zip(consumed, produced)) if a != b), min(len(consumed), len(produced)))
        raise ValueError(f'원문과 구역으로 나눈 글자가 어긋납니다(공백 제외) — 위치 {first}: {consumed[first:first + 30]!r} / {produced[first:first + 30]!r}')
    names = [heading_key(s['heading']) for s in out['sections']]
    if '이유' not in names or '주문' not in names:
        raise ValueError('주문 또는 이유 구역이 없습니다')
    return out


def check_identity(target, parsed):
    """판례검색 머리 줄의 선고일·사건번호가 등록부와 맞는지 확인한다(다르면 ValueError)."""
    if target.get('decisionDate') and target['decisionDate'] != parsed['date']:
        raise ValueError(f'선고일 불일치: 등록부 {target["decisionDate"]} / 판례검색 {parsed["date"]}')
    key = target['lookupKey']
    if key not in parsed['numbers']:
        raise ValueError(f'사건번호 불일치: 등록부 {key} / 판례검색 {parsed["metaLine"]}')


def source_note(kind, added=None):
    where = '판례집·공보 수록본' if kind == 'casebook' else '결정문 원본'
    text = (f'헌법재판소 판례검색(isearch.ccourt.go.kr) 수록 {where}. 국가법령정보센터 공식 원문이 아니라 같은 재판의 헌법재판소 공개 자료다. '
            '사이트의 화면 장식·검색 안내·유사판례는 제외했고, 줄 끝 공백·빈 줄 정리와 줄 안 연속 공백 줄임 외에 글자는 바꾸지 않았다.')
    if added:
        text += ' law.go.kr 수집본에 없는 구역(%s)만 보충했다.' % '·'.join(heading_key(h) for h in added)
    return text


def common_record(target, parsed, link, query, retrieved_at, raw_sha):
    return {'provider': PROVIDER, 'sourceLabel': LABEL, 'sourceHeader': parsed['metaLine'],
            'sourceUrl': 'https://isearch.ccourt.go.kr/', 'suppliedAt': retrieved_at,
            'retrieval': {'method': 'ccourt-isearch:view', 'query': query, 'link': link, 'catalog': parsed['catalog'],
                          'sourceTextSha256': raw_sha, 'retrievedAt': retrieved_at,
                          'formattingOnly': ['줄 끝 공백·빈 줄 정리', '줄 안 연속 공백 줄임', '사이트 화면 장식 제외']}}


def full_record(target, parsed, link, query, retrieved_at, raw_sha):
    """law.go.kr 수집본이 없을 때: fetched/<id>.json. citation 은 law.go.kr 형식(식별·재판유형 판별용)으로 적는다."""
    when = parsed['date']
    year, month, day = when.split('-')
    citation = f'[전원재판부 {target["lookupKey"]}, {int(year)}. {int(month)}. {int(day)}.]'
    record = {'id': target['id'], 'caseNumber': target['caseNumber'], 'lookupKey': target['lookupKey'], 'kind': 'detc',
              'pageTitle': parsed['title'], 'citation': citation}
    record.update(common_record(target, parsed, link, query, retrieved_at, raw_sha))
    record['sourceNote'] = source_note(parsed['kind'])
    record['sections'] = parsed['sections']
    return record


def supplement_record(target, parsed, official, link, query, retrieved_at, raw_sha):
    """공식 수집본에 판시사항·결정요지만 있을 때: 빠진 구역만 fetched/<id>.supplement.json 으로 보충한다.

    같은 재판인지는 공식본의 판시사항·결정요지(가운뎃점 표기 차이는 무시)가 판례검색 글자와 같은지로 확인한다. 그 밖의 공통 구역
    (참조조문·참조판례 등)은 공식본을 그대로 쓰고, 글자가 다르면 retrieval.officialDiffers 에 제목만 남긴다."""
    have = {heading_key(s['heading']): s for s in official['sections']}
    added, checked, differs = [], [], []
    for section in parsed['sections']:
        key = heading_key(section['heading'])
        if key in have and compact(have[key].get('text')):
            same = dotless(have[key]['text']) == dotless(section['text'])
            if key in IDENTITY_HEADS:
                if not same:
                    raise ValueError(f'공식본과 판례검색의 {key} 글자가 다릅니다 — 같은 재판인지 확인하세요')
                checked.append(key)
            elif not same:
                differs.append(key)
        elif key not in have:
            added.append(section)
    if not any(heading_key(s['heading']) == '이유' for s in added):
        raise ValueError('공식 수집본에 없는 【이 유】 구역이 없어 보충할 것이 없습니다')
    if not checked:
        raise ValueError('공식본과 글자를 대조할 판시사항·결정요지가 없어 같은 재판임을 확인할 수 없습니다')
    record = {'id': target['id'], 'kind': 'supplement'}
    record.update(common_record(target, parsed, link, query, retrieved_at, raw_sha))
    note = source_note(parsed['kind'], [s['heading'] for s in added])
    if differs:
        note += ' 공식 수집본과 글자가 다른 공통 구역(%s)은 공식 수집본을 그대로 쓴다.' % '·'.join(differs)
    record['sourceNote'] = note
    record['retrieval']['verifiedAgainstOfficial'] = checked
    if differs:
        record['retrieval']['officialDiffers'] = differs
    record['sections'] = added
    return record


# ---------------- browser ----------------
def view_text(page, ctx, case_number):
    """판례검색에서 사건번호로 찾은 첫 한글판례의 상세(팝업) innerText 와 링크를 돌려준다."""
    page.goto(SEARCH_URL, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(2000)
    page.fill('#searchInput', case_number)
    page.press('#searchInput', 'Enter')
    page.wait_for_timeout(4000)
    anchors = page.query_selector_all('a[onclick*="fn_view"][onclick*="\'00\'"]')
    if not anchors:
        raise ValueError('판례검색 결과 없음: ' + case_number)
    onclick = anchors[0].get_attribute('onclick') or ''
    link = re.search(r"'(\d+_\d+)'\)", onclick)
    with ctx.expect_page() as popup:
        anchors[0].click()
    view = popup.value
    try:
        view.wait_for_load_state('domcontentloaded')
        view.wait_for_timeout(3500)
        text = view.evaluate('() => document.body.innerText')
    finally:
        view.close()
    return text, (link.group(1) if link else '')


def load_target(registry, cid):
    record = next((c for c in registry if c['id'] == cid), None)
    if record is None:
        raise ValueError('registry 에 없는 id: ' + cid)
    return {'id': cid, 'caseNumber': record['caseNumber'], 'lookupKey': record.get('lookupKey') or lookup_key(record['caseNumber']),
            'decisionDate': record.get('decisionDate')}


def run_one(page, ctx, target, mode, dry_run, retrieved_at):
    text, link = view_text(page, ctx, target['lookupKey'])
    parsed = parse_view(text)
    check_identity(target, parsed)
    raw_sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    query = target['lookupKey']
    official_path = os.path.join(FETCHED, target['id'] + '.json')
    official = json.loads(Path(official_path).read_text(encoding='utf-8')) if os.path.isfile(official_path) else None
    if mode == 'auto':
        mode = 'supplement' if official and not any(heading_key(s['heading']) == '이유' for s in official['sections']) else 'full'
    if mode == 'supplement':
        if not official:
            raise ValueError('supplement 는 공식 수집본(<id>.json)이 있어야 합니다')
        record, path = supplement_record(target, parsed, official, link, query, retrieved_at, raw_sha), os.path.join(FETCHED, target['id'] + '.supplement.json')
    else:
        if official and any(heading_key(s['heading']) == '이유' for s in official['sections']):
            raise ValueError('이미 전문이 있는 공식 수집본이 있어 덮어쓰지 않습니다')
        if official:
            raise ValueError('공식 수집본(요지만 있음)이 있으면 supplement 를 쓰세요(공식본을 지우지 않습니다)')
        record, path = full_record(target, parsed, link, query, retrieved_at, raw_sha), official_path
    if not dry_run:
        with open(path, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(record, handle, ensure_ascii=False, indent=1)
        miss = os.path.join(FETCHED, target['id'] + '.missing.json')
        if mode == 'full' and os.path.exists(miss):
            os.remove(miss)
    chars = sum(len(s['text']) for s in record['sections'])
    return mode, os.path.relpath(path, ROOT).replace(os.sep, '/'), [s['heading'] for s in record['sections']], chars, link


def cmd_fetch(args):
    from playwright.sync_api import sync_playwright
    registry = json.loads(Path(REG).read_text(encoding='utf-8'))['cases']
    retrieved_at = args.retrieved_at or time.strftime('%Y-%m-%d')
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        for cid in args.id:
            try:
                target = load_target(registry, cid)
                mode, path, heads, chars, link = run_one(page, ctx, target, args.mode, args.dry_run, retrieved_at)
                print(f'OK   {cid} [{mode}] {path} {chars}자 link={link} {heads}')
            except Exception as exc:  # noqa: BLE001 - 건별 실패를 보고하고 계속한다
                failures += 1
                print(f'FAIL {cid} {type(exc).__name__}: {exc}')
            time.sleep(args.delay)
        browser.close()
    if args.dry_run:
        print('--dry-run: 저장하지 않음')
    sys.exit(1 if failures else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('fetch')
    p.add_argument('--id', action='append', required=True)
    p.add_argument('--mode', choices=('auto', 'full', 'supplement'), default='auto')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--delay', type=float, default=1.5)
    p.add_argument('--retrieved-at')
    p.set_defaults(fn=cmd_fetch)
    args = ap.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()
