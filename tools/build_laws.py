#!/usr/bin/env python3
"""Parse the legalize-kr markdown statutes (zip attached by the user) into data/laws.json.

Usage: python3 tools/build_laws.py <dir-with-md-files>
Output schema (compact):
{
  "groups": [{"id","label"}],
  "laws": [ { "id","group","name","short","kind","meta":{...},
              "toc":[{"id","l":1..4,"t":"제1편 총칙","a":firstArticleIndex}],
              "articles":[{"id","no":"제1조","t":"법원","h":tocId,"b":[[mark,text],...]}],
              "supp":[{"t":"부칙 <제471호,1958.2.22>","b":[[mark,text],...]}],
              "versions":[ {same as a law body + "id","label","alias","promulgated","effective","form","current","preamble"} ]  # 헌법 only
  } ]
}
Body line marks: '' plain paragraph · '①' 항 · '1.' 호 · '가.' 목 · 'X' 삭제 · 'N' note ([전문개정 …]) · 'T' table/pre line
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'laws.json')

GROUPS = [
    {"id": "const", "label": "헌법"},
    {"id": "civil", "label": "민사법"},
    {"id": "crim", "label": "형사법"},
    {"id": "admin", "label": "행정법"},
    {"id": "gov", "label": "법원과 국회에 관한 법"},
    {"id": "econ", "label": "경제법·지식재산법"},
]
# file stem -> (id, group, short)
LAW_INDEX = [
    ("01_헌법", "constitution", "const", "헌법"),
    ("10_헌법재판소법", "ccourt-act", "const", "헌법재판소법"),
    ("11_국회법", "assembly-act", "gov", "국회법"),
    ("12_법원조직법", "court-org-act", "gov", "법원조직법"),
    ("13_군사법원법", "military-court-act", "gov", "군사법원법"),
    ("14_공직선거법", "election-act", "gov", "공직선거법"),
    ("07_행정기본법", "admin-basic-act", "admin", "행정기본법"),
    ("09_행정절차법", "admin-procedure-act", "admin", "행정절차법"),
    ("08_행정소송법", "admin-litigation-act", "admin", "행정소송법"),
    ("15_국가공무원법", "national-officials-act", "admin", "국가공무원법"),
    ("16_지방공무원법", "local-officials-act", "admin", "지방공무원법"),
    ("경찰관 직무집행법", "police-duties-act", "admin", "경찰관직무집행법"),
    ("개인정보 보호법", "pipa", "admin", "개인정보보호법"),
    ("02_민법", "civil-code", "civil", "민법"),
    ("04_민사소송법", "civil-procedure-act", "civil", "민사소송법"),
    ("05_민사집행법", "civil-execution-act", "civil", "민사집행법"),
    ("소송촉진 등에 관한 특례법", "litigation-promotion-act", "civil", "소송촉진법"),
    ("상고심절차에 관한 특례법", "appeal-procedure-act", "civil", "상고심절차특례법"),
    ("03_형법", "criminal-code", "crim", "형법"),
    ("06_형사소송법", "criminal-procedure-act", "crim", "형사소송법"),
    ("형의 실효 등에 관한 법률", "criminal-record-act", "crim", "형실효법"),
    ("독점규제 및 공정거래에 관한 법률", "fair-trade-act", "econ", "공정거래법"),
    ("부정경쟁방지 및 영업비밀보호에 관한 법률", "unfair-competition-act", "econ", "부정경쟁방지법"),
    ("특허법", "patent-act", "econ", "특허법"),
    ("상표법", "trademark-act", "econ", "상표법"),
    ("디자인보호법", "design-act", "econ", "디자인보호법"),
]

H_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*$')
ART_RE = re.compile(r'^(제\d+조(?:의\d+)*)\s*(?:\((.*)\))?\s*$')
PARA_RE = re.compile(r'^\*\*([①-⑳㉑-㉟])\*\*\s*(.*)$')
PARA2_RE = re.compile(r'^([①-⑳㉑-㉟])\s*(.*)$')
HO_RE = re.compile(r'^(\d{1,3}(?:의\d+)?\.)\s+(.*)$')
MOK_RE = re.compile(r'^([가-힣](?:의\d+)?\.|\(?\d{1,3}\)|[가-힣]\))\s+(.*)$')
DEL_RE = re.compile(r'^삭제\s*(<.*>)?\s*$')
NOTE_RE = re.compile(r'^\[(전문개정|본조신설|제목개정|본조개정|시행일|.{0,40}헌법재판소.{0,80})[^\]]*\]\s*$')
TABLE_RE = re.compile(r'^[|+]')
LEVEL_OF = {'편': 1, '장': 2, '절': 3, '관': 4}


def strip_md(s):
    s = s.replace('**', '')
    s = re.sub(r'<a id="[^"]*"></a>', '', s)
    s = re.sub(r'\\([.\\*_\[\]()<>#+\-!`~])', r'\1', s)  # markdown escapes: 1\. -> 1.
    return s.strip()


def parse_frontmatter(text):
    meta = {}
    if text.startswith('---'):
        end = text.find('\n---', 3)
        if end > 0:
            block = text[3:end]
            for line in block.split('\n'):
                m = re.match(r'^([^:]+):\s*(.*)$', line)
                if m:
                    k, v = m.group(1).strip(), m.group(2).strip().strip('"').strip("'")
                    meta[k] = v
            text = text[end + 4:]
    return meta, text


def body_lines(lines):
    """Turn raw article lines into [mark, text] pairs."""
    out = []
    for raw in lines:
        l = raw.rstrip()
        if not l.strip():
            continue
        s = strip_md(l) if not TABLE_RE.match(l) else l.rstrip()
        if TABLE_RE.match(l):
            out.append(['T', l.rstrip()]); continue
        m = PARA_RE.match(s) or PARA2_RE.match(s)
        if m:
            out.append([m.group(1), m.group(2).strip()]); continue
        m = HO_RE.match(s)
        if m:
            out.append([m.group(1), m.group(2).strip()]); continue
        m = MOK_RE.match(s)
        if m:
            out.append([m.group(1), m.group(2).strip()]); continue
        if DEL_RE.match(s):
            out.append(['X', s]); continue
        if NOTE_RE.match(s):
            out.append(['N', s]); continue
        out.append(['', s])
    return out


def parse_law_body(lines, prefix):
    """Parse the markdown body of one law (or one constitution version) into toc/articles/supp.
    `lines` excludes frontmatter and the top-level '# <law name>' heading."""
    toc, articles, supp = [], [], []
    cur_art = None
    cur_lines = []
    head_id = None
    in_supp = False
    supp_cur = None
    skip_until_heading = False
    counter = [0]
    preamble = []
    in_preamble = False

    def flush_article():
        nonlocal cur_art, cur_lines
        if cur_art is not None:
            cur_art['b'] = body_lines(cur_lines)
            articles.append(cur_art)
        cur_art, cur_lines = None, []

    def new_id():
        counter[0] += 1
        return f'{prefix}-{counter[0]}'

    for raw in lines:
        hm = H_RE.match(raw)
        if hm:
            level, txt = len(hm.group(1)), strip_md(hm.group(2))
            if txt == '목차':
                skip_until_heading = True
                continue
            skip_until_heading = False
            if txt.startswith('부칙'):
                flush_article()
                in_supp = True
                supp_cur = None
                continue
            am = ART_RE.match(txt)
            if am and level >= 4:
                if in_supp:
                    # articles inside 부칙 are kept as plain lines under the current 부칙 block
                    if supp_cur is None:
                        supp_cur = {'t': '부칙', 'b': []}
                        supp.append(supp_cur)
                    supp_cur['b'].append(['', txt])
                    continue
                flush_article()
                cur_art = {'id': new_id(), 'no': am.group(1), 't': (am.group(2) or '').strip(), 'h': head_id}
                in_preamble = False
                continue
            sm = re.match(r'^제\d+(편|장|절|관)', txt)
            if sm and not in_supp:
                flush_article()
                head_id = new_id()
                toc.append({'id': head_id, 'l': LEVEL_OF[sm.group(1)], 't': txt, 'a': len(articles)})
                in_preamble = False
                continue
            # any other heading: ignore
            continue
        if skip_until_heading:
            continue
        if in_supp:
            s = raw.rstrip()
            if not s.strip():
                continue
            if re.match(r'^부칙\s*<', s.strip()) or s.strip() == '부칙':
                supp_cur = {'t': s.strip(), 'b': []}
                supp.append(supp_cur)
                continue
            if supp_cur is None:
                supp_cur = {'t': '부칙', 'b': []}
                supp.append(supp_cur)
            supp_cur['b'].extend(body_lines([s]))
            continue
        if cur_art is not None:
            cur_lines.append(raw)
            continue
        # lines before the first article / heading (e.g. constitution preamble)
        s = strip_md(raw)
        if not s:
            continue
        if s == '전문':
            in_preamble = True
            continue
        if s.startswith('>'):
            continue
        if TABLE_RE.match(s):
            continue
        if in_preamble or not toc:
            preamble.append(s)
    flush_article()
    return toc, articles, supp, '\n'.join(preamble)


def parse_constitution(text, law_id):
    meta, body = parse_frontmatter(text)
    # split into versions on '# 헌법 제N호 ...' headings
    parts = re.split(r'\n(?=# 헌법 제\d+호)', body)
    versions = []
    for part in parts:
        hm = re.match(r'^# (헌법 제(\d+)호)\s+(.*?)\s*(?:—\s*(현행|구 헌법))?\s*$', part.split('\n', 1)[0])
        if not hm:
            continue
        label, no, alias, status = hm.group(1), int(hm.group(2)), hm.group(3).strip(), hm.group(4)
        alias = alias.replace('— 현행', '').strip()
        lines = part.split('\n')[1:]
        bq = next((l for l in lines if l.startswith('>')), '')
        promulgated = re.search(r'공포\s*([\d.]+)', bq)
        effective = re.search(r'시행\s*([\d.]+)', bq)
        form = re.search(r'·\s*(제정|전부개정|일부개정)', bq)
        vid = f'{law_id}-v{no}'
        toc, articles, supp, preamble = parse_law_body(lines, vid)
        versions.append({
            'id': vid, 'no': no, 'label': label, 'alias': alias,
            'promulgated': promulgated.group(1) if promulgated else '', 'effective': effective.group(1) if effective else '',
            'form': form.group(1) if form else '', 'current': status == '현행',
            'preamble': preamble, 'toc': toc, 'articles': articles, 'supp': supp,
        })
    versions.sort(key=lambda v: -v['no'])  # current (10) first, then 9 ... 1
    return meta, versions


def main():
    src = sys.argv[1]
    laws = []
    for stem, lid, group, short in LAW_INDEX:
        path = os.path.join(src, stem + '.md')
        if not os.path.exists(path):
            print('MISSING', path, file=sys.stderr); continue
        text = open(path, encoding='utf-8').read()
        if lid == 'constitution':
            meta, versions = parse_constitution(text, lid)
            cur = next(v for v in versions if v['current'])
            laws.append({
                'id': lid, 'group': group, 'name': '대한민국헌법', 'short': short, 'kind': '헌법',
                'meta': {'promulgated': cur['promulgated'], 'effective': cur['effective'], 'no': cur['label'],
                         'source': meta.get('출처', ''), 'asof': meta.get('기준일', '')},
                'versions': [{k: v[k] for k in ('id', 'no', 'label', 'alias', 'promulgated', 'effective', 'form', 'current', 'preamble', 'toc', 'articles', 'supp')} for v in versions],
            })
            continue
        meta, body = parse_frontmatter(text)
        lines = body.split('\n')
        # the law name is the first '# <name>' heading (frontmatter 제목 may repeat for annex titles)
        name = stem.split('_', 1)[-1]
        for i, l in enumerate(lines[:8]):
            if l.startswith('# ') and not re.match(r'^# 제\d+(편|장)', l):
                name = strip_md(l[2:])
                lines = lines[:i] + lines[i + 1:]
                break
        toc, articles, supp, _ = parse_law_body(lines, lid)
        laws.append({
            'id': lid, 'group': group, 'name': name, 'short': short, 'kind': meta.get('법령구분', '법률'),
            'meta': {'promulgated': meta.get('공포일자', ''), 'no': meta.get('공포번호', ''), 'effective': meta.get('시행일자', ''),
                     'dept': meta.get('소관부처', '').strip('- ').strip() or '', 'status': meta.get('상태', ''),
                     'source': meta.get('출처', ''), 'asof': meta.get('기준일', '')},
            'toc': toc, 'articles': articles, 'supp': supp,
        })
    data = {'groups': GROUPS, 'laws': laws}
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'wrote {OUT}: {len(laws)} laws, {os.path.getsize(OUT)/1024:.0f} KB')
    for l in laws:
        if 'versions' in l:
            print(f"  {l['name']}: {len(l['versions'])} versions; current articles={len(l['versions'][0]['articles'])} toc={len(l['versions'][0]['toc'])} preamble={len(l['versions'][0]['preamble'])}")
        else:
            print(f"  {l['name']}: articles={len(l['articles'])} toc={len(l['toc'])} supp={len(l['supp'])}")


if __name__ == '__main__':
    main()
