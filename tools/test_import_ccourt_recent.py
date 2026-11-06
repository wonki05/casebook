from pathlib import Path
import tempfile
import unittest

import import_ccourt_recent
from import_ccourt_recent import collect, plan, read_page


def candidate(number='2023헌바1', date='2024-02-29', event='100'):
    return {'status': 'ok', 'caseNumber': number, 'date': date, 'title': '사건명',
            'court': '헌법재판소', 'decisionType': '결정', 'ccourtSource': {'eventId': event}}


def record(number='2023헌바1', date='2024-02-29', group='ccourt', id='old'):
    return {'id': id, 'group': group, 'court': '헌법재판소', 'caseNumber': number,
            'decisionDate': date, 'decisionType': '결정'}


def html(number='2023헌바1등', date='2024. 2. 29.'):
    return f'''<input name="cbIdx" value="1195"><input name="pageIndex" value="1">
<input name="searchDateFrom" value="2009-01-01"><input name="searchDateTo" value="2026-10-22">
<div class="bbsTotal">총 <span>1</span>건</div><a class="num active">1</a>
<a onclick="viewPop('1195','1234');"><div><b class="caseNum">{number}</b>
<span class="caseInfo">종국일자<em>|</em>{date}</span><span class="caseInfo">종국결과<em>|</em>합헌,기각</span></div><b class="title">사건명 &amp; 이름</b>
<div class="desc">truncated<br> preview</div></a>'''


class TestRecentImport(unittest.TestCase):
    def test_parse_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'page-001.html'
            p.write_text(html(), encoding='utf-8')
            rows, total = read_page(p, 1)
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]['caseNumber'], '2023헌바1등')
            self.assertEqual(rows[0]['date'], '2024-02-29')
            self.assertEqual(rows[0]['title'], '사건명 & 이름')
            self.assertEqual(rows[0]['ccourtSource']['eventId'], '1234')
            self.assertEqual(rows[0]['ccourtSource']['result'], '합헌,기각')
            self.assertEqual(len(rows[0]['ccourtSource']['sourceSha256']), 64)
            self.assertNotIn('editorial', rows[0])

    def test_empty_or_junk_title_uses_case_number_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            for title in ('', '1111-33333', '국가제정~~'):
                p = Path(tmp) / 'page-001.html'
                p.write_text(html().replace('사건명 &amp; 이름', title), encoding='utf-8')
                rows, _ = read_page(p, 1)
                self.assertEqual(rows[0]['status'], 'ok')
                self.assertEqual(rows[0]['title'], '2023헌바1등 사건')
                self.assertEqual(rows[0]['listTitle'], title)

    def test_empty_case_number_needs_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'page-001.html'
            p.write_text(html(number=''), encoding='utf-8')
            rows, _ = read_page(p, 1)
            self.assertEqual(rows[0]['status'], 'review')
            self.assertEqual(plan(rows, []), {'ready': 0, 'existing': 0, 'conflicts': 1})
            import_ccourt_recent.CASE_NUMBER_OVERRIDES['1234'] = '2023헌바9등'
            try:
                rows, _ = read_page(p, 1)
            finally:
                import_ccourt_recent.CASE_NUMBER_OVERRIDES.clear()
            self.assertEqual((rows[0]['status'], rows[0]['caseNumber']), ('ok', '2023헌바9등'))

    def test_failed_page_and_range_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'page-001.html').write_text(html(), encoding='utf-8')
            (root / 'page-002.html').write_text('incomplete', encoding='utf-8')
            rows, report = collect(root, '2025-01-01', None)
            self.assertEqual(rows, [])
            self.assertEqual(len(report['invalidPages']), 1)

    def test_missing_page_scope_is_bounded_by_neighbor_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = html(date='2025. 1. 1.').replace('<span>1</span>건', '<span>30</span>건')
            third = html(date='2019. 1. 1.').replace('<span>1</span>건', '<span>30</span>건')
            third = third.replace('name="pageIndex" value="1"', 'name="pageIndex" value="3"')
            third = third.replace('class="num active">1</a>', 'class="num active">3</a>')
            (root / 'page-001.html').write_text(first, encoding='utf-8')
            (root / 'page-003.html').write_text(third, encoding='utf-8')
            _, report = collect(root, '2020-01-01', None)
            self.assertTrue(report['datesDescending'])
            self.assertEqual(report['missingInScopePages'], [2])
            self.assertEqual((report['minDate'], report['maxDate']), ('2019-01-01', '2025-01-01'))

    def test_same_placement_and_separate_standard_placement(self):
        rows = [candidate(), candidate('2023헌바2', event='101')]
        counts = plan(rows, [record(), record('2023헌바2', group='standard', id='std')])
        self.assertEqual(counts, {'ready': 1, 'existing': 1, 'conflicts': 0})
        self.assertEqual(rows[0]['status'], 'skip')
        self.assertEqual(rows[1]['status'], 'ok')

    def test_reversed_explicit_co_cases_and_different_date(self):
        rows = [candidate('2023헌바2·1(병합)'), candidate('2023헌바3', event='101')]
        old = [record('2023헌바1·2(병합)'), record('2023헌바3', date='2023-02-28', id='earlier')]
        plan(rows, old)
        self.assertEqual(rows[0]['status'], 'skip')
        self.assertEqual(rows[1]['status'], 'review')

    def test_standard_co_case_representative_requires_review(self):
        rows = [candidate('2023헌바2·1(병합)')]
        plan(rows, [record('2023헌바1·2(병합)', group='standard')])
        self.assertEqual(rows[0]['status'], 'review')

    def test_existing_ccourt_does_not_hide_standard_identity_conflict(self):
        rows = [candidate('2023헌바2·1(병합)')]
        plan(rows, [record('2023헌바2·1(병합)', id='cc-existing'),
                    record('2023헌바1·2(병합)', group='standard', id='std-existing')])
        self.assertEqual(rows[0]['status'], 'review')
        self.assertEqual(set(rows[0]['matches']), {'cc-existing', 'std-existing'})

    def test_duplicate_source_and_docket_in_batch(self):
        rows = [candidate(), candidate(event='101'), candidate('2023헌바9', event='101')]
        plan(rows, [])
        self.assertEqual([r['status'] for r in rows], ['ok', 'skip', 'review'])


if __name__ == '__main__':
    unittest.main()
