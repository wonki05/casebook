"""Tests for tools/check_fulltext_lines.py (decision texts that lost their line breaks)."""
import json
from pathlib import Path
import tempfile
import unittest

from check_fulltext_lines import FETCHED, inspect, scan, validation_errors

PAGE = {'id': 'cc-page', 'kind': 'detc', 'sections': [
    {'heading': '【판시사항】', 'text': '1. 첫째 여부(적극)\n2. 둘째 여부(소극)'},
    {'heading': '【전문】', 'text': ''},
    {'heading': '【당 사 자】', 'text': '청 구 인 홍길동'},
    {'heading': '【주 문】', 'text': '이 사건 심판청구를 기각한다.'},
    {'heading': '【이 유】', 'text': '1. 사건개요\n' + '가. 사실관계 문장입니다. ' * 40 + '\n2. 판단\n' + '판단 문장입니다. ' * 40}]}
API = {'id': 'cc-api', 'kind': 'detc', 'retrieval': {'method': 'korean-law:get_decision_text'}, 'sections': [
    {'heading': '【판시사항】', 'text': '1. 첫째 여부(적극)2. 둘째 여부(소극)\n\n'},
    {'heading': '【전문】', 'text': '【당 사 자】청구인 홍길동【주 문】이 사건 심판청구를 기각한다.【이 유】1. 사건개요'
                                  + '가. 사실관계 문장입니다. ' * 80 + '2. 판단' + '판단 문장입니다. ' * 80 + '\n'}]}


def codes(record, notes=False):
    return [code for code, _ in inspect(record, notes)]


class LineCheckTests(unittest.TestCase):
    def test_page_collected_record_passes(self):
        self.assertEqual(codes(PAGE, notes=True), [])

    def test_flat_api_record_is_flagged(self):
        self.assertEqual(codes(API), ['one-line-body', 'inline-section-markers'])
        self.assertEqual(codes(API, notes=True), ['one-line-body', 'glued-items', 'inline-section-markers'])

    def test_short_flat_record_is_caught_by_markers(self):
        short = {'kind': 'detc', 'sections': [{'heading': '【전문】', 'text': '사 건 2021헌마1 【주 문】각하한다.【이 유】부적법하다.'}]}
        self.assertEqual(codes(short), ['inline-section-markers'])

    def test_markers_on_their_own_lines_are_not_run_on(self):
        ok = {'kind': 'detc', 'sections': [{'heading': '【전문】', 'text': '청구인 홍길동\n【주 문】\n각하한다.\n[이 유]\n부적법하다.'}]}
        self.assertEqual(codes(ok), [])

    def test_long_paragraphs_with_breaks_pass(self):
        text = '\n'.join(['긴 문단입니다. ' * 120] * 5)  # 5 paragraphs of ~1,100 characters
        self.assertEqual(codes({'kind': 'detc', 'sections': [{'heading': '【이 유】', 'text': text}]}), [])

    def test_scan_filters_kind_and_skips_missing_and_supplements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prec = dict(API, id='sc-api', kind='prec')
            for name, value in [('cc-api.json', API), ('cc-page.json', PAGE), ('sc-api.json', prec),
                                ('cc-x.missing.json', {'id': 'cc-x'}), ('cc-page.supplement.json', API)]:
                (root / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            self.assertEqual([item['id'] for item in scan(root)], ['cc-api'])
            self.assertEqual([item['id'] for item in scan(root, None)], ['cc-api', 'sc-api'])
            errors = validation_errors(root)
            self.assertEqual(len(errors), 1)
            self.assertIn('fetch_lawgo.py --id cc-api --force', errors[0])

    def test_collected_constitutional_texts_keep_line_breaks(self):
        """Corpus gate: every collected constitutional decision keeps its sections and paragraphs."""
        if not FETCHED.is_dir():
            self.skipTest('no data/fetched')
        found = scan(FETCHED)
        self.assertEqual([], [(item['id'], [p['code'] for p in item['problems']]) for item in found])


class MismatchedOrderHeadingTests(unittest.TestCase):
    """build_data.brackets(): a page whose order heading closes with 〕 holds the order inside the heading."""

    def test_order_moves_out_of_heading_unchanged(self):
        from build_data import brackets
        order = '1. 심판청구를 모두 기각한다.2. 나머지 심판청구를 각하한다.'
        self.assertEqual(brackets([{'heading': '【주 문〕' + order, 'text': ''}]),
                         [{'heading': '[주 문]', 'text': order}])
        self.assertEqual(brackets([{'heading': '【주 문〕', 'text': order}]),
                         [{'heading': '[주 문]', 'text': order}])
        self.assertEqual(brackets([{'heading': '【이 유】', 'text': '1. 사건개요'}]),
                         [{'heading': '[이 유]', 'text': '1. 사건개요'}])


if __name__ == '__main__':
    unittest.main()
