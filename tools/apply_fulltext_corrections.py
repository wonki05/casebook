#!/usr/bin/env python3
"""사용자가 승인한 공식 수집본(data/fetched/<file>.json)의 글자 정정·섹션 보충을 적용한다.

  python -X utf8 tools/apply_fulltext_corrections.py --from data/standard-cases/_reports/fulltext-corrections-20261102.json [--dry-run | --check]

정정 목록 JSON:
  {"approvedBy": "...", "approvedAt": "YYYY-MM-DD", "items": [
     {"file": "std-civil-956", "section": "【참조조문】", "before": "제3조2의 제2항", "after": "제3조의2 제2항",
      "count": 1, "reason": "...", "confidence": "높음"},
     {"file": "std-civil-984", "op": "replaceSection", "section": "【판시사항】", "text": "[1] …\\n[2] …",
      "source": {"provider": "user", "sourceLabel": "사용자 제공", "sourceNote": "..."}, "reason": "..."}]}

- 정정 전·후 문구와 이유를 대상 파일의 `corrections` 배열에 남긴다(정정 전 문구가 곧 law.go.kr 원문이다). 그 밖의 글자는 바꾸지 않는다.
- replaceSection 은 한 섹션 전체를 사용자 제공 텍스트로 바꾸고 law.go.kr 원문 섹션을 `corrections[].beforeText` 에,
  출처를 `sectionSources[<섹션>]` 에 남긴다. 파일 전체의 출처(`sourceLabel`)는 바꾸지 않는다.
- 이미 적용된 항목은 건너뛴다(멱등). 재수집(fetch_lawgo.py --force)이 정정을 덮어쓰면 이 도구를 다시 실행한다.
- 정정 전 문구가 지정한 횟수만큼 나오지 않으면 아무 파일도 쓰지 않고 중단한다. 파일 서식(indent=1, 끝 줄바꿈 없음)은 유지한다.
"""
import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FETCHED = os.path.join(ROOT, 'data', 'fetched')


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)


def find_section(obj, heading, label):
    hits = [s for s in obj['sections'] if s.get('heading') == heading]
    if len(hits) != 1:
        raise ValueError(f'{label}: 섹션 {heading!r} 가 정확히 하나 있어야 합니다({len(hits)}개)')
    return hits[0]


def record_exists(obj, record):
    return any(all(c.get(k) == v for k, v in record.items()) for c in obj.get('corrections', []))


def apply_item(obj, item, meta):
    """obj 를 제자리에서 고치고 'applied'|'already'|'check-ok' 를 돌려준다. 문제가 있으면 ValueError."""
    label = f"{item['file']} {item['section']}"
    section = find_section(obj, item['section'], label)
    stamp = {'approvedBy': meta['approvedBy'], 'approvedAt': meta['approvedAt']}
    if item.get('op') == 'replaceSection':
        text = item['text']
        source = {**item['source'], 'suppliedAt': meta['approvedAt']}
        record = {'section': item['section'], 'op': 'replaceSection', 'reason': item['reason'], **stamp}
        if section['text'] == text and obj.get('sectionSources', {}).get(item['section']) == source:
            return 'already'
        record['beforeText'] = section['text']
        section['text'] = text
        obj.setdefault('sectionSources', {})[item['section']] = source
        obj.setdefault('corrections', []).append(record)
        return 'applied'
    before, after, count = item['before'], item['after'], item.get('count', 1)
    if not before or before == after:
        raise ValueError(f'{label}: 정정 전후 문구가 비었거나 같습니다')
    record = {'section': item['section'], 'before': before, 'after': after, 'reason': item['reason'],
              'confidence': item.get('confidence'), **({'count': count} if count != 1 else {}), **stamp}
    if section['text'].count(before) == 0 and section['text'].count(after) >= count and record_exists(obj, record):
        return 'already'
    if section['text'].count(before) != count:
        raise ValueError(f"{label}: 정정 전 문구가 {count}회 나오지 않습니다({section['text'].count(before)}회): {before!r}")
    section['text'] = section['text'].replace(before, after)
    obj.setdefault('corrections', []).append(record)
    return 'applied'


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
            if dump(obj) != text:
                raise ValueError(f"{item['file']}: 파일 서식이 도구의 출력(indent=1)과 달라 서식을 보존할 수 없습니다")
            loaded[path] = (text, obj, eol)
        result = apply_item(loaded[path][1], item, meta)
        results.append((item['file'], item['section'], result))
    changed = {p: (o, eol) for p, (text, o, eol) in loaded.items() if dump(o) != text}
    if check:
        pending = [r for r in results if r[2] != 'already']
        if pending:
            raise ValueError(f'아직 적용되지 않은 정정 {len(pending)}건: {pending[:3]}')
    elif write:
        for path, (obj, eol) in changed.items():
            with open(path, 'w', encoding='utf-8', newline='') as out:
                out.write(dump(obj).replace('\n', eol))
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
