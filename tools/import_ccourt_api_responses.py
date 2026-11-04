#!/usr/bin/env python3
"""Review or import retained Korean-law constitutional API response envelopes.

Dry-run is the default. With --apply, create only absent fetched/missing files;
existing source files are never overwritten. The registry remains read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import tempfile

from case_identity import identity
from fetch_lawgo import cached_official_location
from import_lawgo_api import record_from_api


ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / 'data/inbox/korean-law-ccourt'
REGISTRY = ROOT / 'data/registry.json'
FETCHED = ROOT / 'data/fetched'
STATUSES = {'downloaded', 'truncated', 'not_found', 'ambiguous', 'api_error', 'exception'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def existing_full_source(path, placement):
    try:
        record = read_json(path)
        return bool(cached_official_location(placement, record) and any(
            '전문' in section.get('heading', '') and section.get('text', '').strip()
            for section in record.get('sections', [])))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def create_only(path, value):
    """Exclusive creation protects files created by another session too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1)
            stream.write('\n')
    except FileExistsError:
        return False
    return True


def run(registry, inbox, fetched, apply=False):
    placements = defaultdict(list)
    for case in read_json(registry)['cases']:
        if case.get('group') == 'ccourt':
            placements[case.get('decisionId')].append(case)
    entries, reserved = [], set()
    paths = sorted(inbox.glob('event-*.json'))
    for path in paths:
        entry = {'source': path.as_posix()}
        try:
            envelope = read_json(path)
            target, outcome = envelope['target'], envelope['outcome']
            for key in ('number', 'date', 'did', 'event'):
                if not isinstance(target.get(key), str) or target[key] != outcome.get(key):
                    raise ValueError('envelope target/outcome mismatch: ' + key)
            if path.name != 'event-' + target['event'] + '.json' or not target['event'].isdigit():
                raise ValueError('envelope event does not match filename')
            entry.update({k: target[k] for k in ('number', 'date', 'did', 'event')})
            status = outcome.get('status')
            if status not in STATUSES:
                raise ValueError('unknown response status')
            entry['status'] = status
            if outcome.get('seq') is not None:
                entry['seq'] = str(outcome['seq'])
            matches = placements.get(target['did'], [])
            if not matches:
                raise ValueError('no ccourt placement with matching decisionId')
            for placement in matches:
                pid = placement.get('id', '')
                item = dict(entry, id=pid)
                try:
                    if not re.fullmatch(r'[A-Za-z0-9_-]+', pid):
                        raise ValueError('unsafe placement id')
                    ident = identity(placement)
                    if (ident['decisionId'] != target['did'] or ident['courtId'] != 'cc'
                            or ident['decisionType'] != '결정' or placement.get('decisionDate') != target['date']
                            or (placement.get('lookupKey') or placement.get('caseNumber')) != target['number']):
                        raise ValueError('target does not match registered identity, date, court or lookup key')
                    if pid in reserved:
                        item.update(action='skipped', reason='duplicate envelope for placement')
                        entries.append(item)
                        continue
                    reserved.add(pid)
                    dest = fetched / (pid + '.json')
                    missing = fetched / (pid + '.missing.json')
                    if dest.exists() and existing_full_source(dest, placement):
                        item.update(action='skipped', reason='existing valid full source preserved')
                        entries.append(item)
                        continue
                    reason = None
                    record = None
                    if status != 'downloaded':
                        reason = 'Korean-law API: ' + status
                    else:
                        try:
                            record = record_from_api(envelope.get('response'), placement, outcome.get('seq'), 'constitutional')
                        except (ValueError, TypeError, KeyError) as error:
                            reason = 'Korean-law API response rejected: ' + str(error)
                    if dest.exists():
                        reason = 'Existing source lacks verified full text and was preserved' + (('; ' + reason) if reason else '')
                        record = None
                    if record is not None:
                        if apply and not create_only(dest, record):
                            item.update(action='skipped', reason='source appeared during import and was preserved')
                        else:
                            item.update(action='accepted', reason='full response validated')
                            item['bodyQuality'] = record['retrieval'].get('bodyQuality')
                    else:
                        item.update(action='missing', reason=reason)
                        miss = {'id': pid, 'reason': reason, 'triedUrls': [],
                                'apiSource': path.as_posix(), 'apiStatus': status}
                        if outcome.get('seq') is not None:
                            miss['apiSeq'] = str(outcome['seq'])
                        if missing.exists():
                            item['missingFile'] = 'existing file preserved'
                        elif apply:
                            item['missingFile'] = 'created' if create_only(missing, miss) else 'existing file preserved'
                        else:
                            item['missingFile'] = 'would create'
                    entries.append(item)
                except (ValueError, KeyError, TypeError) as error:
                    item.update(action='skipped', reason=str(error))
                    entries.append(item)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            entry.update(action='skipped', reason='invalid envelope: ' + str(error))
            entries.append(entry)
    return {'mode': 'apply' if apply else 'dry-run', 'envelopes': len(paths),
            'counts': dict(Counter(item['action'] for item in entries)),
            'statusCounts': dict(Counter(item.get('status', 'invalid') for item in entries)), 'entries': entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=REGISTRY)
    parser.add_argument('--inbox', type=Path, default=INBOX)
    parser.add_argument('--fetched', type=Path, default=FETCHED)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=Path, help='write a JSON report (dry-run otherwise prints only)')
    args = parser.parse_args()
    report_path = args.report or (args.inbox / 'import-report.json' if args.apply else None)
    if report_path:
        resolved = report_path.resolve()
        if resolved == args.registry.resolve() or resolved.parent == args.fetched.resolve() or resolved.name.startswith('event-'):
            parser.error('Report path must not replace registry, fetched files, or raw envelopes')
    result = run(args.registry, args.inbox, args.fetched, args.apply)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n', dir=report_path.parent, delete=False) as stream:
                temp = Path(stream.name)
                stream.write(payload)
            os.replace(temp, report_path)
        finally:
            if temp and temp.exists():
                temp.unlink()
    print(payload, end='')


if __name__ == '__main__':
    main()
