#!/usr/bin/env python3
"""Import a saved, full official Korean-law API response without rewriting its body.

The input is the retained get_decision_text(domain='precedent', full=True) tool
response. Metadata must match the existing target; an abbreviated merged docket
may contain the target as any explicitly listed member. Registry is read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from case_identity import case_number_list, court_id, identity
from fetch_lawgo import direct_url, finish

LABELS = {'판시사항': '【판시사항】', '판결요지': '【판결요지】', '결정요지': '【결정요지】',
          '심판대상조문': '【심판대상조문】', '참조조문': '【참조조문】', '참조판례': '【참조판례】'}
LABEL_RE = re.compile(r'(?m)^(' + '|'.join(LABELS) + r'):\n')


def response_text(response):
    if not isinstance(response, dict) or response.get('isError'):
        raise ValueError('The retained tool response is missing or unsuccessful')
    texts = [block.get('text', '') for block in response.get('content', []) if block.get('type') == 'text']
    if len(texts) != 1 or not texts[0]:
        raise ValueError('Expected one complete official text block')
    return texts[0]


def record_from_api(response, target, seq):
    """Return the ordinary fetched schema; retain source substrings verbatim."""
    if not re.fullmatch(r'\d+', str(seq)):
        raise ValueError('Official precedent serial must be numeric')
    text = response_text(response)
    title = re.match(r'\A=== (.+) ===\n', text)
    full_marker = re.search(r'(?m)^전문:\n', text)
    if not title or not full_marker:
        raise ValueError('Complete official header/full text was not returned')
    header = text[:full_marker.start()]
    values = {}
    for name in ('사건번호', '법원', '선고일', '판결유형'):
        match = re.search(r'^  ' + name + r': (.+)$', header, re.M)
        if not match:
            raise ValueError('Missing official metadata: ' + name)
        values[name] = match[1]
    date = values['선고일']
    if not re.fullmatch(r'\d{8}', date):
        raise ValueError('Unexpected official decision date')
    date = f'{date[:4]}-{date[4:6]}-{date[6:8]}'
    key = target.get('lookupKey') or target['caseNumber']
    if key not in case_number_list(values['사건번호']):
        raise ValueError('Official docket does not explicitly contain the registered target')
    if date != target.get('decisionDate'):
        raise ValueError('Official decision date differs from the registered target')
    if court_id(values['법원']) != court_id(target['court'], target.get('courtId')):
        raise ValueError('Official court differs from the registered target')
    if values['판결유형'] != target.get('decisionType', '판결'):
        raise ValueError('Official decision type differs from the registered target')
    registered = identity(target)
    for name, value in registered.items():
        if target.get(name) and target[name] != value:
            raise ValueError('Registered identity field differs: ' + name)
    full = text[full_marker.end():]
    if not full.strip() or not ('【주 문】' in full or '【주문】' in full):
        raise ValueError('Official full text lacks its judgment order')
    sections = []
    markers = list(LABEL_RE.finditer(header))
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(header)
        sections.append({'heading': LABELS[marker[1]], 'text': header[marker.end():end]})
    sections.append({'heading': '【전문】', 'text': full})
    when = f'{int(date[:4])}. {int(date[5:7])}. {int(date[8:])}.'
    citation = f'[{values["법원"]} {when} 선고 {values["사건번호"]} {values["판결유형"]}]'
    data = {'pageTitle': title[1], 'citation': citation, 'sections': sections}
    result = finish(dict(target, lookupKey=key), 'prec', str(seq), direct_url('prec', str(seq)), data, [])
    if not result['ok']:
        raise ValueError(result['reason'])
    record = result['rec']
    record['officialCaseNumber'] = values['사건번호']
    record['retrieval'] = {'method': 'korean-law:get_decision_text', 'domain': 'precedent', 'full': True,
                           'sourceTextSha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('response', type=Path)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--seq', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding='utf-8'))
    matches = [item for item in registry['cases'] if item['id'] == args.id]
    if len(matches) != 1:
        parser.error('Expected exactly one existing registered target')
    record = record_from_api(json.loads(args.response.read_text(encoding='utf-8')), matches[0], args.seq)
    if args.output.exists():
        parser.error('Output already exists; retain the existing source and choose another path')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'{record["id"]}: {len(record["sections"][-1]["text"])} official full-text characters retained')


if __name__ == '__main__':
    main()
