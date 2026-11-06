"""페이지 그룹별 판시사항·요지 우선순위(build_data.SUMMARY_PRECEDENCE)와 표준판례 배치 링크(standardPlacements).

같은 재판이 표준판례 페이지와 헌법재판소 주요결정 페이지에 함께 배치되면 표준판례 배치는 검증된 표준판례 발췌를,
헌법재판소 배치는 재판 전체를 조명하는 공식 판시사항·결정요지를 먼저 보여 준다. 어느 쪽도 원출처 문자열을 바꾸지 않는다.
"""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_data

STANDARD_SOURCE = {'verified': True, 'book': '표준판례', 'edition': '2026년 개정판', 'file': 'data/standard-cases/헌법.pdf', 'pages': [247],
                   'issues': [{'n': '1.', 'text': '표준판례 쟁점'}], 'holdings': [{'n': '1.', 'text': '표준판례 요지'}]}
EDITORIAL = {'issues': ['1. 편집 쟁점인지 여부(적극)', '2. 둘째 쟁점인지 여부(소극)'], 'holding': ['1. 편집 요지', '2. 둘째 요지'],
             'basis': {'label': '헌법재판소 최근 주요결정 게시물', 'url': 'https://www.ccourt.go.kr/site/kor/ex/bbs/View.do?cbIdx=1195&bcIdx=1', 'basedOn': 'post'}}
FETCHED = {'citation': '[헌법재판소 2020. 1. 30. 선고 2020헌마1 결정]', 'sourceUrl': 'https://www.law.go.kr/example', 'pageTitle': '공식 사건명 위헌확인',
           'sections': [{'heading': '【판시사항】', 'text': '1. 공식 쟁점인지 여부(소극)'}, {'heading': '【결정요지】', 'text': '1. 공식 요지'},
                        {'heading': '【주문】', 'text': '심판청구를 기각한다.'}]}


class PageSummaryPrecedenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg, self.toc, self.output = root / 'registry.json', root / 'toc.json', root / 'cases.json'
        self.fetched = root / 'fetched'
        self.fetched.mkdir()
        self.toc.write_text(json.dumps({'constitution': [{'id': 'hb-1', 'label': '기본권', 'children': []}]}, ensure_ascii=False), encoding='utf-8')
        self.patches = patch.multiple(build_data, REG=str(self.reg), TOC_FILE=str(self.toc), OUT=str(self.output), FETCHED=str(self.fetched))
        self.patches.start()
        self.addCleanup(self.patches.stop)
        common = dict(subject='constitution', court='헌법재판소', caseNumber='2020헌마1', decisionDate='2020-01-30', decisionType='결정', result='', tags=[])
        self.standard = dict(common, id='std-constitution-01', group='standard', title='표준판례 제목', tocPath=['hb-1'], editorial={},
                             standard={'order': 1}, standardSource=copy.deepcopy(STANDARD_SOURCE))
        self.ccourt = dict(common, id='cc-2020heolma1', group='ccourt', title='헌법재판소 제목', tocPath=[], editorial=copy.deepcopy(EDITORIAL))
        self.enbanc_like = None

    def build(self, records, fetched=FETCHED):
        self.reg.write_text(json.dumps({'cases': records}, ensure_ascii=False), encoding='utf-8')
        if fetched is not None:
            (self.fetched / 'cc-2020heolma1.json').write_text(json.dumps(fetched, ensure_ascii=False), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            build_data.build()
        return {c['id']: c for c in json.loads(self.output.read_text(encoding='utf-8'))['cases']}

    def test_group_defaults(self):
        self.assertEqual(build_data.summary_precedence('standard'), ('standard', 'official', 'editorial'))
        self.assertEqual(build_data.summary_precedence('research'), ('standard', 'official', 'editorial'))
        for group in ('annual', 'enbanc', 'ccourt'):
            self.assertEqual(build_data.summary_precedence(group), ('official', 'standard', 'editorial'))
        self.assertEqual(build_data.summary_precedence('ccourt', 'standard'), ('standard', 'official', 'editorial'))
        self.assertEqual(build_data.summary_precedence('standard', 'official'), ('official', 'standard', 'editorial'))
        with self.assertRaises(ValueError):
            build_data.summary_precedence('ccourt', 'bogus')

    def test_standard_page_keeps_standard_and_ccourt_page_shows_official(self):
        cases = self.build([self.standard, self.ccourt])
        std, cc = cases['std-constitution-01'], cases['cc-2020heolma1']
        self.assertEqual(std['summaryType'], 'standard')
        self.assertEqual(std['summaryPrecedence'], ['standard', 'official', 'editorial'])
        self.assertEqual(std['issues'][0]['text'], '표준판례 쟁점')
        self.assertEqual(std['fieldSources']['issues']['type'], 'standard')
        self.assertNotIn('standardPlacements', std)
        self.assertTrue(cc['isStandard'])
        self.assertEqual(cc['summaryType'], 'official')
        self.assertEqual(cc['summaryPrecedence'], ['official', 'standard', 'editorial'])
        self.assertEqual(cc['issues'], [{'n': '1.', 'text': '공식 쟁점인지 여부(소극)'}])
        self.assertEqual(cc['holdings'][0]['text'], '공식 요지')
        self.assertEqual(cc['fieldSources']['issues'], {'type': 'official', 'label': '국가법령정보센터', 'url': 'https://www.law.go.kr/example'})
        self.assertEqual(cc['fieldSources']['holdings']['type'], 'official')
        self.assertIsNone(cc['standardSource'])
        self.assertEqual(cc['standardPlacements'], [{'id': 'std-constitution-01', 'page': 'std-constitution', 'subject': 'constitution',
                                                     'title': '표준판례 제목', 'tocPath': ['hb-1']}])
        self.assertEqual(cc['officialSummary']['issues'][0]['text'], '공식 쟁점인지 여부(소극)')
        self.assertEqual(cc['caseName'], '공식 사건명 위헌확인')
        self.assertEqual(cc['title'], '헌법재판소 제목')
        self.assertNotIn('summarySource', cc)

    def test_placement_override_in_both_directions(self):
        self.ccourt['summarySource'] = 'standard'
        self.standard['summarySource'] = 'official'
        cases = self.build([self.standard, self.ccourt])
        cc, std = cases['cc-2020heolma1'], cases['std-constitution-01']
        self.assertEqual(cc['summarySource'], 'standard')
        self.assertEqual(cc['summaryPrecedence'], ['standard', 'official', 'editorial'])
        self.assertEqual(cc['summaryType'], 'standard')
        self.assertEqual(cc['issues'][0]['text'], '표준판례 쟁점')
        self.assertEqual(cc['standardSource']['pages'], [247])
        self.assertEqual(std['summaryType'], 'official')
        self.assertEqual(std['issues'][0]['text'], '공식 쟁점인지 여부(소극)')

    def test_invalid_override_fails_closed(self):
        self.ccourt['summarySource'] = 'bogus'
        with self.assertRaises(ValueError):
            self.build([self.standard, self.ccourt])

    def test_fallback_to_standard_then_editorial_with_basis(self):
        cases = self.build([self.standard, self.ccourt], fetched=None)
        cc = cases['cc-2020heolma1']
        self.assertEqual(cc['summaryType'], 'standard')
        self.assertEqual(cc['fieldSources']['issues']['type'], 'standard')
        self.assertEqual(cc['standardPlacements'][0]['id'], 'std-constitution-01')
        self.standard.pop('standardSource')
        cases = self.build([self.standard, self.ccourt], fetched=None)
        cc = cases['cc-2020heolma1']
        self.assertEqual(cc['summaryType'], 'editorial')
        self.assertEqual(cc['issues'], [{'n': '1.', 'text': '편집 쟁점인지 여부(적극)'}, {'n': '2.', 'text': '둘째 쟁점인지 여부(소극)'}])
        self.assertEqual(cc['holdings'][1], {'n': '2.', 'text': '둘째 요지'})
        self.assertEqual(cc['fieldSources']['issues'], {'type': 'editorial', 'label': '편집 요약', 'basis': EDITORIAL['basis']})
        self.assertEqual(cc['fieldSources']['statutes'], {'type': 'missing'})
        self.assertTrue(cc['isStandard'])

    def test_official_arriving_later_wins_over_editorial_without_registry_change(self):
        self.standard.pop('standardSource')
        before = self.build([self.standard, self.ccourt], fetched=None)['cc-2020heolma1']
        self.assertEqual(before['summaryType'], 'editorial')
        after = self.build([self.standard, self.ccourt])['cc-2020heolma1']
        self.assertEqual(after['summaryType'], 'official')
        self.assertEqual(after['issues'][0]['text'], '공식 쟁점인지 여부(소극)')
        self.assertNotIn('basis', after['fieldSources']['issues'])

    def test_editorial_items_keep_their_own_numbering(self):
        self.assertEqual(build_data.editorial_items(['1. 첫째', '[2] 둘째', '번호 없음', '  ']),
                         [{'n': '1.', 'text': '첫째'}, {'n': '[2]', 'text': '둘째'}, {'n': '', 'text': '번호 없음'}])
        self.assertEqual(build_data.editorial_items('1. 첫째\n2. 둘째'), [{'n': '1.', 'text': '첫째'}, {'n': '2.', 'text': '둘째'}])

    def test_multiple_standard_placements_follow_subject_then_book_order(self):
        second = dict(self.standard, id='std-constitution-02', title='둘째 배치', tocPath=['hb-1'], standard={'order': 0})
        admin = dict(self.standard, id='std-administrative-01', subject='administrative', title='행정법 배치', tocPath=[], standard={'order': 5})
        cases = self.build([self.standard, second, admin, self.ccourt])
        self.assertEqual([p['id'] for p in cases['cc-2020heolma1']['standardPlacements']],
                         ['std-constitution-02', 'std-constitution-01', 'std-administrative-01'])
        self.assertEqual(cases['std-administrative-01']['page'], 'std-administrative')


if __name__ == '__main__':
    unittest.main()
