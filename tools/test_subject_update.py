"""CLI regression tests for classification changes without changing case identity."""
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
from case_identity import identity


class SubjectUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg = root / 'registry.json'
        self.toc = root / 'toc.json'
        self.fetched = root / 'fetched'
        self.fetched.mkdir()
        self.records = []
        for cid, group, subject, number, court, kind in (
            ('cc-fixture', 'ccourt', 'constitution', '2020헌마1', '헌법재판소', '결정'),
            ('enbanc-fixture', 'enbanc', 'civil', '2020다1', '대법원', '판결'),
            ('std-civil-01', 'standard', 'civil', '2020다2', '대법원', '판결'),
            ('annual-fixture', 'annual', 'civil', '2020다3', '대법원', '판결'),
        ):
            case = dict(id=cid, group=group, subject=subject, caseNumber=number,
                        court=court, decisionType=kind, decisionDate='2020-01-01',
                        title='Test fixture', tocPath=['mb-1'] if group == 'standard' else [],
                        tags=[], editorial={'issues': ['fixture']},
                        lawgo={'kind': 'detc' if court == '헌법재판소' else 'prec', 'seq': 'fixture'},
                        standardSource={'verified': True, 'book': 'Test fixture',
                                        'edition': 'test', 'file': 'fixture.pdf',
                                        'pages': [1], 'issues': ['fixture']})
            if group == 'annual':
                case['annual'] = dict(year=2020, field='civil', article='fixture', url='https://example.test/')
            case.update(identity(case))
            self.records.append(case)
            (self.fetched / (cid + '.json')).write_text('{"citation": "", "fixture": true}', encoding='utf-8')
        self.reg.write_text(json.dumps({'cases': self.records}, ensure_ascii=False), encoding='utf-8')
        self.toc.write_text(json.dumps({
            'civil': [{'id': 'mb-1', 'label': 'Civil', 'children': []}],
            'administrative': [{'id': 'ab-1', 'label': 'Administrative', 'children': [
                {'id': 'ab-1-1', 'label': 'Child', 'children': []}]}],
        }), encoding='utf-8')
        self.addCleanup(patch.stopall)
        patch.multiple(add_cases, REG=str(self.reg), TOC=str(self.toc), FETCHED=str(self.fetched)).start()

    def cli(self, *args):
        with patch.object(sys, 'argv', ['add_cases.py', *args]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            add_cases.main()

    def record(self, cid):
        return next(c for c in json.loads(self.reg.read_text(encoding='utf-8'))['cases'] if c['id'] == cid)

    def rejected(self, *args):
        before = self.reg.read_bytes()
        with self.assertRaises(SystemExit):
            self.cli('set', *args)
        self.assertEqual(self.reg.read_bytes(), before)

    def test_ccourt_and_enbanc_preserve_identity_sources_and_files(self):
        files = {p.name: p.read_bytes() for p in self.fetched.iterdir()}
        for cid in ('cc-fixture', 'enbanc-fixture'):
            original = copy.deepcopy(self.record(cid))
            self.cli('set', cid, '--subject', 'administrative')
            original['subject'] = 'administrative'
            self.assertEqual(self.record(cid), original)
        self.assertEqual({p.name: p.read_bytes() for p in self.fetched.iterdir()}, files)

    def test_invalid_subject_rejected_without_write(self):
        self.rejected('cc-fixture', '--subject', 'unknown')

    def test_standard_move_requires_valid_destination_hierarchy(self):
        for extra in ([], ['--toc', ''], ['--toc', 'mb-1'], ['--toc', 'ab-1-1'],
                      ['--toc', 'ab-1-1/ab-1'], ['--toc', 'missing']):
            with self.subTest(extra=extra):
                self.rejected('std-civil-01', '--subject', 'administrative', *extra)
        self.rejected('std-civil-01', '--subject', 'ip', '--toc', 'mb-1')
        before = self.record('std-civil-01')
        self.cli('set', 'std-civil-01', '--subject', 'administrative', '--toc', 'ab-1/ab-1-1')
        before.update(subject='administrative', tocPath=['ab-1', 'ab-1-1'])
        self.assertEqual(self.record('std-civil-01'), before)

    def test_annual_subject_must_agree_with_existing_or_new_field(self):
        self.rejected('annual-fixture', '--subject', 'criminal')
        self.rejected('annual-fixture', '--subject', 'criminal', '--field', 'family')
        before = self.record('annual-fixture')
        self.cli('set', 'annual-fixture', '--subject', 'criminal', '--field', 'criminal-special')
        after = self.record('annual-fixture')
        self.assertEqual(after['subject'], 'criminal')
        self.assertEqual(after['annual']['field'], 'criminal-special')
        self.assertEqual(after['decisionId'], before['decisionId'])
        self.cli('set', 'annual-fixture', '--field', 'family')
        self.assertEqual(self.record('annual-fixture')['subject'], 'civil')

    def test_nonstandard_old_toc_requires_explicit_clear(self):
        reg = json.loads(self.reg.read_text(encoding='utf-8'))
        reg['cases'][0]['tocPath'] = ['mb-1']
        self.reg.write_text(json.dumps(reg, ensure_ascii=False), encoding='utf-8')
        self.rejected('cc-fixture', '--subject', 'administrative')
        self.cli('set', 'cc-fixture', '--subject', 'administrative', '--toc', '')
        self.assertEqual(self.record('cc-fixture')['tocPath'], [])

    def test_annual_subject_without_field_does_not_guess(self):
        reg = json.loads(self.reg.read_text(encoding='utf-8'))
        reg['cases'][-1]['annual'].pop('field')
        self.reg.write_text(json.dumps(reg, ensure_ascii=False), encoding='utf-8')
        self.rejected('annual-fixture', '--subject', 'civil')


if __name__ == '__main__':
    unittest.main()
