#!/usr/bin/env python3
"""법률신문 「분야별 중요판례분석」 기사(idxno)를 받아 annual_cases.py 입력 형식의 텍스트로 저장한다.

  python tools/lawtimes_fetch.py 209192 208764 … [--out data/inbox/annual] [--delay 4] [--all] [--force]
저장 형식(data/inbox/annual/<year>-<field>[-n].txt): 1행 기사 제목, 2행 기사 URL, 3행부터 본문(문단마다 줄바꿈).
- 연도·분야는 제목에서 정한다(tools/subjects.py 의 article_year·guess_field). 대상 분야(헌법·행정법·민법·형법·상법·지식재산권법)가
  아닌 기사는 건너뛴다(--all 이면 <year>-other-<idxno>.txt 로 저장). 같은 연도·분야 기사가 여럿이면 -1, -2 … 를 붙인다.
- 기사 목록(idxno)은 https://www.lawtimes.co.kr/news/articleList.html?sc_serial_code=SRN245 에서 확인한다.
  서버가 짧은 시간의 연속 요청을 막으므로 --delay(초)를 지킨다. 본문은 화면의 기사 본문 영역만 옮기며 고치지 않는다.
"""
import argparse, html, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from subjects import article_year, guess_field  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'
VIEW = 'https://www.lawtimes.co.kr/news/articleView.html?idxno={}'


def article_text(page):
    """기사 페이지 HTML → (제목, 본문). 본문은 #article-view-content-div 안의 문단만, <style>/<script> 는 버린다."""
    t = re.search(r'<meta property="og:title" content="([^"]*)"', page) or re.search(r'<title>([^<]*?)(?:\s*<\s*[^<]*)?</title>', page)
    title = html.unescape(t.group(1)).strip() if t else ''
    title = re.sub(r'\s*-\s*법률신문\s*$', '', re.split(r'\s+<\s+', title)[0]).strip()
    m = re.search(r'<article[^>]*id="article-view-content-div"[^>]*>(.*?)</article>', page, re.S)
    if not m:
        return title, ''
    body = re.sub(r'<(script|style)\b.*?</\1>', '', m.group(1), flags=re.S | re.I)
    body = re.sub(r'<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>', '\n', body, flags=re.I)
    body = html.unescape(re.sub(r'<[^>]+>', '', body)).replace('\xa0', ' ')
    lines = [re.sub(r'[ \t]+', ' ', l).strip() for l in body.split('\n')]
    return title, '\n'.join(l for l in lines if l)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('idxno', nargs='+')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'inbox', 'annual'))
    ap.add_argument('--delay', type=float, default=4.0)
    ap.add_argument('--all', action='store_true', help='대상 밖 분야 기사도 저장')
    ap.add_argument('--force', action='store_true', help='같은 idxno 를 이미 저장했어도 다시 받는다')
    a = ap.parse_args()
    import requests
    s = requests.Session(); s.headers.update({'User-Agent': UA})
    os.makedirs(a.out, exist_ok=True)
    done = {}
    for f in os.listdir(a.out):
        if f.endswith('.txt'):
            lines = open(os.path.join(a.out, f), encoding='utf-8').read().split('\n', 2)
            m = re.search(r'idxno=(\d+)', lines[1] if len(lines) > 1 else '')
            if m: done[m.group(1)] = f
    for i, idx in enumerate(a.idxno):
        if idx in done and not a.force:
            print(f'{idx}: 이미 있음 → {done[idx]}'); continue
        if i: time.sleep(a.delay)
        r = s.get(VIEW.format(idx), timeout=60)
        title, body = article_text(r.text)
        year, field = article_year(title), guess_field(title)
        if r.status_code != 200 or not title or len(body) < 500:
            print(f'{idx}: 실패 (HTTP {r.status_code}, 제목 {title[:40]!r}, 본문 {len(body)}자) — 잠시 뒤 다시 시도'); continue
        if not field and not a.all:
            print(f'{idx}: 대상 밖 분야 — 건너뜀 ({title})'); continue
        stem = f'{year}-{field or "other-" + idx}'
        if idx in done:
            name = done[idx]
        else:
            # 같은 연도·분야 기사: 첫 기사는 번호 없이, 두 번째부터 -1(첫 기사 이름을 바꿈), -2, -3 … 으로 이어 붙인다
            nums = [int(m.group(1)) for f in os.listdir(a.out) for m in [re.fullmatch(re.escape(stem) + r'-(\d+)\.txt', f)] if m]
            plain = os.path.join(a.out, f'{stem}.txt')
            if os.path.exists(plain):
                os.replace(plain, os.path.join(a.out, f'{stem}-{max(nums, default=0) + 1}.txt'))
                nums.append(max(nums, default=0) + 1)
                done = {k: (f'{stem}-{nums[-1]}.txt' if v == f'{stem}.txt' else v) for k, v in done.items()}
            name = f'{stem}-{max(nums) + 1}.txt' if nums else f'{stem}.txt'
        open(os.path.join(a.out, name), 'w', encoding='utf-8').write(f'{title}\n{VIEW.format(idx)}\n{body}\n')
        done[idx] = name
        print(f'{idx}: {name} ← {title} ({len(body)}자)')


if __name__ == '__main__':
    main()
