#!/usr/bin/env python3
"""국가법령정보센터(law.go.kr)에서 판례·헌재결정례 공식 텍스트를 그대로 추출해 data/fetched/<id>.json 으로 저장.

이 스크립트는 **사용자 PC(한국 네트워크)에서** 실행한다. 샌드박스에서는 law.go.kr 접속이 막혀 있다.

Usage:
  python3 tools/fetch_lawgo.py --all-missing            # registry.json 에 있지만 fetched/ 에 없는 사건 전부
  python3 tools/fetch_lawgo.py --id enbanc-2023da275578 # 특정 사건(재시도)
  python3 tools/fetch_lawgo.py --case 2023다275578 --id enbanc-2023da275578   # registry 에 없어도 임시 조회
  옵션: --engine playwright(기본)|requests   --delay 1.5   --force(기존 파일 덮어쓰기)   --retry-missing(.missing.json 도 재시도)

출력 스키마는 tools/FETCH_GUIDE.md §3 과 동일: {id, caseNumber, lookupKey, kind, seq, sourceUrl, pageTitle, citation, sections[{heading,text}]}
텍스트는 요약·수정 없이 페이지 그대로. 실패하면 <id>.missing.json 에 사유 기록.
"""
import argparse, json, os, re, sys, time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG = os.path.join(ROOT, 'data', 'registry.json')
FETCHED = os.path.join(ROOT, 'data', 'fetched')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from casenum import lookup_key, is_cc  # noqa: E402
from case_identity import case_number_list, court_id  # noqa: E402

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 lawbook-study/1.0'

# 브라우저 안에서 실행할 추출기 (FETCH_GUIDE.md 와 동일한 로직)
EXTRACT_JS = r"""
() => {
  const root = document.querySelector('#conScroll') || document.querySelector('#contentBody');
  if (!root) return {error:'no root', title: document.title, url: location.href};
  const blocks = new Set(['P','DIV','LI','TR','H1','H2','H3','H4','H5','H6']);
  // Body <img> (formulas, tables, figures) cannot be turned into text: leave them out of the text and record where they were in omittedImages (MARK is a temporary private-use marker that never reaches the saved text).
  const MARK = '\ue000', images = [];
  const attr = (node, name) => (node.getAttribute ? node.getAttribute(name) : '') || '';
  const clean = text => text.replace(/\u00a0/g,' ').replace(/[ \t]+\n/g,'\n').replace(/\n{3,}/g,'\n\n').trim();
  const nodeText = node => {
    if (node.nodeType === 3) return node.nodeValue || '';
    if (node.nodeType !== 1 || ['INPUT','SCRIPT','STYLE'].includes(node.tagName)) return '';
    if (node.tagName === 'BR') return '\n';
    if (node.tagName === 'IMG') { images.push({src: attr(node, 'src'), alt: attr(node, 'alt')}); return MARK; }
    const value = Array.from(node.childNodes).map(nodeText).join('');
    return blocks.has(node.tagName) ? '\n' + value + '\n' : value;
  };
  const sections = [], omitted = []; let current = {heading:'', text:''}, used = 0;
  const flush = () => {
    const marked = clean(current.text);
    current.text = clean(current.text.split(MARK).join(''));
    let nonSpace = 0;
    Array.from(marked).forEach((ch, i) => {
      if (ch === MARK) {
        const before = Array.from(marked.slice(0, i).split(MARK).join('').replace(/\s+/g, ' ').trim()).slice(-20).join('');
        omitted.push(Object.assign({section: current.heading, offset: nonSpace, before}, images[used++]));
      } else if (/\S/.test(ch)) nonSpace += 1;
    });
    if (current.heading || current.text) sections.push(current);
  };
  Array.from(root.childNodes).forEach(node => {
    if (node.nodeType === 1 && /^H[1-6]$/.test(node.tagName)) {
      flush(); current = {heading:node.textContent.trim(), text:''};
      (node.getElementsByTagName ? Array.from(node.getElementsByTagName('img')) : []).forEach(img =>
        omitted.push({section: current.heading, offset: 0, before: '', inHeading: true, src: attr(img, 'src'), alt: attr(img, 'alt')}));
    } else current.text += nodeText(node);
  });
  flush();
  const h2 = document.querySelector('#contentBody h2'), sub = document.querySelector('#contentBody .subtit1');
  return {pageTitle:h2?h2.textContent.trim():document.title, citation:sub?sub.textContent.trim():'', url:location.href, sections, omittedImages: omitted};
}
"""


def pretty_url(case_number):
    key = lookup_key(case_number)
    return (f"https://www.law.go.kr/헌재결정례/({key})" if is_cc(key) else f"https://www.law.go.kr/판례/({key})"), key


def direct_url(kind, seq):
    return f"https://www.law.go.kr/LSW/{'detcInfoP' if kind == 'detc' else 'precInfoP'}.do?{'detcSeq' if kind == 'detc' else 'precSeq'}={seq}"


# ---------------- engine: playwright ----------------
def fetch_playwright(targets, delay, force):
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        for t in targets:
            r = fetch_one_pw(page, t)
            results.append(r)
            time.sleep(delay)
        browser.close()
    return results


def fetch_one_pw(page, t):
    kind = t.get('kind') or ('detc' if is_cc(t['lookupKey']) else 'prec')
    seq = t.get('seq')
    tried = []
    try:
        if not seq:
            url, key = pretty_url(t['caseNumber'])
            tried.append(url)
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_timeout(2500)
            srcs = page.evaluate("() => Array.from(document.querySelectorAll('iframe')).map(f => f.src)")
            m = next((re.search(r'(precSeq|detcSeq)=(\d+)', s or '') for s in srcs if re.search(r'(precSeq|detcSeq)=(\d+)', s or '')), None)
            if not m:
                body = page.evaluate("() => document.body ? document.body.innerText.slice(0, 300) : ''")
                return {'id': t['id'], 'ok': False, 'reason': '한글주소 조회 실패 — 공식 검색·병합번호 확인 필요(미게재 확정 아님): ' + body.replace('\n', ' ')[:120], 'triedUrls': tried}
            kind, seq = ('prec' if m.group(1) == 'precSeq' else 'detc'), m.group(2)
        url = direct_url(kind, seq)
        tried.append(url)
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_selector('#conScroll', timeout=20000)
        page.wait_for_timeout(800)
        data = page.evaluate(EXTRACT_JS)
        return finish(t, kind, seq, url, data, tried)
    except Exception as e:
        return {'id': t['id'], 'ok': False, 'reason': f'{type(e).__name__}: {e}'[:200], 'triedUrls': tried}


# ---------------- engine: requests ----------------
def fetch_requests(targets, delay, force):
    import requests
    from bs4 import BeautifulSoup
    s = requests.Session(); s.headers['User-Agent'] = UA
    results = []
    for t in targets:
        kind = t.get('kind') or ('detc' if is_cc(t['lookupKey']) else 'prec')
        seq = t.get('seq'); tried = []
        try:
            if not seq:
                url, key = pretty_url(t['caseNumber']); tried.append(url)
                html = s.get(url, timeout=30).text
                m = re.search(r'(precSeq|detcSeq)=(\d+)', html)
                if not m:
                    results.append({'id': t['id'], 'ok': False, 'reason': '한글주소 조회 실패 — 공식 검색·병합번호 확인 필요(미게재 확정 아님)', 'triedUrls': tried}); time.sleep(delay); continue
                kind, seq = ('prec' if m.group(1) == 'precSeq' else 'detc'), m.group(2)
            url = direct_url(kind, seq); tried.append(url)
            html = s.get(url, timeout=30).text
            soup = BeautifulSoup(html, 'lxml')
            root = soup.select_one('#conScroll') or soup.select_one('#contentBody')
            if not root:
                results.append({'id': t['id'], 'ok': False, 'reason': 'conScroll 없음 — 본문이 JS 로 로드되는 페이지이면 --engine playwright 를 쓰세요', 'triedUrls': tried}); time.sleep(delay); continue
            sections, omitted_images = soup_sections_with_images(root)
            h2 = soup.select_one('#contentBody h2'); sub = soup.select_one('#contentBody .subtit1')
            data = {'pageTitle': h2.get_text(strip=True) if h2 else soup.title.get_text(strip=True) if soup.title else '', 'citation': sub.get_text(strip=True) if sub else '', 'url': url, 'sections': sections, 'omittedImages': omitted_images}
            results.append(finish(t, kind, seq, url, data, tried))
        except Exception as e:
            results.append({'id': t['id'], 'ok': False, 'reason': f'{type(e).__name__}: {e}'[:200], 'triedUrls': tried})
        time.sleep(delay)
    return results


IMG_MARK = ''  # 본문 <img> 자리를 잠시 표시하는 사설 영역 문자(저장하는 글자에는 남지 않는다)


def _soup_node_text(node, images=None):
    """Read every DOM node, keeping inline text adjacent and block boundaries apart.

    images 가 리스트이면 <img> 를 IMG_MARK 한 글자로 바꾸고 src·alt 를 순서대로 모은다(글자에는 남기지 않는다)."""
    from bs4 import Comment, NavigableString
    if isinstance(node, Comment):
        return ''
    if isinstance(node, NavigableString):
        return str(node)
    name = (getattr(node, 'name', '') or '').lower()
    if name in ('input', 'script', 'style'):
        return ''
    if name == 'br':
        return '\n'
    if name == 'img':
        if images is None:
            return ''
        images.append({'src': node.get('src') or '', 'alt': node.get('alt') or ''})
        return IMG_MARK
    text = ''.join(_soup_node_text(child, images) for child in node.children)
    return '\n' + text + '\n' if name in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6') else text


def _clean_text(text):
    text = text.replace('\u00a0', ' ')
    return re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+\n', '\n', text)).strip()


def soup_text(el):
    return _clean_text(_soup_node_text(el))


def _marked_section(raw, heading, images, cursor):
    """표지가 든 원문에서 (글자, 생략한 이미지 기록) 을 만든다. 글자는 표지 없이 정리한 결과와 같다.

    offset 은 이 구역 글자 앞쪽의 공백 아닌 글자 수, before 는 그 앞 20자(공백 하나로 접음)다."""
    marked = _clean_text(raw)
    omitted, non_space = [], 0
    for i, ch in enumerate(marked):
        if ch == IMG_MARK:
            before = re.sub(r'\s+', ' ', marked[:i].replace(IMG_MARK, '')).strip()[-20:]
            omitted.append({'section': heading, 'offset': non_space, 'before': before, **images[cursor + len(omitted)]})
        elif not ch.isspace():
            non_space += 1
    return _clean_text(raw.replace(IMG_MARK, '')), omitted


def soup_sections_with_images(root):
    """Equivalent to EXTRACT_JS: (sections, omittedImages). 이미지는 글자로 옮길 수 없어 위치만 기록한다."""
    sections, omitted, images, cursor = [], [], [], 0
    current = {'heading': '', 'text': ''}
    def flush():
        nonlocal cursor
        text, found = _marked_section(current['text'], current['heading'], images, cursor)
        cursor += len(found)
        omitted.extend(found)
        current['text'] = text
        if current['heading'] or current['text']:
            sections.append(current)
    for node in root.contents:
        name = getattr(node, 'name', '') or ''
        if re.fullmatch(r'h[1-6]', name, re.I):
            flush()
            current = {'heading': node.get_text().strip(), 'text': ''}
            for img in node.find_all('img'):
                omitted.append({'section': current['heading'], 'offset': 0, 'before': '', 'inHeading': True,
                                'src': img.get('src') or '', 'alt': img.get('alt') or ''})
        else:
            current['text'] += _soup_node_text(node, images)
    flush()
    return sections, omitted


def soup_sections(root):
    """Equivalent to EXTRACT_JS, including direct text and inline elements."""
    return soup_sections_with_images(root)[0]

# ---------------- common ----------------
def citation_identity(citation):
    """Read official court/date/dockets, expanding abbreviated merged members."""
    match = re.search(r'(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.', citation or '')
    if not match:
        return None
    tail = (citation or '')[match.end():]
    # Constitutional pages put the docket before the date and identify the
    # deciding panel, e.g. [전원재판부 2011헌바129,172(병합), 2014. 10. 30.].
    # The panel is not a separate court; keep the same strict court/date/member
    # checks in finish() once this official citation grammar is recognized.
    prefix = (citation or '')[:match.start()].strip(' []【】')
    # 일부 오래된 결정은 재판부 표기 없이 '[ 97헌가14, 1999. 4. 29.]' 로만 적힌다(번호부는 헌법재판소 사건부호만 허용).
    panel = re.fullmatch(r'(?:(?:헌법재판소\s+)?(?:전원재판부|지정재판부)\s+)?(.+),', prefix)
    if panel:
        number = panel.group(1).strip()
        members = case_number_list(number)
        if (not members or not all(re.fullmatch(r'\d{2,4}헌[가-힣]+\d+', item) for item in members)
                or not re.fullmatch(r'\s*(?:,\s*[^\[\]【】\n]+)?[\]】]?\s*', tail)):
            return None
        return {'court': '헌법재판소',
                'decisionDate': f'{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}',
                'caseNumber': number, 'members': members, 'decisionType': '결정'}
    rest = re.match(r'\s*(?:선고|자)\s*(.*?)\s*(판결|결정)', tail)
    if not rest:
        return None
    number = re.sub(r'\s*(?:전원합의체|소부)\s*$', '', rest.group(1)).strip()
    members = case_number_list(number)
    if not members:
        return None
    return {'court': citation[:match.start()].strip(' []【】'),
            'decisionDate': f'{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}',
            'caseNumber': number, 'members': members, 'decisionType': rest.group(2)}


def finish(t, kind, seq, url, data, tried):
    if not data or data.get('error') or not data.get('sections'):
        return {'id': t['id'], 'ok': False, 'reason': 'extract failed: ' + str((data or {}).get('error')), 'triedUrls': tried}
    key = t['lookupKey']
    metadata = citation_identity(data.get('citation') or '')
    reason = None
    if metadata:
        if key not in metadata['members']:
            reason = f'페이지의 사건번호가 {key} 와 일치하지 않음: {data.get("citation")}'
        elif t.get('decisionDate') and t['decisionDate'] != metadata['decisionDate']:
            reason = f'선고일 불일치: {t["decisionDate"]} / {metadata["decisionDate"]}'
        elif t.get('decisionType') and t['decisionType'] != metadata['decisionType']:
            reason = f'재판유형 불일치: {t["decisionType"]} / {metadata["decisionType"]}'
        if not reason and t.get('court'):
            try:
                if court_id(t['court'], t.get('courtId')) != court_id(metadata['court']):
                    reason = f'법원 불일치: {t["court"]} / {metadata["court"]}'
            except ValueError as error:
                reason = str(error)
    elif t.get('decisionDate') or t.get('court'):
        reason = '공식 인용문에서 법원·선고일·사건번호를 확인하지 못함'
    elif key not in (data.get('citation') or '') and key not in (data.get('pageTitle') or '') and not any(key in (s.get('text') or '')[:400] for s in data['sections'][:3]):
        reason = f'페이지의 사건번호가 {key} 와 일치하지 않음: {data.get("citation")}'
    if reason:
        return {'id': t['id'], 'ok': False, 'reason': reason, 'triedUrls': tried}
    rec = {'id': t['id'], 'caseNumber': t['caseNumber'], 'lookupKey': key, 'kind': kind, 'seq': str(seq), 'sourceUrl': url,
           'pageTitle': data.get('pageTitle', ''), 'citation': data.get('citation', ''), 'sections': data['sections']}
    images = data.get('omittedImages') or []
    if images:
        # 본문 이미지(수식·표·그림)는 글자로 옮길 수 없어 본문에서 빠진다. 공식 문자열 사이에 표식을 끼우지 않고 위치만 남긴다.
        rec['retrieval'] = {'method': 'law.go.kr-page', 'omittedImageCount': len(images), 'omittedImages': images,
                            'note': '본문에 포함된 이미지는 글자로 옮길 수 없어 sections 에서 빠졌다. 구역(section)과 그 구역 글자 앞쪽의 공백 아닌 글자 수(offset)·앞 20자(before)로 위치를 남긴다.'}
    return {'id': t['id'], 'ok': True, 'rec': rec, 'chars': sum(len(s.get('text', '')) for s in data['sections'])}


def cached_official_location(target, record):
    """Reuse only a matching official cache's already-verified serial number."""
    if not isinstance(record, dict) or record.get('id') != target['id']:
        return None
    kind, seq = record.get('kind'), str(record.get('seq') or '')
    if kind not in ('prec', 'detc') or not seq.isdigit():
        return None
    url = direct_url(kind, seq)
    if record.get('sourceUrl') != url or record.get('sourceLabel', '국가법령정보센터') != '국가법령정보센터':
        return None
    if not finish(target, kind, seq, url, record, [])['ok']:
        return None
    return {'kind': kind, 'seq': seq}


def missing_record_location(target, record):
    """.missing.json 이 남긴 공식 일련번호(apiSeq: law.go.kr 의 detcSeq/precSeq 와 같은 번호)를 조회 힌트로 쓴다.

    힌트일 뿐이므로 finish() 의 사건번호·선고일·재판유형 검사를 통과해야 저장된다."""
    if not isinstance(record, dict) or record.get('id') != target['id']:
        return None
    seq = str(record.get('apiSeq') or '')
    if not seq.isdigit():
        return None
    return {'kind': 'detc' if is_cc(target['lookupKey']) else 'prec', 'seq': seq}


def write_missing(path, result, now=None):
    """실패 기록을 쓴다. 이전 기록의 부가 필드(apiSource·apiStatus·apiSeq 등)는 지우지 않고 reason 만 갱신한다."""
    previous = {}
    if os.path.exists(path):
        try:
            previous = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = {}
    record = dict(previous)
    if previous.get('reason') and previous.get('reason') != result['reason']:
        record['previousReason'] = previous['reason']
    record.update({'id': result['id'], 'reason': result['reason'], 'triedUrls': result.get('triedUrls', [])})
    record['retriedAt'] = now or time.strftime('%Y-%m-%d')
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--all-missing', action='store_true')
    ap.add_argument('--id', action='append', default=[])
    ap.add_argument('--case', help='registry 에 없는 사건번호를 임시로 조회 (--id 와 함께)')
    ap.add_argument('--engine', choices=['playwright', 'requests'], default='playwright')
    ap.add_argument('--delay', type=float, default=1.5)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--retry-missing', action='store_true')
    a = ap.parse_args()
    os.makedirs(FETCHED, exist_ok=True)
    reg = json.load(open(REG, encoding='utf-8'))['cases'] if os.path.exists(REG) else []
    by_id = {c['id']: c for c in reg}
    targets = []
    if a.case:
        if not a.id:
            print('--case 에는 --id 가 필요합니다'); sys.exit(2)
        targets.append({'id': a.id[0], 'caseNumber': a.case, 'lookupKey': lookup_key(a.case)})
    else:
        ids = a.id or ([c['id'] for c in reg] if a.all_missing else [])
        for cid in ids:
            c = by_id.get(cid)
            if not c:
                print('registry 에 없는 id:', cid); continue
            out = os.path.join(FETCHED, cid + '.json')
            miss = os.path.join(FETCHED, cid + '.missing.json')
            if os.path.exists(out) and not a.force and not a.id:
                continue
            if os.path.exists(miss) and a.all_missing and not a.retry_missing:
                continue
            target = {key: c[key] for key in ('court', 'courtId', 'decisionDate', 'decisionType') if c.get(key)}
            target.update({'id': cid, 'caseNumber': c['caseNumber'], 'lookupKey': c.get('lookupKey') or lookup_key(c['caseNumber'])})
            lg = c.get('lawgo') or {}
            if not lg.get('seq') and os.path.exists(out):
                try:
                    lg = cached_official_location(target, json.loads(Path(out).read_text(encoding='utf-8'))) or lg
                except (OSError, ValueError):
                    pass
            if not lg.get('seq') and os.path.exists(miss):
                try:
                    lg = missing_record_location(target, json.loads(Path(miss).read_text(encoding='utf-8'))) or lg
                except (OSError, ValueError):
                    pass
            target.update({'kind': lg.get('kind'), 'seq': lg.get('seq')})
            targets.append(target)
    if not targets:
        print('조회할 사건이 없습니다.'); return
    print(f'{len(targets)}건 조회 ({a.engine})')
    results = fetch_playwright(targets, a.delay, a.force) if a.engine == 'playwright' else fetch_requests(targets, a.delay, a.force)
    ok = 0
    for r in results:
        if r['ok']:
            path = os.path.join(FETCHED, r['id'] + '.json')
            json.dump(r['rec'], open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            miss = os.path.join(FETCHED, r['id'] + '.missing.json')
            if os.path.exists(miss):
                os.remove(miss)
            ok += 1
            print(f"  OK   {r['id']}  {len(r['rec']['sections'])} sections, {r['chars']} chars  {r['rec']['citation']}")
        else:
            write_missing(os.path.join(FETCHED, r['id'] + '.missing.json'), r)
            print(f"  MISS {r['id']}  {r['reason']}")
    print(f'완료: 성공 {ok} / 실패 {len(results) - ok}. 다음: python3 tools/build_data.py && make build check')


if __name__ == '__main__':
    main()
