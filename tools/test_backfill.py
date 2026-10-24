"""Backfill safety checks; mocked setters never write a real registry."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import standard_source_backfill as backfill

DID = 'sc-2020da10000-20200101-judgment'
SOURCE = {
    'verified': True, 'book': '합성 시험 자료', 'edition': '시험용',
    'file': 'test-fixture.pdf', 'pages': [1],
    'holdings': [{'n': '', 'text': '합성 시험용 요지.'}],
}


class StandardSourceBackfillTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lawbook-backfill-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidates = self.root / 'candidates.json'
        self.registry = self.root / 'registry.json'
        self.registry.write_text(json.dumps({'cases': [
            {'id': 'existing-test-case', 'decisionId': DID},
        ]}), encoding='utf-8')
        self.original_registry = self.registry.read_bytes()

    def candidate(self):
        return {'status': 'ok', 'decisionId': DID, 'standardSource': copy.deepcopy(SOURCE)}

    def invoke(self, candidates, *extra):
        self.candidates.write_text(json.dumps({'candidates': candidates}, ensure_ascii=False), encoding='utf-8')
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = backfill.main([
                '--candidates', str(self.candidates), '--registry', str(self.registry), *extra,
            ])
        self.assertEqual(self.registry.read_bytes(), self.original_registry)
        return code, stdout.getvalue()

    def success(self, command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout='수정 완료', stderr='')

    def test_review_skip_and_unset_status_never_attempt_identity_or_set(self):
        candidates = [
            {'status': 'review', 'caseNumber': '2016추5087', 'standardSource': SOURCE},
            {'status': 'skip', 'standardSource': SOURCE},
            {'standardSource': SOURCE},
        ]
        with patch.object(backfill, 'identity') as identify, patch.object(backfill.subprocess, 'run') as setter:
            code, output = self.invoke(candidates)
        self.assertEqual(code, 0)
        self.assertIn('적용 0건, 이미 있음 0건, 충돌 0건', output)
        identify.assert_not_called()
        setter.assert_not_called()

    def test_valid_ok_candidate_sets_expected_source_and_counts_success(self):
        temporary_sources = []

        def checked_set(command, **kwargs):
            self.assertEqual(command[4:7], ['set', 'existing-test-case', '--standard-source'])
            source_path = Path(command[7])
            temporary_sources.append(source_path)
            self.assertEqual(json.loads(source_path.read_text(encoding='utf-8')), SOURCE)
            return self.success(command, **kwargs)

        with patch.object(backfill.subprocess, 'run', side_effect=checked_set) as setter:
            code, output = self.invoke([self.candidate()])
        self.assertEqual(code, 0)
        self.assertIn('적용 1건, 이미 있음 0건, 충돌 0건', output)
        setter.assert_called_once()
        self.assertTrue(all(not path.exists() for path in temporary_sources))

    def test_failed_set_is_not_counted_as_applied(self):
        temporary_sources = []

        def failed_set(command, **kwargs):
            temporary_sources.append(Path(command[-1]))
            return subprocess.CompletedProcess(command, 2, stdout='', stderr='검증 실패')

        with patch.object(backfill.subprocess, 'run', side_effect=failed_set):
            code, output = self.invoke([self.candidate()])
        self.assertEqual(code, 1)
        self.assertIn('적용 0건, 이미 있음 0건, 충돌 1건', output)
        self.assertIn('set 실패: 검증 실패', output)
        self.assertNotIn('  적용 ', output)
        self.assertTrue(all(not path.exists() for path in temporary_sources))

    def test_set_launch_error_returns_failure_without_counting_application(self):
        temporary_sources = []

        def launch_error(command, **kwargs):
            temporary_sources.append(Path(command[-1]))
            raise OSError('launch unavailable')

        with patch.object(backfill.subprocess, 'run', side_effect=launch_error):
            code, output = self.invoke([self.candidate()])
        self.assertEqual(code, 1)
        self.assertIn('적용 0건, 이미 있음 0건, 충돌 1건', output)
        self.assertIn('set 실행 실패: launch unavailable', output)
        self.assertTrue(all(not path.exists() for path in temporary_sources))

    def test_duplicate_candidates_only_set_target_once(self):
        with patch.object(backfill.subprocess, 'run', side_effect=self.success) as setter:
            code, output = self.invoke([self.candidate(), self.candidate()])
        self.assertEqual(code, 0)
        setter.assert_called_once()
        self.assertIn('적용 1건, 이미 있음 1건, 충돌 0건', output)

    def test_conflicting_duplicate_does_not_overwrite_successful_backfill(self):
        different = self.candidate()
        different['standardSource']['holdings'][0]['text'] = '다른 시험용 요지.'
        with patch.object(backfill.subprocess, 'run', side_effect=self.success) as setter:
            code, output = self.invoke([self.candidate(), different])
        self.assertEqual(code, 1)
        setter.assert_called_once()
        self.assertIn('적용 1건, 이미 있음 0건, 충돌 1건', output)
        self.assertIn('기존 standardSource 와 텍스트가 다름', output)

    def test_dry_run_tracks_duplicates_without_invoking_setter(self):
        with patch.object(backfill.subprocess, 'run') as setter:
            code, output = self.invoke([self.candidate(), self.candidate()], '--dry-run')
        self.assertEqual(code, 0)
        setter.assert_not_called()
        self.assertIn('적용 1건, 이미 있음 1건, 충돌 0건 (dry-run)', output)

    def test_ok_candidate_with_unresolved_identity_still_fails(self):
        candidate = {'status': 'ok', 'standardSource': SOURCE, 'court': '대법원',
                     'caseNumber': 'bad', 'date': '2020-01-01'}
        with patch.object(backfill, 'identity', side_effect=ValueError('identity invalid')), \
                patch.object(backfill.subprocess, 'run') as setter:
            code, output = self.invoke([candidate])
        self.assertEqual(code, 1)
        setter.assert_not_called()
        self.assertIn('decisionId 계산 실패: identity invalid', output)


if __name__ == '__main__':
    unittest.main()
