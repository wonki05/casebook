"""Workbook excerpts share exact decisions without losing source/placement data."""
import copy
import unittest

import build_data
import case_identity as ci
from test_identity import record, standard
import test_identity as fixtures
import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


def workbook(row=2, **fields):
    return {'verified': True, 'book': '표준판례', 'edition': '2026년',
            'file': 'fixture.xlsx', 'format': 'xlsx', 'sheet': '민법',
            'rows': [row], 'sha256': 'fixture-digest', 'preferred': True,
            **fields}


def resolved(records):
    identities = {r['id']: ci.identity(r) for r in records}
    return ci.standard_sources_by_decision(records, identities)[identities[records[0]['id']]['decisionId']]


class WorkbookSourceTests(unittest.TestCase):
    def test_xlsx_uses_real_sheet_rows_and_separate_facts(self):
        src = workbook(facts=[{'n': '', 'text': '  원문\n줄바꿈  '}])
        ci.validate_standard_source(src)
        for changes in ({'rows': []}, {'rows': [True]}, {'rows': [0]},
                        {'sheet': ''}, {'pages': [2]}, {'preferred': 'true'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ci.validate_standard_source({**src, **changes})
        self.assertEqual(src['facts'][0]['text'], '  원문\n줄바꿈  ')

    def test_preferred_workbook_replaces_only_provided_fields(self):
        legacy = record(standardSource=standard(
            holdings=[{'n': '', 'text': '이전 요지'}], statutes=['이전 참조조문']))
        latest = record(id='latest', standardSource=workbook(
            holdings=[{'n': '', 'text': '  현재 요지\n원문 그대로  '}]))
        before = copy.deepcopy([legacy, latest])
        fields = resolved([legacy, latest])
        self.assertEqual(fields['holdings']['value'], latest['standardSource']['holdings'])
        self.assertEqual(fields['statutes']['value'], ['이전 참조조문'])
        self.assertEqual([legacy, latest], before)

    def test_same_workbook_rows_combine_in_source_order_and_keep_provenance(self):
        first = record(id='first', title='첫 단원', standardSource=workbook(2,
            issues=[{'n': '', 'text': '첫 쟁점'}], holdings=[{'n': '', 'text': '공통 요지'}]))
        second = record(id='second', title='다른 단원', standardSource=workbook(8,
            issues=[{'n': '', 'text': '다른 쟁점'}], holdings=[{'n': '', 'text': '공통 요지'}]))
        fields = resolved([second, first])
        self.assertEqual([x['text'] for x in fields['issues']['value']], ['첫 쟁점', '다른 쟁점'])
        self.assertEqual(fields['holdings']['value'], [{'n': '', 'text': '공통 요지'}])
        self.assertEqual([s['rows'] for s in fields['holdings']['sources']], [[2], [8]])
        self.assertEqual([first['title'], second['title']], ['첫 단원', '다른 단원'])

    def test_distinct_workbooks_and_same_filename_different_hash_do_not_merge(self):
        a = record(standardSource=workbook(holdings=[{'n': '', 'text': 'A'}]))
        for change in ({'file': 'other.xlsx'}, {'sha256': 'changed-digest'}, {'edition': '다른 판본'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                b = record(id='second', standardSource={**workbook(holdings=[{'n': '', 'text': 'B'}]), **change})
                resolved([a, b])

    def test_archive_is_preserved_without_overriding_current_source(self):
        old = workbook(holdings=[{'n': '', 'text': '보관 요지'}])
        current = workbook(holdings=[{'n': '', 'text': '현재 요지'}])
        r = record(standardSource=current, standardSourceHistory=[old])
        before = copy.deepcopy(r)
        self.assertEqual(resolved([r])['holdings']['value'], current['holdings'])
        self.assertEqual(r, before)

    def test_explicit_empty_preferred_field_stays_empty(self):
        a = record(standardSource=standard(holdings=[{'n': '', 'text': '이전 요지'}]))
        b = record(id='second', standardSource=workbook(holdings=[]))
        self.assertEqual(resolved([a, b])['holdings']['value'], [])

    def test_build_shares_fulltext_and_summary_but_keeps_standard_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = record(id='first', title='앞 단원', standard={'order': 2, 'removed': False},
                           legacyIds=['sc-2024da99999-20250102-judgment'],
                           standardSource=workbook(2, holdings=[{'n': '', 'text': '앞 요지'}]))
            second = record(id='second', title='뒤 단원', standard={'order': 1, 'removed': True},
                            standardSource=workbook(8, facts=[{'n': '', 'text': '원문 사실관계'}],
                                                    holdings=[{'n': '', 'text': '뒤 요지'}]))
            reg, toc, fetched, out = fixtures.CliAndBuildTests().fixture(root, [first, second])
            official = {'kind': 'prec', 'citation': '대법원 2025. 1. 2. 선고 2024다12345 판결',
                        'sections': [{'heading': '【이 유】', 'text': '공식 전문 그대로'}]}
            original = json.dumps(official, ensure_ascii=False).encode('utf-8')
            source_file = fetched / 'first.json'
            source_file.write_bytes(original)
            with patch.multiple(build_data, REG=str(reg), TOC_FILE=str(toc), FETCHED=str(fetched), OUT=str(out)), contextlib.redirect_stdout(io.StringIO()):
                build_data.build()
            data = json.loads(out.read_text(encoding='utf-8'))['cases']
            self.assertEqual([r['id'] for r in data], ['second', 'first'])
            for r in data:
                self.assertEqual(r['officialSourceId'], 'first')
                self.assertEqual(r['fullText'][0]['text'], '공식 전문 그대로')
                self.assertEqual([x['text'] for x in r['holdings']], ['앞 요지', '뒤 요지'])
                self.assertEqual(r['facts'], [{'n': '', 'text': '원문 사실관계'}])
                self.assertEqual(r['fieldSources']['facts']['type'], 'standard')
            self.assertTrue(data[0]['standard']['removed'])
            self.assertFalse(data[1]['standard']['removed'])
            self.assertEqual(data[1]['legacyIds'], first['legacyIds'])
            self.assertEqual(source_file.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
