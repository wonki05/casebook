"""A row whose cells run two judgments together is split into a new placement without rewording any source line,
and a reviewed identity swap never links a decision ID that is still live on another placement."""
import tempfile
import unittest
from pathlib import Path

import openpyxl

from add_cases import make_entry
from case_identity import identity
from standard_xlsx import SHEETS, plan_import, read_workbook

HEADER = ['번호', '제목', '판례 정보', '쟁점', '선정이유', '판결(결정)요지']
EVIDENCE = ['https://www.law.go.kr/LSW/precInfoP.do?precSeq=1']
ISSUES = '갑 사건 쟁점\n1. 을 사건 쟁점 하나\n2. 을 사건 쟁점 둘'
HOLDINGS = '갑 사건 요지 하나\n갑 사건 요지 둘\n1. 을 사건 요지'
REASON = '을 사건을 확인한 결정이다.'
SPLIT = {'caseNumber': '2021다2', 'date': '2022-03-04', 'decisionType': '판결', 'title': '을 사건',
         'tocPath': ['mb-1'], 'lines': {'issues': [1, 2], 'holdings': [2]}, 'selectionReason': True,
         'evidence': EVIDENCE, 'reason': '번호가 이어 붙은 행'}


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


class SplitOffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'book.xlsx'
        make_workbook(self.path, [
            [1, '앞 사건', '대법원 2019-01-02 선고 2018다1', '앞 쟁점', '앞 이유', '앞 요지'],
            [2, '갑 사건', '대법원 2020-05-06 선고 2020다1', ISSUES, REASON, HOLDINGS]])
        wb = openpyxl.load_workbook(self.path)
        wb['민법'].cell(3, 3).hyperlink = 'https://example.com/case-a'
        wb.save(self.path)

    def read(self, patch=None):
        rows = {'민법:3': patch} if patch is not None else {}
        catalog = read_workbook(self.path, {'cases': []}, {'rows': rows})
        self.assertFalse(catalog['conflicts'])
        return catalog, {c['standard']['entryId']: c for c in catalog['candidates'] if c['subject'] == 'civil'}

    def test_split_keeps_every_line_and_moves_the_reason(self):
        catalog, cands = self.read({'evidence': EVIDENCE, 'reason': '분리', 'splitOff': [SPLIT]})
        self.assertEqual(set(cands), {'민법:2', '민법:3', '민법:3/2'})
        base, part = cands['민법:3'], cands['민법:3/2']
        self.assertEqual(base['standardSource']['issues'][0]['text'], '갑 사건 쟁점')
        self.assertEqual(part['standardSource']['issues'][0]['text'], '1. 을 사건 쟁점 하나\n2. 을 사건 쟁점 둘')
        self.assertEqual(base['standardSource']['holdings'][0]['text'], '갑 사건 요지 하나\n갑 사건 요지 둘')
        self.assertEqual(part['standardSource']['holdings'][0]['text'], '1. 을 사건 요지')
        # 남은 줄과 떼어낸 줄을 다시 합치면 원래 줄 전체다.
        self.assertEqual(sorted((base['standardSource']['issues'][0]['text'] + '\n' + part['standardSource']['issues'][0]['text']).split('\n')),
                         sorted(ISSUES.split('\n')))
        self.assertEqual((base['selectionReason'], part['selectionReason']), ('', REASON))
        self.assertTrue(part['newPlacement'])
        self.assertNotIn('newPlacement', base)
        self.assertEqual((part['caseNumber'], part['date'], part['title']), ('2021다2', '2022-03-04', '을 사건'))
        self.assertNotEqual(part['decisionId'], base['decisionId'])
        self.assertEqual(part['standard']['entryId'], '민법:3/2')
        self.assertEqual(part['standard']['splitFrom'], '민법:3')
        self.assertAlmostEqual(part['standard']['order'], base['standard']['order'] + 0.1)
        self.assertEqual(part['identityReview']['evidence'], EVIDENCE)
        self.assertEqual(part['standard']['sourceReview']['splitFrom'], '민법:3')
        self.assertEqual(base['standard']['sourceUrl'], 'https://example.com/case-a')
        self.assertNotIn('sourceUrl', part['standard'])   # 인용 셀의 링크는 원래 행의 재판을 가리킨다
        # 원래 셀 전체는 정정 전 값으로 남는다.
        review = base['standard']['sourceReview']
        self.assertEqual(review['correctedSourceValues'], {'issues': ISSUES, 'holdings': HOLDINGS, 'selectionReason': REASON})
        self.assertEqual(review['textCorrections'][0]['field'], 'splitOff')
        self.assertEqual(review['textCorrections'][0]['newEntryId'], '민법:3/2')
        self.assertNotIn('identityReview', base)   # 원래 행의 식별은 바뀌지 않았다
        self.assertEqual(len(catalog['sourceAnomalies']), 1)
        # 통합문서 셀은 그대로다.
        ws = openpyxl.load_workbook(self.path)['민법']
        self.assertEqual((ws.cell(3, 4).value, ws.cell(3, 5).value, ws.cell(3, 6).value), (ISSUES, REASON, HOLDINGS))

    def test_split_without_moving_the_reason_leaves_it_on_the_base_row(self):
        spec = {k: v for k, v in SPLIT.items() if k != 'selectionReason'}
        _, cands = self.read({'evidence': EVIDENCE, 'splitOff': [spec]})
        self.assertEqual(cands['민법:3']['selectionReason'], REASON)
        self.assertEqual(cands['민법:3/2']['selectionReason'], '')   # 원래 줄에 선정이유가 없으면 비어 있다(복제하지 않는다)

    def test_split_runs_together_with_a_text_correction(self):
        _, cands = self.read({'evidence': EVIDENCE, 'splitOff': [SPLIT],
                              'textCorrections': {'holdings': [{'before': '요지 하나', 'after': '요지 일'}]}})
        self.assertEqual(cands['민법:3']['standardSource']['holdings'][0]['text'], '갑 사건 요지 일\n갑 사건 요지 둘')
        fields = [item['field'] for item in cands['민법:3']['standard']['sourceReview']['textCorrections']]
        self.assertEqual(fields, ['splitOff', 'holdings'])

    def test_invalid_splits_are_rejected(self):
        bad = [
            {'splitOff': [SPLIT]},   # 근거 없음
            {'evidence': EVIDENCE, 'splitOff': [{**SPLIT, 'lines': {'issues': [9], 'holdings': [2]}}]},   # 없는 줄
            {'evidence': EVIDENCE, 'splitOff': [{**SPLIT, 'lines': {'issues': [0, 1, 2], 'holdings': [2]}}]},   # 남는 줄 없음
            {'evidence': EVIDENCE, 'splitOff': [{**SPLIT, 'lines': {'issues': [True], 'holdings': [2]}}]},   # 정수가 아님
            {'evidence': EVIDENCE, 'splitOff': [{**SPLIT, 'lines': {'facts': [1]}}]},   # 없는 칸
            {'evidence': EVIDENCE, 'splitOff': [{k: v for k, v in SPLIT.items() if k != 'tocPath'}]},
            {'evidence': EVIDENCE, 'splitOff': [{k: v for k, v in SPLIT.items() if k != 'evidence'}]},
        ]
        for patch in bad:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.read(patch)


class PlanImportTests(unittest.TestCase):
    def setUp(self):
        self.toc = {'civil': [{'id': 'mb-1', 'label': '총칙', 'children': []},
                              {'id': 'mb-2', 'label': '물권', 'children': []}]}
        self.reg = {'cases': []}

    def existing(self, number, date, title, path=('mb-1',)):
        entry = make_entry(self.reg, self.toc, 'standard', 'civil', number, date, title, list(path),
                           court='대법원', decision_type='판결')
        self.reg['cases'].append(entry)
        return entry

    def candidate(self, row, number, date, title, path=('mb-1',), **extra):
        c = {'subject': 'civil', 'court': '대법원', 'caseNumber': number, 'date': date,
             'decisionType': '판결', 'title': title, 'tocPath': list(path), 'sheet': '민법', 'row': row,
             'selectionReason': '', 'standard': {'edition': '2026', 'entryId': f'민법:{row}', 'order': row - 1,
                                                 'removed': False, 'sheet': '민법', 'row': row},
             'standardSource': {'verified': True, 'book': '표준판례', 'edition': '2026', 'file': 'source.xlsx',
                                'format': 'xlsx', 'sheet': '민법', 'rows': [row], 'preferred': True,
                                'issues': [{'n': '', 'text': f'쟁점 {row}'}]}}
        c.update(extra)
        c.update(identity({**c, 'decisionDate': date}))
        return c

    def catalog(self, candidates):
        return {'source': {'file': 'source.xlsx', 'edition': '2026'}, 'candidates': candidates,
                'subjects': {'civil': {'sheet': '민법', 'rows': len(candidates)}},
                'rawIdentities': [{'subject': 'civil', 'court': c['court'], 'caseNumber': c['caseNumber'], 'sheet': '민법'}
                                  for c in candidates]}

    def split_candidates(self, base_number='2020다1', base_date='2020-05-06'):
        base = self.candidate(2, base_number, base_date, '갑 사건')
        part = self.candidate(2, '2021다2', '2022-03-04', '을 사건', newPlacement=True)
        part['standard'] = {**part['standard'], 'entryId': '민법:2/2', 'order': 1.1, 'splitFrom': '민법:2'}
        part['identityReview'] = {'evidence': EVIDENCE, 'reason': '분리'}
        return base, part

    def test_split_part_is_added_once_and_matched_by_entry_id_afterwards(self):
        old = self.existing('2020다1', '2020-05-06', '갑 사건')
        base, part = self.split_candidates()
        catalog = self.catalog([base, part])
        result, report = plan_import(self.reg, self.toc, catalog, make_entry)
        self.assertEqual(len(result['cases']), 2)
        self.assertEqual(result['cases'][0]['id'], old['id'])
        added = result['cases'][1]
        self.assertEqual((added['caseNumber'], added['standard']['entryId']), ('2021다2', '민법:2/2'))
        self.assertEqual([c['entryId'] for c in report['added']], ['민법:2/2'])
        self.assertEqual(added['standard']['identityReview']['evidence'], EVIDENCE)
        again, again_report = plan_import(result, self.toc, catalog, make_entry)
        self.assertEqual(result, again)   # 다시 가져와도 같은 배치를 찾아 새로 늘리지 않는다
        self.assertFalse(again_report['added'])

    def test_split_part_never_takes_over_an_existing_placement_of_the_same_decision(self):
        # 같은 재판의 기존 배치가 있어도 떼어낸 배치는 그것을 가로채지 않고 자기 entryId 로만 찾는다.
        old = self.existing('2021다2', '2022-03-04', '을 사건', ('mb-2',))
        base, part = self.split_candidates()
        result, report = plan_import(self.reg, self.toc, self.catalog([base, part]), make_entry)
        untouched = next(c for c in result['cases'] if c['id'] == old['id'])
        self.assertEqual(untouched['tocPath'], ['mb-2'])
        self.assertNotEqual(untouched['standard']['entryId'], '민법:2/2')
        added = [c for c in result['cases'] if c['standard']['entryId'] == '민법:2/2']
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]['decisionId'], untouched['decisionId'])   # 같은 재판의 추가 배치다
        classes = {c['entryId']: c['classification'] for c in report['added']}
        self.assertEqual(classes, {'민법:2': 'new-decision', '민법:2/2': 'additional-placement'})

    def swap(self, first, second):
        a_row = self.candidate(2, second['caseNumber'], second['date'], first['title'],
                               matchExistingId=first['id'], identityReview={'evidence': EVIDENCE, 'reason': '인용 바뀜'})
        b_row = self.candidate(3, first['caseNumber'], first['decisionDate'], second['title'],
                               matchExistingId=second['id'], identityReview={'evidence': EVIDENCE, 'reason': '인용 바뀜'})
        return a_row, b_row

    def test_swapped_citations_do_not_alias_decision_ids_that_stay_live(self):
        a = self.existing('2000다123', '2000-01-01', '갑 제목')
        b = self.existing('2001다456', '2001-02-02', '을 제목', ('mb-2',))
        a_before, b_before = a['decisionId'], b['decisionId']
        a_row, b_row = self.swap(a, {'caseNumber': '2001다456', 'date': '2001-02-02', 'title': '을 제목', 'id': b['id']})
        b_row['caseNumber'], b_row['date'] = '2000다123', '2000-01-01'
        for c in (a_row, b_row):
            c.update(identity({**c, 'decisionDate': c['date']}))
        a_row['tocPath'], b_row['tocPath'] = ['mb-1'], ['mb-2']
        result, report = plan_import(self.reg, self.toc, self.catalog([a_row, b_row]), make_entry)
        new_a, new_b = result['cases']
        self.assertEqual((new_a['decisionId'], new_b['decisionId']), (b_before, a_before))   # 서로 바뀌었다
        aliases = result.get('identityAliases', {})
        self.assertNotIn(a_before, aliases)   # 아직 쓰이는 재판 ID 는 다른 재판으로 이어 붙이지 않는다
        self.assertNotIn(b_before, aliases)
        self.assertNotIn(b_before, new_a.get('legacyIds', []))
        self.assertNotIn(a_before, new_b.get('legacyIds', []))
        self.assertEqual(len(report['identityCorrections']), 2)
        for correction in report['identityCorrections']:
            self.assertIn('aliasSkipped', correction)
        self.assertEqual(new_a['identityHistory'][0]['previousIdentity']['decisionId'], a_before)   # 정정 이력은 남는다
        again, _ = plan_import(result, self.toc, self.catalog([a_row, b_row]), make_entry)
        self.assertEqual(result, again)

    def test_correction_to_an_unused_identity_still_aliases_the_old_decision(self):
        old = self.existing('2000다123', '2000-01-01', '갑 제목')
        row = self.candidate(2, '2000다123', '2000-01-02', '갑 제목', matchExistingId=old['id'],
                             identityReview={'evidence': EVIDENCE, 'reason': '선고일 보정'})
        result, report = plan_import(self.reg, self.toc, self.catalog([row]), make_entry)
        self.assertEqual(result['identityAliases'][old['decisionId']], row['decisionId'])
        self.assertIn(old['decisionId'], result['cases'][0]['legacyIds'])
        self.assertNotIn('aliasSkipped', report['identityCorrections'][0])


if __name__ == '__main__':
    unittest.main()
