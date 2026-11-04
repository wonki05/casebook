"""Batch import safety tests with an isolated temporary registry and inbox."""
import json
from pathlib import Path
import tempfile
import unittest

from case_identity import identity
from import_ccourt_api_responses import run


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.registry, self.inbox, self.fetched = root / 'registry.json', root / 'inbox', root / 'fetched'
        self.inbox.mkdir()
        self.placement = {'id': 'cc-fixture', 'group': 'ccourt', 'caseNumber': '2020헌마389',
                          'lookupKey': '2020헌마389', 'court': '헌법재판소',
                          'decisionType': '결정', 'decisionDate': '2024-08-29'}
        self.placement.update(identity(self.placement))
        self.registry.write_text(json.dumps({'cases': [self.placement]}), encoding='utf-8')
        self.target = {'number': '2020헌마389', 'date': '2024-08-29',
                       'did': self.placement['decisionId'], 'event': '123'}
        self.source = ('=== 사건 ===\n기본 정보:\n  사건번호: 2020헌마389\n  종국일자: 20240829\n\n'
                       '전문:\n[주    문]기각한다.[이    유]결론 주문과 같이 결정한다.')

    def envelope(self, status='downloaded', text=None, seq='321'):
        value = {'target': self.target, 'outcome': dict(self.target, status=status, seq=seq),
                 'response': {'content': [{'type': 'text', 'text': self.source if text is None else text}]}}
        (self.inbox / 'event-123.json').write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def test_dry_run_and_apply_keep_source_exactly(self):
        self.envelope()
        report = run(self.registry, self.inbox, self.fetched)
        self.assertEqual(report['counts'], {'accepted': 1})
        self.assertFalse(self.fetched.exists())
        self.assertEqual(run(self.registry, self.inbox, self.fetched, True)['counts'], {'accepted': 1})
        stored = json.loads((self.fetched / 'cc-fixture.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['sections'][-1]['text'], self.source.split('전문:\n', 1)[1])
        before = (self.fetched / 'cc-fixture.json').read_bytes()
        self.assertEqual(run(self.registry, self.inbox, self.fetched, True)['counts'], {'skipped': 1})
        self.assertEqual(before, (self.fetched / 'cc-fixture.json').read_bytes())

    def test_truncated_and_partial_are_never_saved_as_full(self):
        for status, text in [('truncated', self.source + '⚠️ 응답이 너무 길어 50,000자로 잘렸습니다.'),
                             ('downloaded', self.source.replace('결론 주문과 같이 결정한다.', '잘린 이유'))]:
            with self.subTest(status=status):
                self.envelope(status, text)
                result = run(self.registry, self.inbox, self.fetched, True)
                self.assertEqual(result['counts'], {'missing': 1})
                self.assertFalse((self.fetched / 'cc-fixture.json').exists())
                missing = json.loads((self.fetched / 'cc-fixture.missing.json').read_text(encoding='utf-8'))
                self.assertIn('event-123.json', missing['apiSource'])
                (self.fetched / 'cc-fixture.missing.json').unlink()

    def test_existing_invalid_source_and_missing_file_are_preserved(self):
        self.envelope()
        self.fetched.mkdir()
        full, missing = self.fetched / 'cc-fixture.json', self.fetched / 'cc-fixture.missing.json'
        full.write_text('{}', encoding='utf-8')
        missing.write_text('previous missing', encoding='utf-8')
        result = run(self.registry, self.inbox, self.fetched, True)
        self.assertEqual(result['counts'], {'missing': 1})
        self.assertEqual(full.read_text(encoding='utf-8'), '{}')
        self.assertEqual(missing.read_text(encoding='utf-8'), 'previous missing')

    def test_mismatched_target_cannot_write(self):
        self.envelope()
        self.target['number'] = '2020헌마390'
        self.envelope()
        self.assertEqual(run(self.registry, self.inbox, self.fetched, True)['counts'], {'skipped': 1})
        self.assertFalse(self.fetched.exists())


if __name__ == '__main__':
    unittest.main()
