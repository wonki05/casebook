"""Reviewed text corrections never touch the workbook cell and keep every original string."""
import tempfile
import unittest
from pathlib import Path

import openpyxl

from standard_xlsx import SHEETS, read_workbook

HEADER = ['번호', '제목', '판례 정보', '쟁점', '선정이유', '판결(결정)요지']
EVIDENCE = ['https://www.law.go.kr/LSW/precInfoP.do?precSeq=1']


def make_workbook(path, civil_rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for sheet in SHEETS:
        ws = wb.create_sheet(sheet)
        ws.append(HEADER)
        rows = civil_rows if sheet == '민법' else [[1, '다른 과목', '대법원 2020-01-02 선고 2019도1234', '쟁점', '이유', '요지']]
        for row in rows:
            ws.append(row)
    wb.save(path)


class TextCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'book.xlsx'
        self.rows = [
            [1, '계약금 (3) ： 특 별한 사정', '대법원 2024-01-04 선고 2022다256624', '쟁점 원문 육비', '선정이유 입칠채권 입칠채권', '요지 공동상속이들 원문'],
            [2, '분리 대상', '대법원 2024-02-04 선고 2022다256625', '쟁점 문장\n<판결요지>   판결요지 문장입니다.  ', '선정이유', None],
        ]
        make_workbook(self.path, self.rows)

    def read(self, patches):
        catalog = read_workbook(self.path, {'cases': []}, {'rows': patches})
        self.assertFalse(catalog['conflicts'])
        return {c['standard']['entryId']: c for c in catalog['candidates'] if c['subject'] == 'civil'}

    def test_corrections_apply_to_candidate_and_keep_complete_originals(self):
        cands = self.read({'민법:2': {'evidence': EVIDENCE, 'reason': '오탈자 정정', 'textCorrections': {
            'title': [{'before': '특 별한', 'after': '특별한'}],
            'issues': [{'before': '육비', 'after': '유익비'}],
            'selectionReason': [{'before': '입칠채권', 'after': '입질채권', 'count': 2}],
            'holdings': [{'before': '공동상속이들', 'after': '공동상속인들'}]}}})
        c = cands['민법:2']
        self.assertEqual(c['title'], '계약금 (3) ： 특별한 사정')
        self.assertEqual(c['standardSource']['issues'][0]['text'], '쟁점 원문 유익비')
        self.assertEqual(c['standardSource']['holdings'][0]['text'], '요지 공동상속인들 원문')
        self.assertEqual(c['selectionReason'], '선정이유 입질채권 입질채권')
        review = c['standard']['sourceReview']
        self.assertEqual(review['sourceTitle'], '계약금 (3) ： 특 별한 사정')
        self.assertEqual(review['correctedSourceValues'], {
            'title': '계약금 (3) ： 특 별한 사정', 'issues': '쟁점 원문 육비',
            'selectionReason': '선정이유 입칠채권 입칠채권', 'holdings': '요지 공동상속이들 원문'})
        self.assertEqual(len(review['textCorrections']), 4)
        self.assertEqual(review['evidence'], EVIDENCE)
        self.assertNotIn('identityReview', c)   # 글자 정정만 한 행은 식별 검토 행이 아니다
        # 통합문서 셀은 그대로다.
        ws = openpyxl.load_workbook(self.path)['민법']
        self.assertEqual(ws.cell(2, 6).value, '요지 공동상속이들 원문')

    def test_untouched_rows_have_no_review_and_identity_patch_keeps_its_review(self):
        cands = self.read({'민법:3': {'evidence': EVIDENCE, 'reason': '전원합의체', 'enBanc': True,
                                      'textCorrections': {'selectionReason': [{'before': '선정이유', 'after': '선정 이유'}]}}})
        self.assertNotIn('sourceReview', cands['민법:2']['standard'])
        c = cands['민법:3']
        self.assertTrue(c['enBanc'])
        self.assertEqual(c['identityReview']['evidence'], EVIDENCE)
        self.assertEqual(c['standard']['sourceReview']['correctedSourceValues'], {'selectionReason': '선정이유'})

    def test_move_to_holdings_splits_marker_and_keeps_original(self):
        cands = self.read({'민법:3': {'evidence': EVIDENCE, 'reason': '칸 구조', 'moveToHoldings': {'marker': '<판결요지>'}}})
        c = cands['민법:3']
        self.assertEqual(c['standardSource']['issues'], [{'n': '', 'text': '쟁점 문장'}])
        self.assertEqual(c['standardSource']['holdings'], [{'n': '', 'text': '판결요지 문장입니다.'}])
        review = c['standard']['sourceReview']
        self.assertEqual(review['correctedSourceValues']['issues'], '쟁점 문장\n<판결요지>   판결요지 문장입니다.  ')
        self.assertEqual(review['textCorrections'][0]['field'], 'issues→holdings')

    def test_wrong_count_missing_text_empty_cell_and_missing_evidence_are_rejected(self):
        bad = [
            {'evidence': EVIDENCE, 'textCorrections': {'selectionReason': [{'before': '입칠채권', 'after': '입질채권'}]}},   # 2회인데 count 1
            {'evidence': EVIDENCE, 'textCorrections': {'holdings': [{'before': '없는 문구', 'after': 'x'}]}},
            {'evidence': EVIDENCE, 'textCorrections': {'holdings': [{'before': 'a', 'after': 'a'}]}},
            {'evidence': EVIDENCE, 'textCorrections': {'unknown': [{'before': 'a', 'after': 'b'}]}},
            {'textCorrections': {'holdings': [{'before': '원문', 'after': '정문'}]}},
        ]
        for patch in bad:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.read({'민법:2': patch})
        with self.assertRaises(ValueError):   # 비어 있는 요지 칸
            self.read({'민법:3': {'evidence': EVIDENCE, 'textCorrections': {'holdings': [{'before': 'a', 'after': 'b'}]}}})
        with self.assertRaises(ValueError):   # 요지 칸이 있으면 이동 불가
            self.read({'민법:2': {'evidence': EVIDENCE, 'moveToHoldings': {'marker': '쟁점'}}})
        with self.assertRaises(ValueError):   # 표지가 없음
            self.read({'민법:3': {'evidence': EVIDENCE, 'moveToHoldings': {'marker': '<없음>'}}})


if __name__ == '__main__':
    unittest.main()
