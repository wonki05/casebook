"""Merged review files preserve both correction formats across one reimport."""
import copy
import tempfile
import unittest
from pathlib import Path

import openpyxl

from add_cases import make_entry
from standard_xlsx import SHEETS, assign_toc, plan_import, read_workbook


class MixedCorrectionImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'book.xlsx'
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for index, sheet in enumerate(SHEETS, start=1):
            ws = wb.create_sheet(sheet)
            ws.append(['번호', '제목', '판례 정보', '쟁점', '선정이유', '요지'])
            ws.append([1, sheet + ' 제목', f'대법원 2020-01-02 선고 2019다{index}',
                       sheet + ' 쟁점 오기', sheet + ' 이유', sheet + ' 요지 오기'])
        wb.save(self.path)
        wb.close()
        self.overrides = {
            'rows': {'민법:2': {'evidence': ['민법 정정 근거'], 'reason': '행별 정정',
                             'textCorrections': {'holdings': [{'before': '요지 오기', 'after': '요지 정정'}]}}},
            'textCorrections': {
                '민법:2': {'evidence': ['민법 별도 근거'], 'reason': '연산 정정',
                         'changes': [{'op': 'replace', 'field': 'issues', 'from': '쟁점 오기', 'to': '쟁점 정정'}]},
                '형법:2': {'evidence': ['형법 정정 근거'], 'reason': '형법 연산 정정',
                         'changes': [{'op': 'replace', 'field': 'holdings', 'from': '요지 오기', 'to': '요지 정정'}]},
            },
        }
        self.toc = {subject: [{'id': f'{subject}-1', 'label': '제1장', 'children': []}]
                    for subject in SHEETS.values()}
        self.paths = {f'{sheet}:2': [f'{subject}-1'] for sheet, subject in SHEETS.items()}

    def catalog(self, reg, overrides=None):
        result = read_workbook(self.path, reg, overrides)
        self.assertFalse(result['conflicts'])
        return assign_toc(result, reg, self.toc, self.paths)

    def test_both_formats_keep_separate_evidence_and_originals_through_reimport(self):
        original_book = self.path.read_bytes()
        review = copy.deepcopy(self.overrides)
        empty = {'cases': []}
        raw_reg, _ = plan_import(empty, self.toc, self.catalog(empty), make_entry)
        raw_civil = next(c for c in raw_reg['cases'] if c['subject'] == 'civil')

        catalog = self.catalog(raw_reg, self.overrides)
        merged_reg, report = plan_import(raw_reg, self.toc, catalog, make_entry)
        civil = next(c for c in merged_reg['cases'] if c['subject'] == 'civil')
        criminal = next(c for c in merged_reg['cases'] if c['subject'] == 'criminal')
        self.assertEqual(civil['standardSource']['issues'][0]['text'], '민법 쟁점 정정')
        self.assertEqual(civil['standardSource']['holdings'][0]['text'], '민법 요지 정정')
        self.assertEqual(criminal['standardSource']['holdings'][0]['text'], '형법 요지 정정')
        self.assertEqual(civil['standard']['sourceReview']['correctedSourceValues'], {'holdings': '민법 요지 오기'})
        self.assertEqual(civil['standard']['sourceReview']['evidence'], ['민법 정정 근거'])
        self.assertEqual(civil['standard']['textCorrections']['evidence'], ['민법 별도 근거'])
        self.assertEqual(civil['standardSourceHistory'], [raw_civil['standardSource']])
        self.assertEqual(len(report['textCorrections']), 2)
        self.assertEqual(len(report['sourceAnomalies']), 1)

        again, again_report = plan_import(merged_reg, self.toc,
                                         self.catalog(merged_reg, self.overrides), make_entry)
        self.assertEqual(again, merged_reg)
        self.assertEqual(again_report['changed'], [])
        self.assertEqual(self.overrides, review)
        self.assertEqual(self.path.read_bytes(), original_book)

    def test_dropping_all_study_fields_omits_the_empty_source(self):
        overrides = {'rows': {}, 'textCorrections': {
            '형법:2': {'reason': '다른 재판의 셀 제외', 'evidence': ['대조 근거'],
                     'changes': [{'op': 'drop', 'field': 'issues'}, {'op': 'drop', 'field': 'holdings'}]}}}
        catalog = self.catalog({'cases': []}, overrides)
        criminal = next(c for c in catalog['candidates'] if c['subject'] == 'criminal')
        self.assertNotIn('standardSource', criminal)
        self.assertEqual(len(criminal['standard']['textCorrections']['changes']), 2)


if __name__ == '__main__':
    unittest.main()
