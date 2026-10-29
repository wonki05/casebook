"""Meaningful safeguards for retained IDs, multiple placements and deletion."""
import copy
import unittest

from add_cases import make_entry
from case_identity import identity
from standard_xlsx import plan_import, assign_toc


class StandardImportTests(unittest.TestCase):
    def setUp(self):
        self.toc = {'civil': [{'id': 'mb-1', 'label': '총칙', 'children': []},
                              {'id': 'mb-2', 'label': '물권', 'children': []}]}
        self.reg = {'cases': []}
        self.old = make_entry(self.reg, self.toc, 'standard', 'civil', '2000다123',
                              '2000-01-01', '기존 제목', ['mb-1'], court='대법원', decision_type='판결')
        self.reg['cases'].append(self.old)

    def candidate(self, row=2, title='단원 제목', path=None, number='2000다123', date='2000-01-01'):
        c = {'subject': 'civil', 'court': '대법원', 'caseNumber': number, 'date': date,
             'decisionType': '판결', 'title': title, 'tocPath': path or ['mb-1'],
             'sheet': '민법', 'row': row, 'selectionReason': '원문 선정이유',
             'standard': {'edition': '2026', 'entryId': f'민법:{row}', 'order': row - 1,
                          'removed': False, 'sheet': '민법', 'row': row},
             'standardSource': {'verified': True, 'book': '표준판례', 'edition': '2026',
                  'file': 'source.xlsx', 'format': 'xlsx', 'sheet': '민법', 'rows': [row],
                  'preferred': True, 'issues': [{'n': '', 'text': f'원문  {row}\n내용'}]}}
        c.update(identity({**c, 'decisionDate': date}))
        return c

    def catalog(self, candidates, raw=None):
        return {'source': {'file': 'source.xlsx', 'edition': '2026'}, 'candidates': candidates,
                'subjects': {'civil': {'sheet': '민법', 'rows': len(candidates)}},
                'rawIdentities': raw if raw is not None else [
                    {'subject': 'civil', 'court': c['court'], 'caseNumber': c['caseNumber'], 'sheet': '민법'} for c in candidates]}

    def test_duplicate_decision_keeps_two_placements_and_exact_text(self):
        candidates = [self.candidate(), self.candidate(3, '다른 단원 제목', ['mb-2'])]
        result, report = plan_import(self.reg, self.toc, self.catalog(candidates), make_entry)
        self.assertEqual(len(result['cases']), 2)
        self.assertEqual(result['cases'][0]['id'], self.old['id'])
        self.assertEqual(result['cases'][0]['decisionId'], result['cases'][1]['decisionId'])
        self.assertEqual(result['cases'][1]['tocPath'], ['mb-2'])
        self.assertEqual(result['cases'][1]['standardSource']['issues'][0]['text'], '원문  3\n내용')
        self.assertEqual(report['added'][0]['classification'], 'additional-placement')
        self.assertEqual(self.reg['cases'][0]['title'], '기존 제목')
        again, _ = plan_import(result, self.toc, self.catalog(candidates), make_entry)
        self.assertEqual(result, again)

    def test_other_sheet_presence_is_not_deletion(self):
        raw = [{'subject': None, 'court': '대법원', 'caseNumber': '2000다123', 'sheet': '민사소송법'}]
        result, report = plan_import(self.reg, self.toc, self.catalog([], raw), make_entry)
        self.assertFalse(result['cases'][0]['standard']['removed'])
        self.assertEqual(len(report['relocatedPlacements']), 1)
        self.assertFalse(report['removed'])

    def test_reviewed_later_placement_is_reserved_before_earlier_fallback(self):
        early = self.candidate(2, '새 단원', ['mb-2'])
        later = self.candidate(3, '기존 제목', ['mb-1'])
        later['matchExistingId'] = self.old['id']
        later['identityReview'] = {'evidence': 'reviewed same chapter and judgment'}
        catalog = assign_toc(self.catalog([early, later]), self.reg, self.toc)
        self.assertNotIn('matchedId', early)
        self.assertEqual(later['matchedId'], self.old['id'])
        result, report = plan_import(self.reg, self.toc, catalog, make_entry)
        original = next(c for c in result['cases'] if c['id'] == self.old['id'])
        self.assertEqual(original['tocPath'], ['mb-1'])
        self.assertEqual(original['standard']['entryId'], '민법:3')
        self.assertEqual(report['added'][0]['entryId'], '민법:2')
        again, _ = plan_import(result, self.toc, catalog, make_entry)
        self.assertEqual(result, again)

    def test_two_reviewed_rows_cannot_reserve_one_placement(self):
        candidates = [self.candidate(), self.candidate(3)]
        for c in candidates:
            c['matchExistingId'] = self.old['id']
            c['identityReview'] = {'evidence': 'reviewed source'}
        with self.assertRaises(ValueError):
            plan_import(self.reg, self.toc, self.catalog(candidates), make_entry)

    def test_absent_decision_is_preserved_and_flagged(self):
        result, report = plan_import(self.reg, self.toc, self.catalog([]), make_entry)
        self.assertEqual(result['cases'][0]['id'], self.old['id'])
        self.assertEqual(result['cases'][0]['title'], self.old['title'])
        self.assertTrue(result['cases'][0]['standard']['removed'])
        self.assertEqual(len(report['removed']), 1)

    def test_reviewed_correction_preserves_alias(self):
        c = self.candidate(date='2000-01-02')
        c['matchExistingId'] = self.old['id']
        c['identityReview'] = {'evidence': 'official source', 'sourceCitation': 'raw citation'}
        result, report = plan_import(self.reg, self.toc, self.catalog([c]), make_entry)
        self.assertEqual(result['cases'][0]['id'], self.old['id'])
        self.assertEqual(result['identityAliases'][self.old['decisionId']], c['decisionId'])
        self.assertIn(self.old['decisionId'], result['cases'][0]['legacyIds'])
        self.assertEqual(len(report['identityCorrections']), 1)

    def test_new_reviewed_entry_retains_evidence_on_first_import(self):
        candidate = self.candidate(number='2000다999')
        candidate['identityReview'] = {'evidence': 'official source', 'sourceCitation': 'raw citation'}
        catalog = self.catalog([candidate])
        result, report = plan_import(self.reg, self.toc, catalog, make_entry)
        new = next(c for c in result['cases'] if c['id'] == report['added'][0]['id'])
        self.assertEqual(new['standard']['identityReview'], candidate['identityReview'])
        again, _ = plan_import(result, self.toc, catalog, make_entry)
        self.assertEqual(result, again)

    def test_unresolved_catalog_cannot_apply(self):
        catalog = self.catalog([self.candidate()])
        catalog['conflicts'] = [{'reason': 'missing date'}]
        with self.assertRaises(ValueError):
            plan_import(self.reg, self.toc, catalog, make_entry)

    def test_nonstandard_records_unchanged(self):
        c = copy.deepcopy(self.old)
        c.update(id='annual-2020-01', group='annual', annual={'year': 2020, 'field': 'civil'})
        self.reg['cases'].append(c)
        result, _ = plan_import(self.reg, self.toc, self.catalog([self.candidate()]), make_entry)
        self.assertEqual(result['cases'][1], c)

    def test_reviewed_wrong_docket_does_not_prevent_deletion(self):
        candidate = self.candidate(number='2000다999')
        catalog = self.catalog([candidate], [{'subject': 'civil', 'court': '대법원',
                                             'caseNumber': '2000다123', 'sheet': '민법'}])
        result, report = plan_import(self.reg, self.toc, catalog, make_entry)
        self.assertTrue(result['cases'][0]['standard']['removed'])
        self.assertEqual(report['removed'][0]['id'], self.old['id'])

    def test_legacy_source_exclusion_keeps_unchanged_archive(self):
        self.old['standardSource'] = {'verified': True, 'book': '표준판례', 'edition': '2023',
            'file': 'source.pdf', 'pages': [1], 'issues': [{'n': '', 'text': '올바른 쟁점'}],
            'holdings': [{'n': '', 'text': '다른 사건에서 혼입된 원문'}]}
        original = copy.deepcopy(self.old['standardSource'])
        catalog = self.catalog([])
        catalog['legacySourceExclusions'] = {self.old['id']: {'fields': ['holdings'],
            'evidence': '검토한 원본과 공식 판결', 'reason': '상이한 사건의 요지 혼입'}}
        result, report = plan_import(self.reg, self.toc, catalog, make_entry)
        self.assertNotIn('holdings', result['cases'][0]['standardSource'])
        self.assertEqual(result['cases'][0]['standardSourceHistory'], [original])
        self.assertEqual(report['sourceAnomalies'][0]['excludedFields'], ['holdings'])


if __name__ == '__main__':
    unittest.main()
