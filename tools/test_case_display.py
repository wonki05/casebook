"""set --case 변경이 표시만 바꾸고 재판 식별·공식 수집본을 보존하는지 검사."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import add_cases
from case_identity import identity


class CaseDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg, self.toc, self.fetched = root / 'registry.json', root / 'toc.json', root / 'fetched'
        self.fetched.mkdir()
        self.toc.write_text('{}', encoding='utf-8')
        self.file = self.fetched / 'compat-old-id.json'
        self.file.write_text('{"citation":"","preserve":"official"}', encoding='utf-8')
        self.original = {
            'id': 'compat-old-id', 'group': 'enbanc', 'subject': 'civil', 'title': 'fixture',
            'court': '대법원', 'caseNumber': '2020다1', 'lookupKey': '2020다1',
            'decisionDate': '2020-01-01', 'decisionType': '판결', 'enBanc': True,
            'tocPath': [], 'tags': [], 'memo': '원본 유지', 'lawgo': {'seq': 'fixture', 'kind': 'prec'},
            'standardSource': {'verified': True, 'book': 'fixture', 'edition': 'test', 'file': 'fixture.pdf',
                               'pages': [1], 'holdings': [{'n': '', 'text': 'fixture'}]},
        }
        self.original.update(identity(self.original))
        self.write_record(self.original)
        self.patch = patch.multiple(add_cases, REG=str(self.reg), TOC=str(self.toc), FETCHED=str(self.fetched))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write_record(self, record, aliases=True):
        payload = {'cases': [copy.deepcopy(record)]}
        if aliases:
            payload['identityAliases'] = {'preserved-alias': record['decisionId']}
        self.reg.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def read(self):
        return json.loads(self.reg.read_text(encoding='utf-8'))

    def cli(self, *args):
        with patch.object(sys, 'argv', ['add_cases.py', 'set', 'compat-old-id', *args]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            add_cases.main()

    def reject(self, *args):
        original = self.reg.read_bytes()
        fetched = self.file.read_bytes()
        with self.assertRaises(SystemExit):
            self.cli(*args)
        self.assertEqual(self.reg.read_bytes(), original)
        self.assertEqual(self.file.read_bytes(), fetched)

    def test_full_merged_display_changes_only_case_number(self):
        original = self.read()
        fetched = self.file.read_bytes()
        self.cli('--case', '2020다1·2020다2')
        expected = copy.deepcopy(original)
        expected['cases'][0]['caseNumber'] = '2020다1·2020다2'
        self.assertEqual(self.read(), expected)
        self.assertEqual(self.file.read_bytes(), fetched)

    def test_abbreviated_and_different_docket_symbols_preserve_identity(self):
        record = copy.deepcopy(self.original)
        for key in ('courtId', 'caseNumberId', 'caseId', 'decisionId'):
            record.pop(key)
        record.update(caseNumber='97므513·520', lookupKey='97므513')
        record.update(identity(record))
        self.write_record(record)
        self.cli('--case', '97므513·520·97스12')
        expected = copy.deepcopy(record)
        expected['caseNumber'] = '97므513·520·97스12'
        self.assertEqual(self.read()['cases'][0], expected)

    def test_historical_number_and_missing_lookup_key_are_preserved(self):
        record = copy.deepcopy(self.original)
        for key in ('courtId', 'caseNumberId', 'caseId', 'decisionId', 'lookupKey'):
            record.pop(key)
        record.update(caseNumber='4287형상176', decisionDate='1954-06-21')
        record.update(identity(record))
        self.write_record(record, aliases=False)
        self.cli('--case', '4287형상176·177')
        expected = copy.deepcopy(record)
        expected['caseNumber'] = '4287형상176·177'
        self.assertEqual(self.read(), {'cases': [expected]})

    def test_changed_representative_and_malformed_tails_rejected(self):
        for value in ('2020다2·2020다1', '2020다9', '', '2020다1·', '2020다1·잘못된번호',
                      '2020다1·2020다2뒤텍스트', '2020다1등임의문자'):
            with self.subTest(value=value):
                self.reject('--case', value)

    def test_identity_changing_options_cannot_accompany_display_edit(self):
        for extra in (['--date', '2021-01-01'], ['--court', '서울고등법원'], ['--decision-type', '결정']):
            with self.subTest(extra=extra):
                self.reject('--case', '2020다1·2020다2', *extra)

    def test_stale_stored_ids_and_lookup_mismatch_rejected(self):
        for field, value in (('caseId', 'wrong'), ('decisionId', 'wrong'), ('lookupKey', '2020다9')):
            with self.subTest(field=field):
                record = copy.deepcopy(self.original)
                record[field] = value
                self.write_record(record)
                self.reject('--case', '2020다1·2020다2')


if __name__ == '__main__':
    unittest.main()
