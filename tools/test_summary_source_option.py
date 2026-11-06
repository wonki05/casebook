"""add_cases.py set --summary-source / --editorial 와 validate 의 구조 검사."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import add_cases


class SummarySourceOptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg, self.toc, self.editorial = root / 'registry.json', root / 'toc.json', root / 'editorial.json'
        (root / 'fetched').mkdir()
        self.reg.write_text('{"cases": []}', encoding='utf-8')
        self.toc.write_text('{}', encoding='utf-8')
        self.patches = patch.multiple(add_cases, REG=str(self.reg), TOC=str(self.toc), FETCHED=str(root / 'fetched'))
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.cli('add', '--group', 'ccourt', '--subject', 'constitution', '--case', '2020헌마1', '--date', '2020-01-30', '--title', '목록 제목')
        self.id = self.record()['id']

    def cli(self, *args):
        with patch.object(sys, 'argv', ['add_cases.py', *args]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            add_cases.main()

    def record(self):
        return json.loads(self.reg.read_text(encoding='utf-8'))['cases'][0]

    def write_editorial(self, value):
        self.editorial.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return str(self.editorial)

    def test_summary_source_round_trip(self):
        self.assertNotIn('summarySource', self.record())
        self.cli('set', self.id, '--summary-source', 'standard')
        self.assertEqual(self.record()['summarySource'], 'standard')
        self.cli('validate')
        self.cli('set', self.id, '--summary-source', 'official')
        self.assertEqual(self.record()['summarySource'], 'official')
        self.cli('set', self.id, '--summary-source', 'auto')
        self.assertNotIn('summarySource', self.record())
        with self.assertRaises(SystemExit):
            self.cli('set', self.id, '--summary-source', 'bogus')

    def test_validate_rejects_corrupted_summary_source(self):
        data = json.loads(self.reg.read_text(encoding='utf-8'))
        data['cases'][0]['summarySource'] = 'bogus'
        self.reg.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(SystemExit):
            self.cli('validate')

    def test_editorial_file_is_checked_and_stored(self):
        good = {'issues': ['1. 심판대상조항이 평등권을 침해하는지 여부(소극)'], 'holdings': ['1. 합리적 이유가 있다.'], 'statutes': ['민법 제1조'],
                'basis': {'label': '헌법재판소 최근 주요결정 게시물', 'url': 'https://www.ccourt.go.kr/site/kor/ex/bbs/View.do?cbIdx=1195&bcIdx=1', 'basedOn': 'post'}}
        self.cli('set', self.id, '--editorial', self.write_editorial(good))
        stored = self.record()['editorial']
        self.assertEqual(stored['holding'], good['holdings'])   # holdings → holding (build_data 가 읽는 키)
        self.assertNotIn('holdings', stored)
        self.assertEqual(stored['issues'], good['issues'])
        self.assertEqual(stored['basis'], good['basis'])
        self.cli('validate')
        for bad in [dict(good, issues='【쟁점】'), dict(good, issues=['헌재 결정의 효력']), dict(good, issues=['전합 판결']),
                    dict(good, extra=['x']), dict(good, basis={'url': 'https://x'}), dict(good, basis=dict(good['basis'], url='ftp://x')),
                    dict(good, basis=dict(good['basis'], other='x')), dict(good, issues=[''] ), ['list']]:
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                self.cli('set', self.id, '--editorial', self.write_editorial(bad))
        self.assertEqual(self.record()['editorial']['basis'], good['basis'])   # 거부된 파일은 저장되지 않는다
        self.assertEqual(add_cases.checked_editorial({'issues': ['안전합니다', '헌재결정례 검색']})['issues'], ['안전합니다', '헌재결정례 검색'])

    def test_validate_reports_corrupted_editorial(self):
        data = json.loads(self.reg.read_text(encoding='utf-8'))
        data['cases'][0]['editorial'] = {'issues': ['【쟁점】']}
        self.reg.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(SystemExit):
            self.cli('validate')

    def test_candidate_file_carries_summary_source_and_editorial(self):
        candidates = Path(self.temp.name) / 'candidates.json'
        item = dict(status='ok', subject='constitution', court='헌법재판소', caseNumber='2021헌마2', date='2021-02-25', decisionType='결정',
                    title='후보 제목', summarySource='standard', editorial={'issues': ['1. 쟁점 여부(적극)'], 'holding': ['1. 요지']})
        candidates.write_text(json.dumps(dict(group='ccourt', candidates=[item]), ensure_ascii=False), encoding='utf-8')
        self.cli('add', '--from', str(candidates))
        added = json.loads(self.reg.read_text(encoding='utf-8'))['cases'][1]
        self.assertEqual(added['summarySource'], 'standard')
        self.assertEqual(added['editorial']['holding'], ['1. 요지'])
        item['summarySource'] = 'bogus'
        item['caseNumber'] = '2021헌마3'
        candidates.write_text(json.dumps(dict(group='ccourt', candidates=[item]), ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(SystemExit):
            self.cli('add', '--from', str(candidates))


if __name__ == '__main__':
    unittest.main()
