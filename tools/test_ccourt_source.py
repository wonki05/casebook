"""Registration and validation of Constitutional Court list provenance."""
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


class CcourtSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg = root / 'registry.json'
        self.toc = root / 'toc.json'
        self.candidates = root / 'candidates.json'
        fetched = root / 'fetched'
        fetched.mkdir()
        self.reg.write_text('{"cases": []}', encoding='utf-8')
        self.toc.write_text('{}', encoding='utf-8')
        self.patches = patch.multiple(add_cases, REG=str(self.reg), TOC=str(self.toc), FETCHED=str(fetched))
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.source = dict(provider='헌법재판소', boardId='1195', eventId='4268005',
                           listUrl='https://www.ccourt.go.kr/site/kor/ex/bbs/List.do?cbIdx=1195',
                           sourceUrl='https://www.ccourt.go.kr/site/kor/ex/bbs/View.do?cbIdx=1195&bcIdx=4268005',
                           sourceFile='page-001.html', sourceSha256='a' * 64, page=1,
                           result='합헌,기각')

    def cli(self, *args):
        with patch.object(sys, 'argv', ['add_cases.py', *args]), contextlib.redirect_stdout(io.StringIO()):
            add_cases.main()

    def write_candidate(self, source):
        item = dict(status='ok', subject='constitution', court='헌법재판소',
                    caseNumber='2020헌마1', date='2020-01-30', decisionType='결정',
                    title='목록 제목', ccourtSource=source)
        self.candidates.write_text(json.dumps(dict(group='ccourt', candidates=[item]), ensure_ascii=False), encoding='utf-8')

    def test_round_trip_and_validate(self):
        self.write_candidate(self.source)
        self.cli('add', '--from', str(self.candidates))
        record = json.loads(self.reg.read_text(encoding='utf-8'))['cases'][0]
        self.assertEqual(record['ccourtSource'], self.source)
        self.cli('validate')
        self.cli('add', '--from', str(self.candidates))
        self.assertEqual(len(json.loads(self.reg.read_text(encoding='utf-8'))['cases']), 1)

    def test_invalid_source_rejected_before_save(self):
        for key, value in [('provider', 'other'), ('boardId', 1195), ('eventId', ''),
                           ('listUrl', 'https://www.ccourt.go.kr.evil.test/'),
                           ('sourceUrl', 'http://www.ccourt.go.kr/'), ('sourceFile', '../page.html'),
                           ('sourceSha256', 'A' * 64), ('page', True), ('page', 0), ('result', [])]:
            with self.subTest(key=key, value=value):
                source = copy.deepcopy(self.source)
                source[key] = value
                self.write_candidate(source)
                before = self.reg.read_bytes()
                with self.assertRaises(SystemExit):
                    self.cli('add', '--from', str(self.candidates))
                self.assertEqual(self.reg.read_bytes(), before)

    def test_empty_result_allowed_and_validation_detects_existing_corruption(self):
        self.source['result'] = ''
        self.write_candidate(self.source)
        self.cli('add', '--from', str(self.candidates))
        data = json.loads(self.reg.read_text(encoding='utf-8'))
        data['cases'][0]['ccourtSource']['sourceSha256'] = 'invalid'
        self.reg.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(SystemExit):
            self.cli('validate')


if __name__ == '__main__':
    unittest.main()
