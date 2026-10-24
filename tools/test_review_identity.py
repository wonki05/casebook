"""판정 준비·수거의 다중 재판 식별 회귀 시험. 실제 자료를 읽거나 쓰지 않는다."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import review_prep as prep
import review_collect as collect

A = 'sc-2000da1-20010101-judgment'
B = 'sc-2000da2-20010101-judgment'


def record(did=A, verdict='pending', reason='notes', **extra):
    row = {'seq': 1, 'no': 1, 'chunk': 'c001', 'reason': reason,
           'verdict': verdict, 'textSha256': 'same-text-hash', 'note': ''}
    if did is not None:
        row['decisionId'] = did
    row.update(extra)
    return row


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


class ReviewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.review = self.root / '_review.jsonl'
        entry = {'seq': 1, 'no': 1, 'chunk': 'c001', 'title': '합성 제목', 'pdfPages': [],
                 'sections': {'판결요지': '합성 본문'}, 'notes': [], 'cases': [],
                 'verify': {'fields': {}}}
        write_jsonl(self.root / 'entries.jsonl', [entry])
        (self.root / 'skeleton.json').write_text(json.dumps({'subject': 'commercial', 'entries': [entry]}), encoding='utf-8')

    def run_main(self, fn):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = fn(['--subject', 'commercial', '--dir', str(self.root)])
        return code, buf.getvalue()

    def read_rows(self):
        return [json.loads(line) for line in self.review.read_text(encoding='utf-8').splitlines()]

    def put_parts(self, rows):
        write_jsonl(self.root / '_review_parts' / 'b001.jsonl', rows)

    def prep_items(self):
        return json.loads((self.root / '_review_in' / 'b001.json').read_text(encoding='utf-8'))

    def test_second_decision_verdict_does_not_hide_first_pending(self):
        write_jsonl(self.review, [record(A), record(B), record(B, 'ok')])
        self.assertEqual(self.run_main(prep.main)[0], 0)
        items = self.prep_items()
        self.assertEqual([x['decisionId'] for x in items], [A])

    def test_prep_groups_reasons_only_within_same_decision(self):
        write_jsonl(self.review, [record(A), record(A, reason='title'), record(B)])
        self.assertEqual(self.run_main(prep.main)[0], 0)
        items = {x['decisionId']: x for x in self.prep_items()}
        self.assertEqual(len(items), 2)
        self.assertEqual(items[A]['reasons'], ['notes', 'title'])
        self.assertTrue(items[A]['needsTitle'])
        self.assertEqual(items[B]['reasons'], ['notes'])
        self.assertFalse(items[B]['needsTitle'])

    def test_collect_routes_identical_seq_reason_and_hash_by_decision(self):
        write_jsonl(self.review, [record(A), record(B)])
        self.put_parts([record(A, 'ok'), record(B, 'reject', note='두 번째 재판 판정')])
        self.assertEqual(self.run_main(collect.main)[0], 0)
        rows = self.read_rows()
        self.assertEqual([(x['decisionId'], x['verdict']) for x in rows[2:]], [(A, 'ok'), (B, 'reject')])
        # Recollecting unchanged parts must not duplicate decisions.
        before = self.review.read_bytes()
        self.assertEqual(self.run_main(collect.main)[0], 0)
        self.assertEqual(self.review.read_bytes(), before)

    def test_collect_does_not_apply_foreign_decision_to_only_pending_row(self):
        write_jsonl(self.review, [record(A)])
        self.put_parts([record(B, 'ok')])
        before = self.review.read_bytes()
        self.assertEqual(self.run_main(collect.main)[0], 1)
        self.assertEqual(self.review.read_bytes(), before)

    def test_legacy_result_without_id_matches_one_target(self):
        write_jsonl(self.review, [record(A)])
        self.put_parts([record(None, 'ok')])
        self.assertEqual(self.run_main(collect.main)[0], 0)
        self.assertEqual(self.read_rows()[-1]['decisionId'], A)

    def test_legacy_result_without_id_rejects_ambiguous_targets(self):
        write_jsonl(self.review, [record(A), record(B)])
        self.put_parts([record(None, 'ok')])
        before = self.review.read_bytes()
        self.assertEqual(self.run_main(collect.main)[0], 1)
        self.assertEqual(self.review.read_bytes(), before)

    def test_legacy_pending_record_can_gain_explicit_id(self):
        write_jsonl(self.review, [record(None)])
        self.put_parts([record(A, 'ok')])
        self.assertEqual(self.run_main(collect.main)[0], 0)
        self.assertEqual(self.read_rows()[-1]['decisionId'], A)
        self.assertEqual(len(prep.latest_reviews(self.read_rows())), 1)

    def test_unambiguous_legacy_history_is_latest_for_same_decision(self):
        rows = [record(A), record(None, 'ok')]
        latest = prep.latest_reviews(rows)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[(1, A, 'notes')]['verdict'], 'ok')

    def test_legacy_case_number_can_disambiguate_known_ids(self):
        rows = [record(A, caseNumber='2000다1'), record(B, caseNumber='2000다2'),
                record(None, 'ok', caseNumber='2000다1')]
        latest = prep.latest_reviews(rows)
        self.assertEqual(latest[(1, A, 'notes')]['verdict'], 'ok')
        self.assertEqual(latest[(1, B, 'notes')]['verdict'], 'pending')

    def test_ambiguous_legacy_history_fails_before_prep_writes(self):
        write_jsonl(self.review, [record(A), record(B), record(None, 'ok')])
        self.assertEqual(self.run_main(prep.main)[0], 1)
        self.assertFalse((self.root / '_review_in').exists())
        self.assertEqual(self.run_main(collect.main)[0], 1)
        self.assertEqual(len(self.read_rows()), 3)

    def test_conflicting_duplicate_in_same_collection_does_not_append_twice(self):
        write_jsonl(self.review, [record(A)])
        self.put_parts([record(A, 'ok'), record(A, 'reject')])
        self.assertEqual(self.run_main(collect.main)[0], 1)
        self.assertEqual(len(self.read_rows()), 2)
        self.assertEqual(self.read_rows()[-1]['verdict'], 'ok')

    def test_stale_hash_is_checked_against_its_decision(self):
        write_jsonl(self.review, [record(A, textSha256='hash-a'), record(B, textSha256='hash-b')])
        self.put_parts([record(A, 'ok', textSha256='hash-b')])
        self.assertEqual(self.run_main(collect.main)[0], 1)
        self.assertEqual(len(self.read_rows()), 2)

    def test_foreign_id_cannot_guess_between_explicit_and_legacy_targets(self):
        rows = [record(A, caseNumber='2000다1'), record(None, caseNumber='2000다2')]
        latest = prep.latest_reviews(rows)
        with self.assertRaises(ValueError):
            collect.matching_review(record(B, 'ok'), latest)


if __name__ == '__main__':
    unittest.main()
