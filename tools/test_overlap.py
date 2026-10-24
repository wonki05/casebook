"""CLI regression tests with isolated synthetic overlap fixtures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CHECKER = Path(__file__).with_name('overlap_check.py')
FIRST = 'sc-2020da10000-20200101-judgment'
SECOND = 'sc-2020da20000-20200102-judgment'
ISSUE = '합성 시험용 쟁점 문장이다.'
HOLDING = '합성 시험용 요지 문장이다.'


class OverlapCheckCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lawbook-overlap-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('in', 'out', 'final'):
            (self.root / name).mkdir()

    def write_json(self, folder, did, value):
        path = self.root / folder / f'{did}.json'
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def fixture(self, did=FIRST, *, output=True):
        bundle = {'decisionId': did, 'books': [{
            'subject': '민법', 'book': '합성 시험 자료', 'edition': '시험용',
            'file': 'test-fixture.pdf', 'seq': 1, 'no': 1, 'title': '검증 시험',
            'pdfPages': [1], 'sections': {'쟁점': ISSUE, '판결요지': HOLDING},
            'pdfText': [{'page': 1, 'text': ISSUE + '\n' + HOLDING}],
        }]}
        result = {
            'decisionId': did, 'issues': [{'n': '', 'text': ISSUE}],
            'holdings': [{'n': '', 'text': HOLDING}], 'statutes': [],
            'excluded': [], 'confidence': 'high',
        }
        self.write_json('in', did, bundle)
        if output:
            self.write_json('out', did, result)
        return bundle, result

    def run_check(self, *args):
        return subprocess.run(
            [sys.executable, '-X', 'utf8', str(CHECKER),
             '--dir', str(self.root), *args],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )

    def final(self, did=FIRST):
        return json.loads((self.root / 'final' / f'{did}.json').read_text(encoding='utf-8'))

    def reviewer(self):
        return self.final()['placements'][0]['standardSource']['reviewer']

    def test_require_complete_fails_when_an_input_has_no_output(self):
        self.fixture()
        self.fixture(SECOND, output=False)
        run = self.run_check('--require-complete')
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('종합 출력 없음: ' + SECOND, run.stdout)
        self.assertEqual(self.final()['text']['holdings'][0]['text'], HOLDING)
        self.assertFalse((self.root / 'final' / f'{SECOND}.json').exists())

    def test_only_requested_missing_output_is_an_error(self):
        self.fixture(output=False)
        run = self.run_check('--only', FIRST)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn('종합 출력 없음: ' + FIRST, run.stdout)

    def test_mismatched_identity_does_not_replace_final(self):
        for folder in ('in', 'out'):
            with self.subTest(folder=folder):
                bundle, output = self.fixture()
                value = bundle if folder == 'in' else output
                value['decisionId'] = SECOND
                self.write_json(folder, FIRST, value)
                prior = self.root / 'final' / f'{FIRST}.json'
                prior.write_bytes(b'{"existing": "must remain unchanged"}\n')
                before = prior.read_bytes()
                run = self.run_check()
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn('decisionId 불일치: ' + FIRST, run.stdout)
                self.assertEqual(prior.read_bytes(), before)

    def test_nonverbatim_phrase_is_dropped_and_exit_is_failure(self):
        _, output = self.fixture()
        invented = '어느 입력 원문에도 없는 새로 만든 문장.'
        output['holdings'].append({'n': '[2]', 'text': invented})
        self.write_json('out', FIRST, output)
        run = self.run_check()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        final = self.final()
        self.assertEqual([x['text'] for x in final['text']['holdings']], [HOLDING])
        self.assertEqual(final['report']['dropped'], [{'field': 'holdings', 'text': invented}])
        self.assertNotIn(invented, json.dumps(final['placements'], ensure_ascii=False))

    def test_no_usable_text_fails_with_empty_placements(self):
        _, output = self.fixture()
        output['issues'] = []
        output['holdings'] = [{'n': '', 'text': '원문에 없는 구절'}]
        self.write_json('out', FIRST, output)
        run = self.run_check()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        final = self.final()
        self.assertIsNone(final['text'])
        self.assertEqual(final['placements'], [])
        self.assertEqual(len(final['report']['dropped']), 1)

    def test_existing_reviewer_preserved_without_duplicate_source_suffix(self):
        self.fixture()
        previous = 'Original reviewer; 종합 출처: 민법 p.1'
        self.write_json('final', FIRST, {
            'placements': [{'standardSource': {'reviewer': previous}}],
        })
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.reviewer(), previous)

    def test_output_reviewer_then_explicit_override_takes_precedence(self):
        _, output = self.fixture()
        output['reviewer'] = 'Codex synthesis'
        self.write_json('out', FIRST, output)
        self.write_json('final', FIRST, {
            'placements': [{'standardSource': {'reviewer': 'Earlier reviewer'}}],
        })
        run = self.run_check()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.reviewer(), 'Codex synthesis; 종합 출처: 민법 p.1')
        run = self.run_check('--reviewer', 'Explicit reviewer')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(self.reviewer(), 'Explicit reviewer; 종합 출처: 민법 p.1')

    def test_only_leaves_other_final_bytes_untouched(self):
        self.fixture()
        _, other = self.fixture(SECOND)
        other['decisionId'] = 'unrelated-invalid-output'
        self.write_json('out', SECOND, other)
        untouched = self.root / 'final' / f'{SECOND}.json'
        untouched.write_bytes(b'{"sentinel": "keep original formatting"}\r\n')
        before = untouched.read_bytes()
        run = self.run_check('--only', FIRST, '--reviewer', 'Selected reviewer')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(untouched.read_bytes(), before)
        self.assertEqual(self.reviewer(), 'Selected reviewer; 종합 출처: 민법 p.1')


if __name__ == '__main__':
    unittest.main()
