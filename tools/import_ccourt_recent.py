#!/usr/bin/env python3
"""Prepare reviewed-by-rule ccourt candidates from completed list downloads.

This is a read-only planner. Registration is exclusively through add_cases.py.
The list description is a truncated preview, not a decision or holdings source.
"""
import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from case_identity import case_number_list, identity, primary_case_number
from download_ccourt_recent_pages import DEFAULT_OUT, FORM, LIST_URL, parse_list

ROOT = Path(__file__).resolve().parent.parent
COURT = '헌법재판소'


class Entries(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entry = None
        self.depth = 0
        self.capture = None
        self.parts = []
        self.entries = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.entry is None and tag == 'a':
            match = re.search(r"viewPop\s*\(\s*['\"]1195['\"]\s*,\s*['\"](\d+)['\"]", a.get('onclick', ''))
            if match:
                self.entry = {'eventId': match.group(1), 'infos': []}
                self.depth = 1
                return
        elif self.entry is not None:
            if tag in self.VOID:
                return
            self.depth += 1
            classes = a.get('class', '').split()
            if tag == 'b' and ('caseNum' in classes or 'title' in classes):
                self.capture = 'caseNumber' if 'caseNum' in classes else 'title'
                self.parts = []
            elif tag == 'span' and 'caseInfo' in classes:
                self.capture = 'info'
                self.parts = []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.entry is None or tag in self.VOID:
            return
        if (self.capture in ('caseNumber', 'title') and tag == 'b') or (self.capture == 'info' and tag == 'span'):
            value = ''.join(self.parts).strip()
            if self.capture == 'info':
                self.entry['infos'].append(value)
            else:
                self.entry[self.capture] = value
            self.capture = None
        self.depth -= 1
        if self.depth == 0:
            self.entries.append(self.entry)
            self.entry = None


def read_page(path, page):
    raw = path.read_bytes()
    validated = parse_list(raw, 'utf-8', page)
    parser = Entries()
    parser.feed(raw.decode('utf-8'))
    if [(e['eventId'], e.get('caseNumber')) for e in parser.entries] != validated.cases:
        raise ValueError('entry count or event/case number mismatch')
    result = []
    digest = hashlib.sha256(raw).hexdigest()
    for e in parser.entries:
        date_fields = [x for x in e['infos'] if x.startswith('종국일자')]
        if len(date_fields) != 1 or not e.get('title'):
            raise ValueError('missing or ambiguous date/title for event ' + e['eventId'])
        m = re.fullmatch(r'종국일자\s*\|\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.', date_fields[0])
        if not m:
            raise ValueError('invalid date for event ' + e['eventId'])
        date = dt.date(*map(int, m.groups())).isoformat()
        number = e['caseNumber']
        primary_case_number(number)
        result_fields = [x for x in e['infos'] if x.startswith('종국결과')]
        if len(result_fields) != 1 or '|' not in result_fields[0]:
            raise ValueError('missing or ambiguous result for event ' + e['eventId'])
        result_text = result_fields[0].partition('|')[2].strip()
        result.append({'status': 'ok', 'caseNumber': number, 'date': date,
                       'title': e['title'], 'court': COURT, 'decisionType': '결정',
                       'ccourtSource': {'provider': COURT, 'boardId': '1195',
                           'eventId': e['eventId'], 'listUrl': LIST_URL + '?cbIdx=1195',
                           'sourceUrl': 'https://www.ccourt.go.kr/site/kor/ex/bbs/View.do?cbIdx=1195&bcIdx=' + e['eventId'],
                           'sourceFile': path.name, 'sourceSha256': digest, 'page': page,
                           'result': result_text}})
    return result, validated.total


def members(record):
    # Only explicit display members are evidence; '등' does not identify co-cases.
    return set(case_number_list(record['caseNumber']))


def plan(candidates, records):
    """Classify by explicit members, same court/date/type, and placement."""
    index = {}
    for record in records:
        try:
            fields = identity(record)
        except (KeyError, ValueError) as exc:
            raise ValueError('invalid registry identity for ' + str(record.get('id'))) from exc
        if fields['courtId'] != 'cc':
            continue
        for number in members(record) | {primary_case_number(record.get('lookupKey') or record['caseNumber'])}:
            index.setdefault(number, []).append((record, fields))
    seen_events = set()
    counts = {'ready': 0, 'existing': 0, 'conflicts': 0}
    for c in candidates:
        event = c['ccourtSource']['eventId']
        if event in seen_events:
            c['status'], c['reason'] = 'review', 'duplicate source event across list pages'
        else:
            seen_events.add(event)
            probe = {'court': c['court'], 'caseNumber': c['caseNumber'],
                     'decisionDate': c['date'], 'decisionType': c['decisionType']}
            cid = identity(probe)
            matches = {}
            for number in members(c):
                for record, fields in index.get(number, []):
                    matches[record['id']] = (record, fields)
            different = [(r, f) for r, f in matches.values() if f['decisionId'].split('-')[-2:] != cid['decisionId'].split('-')[-2:]]
            same = [(r, f) for r, f in matches.values() if f['decisionId'].split('-')[-2:] == cid['decisionId'].split('-')[-2:]]
            if different:
                c['status'], c['reason'] = 'review', 'same docket, different decision date or type'
                c['matches'] = [r['id'] for r, _ in different]
            elif len({f['decisionId'] for _, f in same}) > 1:
                c['status'], c['reason'] = 'review', 'matching placements have conflicting representatives'
                c['matches'] = [r['id'] for r, _ in same]
            elif any(r['group'] == 'ccourt' for r, _ in same):
                c['status'], c['reason'] = 'skip', 'existing ccourt placement'
                c['matches'] = [r['id'] for r, _ in same if r['group'] == 'ccourt']
            elif any(f['decisionId'] != cid['decisionId'] for _, f in same):
                c['status'], c['reason'] = 'review', 'co-case uses a different representative; identity needs verification'
                c['matches'] = [r['id'] for r, _ in same]
            else:
                # Index planned candidates too, preventing repeated placements in a batch.
                planned = dict(probe, id='source:' + event, group='ccourt')
                for number in members(c):
                    index.setdefault(number, []).append((planned, cid))
        counts[{'ok': 'ready', 'skip': 'existing', 'review': 'conflicts'}[c['status']]] += 1
    return counts


def collect(folder, since, through):
    candidates, invalid, totals, page_dates = [], [], set(), {}
    for path in sorted(folder.glob('page-*.html')):
        match = re.fullmatch(r'page-(\d+)\.html', path.name)
        if not match:
            continue
        page = int(match.group(1))
        try:
            entries, total = read_page(path, page)
        except (OSError, UnicodeError, ValueError) as exc:
            invalid.append({'file': path.name, 'error': str(exc)})
            continue
        page_dates[page] = [entry['date'] for entry in entries]
        totals.add(total)
        candidates.extend(c for c in entries if since <= c['date'] and (not through or c['date'] <= through))
    if len(totals) > 1:
        raise ValueError('download pages report different search totals; reconcile snapshots')
    total = next(iter(totals), 0)
    pages = sorted(page_dates)
    missing = sorted(set(range(1, (total + 9) // 10 + 1)) - set(pages))
    dates = [date for page in pages for date in page_dates[page]]
    descending = dates == sorted(dates, reverse=True)
    missing_in_scope = []
    for page in missing:
        if not descending:
            missing_in_scope.append(page)
            continue
        before = [p for p in pages if p < page]
        after = [p for p in pages if p > page]
        high = min(page_dates[before[-1]]) if before else FORM['searchDateTo']
        low = max(page_dates[after[0]]) if after else FORM['searchDateFrom']
        if high >= since and (not through or low <= through):
            missing_in_scope.append(page)
    return candidates, {'validPages': len(pages), 'reportedTotal': total, 'missingPages': missing,
                        'missingInScopePages': missing_in_scope, 'datesDescending': descending,
                        'minDate': min(dates) if dates else None, 'maxDate': max(dates) if dates else None,
                        'invalidPages': invalid, 'searchFrom': FORM['searchDateFrom'], 'searchTo': FORM['searchDateTo'],
                        'note': 'List descriptions are truncated previews and are not imported as decision text.'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--registry', type=Path, default=ROOT / 'data' / 'registry.json')
    ap.add_argument('--output', type=Path, required=True, help='new candidate file; existing files are never overwritten')
    ap.add_argument('--since', default='2020-01-01')
    ap.add_argument('--through')
    args = ap.parse_args()
    try:
        since = dt.date.fromisoformat(args.since).isoformat()
        through = dt.date.fromisoformat(args.through).isoformat() if args.through else None
        if through and since > through:
            raise ValueError('--since must not be later than --through')
        records = json.loads(args.registry.read_text(encoding='utf-8'))['cases']
        candidates, report = collect(args.input, since, through)
        if not report['validPages']:
            raise ValueError('no valid completed list pages')
        report['counts'] = plan(candidates, records)
        result = {'group': 'ccourt', 'subject': 'constitution', 'since': since, 'through': through,
                  'report': report, 'candidates': candidates}
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps(report, ensure_ascii=True))
    except (ValueError, OSError, KeyError) as exc:
        ap.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
