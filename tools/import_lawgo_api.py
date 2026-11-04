#!/usr/bin/env python3
"""Import a saved, full official Korean-law API response without rewriting its body.

The input is a retained get_decision_text(..., full=True) tool
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
ANNEX_RE = re.compile(r'(?:\[별(?:지|표)(?:\s*\d+)?\]|\(별(?:지|표)(?:\s*\d+)?\)|【별\s*(?:지|표)】|별지(?:\s*\d+)?\s*(?:청구인\s*명단|관련\s*조항))')


def constitutional_body_quality(full):
    """Require reasons and a closing, including closings before a labelled annex.

    A final newline and plausible last character catch obvious incomplete annex
    endings, but cannot prove an upstream response is complete.
    """
    if re.search(r'<img\b', full, re.I):
        raise ValueError('Constitutional full text contains an external image; source body is incomplete')
    if re.search(r'별\s*(?:지|표)\s*생략', full):
        raise ValueError('Constitutional full text explicitly omits an annex')
    if not re.search(r'(?:【이\s*유\s*】|\[이\s*유\s*\])', full):
        raise ValueError('Constitutional full text lacks reasons; possible partial body')

    def closing(text):
        tail = text.rstrip()[-800:]
        name = r'[가-힣○]{2,5}(?:\(공가로 행정전자서명 불능\))?'
        return bool(re.search(r'결론.{0,600}결정한다[.。](?:\[/\]재판장,[가-힣○]{2,5}(?:,[가-힣○]{2,5}){2,})?$', tail, re.S)
                    or re.search(r'관여\s*재판관.{0,200}주문과\s*같이\s*결정한다[.。]$', tail, re.S)
                    or re.search(r'(?:재판장|재판관),?\s*(?:' + name + r'[,\s]+){2,}' + name + r'$', tail))

    if closing(full):
        return 'recognizable_closing'
    for marker in ANNEX_RE.finditer(full):
        if not closing(full[:marker.start()]):
            continue
        annex = full[marker.end():]
        tail = annex.rstrip()
        # Some API records close a wrapper following the last annex.
        if tail.endswith('[/]'):
            tail = tail[:-3].rstrip()
        # A separator/newline and a plausible terminal character are evidence,
        # not proof: an upstream source could still end mid-word.
        if (tail and full.endswith('\n') and re.search(r'[가-힣0-9○\]）).。┘]$', tail)
                and not re.search(r'(?:재판관|변호사|청구인|법무법인|제|및|또는)$', tail)):
            return 'annex_terminal_heuristic_not_proof'
        raise ValueError('Constitutional annex has an incomplete or unrecognized ending; possible partial body')
    raise ValueError('Constitutional full text lacks recognizable closing; possible partial body')


def response_text(response):
    if not isinstance(response, dict) or response.get('isError'):
        raise ValueError('The retained tool response is missing or unsuccessful')
    texts = [block.get('text', '') for block in response.get('content', []) if block.get('type') == 'text']
    if len(texts) != 1 or not texts[0]:
        raise ValueError('Expected one complete official text block')
    # The connector caps the entire response at 50,000 characters. Reject the
    # cap even if its diagnostic was removed from a retained response.
    if len(texts[0]) >= 50000 or re.search(r'(?:응답|전문|본문).{0,40}(?:잘렸|잘라|절단|truncat)', texts[0], re.I):
        raise ValueError('Official response is truncated or reaches the 50,000-character cap; full text not imported')
    return texts[0]


def record_from_api(response, target, seq, domain='precedent'):
    """Return the ordinary fetched schema; retain source substrings verbatim."""
    if domain not in ('precedent', 'constitutional'):
        raise ValueError('Unsupported Korean-law domain')
    if not re.fullmatch(r'\d+', str(seq)):
        raise ValueError('Official serial must be numeric')
    text = response_text(response)
    title = re.match(r'\A=== (.+) ===\n', text)
    full_marker = re.search(r'(?m)^전문:\n', text)
    if not title or not full_marker:
        raise ValueError('Complete official header/full text was not returned')
    header = text[:full_marker.start()]
    values = {}
    names = (('사건번호', '법원', '선고일', '판결유형') if domain == 'precedent'
             else ('사건번호', '종국일자'))
    for name in names:
        match = re.search(r'^  ' + name + r': (.+)$', header, re.M)
        if not match:
            raise ValueError('Missing official metadata: ' + name)
        values[name] = match[1]
    date = values['선고일' if domain == 'precedent' else '종국일자']
    if not re.fullmatch(r'\d{8}', date):
        raise ValueError('Unexpected official decision date')
    date = f'{date[:4]}-{date[4:6]}-{date[6:8]}'
    key = target.get('lookupKey') or target['caseNumber']
    if key not in case_number_list(values['사건번호']):
        raise ValueError('Official docket does not explicitly contain the registered target')
    if date != target.get('decisionDate'):
        raise ValueError('Official decision date differs from the registered target')
    # The authenticated constitutional domain implies court and decision type;
    # neither appears in this domain's response metadata.
    court = values['법원'] if domain == 'precedent' else '헌법재판소'
    decision_type = values['판결유형'] if domain == 'precedent' else '결정'
    if court_id(court) != court_id(target['court'], target.get('courtId')):
        raise ValueError('Official court differs from the registered target')
    if decision_type != target.get('decisionType', '판결' if domain == 'precedent' else None):
        raise ValueError('Official decision type differs from the registered target')
    registered = identity(target)
    for name, value in registered.items():
        if target.get(name) and target[name] != value:
            raise ValueError('Registered identity field differs: ' + name)
    full = text[full_marker.end():]
    order_pattern = (r'(?:【주\s*문[】〕]|\[주\s*문\])' if domain == 'constitutional'
                     else r'(?:【주\s*문】|\[주\s*문\])')
    if not full.strip() or not re.search(order_pattern, full):
        raise ValueError('Official full text lacks its judgment order')
    quality = None
    if domain == 'constitutional':
        quality = constitutional_body_quality(full)
    sections = []
    markers = list(LABEL_RE.finditer(header))
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(header)
        sections.append({'heading': LABELS[marker[1]], 'text': header[marker.end():end]})
    sections.append({'heading': '【전문】', 'text': full})
    when = f'{int(date[:4])}. {int(date[5:7])}. {int(date[8:])}.'
    citation = f'[{court} {when} 선고 {values["사건번호"]} {decision_type}]'
    data = {'pageTitle': title[1], 'citation': citation, 'sections': sections}
    kind = 'prec' if domain == 'precedent' else 'detc'
    result = finish(dict(target, lookupKey=key), kind, str(seq), direct_url(kind, str(seq)), data, [])
    if not result['ok']:
        raise ValueError(result['reason'])
    record = result['rec']
    record['officialCaseNumber'] = values['사건번호']
    record['retrieval'] = {'method': 'korean-law:get_decision_text', 'domain': domain, 'full': True,
                           'sourceTextSha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
    if quality:
        record['retrieval']['bodyQuality'] = quality
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('response', type=Path)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--seq', required=True)
    parser.add_argument('--domain', choices=('precedent', 'constitutional'), default='precedent')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding='utf-8'))
    matches = [item for item in registry['cases'] if item['id'] == args.id]
    if len(matches) != 1:
        parser.error('Expected exactly one existing registered target')
    record = record_from_api(json.loads(args.response.read_text(encoding='utf-8')), matches[0], args.seq, args.domain)
    if args.output.exists():
        parser.error('Output already exists; retain the existing source and choose another path')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    print(f'{record["id"]}: {len(record["sections"][-1]["text"])} official full-text characters retained')


if __name__ == '__main__':
    main()
