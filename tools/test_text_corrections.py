"""승인된 텍스트 정정(textCorrections): 정확히 일치할 때만 적용하고, 원문 이력과 감사 기록을 남기며, 다시 가져와도 같은 결과가 나온다."""
import copy
import tempfile
import unittest
from pathlib import Path

import openpyxl

from add_cases import make_entry
from standard_xlsx import SHEETS, apply_text_corrections, assign_toc, plan_import, read_workbook

TOC = {subject: [{'id': f'{subject}-1', 'label': '1장', 'children': []}] for subject in SHEETS.values()}
PATHS = {f'{sheet}:2': [f'{subject}-1'] for sheet, subject in SHEETS.items()}
CITATIONS = {'민법': '대법원 2000-01-01 선고 2000다123', '상법': '대법원 2001-01-01 선고 2001다124',
             '형법': '대법원 2002-02-02 선고 2002도125', '헌법': '대법원 2003-01-01 선고 2003다126',
             '행정법': '대법원 2005-01-01 선고 2005두128'}
ROW = ('제목 오탈자', CITATIONS['형법'], '쟁점 문장\n<요지>  요지 본문', '선정이 운에 대한 설명', None)


def make_workbook(path, criminal=ROW):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet in SHEETS:
        ws = wb.create_sheet(sheet)
        ws.append(['번호', '제목', '판례 정보', '쟁점', '선정이유', '요지'])
        if sheet == '형법':
            title, cite, issues, reason, holdings = criminal
        else:
            title, cite, issues, reason, holdings = (f'{sheet} 제목', CITATIONS[sheet], f'{sheet} 쟁점', f'{sheet} 이유', f'{sheet} 요지')
        ws.append(['1', title, cite, issues, reason, holdings])
    wb.save(path)


def overrides(fixes=None):
    return {'rows': {}, 'legacyIdentityCorrections': {}, 'legacySourceExclusions': {}, 'textCorrections': fixes or {}}


def review(*changes):
    return {'형법:2': {'reason': '시험 정정', 'evidence': ['시험 근거'], 'changes': list(changes)}}


FIXES = review({'op': 'replace', 'field': 'title', 'from': '오탈자', 'to': '정정', 'kind': '시험'},
               {'op': 'replace', 'field': 'selectionReason', 'from': '운에', 'to': '운데'},
               {'op': 'split', 'field': 'issues', 'at': '\n<요지>  ', 'into': 'holdings'},
               {'op': 'replace', 'field': 'issues', 'from': '문장', 'to': '문장 ', 'kind': '띄어쓰기'})


class TextCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / 'workbook.xlsx'
        make_workbook(self.path)

    def read(self, fixes=None, reg=None):
        return read_workbook(self.path, reg or {'cases': []}, overrides(fixes))

    def criminal(self, catalog):
        return next(c for c in catalog['candidates'] if c['subject'] == 'criminal')

    def test_replace_and_split_change_only_the_approved_text_and_record_it(self):
        raw = self.criminal(self.read())
        cand = self.criminal(self.read(FIXES))
        self.assertEqual(raw['title'], '제목 오탈자')
        self.assertEqual(cand['title'], '제목 정정')
        self.assertEqual(cand['selectionReason'], '선정이 운데 대한 설명')
        source = cand['standardSource']
        self.assertEqual(source['issues'], [{'n': '', 'text': '쟁점 문장 '}])
        self.assertEqual(source['holdings'], [{'n': '', 'text': '요지 본문'}])
        record = cand['standard']['textCorrections']
        self.assertEqual(record['evidence'], ['시험 근거'])
        self.assertEqual([c['op'] for c in record['changes']], ['replace', 'replace', 'split', 'replace'])
        self.assertEqual(record['changes'][0]['kind'], '시험')
        for other in (c for c in self.read(FIXES)['candidates'] if c['subject'] != 'criminal'):
            self.assertNotIn('textCorrections', other['standard'])
        self.assertEqual(self.read(FIXES)['textCorrections'][0]['row'], 2)

    def test_drop_removes_only_that_cell_and_keeps_the_rest(self):
        fixes = review({'op': 'drop', 'field': 'issues'})
        make_workbook(self.path, ('제목', CITATIONS['형법'], '다른 재판의 쟁점', '이유', '요지 본문'))
        source = self.criminal(self.read(fixes))['standardSource']
        self.assertNotIn('issues', source)
        self.assertEqual(source['holdings'], [{'n': '', 'text': '요지 본문'}])

    def test_unmatched_ambiguous_or_unreviewed_corrections_stop_the_import(self):
        make_workbook(self.path, ('가가 나나', CITATIONS['형법'], '쟁점 쟁점', '이유', '요지'))
        cases = {
            'missing text': review({'op': 'replace', 'field': 'title', 'from': '없는 말', 'to': '다른 말'}),
            'ambiguous': review({'op': 'replace', 'field': 'issues', 'from': '쟁점', 'to': '논점'}),
            'wrong count': review({'op': 'replace', 'field': 'title', 'from': '가', 'to': '라', 'count': 3}),
            'no evidence': {'형법:2': {'changes': [{'op': 'replace', 'field': 'title', 'from': '가가', 'to': '라라'}]}},
            'unknown field': review({'op': 'replace', 'field': 'caseNumber', 'from': '2002', 'to': '2003'}),
            'row not in workbook': {'형법:9': review({'op': 'drop', 'field': 'issues'})['형법:2']},
            'drop of absent cell': review({'op': 'drop', 'field': 'facts'}),
            'split without marker': review({'op': 'split', 'field': 'issues', 'at': '<요지>', 'into': 'holdings'}),
            'empty title': review({'op': 'replace', 'field': 'title', 'from': '가가 나나', 'to': ' '}),
        }
        for name, fixes in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.read(fixes)

    def test_counted_replacement_applies_every_listed_occurrence(self):
        make_workbook(self.path, ('가가 나나', CITATIONS['형법'], '쟁점 쟁점', '이유', '요지'))
        fixes = review({'op': 'replace', 'field': 'issues', 'from': '쟁점', 'to': '논점', 'count': 2})
        self.assertEqual(self.criminal(self.read(fixes))['standardSource']['issues'][0]['text'], '논점 논점')

    def test_function_rejects_a_correction_that_changes_nothing(self):
        state = {'title': '제목', 'selectionReason': '', 'issues': None, 'facts': None, 'holdings': None}
        with self.assertRaises(ValueError):
            apply_text_corrections('형법:2', review({'op': 'replace', 'field': 'title', 'from': '제목', 'to': '제목'})['형법:2'], state)
        self.assertEqual(state['title'], '제목')

    def test_reimport_archives_the_uncorrected_source_and_is_idempotent(self):
        reg0 = {'cases': []}
        raw_catalog = assign_toc(self.read(), reg0, TOC, PATHS)
        reg1, _ = plan_import(reg0, TOC, raw_catalog, make_entry)
        before = copy.deepcopy(next(c for c in reg1['cases'] if c['subject'] == 'criminal'))
        self.assertEqual(before['title'], '제목 오탈자')
        self.assertNotIn('standardSourceHistory', before)

        catalog = assign_toc(self.read(FIXES, reg1), reg1, TOC, PATHS)
        reg2, report = plan_import(reg1, TOC, catalog, make_entry)
        after = next(c for c in reg2['cases'] if c['subject'] == 'criminal')
        self.assertEqual(after['id'], before['id'])
        self.assertEqual(after['decisionId'], before['decisionId'])
        self.assertEqual(after['title'], '제목 정정')
        self.assertEqual(after['selectionReason'], '선정이 운데 대한 설명')
        self.assertEqual(after['standardSourceHistory'], [before['standardSource']])
        self.assertEqual(after['standardSourceHistory'][0]['issues'][0]['text'], '쟁점 문장\n<요지>  요지 본문')
        self.assertEqual([r['id'] for r in report['changed']], [before['id']])
        self.assertEqual(len(report['textCorrections']), 1)

        again_catalog = assign_toc(self.read(FIXES, reg2), reg2, TOC, PATHS)
        reg3, again = plan_import(reg2, TOC, again_catalog, make_entry)
        self.assertEqual(reg3, reg2)
        self.assertEqual(again['changed'], [])


if __name__ == '__main__':
    unittest.main()
