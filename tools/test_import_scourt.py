"""사법정보공개포털 전원합의체 가져오기: 구역 나누기·분야 분류·출처 검증."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import add_cases
import fetch_scourt
import import_scourt

TEXT = """대법원 2026. 7. 22. 선고 2022도5937 전원합의체 판결

                    [
                    상관모욕
                    ]
                〈별칭 사건〉[공2026하,1827]

변경 : 대법원 2030. 1. 1. 선고 2029도1 전원합의체 판결에 의하여 변경

    【판시사항】

        [1] 첫째 쟁점

    【판결요지】
 [1] [다수의견] 본문
【대법관 갑의 반대의견】
반대 본문

【참조조문】
[1] 형법 제1조

【전 문】
【피 고 인】
피고인

【주    문】
  상고를 기각한다.

【이    유】
  이유 본문
"""


class SplitTests(unittest.TestCase):
    def test_sections_headings_and_inline_opinions(self):
        header, sections = import_scourt.split_portal_text(TEXT)
        self.assertTrue(header.startswith('대법원 2026. 7. 22. 선고'))
        heads = [s['heading'] for s in sections]
        self.assertEqual(heads, ['【판시사항】', '【판결요지】', '【참조조문】', '【전 문】', '【피 고 인】', '【주 문】', '【이 유】'])
        by = {s['heading']: s['text'] for s in sections}
        self.assertEqual(by['【판시사항】'], '[1] 첫째 쟁점')
        self.assertIn('【대법관 갑의 반대의견】\n반대 본문', by['【판결요지】'])
        self.assertEqual(by['【전 문】'], '')
        self.assertEqual(by['【주 문】'], '상고를 기각한다.')
        self.assertEqual(import_scourt.case_name(header, 'x'), '상관모욕')

    def test_publication_bracket_is_not_a_case_name(self):
        self.assertEqual(import_scourt.case_name('대법원 1990. 1. 1. 선고 1다1 판결\n\n[공1990.1.1.(1),1]', '대체'), '대체')

    def test_display_number_from_citation(self):
        number = import_scourt.display_number
        self.assertEqual(number('대법원 1993. 10. 8. 선고 93다13490, 13506(반소) 판결', 'x'), '93다13490, 13506(반소)')
        self.assertEqual(number('대법원 1990. 11. 27. 선고 87다카2961, 87다453 전원합의체판결', 'x'), '87다카2961, 87다453')
        self.assertEqual(number('대법원 1993. 5. 22.자 93스14, 15, 16 전원합의체 결정', 'x'), '93스14, 15, 16')
        self.assertEqual(number('대법원 2022. 7. 21. 선고 2018다248855, 248862 전원합의체 판결', 'x'), '2018다248855, 248862')

    def test_discard_note_comes_from_the_header_only(self):
        self.assertEqual(fetch_scourt.discard_note(TEXT), '변경 : 대법원 2030. 1. 1. 선고 2029도1 전원합의체 판결에 의하여 변경')
        self.assertEqual(fetch_scourt.discard_note('대법원 선고\n\n【판시사항】\n변경 : 본문 안의 표현'), '')


class ClassifyTests(unittest.TestCase):
    def test_subject_rules(self):
        classify = import_scourt.classify
        self.assertEqual(classify('2020도1', ''), 'criminal')
        self.assertEqual(classify('2019누1', ''), 'administrative')
        self.assertEqual(classify('2019두1', '상법 제1조'), 'administrative')
        self.assertEqual(classify('2019후1', ''), 'ip')
        self.assertEqual(classify('2019다1', '민법 제1조'), 'civil')
        self.assertEqual(classify('2019다1', '민법 제1조, 상법 제2조'), 'commercial')
        self.assertEqual(classify('2019다1', '저작권법 제1조'), 'ip')
        self.assertEqual(classify('2019다1', '국가배상법 제2조 제1항, 민법 제750조'), 'civil')
        self.assertEqual(classify('2019다1', '[1] 구 상법(2011. 4. 14. 법률 제10600호로 개정되기 전의 것) 제1조'), 'commercial')
        self.assertEqual(classify('2019므1', ''), 'civil')


class ScourtSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg, self.toc, self.candidates = root / 'registry.json', root / 'toc.json', root / 'candidates.json'
        fetched = root / 'fetched'
        fetched.mkdir()
        self.reg.write_text('{"cases": []}', encoding='utf-8')
        self.toc.write_text('{}', encoding='utf-8')
        patches = patch.multiple(add_cases, REG=str(self.reg), TOC=str(self.toc), FETCHED=str(fetched))
        patches.start()
        self.addCleanup(patches.stop)
        self.source = dict(provider='사법정보공개포털', srno='2026000046592', grade='전원합의체', discarded=False)

    def cli(self, *args):
        with patch.object(sys, 'argv', ['add_cases.py', *args]), contextlib.redirect_stdout(io.StringIO()):
            add_cases.main()

    def write_candidate(self, source, **over):
        item = dict(status='ok', subject='civil', court='대법원', caseNumber='2020다1', date='2020-01-30',
                    decisionType='판결', title='제목', enBanc=True, scourtSource=source)
        item.update(over)
        self.candidates.write_text(json.dumps(dict(group='enbanc', candidates=[item]), ensure_ascii=False), encoding='utf-8')

    def test_round_trip_with_discard_note_and_validate(self):
        self.source.update(discarded=True, discardedNote='변경 : 대법원 2030. 1. 1. 선고 2029도1 전원합의체 판결에 의하여 변경')
        self.write_candidate(self.source)
        self.cli('add', '--from', str(self.candidates))
        record = json.loads(self.reg.read_text(encoding='utf-8'))['cases'][0]
        self.assertEqual(record['scourtSource'], self.source)
        self.assertEqual(record['id'], 'enbanc-2020da1')
        self.cli('validate')

    def test_invalid_source_rejected_before_save(self):
        for key, value in [('provider', 'other'), ('srno', 123), ('srno', ''), ('grade', '간행판결'),
                           ('discarded', 'no'), ('discardedNote', 'x'), ('discardedNote', ' ')]:
            with self.subTest(key=key, value=value):
                source = copy.deepcopy(self.source)
                source[key] = value
                if key == 'discardedNote':
                    source['discarded'] = value == ' '
                self.write_candidate(source)
                before = self.reg.read_bytes()
                with self.assertRaises(SystemExit):
                    self.cli('add', '--from', str(self.candidates))
                self.assertEqual(self.reg.read_bytes(), before)

    def test_discarded_grade_requires_discarded_flag_and_group_court_are_checked(self):
        self.source['grade'] = '폐기(변경)'
        self.write_candidate(self.source)
        with self.assertRaises(SystemExit):
            self.cli('add', '--from', str(self.candidates))
        self.source.update(discarded=True)
        self.write_candidate(self.source, subject='administrative')
        self.cli('add', '--from', str(self.candidates))
        with self.assertRaises(ValueError):
            add_cases.validate_scourt_source(self.source, 'standard', '대법원')
        with self.assertRaises(ValueError):
            add_cases.validate_scourt_source(self.source, 'enbanc', '헌법재판소')


if __name__ == '__main__':
    unittest.main()
