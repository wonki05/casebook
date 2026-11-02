"""공식 인용문 해석 시험: 재판부 표기가 없는 헌법재판소 인용문."""
import unittest

import fetch_lawgo as fetch


class CitationIdentityTests(unittest.TestCase):
    def test_constitutional_citation_without_panel(self):
        got = fetch.citation_identity('[ 97헌가14, 1999. 4. 29.]')
        self.assertEqual(got['court'], '헌법재판소')
        self.assertEqual(got['decisionDate'], '1999-04-29')
        self.assertEqual(got['members'], ['97헌가14'])

    def test_panel_and_merged_citations_still_parse(self):
        got = fetch.citation_identity('[전원재판부 2011헌바129,172(병합), 2014. 10. 30.]')
        self.assertEqual(got['members'], ['2011헌바129', '2011헌바172'])
        self.assertEqual(fetch.citation_identity('[전원재판부 88헌가5, 1989. 7. 14.]')['members'], ['88헌가5'])

    def test_ordinary_court_citation_is_not_mistaken(self):
        got = fetch.citation_identity('[대법원 2017. 3. 15. 선고 2013다79887 판결]')
        self.assertEqual(got['court'], '대법원')
        self.assertEqual(got['decisionType'], '판결')
        self.assertIsNone(fetch.citation_identity('[ 2013다79887, 2017. 3. 15.]'))


if __name__ == '__main__':
    unittest.main()
