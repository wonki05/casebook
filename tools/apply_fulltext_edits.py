#!/usr/bin/env python3
"""승인된 공식 수집본(data/fetched/<file>.json) 정정 중 '위치'나 '구조'로 지정하는 연산을 적용한다.

  python -X utf8 tools/apply_fulltext_edits.py --from data/standard-cases/_reports/fulltext-corrections-20261103.json [--dry-run | --check]

apply_fulltext_corrections.py 의 연산(문구 정정, replaceSection)도 같은 목록에서 그대로 처리하고, 여기에 두 연산을 더한다.

  {"file": "std-constitution-195", "op": "replaceAt", "section": "【이 유】", "sectionSha256": "<정정 전 섹션 글자의 SHA-256>",
   "edits": [{"offset": 1122, "before": "?", "after": "⋅"}, ...], "reason": "...", "confidence": "높음"}
  {"file": "std-constitution-368", "op": "splitSection", "section": "[당 사 자]", "markers": ["[주\\u3000\\u3000문]", "[이\\u3000\\u3000유]"],
   "headings": ["【당 사 자】", "【주 문】", "【이 유】"], "reason": "..."}

- replaceAt: 섹션 글자의 지정한 위치(0부터, 정정 전 글자 기준)에서 `before` 가 그대로 나올 때만 `after` 로 바꾼다. 같은 글자가 여럿이거나
  앞뒤 문맥이 같아 문구로는 하나만 지정하기 어려운 정정(깨진 '?' 글자, 한 글자 누락)에 쓴다. `sectionSha256` 은 목록을 만들 때 본 섹션 글자의
  해시여서, 재수집으로 글자가 달라졌으면 적용하지 않고 중단한다. 위치·정정 전후 글자는 파일의 `corrections[]` 에 남는다.
- splitSection: 한 섹션에 당사자·주문·이유가 이어 붙은 수집본(구 형식 페이지)을 `markers`(그 줄 전체가 이 문자열인 줄이 정확히 한 번씩, 순서대로) 기준으로
  `headings` 의 섹션으로 나눈다. 표지 줄만 빠지고 앞뒤 빈 줄·공백만 다듬으며, 나눈 글자를 공백 제외하고 이어 붙이면 원래와 같아야 한다.
  원래 섹션 전체는 `corrections[].beforeText` 에 남는다.
- 이미 적용된 항목은 건너뛴다(멱등). 서식(indent=1, 줄 끝)은 apply_fulltext_corrections.py 와 같다.
"""
import argparse
import hashlib
import json
import os
import re
import sys

import apply_fulltext_corrections as base

FETCHED = base.FETCHED


def sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def stamp(meta):
    return {'approvedBy': meta['approvedBy'], 'approvedAt': meta['approvedAt']}


def apply_replace_at(obj, item, meta):
    label = f"{item['file']} {item['section']}"
    section = base.find_section(obj, item['section'], label)
    text = section['text']
    edits = sorted(item['edits'], key=lambda e: e['offset'])
    if not edits or not item.get('sectionSha256'):
        raise ValueError(f'{label}: replaceAt 에는 edits 와 sectionSha256 이 필요합니다')
    record = {'section': item['section'], 'op': 'replaceAt', 'sectionSha256': item['sectionSha256'], 'edits': edits,
              'reason': item['reason'], 'confidence': item.get('confidence'), **stamp(meta)}
    previous = [c for c in obj.get('corrections', []) if c.get('op') == 'replaceAt' and c.get('section') == item['section']
                and c.get('sectionSha256') == item['sectionSha256'] and c.get('edits') == edits]
    if sha256(text) != item['sectionSha256']:
        if previous and sha256(text) == previous[0].get('afterSha256'):
            return 'already'
        if any(c.get('op') == 'replaceAt' and c.get('section') == item['section'] and c.get('afterSha256') == sha256(text)
               for c in obj.get('corrections', [])):
            raise ValueError(f'{label}: 같은 섹션에 이미 다른 replaceAt 정정이 적용돼 있습니다 — 한 섹션의 위치 정정은 한 항목으로 합치세요')
        raise ValueError(f'{label}: 섹션 글자가 정정 목록을 만들 때와 다릅니다(재수집으로 바뀌었는지 확인하고 목록을 다시 만드세요)')
    end = -1
    for edit in edits:
        offset, before, after = edit['offset'], edit['before'], edit['after']
        if type(offset) is not int or not before or before == after:
            raise ValueError(f'{label}: replaceAt 항목이 올바르지 않습니다: {edit}')
        if offset < end:
            raise ValueError(f'{label}: replaceAt 위치가 겹칩니다: {offset}')
        if text[offset:offset + len(before)] != before:
            raise ValueError(f'{label}: 위치 {offset} 의 글자가 {before!r} 가 아닙니다({text[offset:offset + len(before)]!r})')
        end = offset + len(before)
    pieces, cursor = [], 0
    for edit in edits:
        pieces.append(text[cursor:edit['offset']])
        pieces.append(edit['after'])
        cursor = edit['offset'] + len(edit['before'])
    pieces.append(text[cursor:])
    section['text'] = ''.join(pieces)
    record['afterSha256'] = sha256(section['text'])
    obj.setdefault('corrections', []).append(record)
    return 'applied'


def compact(text):
    return re.sub(r'\s+', '', text)


def apply_split_section(obj, item, meta):
    label = f"{item['file']} {item['section']}"
    markers, headings = item['markers'], item['headings']
    if len(headings) != len(markers) + 1:
        raise ValueError(f'{label}: headings 는 markers 보다 하나 많아야 합니다')
    hits = [s for s in obj['sections'] if s.get('heading') == item['section']]
    if not hits:
        done = [c for c in obj.get('corrections', []) if c.get('op') == 'splitSection' and c.get('section') == item['section']
                and c.get('headings') == headings]
        have = {s.get('heading') for s in obj['sections']}
        if done and set(headings) <= have:
            return 'already'
    section = base.find_section(obj, item['section'], label)
    others = {s.get('heading') for s in obj['sections'] if s is not section}
    if others & set(headings):
        raise ValueError(f'{label}: 이미 있는 구역 이름으로 나눌 수 없습니다: {sorted(others & set(headings))}')
    text = section['text']
    lines = text.split('\n')
    cuts = []
    for marker in markers:
        found = [i for i, line in enumerate(lines) if line.strip() == marker]
        if len(found) != 1:
            raise ValueError(f'{label}: 표지 줄 {marker!r} 가 정확히 한 번 나와야 합니다({len(found)}회)')
        cuts.append(found[0])
    if cuts != sorted(cuts):
        raise ValueError(f'{label}: 표지 줄의 순서가 markers 와 다릅니다')
    bounds = [-1] + cuts + [len(lines)]
    parts = ['\n'.join(lines[bounds[i] + 1:bounds[i + 1]]).strip() for i in range(len(headings))]
    if any(not part for part in parts):
        raise ValueError(f'{label}: 나눈 구역 중 비는 것이 있습니다')
    rebuilt = ''.join(p + m for p, m in zip(parts, markers + ['']))
    if compact(rebuilt) != compact(text):
        raise ValueError(f'{label}: 나눈 글자를 이어 붙이면 원래 글자와 다릅니다')
    index = obj['sections'].index(section)
    obj['sections'][index:index + 1] = [{'heading': h, 'text': p} for h, p in zip(headings, parts)]
    obj.setdefault('corrections', []).append({
        'section': item['section'], 'op': 'splitSection', 'markers': markers, 'headings': headings,
        'reason': item['reason'], **stamp(meta), 'beforeText': text})
    return 'applied'


EXT_OPS = {'replaceAt': apply_replace_at, 'splitSection': apply_split_section}


def apply_item(obj, item, meta):
    handler = EXT_OPS.get(item.get('op'))
    if handler:
        return handler(obj, item, meta)
    if not item.get('op') and item.get('before') and item['before'] in item.get('after', ''):
        # 정정 후 문구가 정정 전 문구를 품으면(예: 북합의서 → 남북합의서) 다시 실행할 때 같은 곳을 또 고치게 된다.
        raise ValueError(f"{item['file']} {item['section']}: 정정 후 문구가 정정 전 문구를 포함해 멱등하지 않습니다 — replaceAt 으로 위치를 지정하세요")
    return base.apply_item(obj, item, meta)


def run(spec, fetched_dir, write=True, check=False):
    meta = {'approvedBy': spec['approvedBy'], 'approvedAt': spec['approvedAt']}
    loaded, results = {}, []
    for item in spec['items']:
        path = os.path.join(fetched_dir, item['file'] + '.json')
        if path not in loaded:
            # Windows 에서 수집한 파일은 CRLF 로 저장돼 있다 — 줄 끝 방식을 그대로 유지한다.
            raw = open(path, encoding='utf-8', newline='').read()
            eol = '\r\n' if '\r\n' in raw else '\n'
            text = raw.replace('\r\n', '\n')
            obj = json.loads(text)
            if base.dump(obj) != text:
                raise ValueError(f"{item['file']}: 파일 서식이 도구의 출력(indent=1)과 달라 서식을 보존할 수 없습니다")
            loaded[path] = (text, obj, eol)
        results.append((item['file'], item['section'], apply_item(loaded[path][1], item, meta)))
    changed = {p: (o, eol) for p, (text, o, eol) in loaded.items() if base.dump(o) != text}
    if check:
        pending = [r for r in results if r[2] != 'already']
        if pending:
            raise ValueError(f'아직 적용되지 않은 정정 {len(pending)}건: {pending[:3]}')
    elif write:
        for path, (obj, eol) in changed.items():
            with open(path, 'w', encoding='utf-8', newline='') as out:
                out.write(base.dump(obj).replace('\n', eol))
    return results, sorted(changed)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--from', dest='spec', required=True)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--check', action='store_true', help='모든 정정이 이미 적용돼 있는지만 확인한다(쓰지 않음)')
    a = ap.parse_args()
    spec = json.load(open(a.spec, encoding='utf-8'))
    try:
        results, changed = run(spec, FETCHED, write=not a.dry_run, check=a.check)
    except ValueError as exc:
        sys.exit(str(exc))
    for file, section, result in results:
        print(f'  {result:<8} {file} {section}')
    print(f"정정 {sum(1 for r in results if r[2] == 'applied')}건 적용, {sum(1 for r in results if r[2] == 'already')}건 이미 적용"
          + (' (dry-run: 쓰지 않음)' if a.dry_run else '') + f", 바뀐 파일 {len(changed)}개")


if __name__ == '__main__':
    main()
