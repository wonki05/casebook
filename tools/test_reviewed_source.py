"""검토가 반영된 최종 출처의 재병합 멱등성 및 전체 쪽수·해시 보존 검사."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md_merge
import md_validate
import pdf2md_lib as L
import test_pdf2md as fixture


def prepare(root):
    d, args = fixture.build_fixture(root)
    fixture.run_quiet(md_validate.main, ['--dir', d])
    fixture.run_quiet(md_merge.main, args)
    fixture.set_verdicts(os.path.join(d, '_review.jsonl'), lambda r:
        {'verdict': 'fix', 'fixedSections': {'참조조문': '상법 제23조 제1항, 제4항'}} if r['seq'] == 3 else
        {'verdict': 'reject'} if r['seq'] == 6 else {'verdict': 'ok'})
    code, output = fixture.run_quiet(md_merge.main, args)
    assert code == 0, output
    return d, args


def candidates(d):
    return {c['seq']: c for c in fixture.load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']}


def register(root, candidate, source=None):
    case = {'id': 'registered-fixture', 'group': 'standard', 'subject': 'commercial',
            'decisionId': candidate['decisionId'], 'standardSource': copy.deepcopy(source or candidate['standardSource'])}
    fixture.write(os.path.join(root, 'registry.json'), json.dumps({'cases': [case]}, ensure_ascii=False))


class ReviewedSourceTests(unittest.TestCase):
    def test_registered_fix_reruns_without_false_conflict_or_new_review(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root)
            original = candidates(d)[3]
            register(root, original)
            review_before = Path(d, '_review.jsonl').read_bytes()
            for _ in range(2):
                code, output = fixture.run_quiet(md_merge.main, args + ['--check'])
                self.assertEqual(code, 0, output)
                updated = candidates(d)[3]
                self.assertEqual(updated['status'], 'ok')
                self.assertEqual(updated['standardSource'], original['standardSource'])
                self.assertEqual(Path(d, '_review.jsonl').read_bytes(), review_before)
                conflicts = fixture.load_json(os.path.join(d, '_conflicts.json'))['stage3']
                self.assertFalse(any(c['kind'] == 'registry-text' and c['seq'] == 3 for c in conflicts))

    def test_genuine_difference_from_final_reviewed_source_remains_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root)
            original = candidates(d)[3]
            source = copy.deepcopy(original['standardSource'])
            source['statutes'] = ['상법 제99조']
            register(root, original, source)
            fixture.run_quiet(md_merge.main, args)
            updated = candidates(d)[3]
            self.assertEqual(updated['status'], 'review')
            self.assertIn('등록부의 같은 재판', updated['statusReason'])
            conflicts = fixture.load_json(os.path.join(d, '_conflicts.json'))['stage3']
            self.assertTrue(any(c['kind'] == 'registry-text' and c['seq'] == 3 for c in conflicts))
            self.assertEqual(updated['standardSource'], original['standardSource'])

    def test_reviewed_pages_and_row_pages_expand_coverage_and_rehash_exact_set(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root)
            original = candidates(d)[1]['standardSource']
            review_path = Path(d, '_review.jsonl')
            review = fixture.read_jsonl(str(review_path))
            for r in review:
                if r.get('seq') == 1 and r.get('reason') != 'title':
                    r['pages'] = [1, 3]
            fixture.write(str(review_path), ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in review))
            entry_path = Path(d, 'entries.jsonl')
            rows = fixture.read_jsonl(str(entry_path))
            rows[0]['pdfPages'] = [1, 2]
            self.assertEqual(rows[0]['verify']['pages'], [1])
            fixture.write(str(entry_path), ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
            code, output = fixture.run_quiet(md_merge.main, args)
            self.assertEqual(code, 0, output)
            updated = candidates(d)[1]['standardSource']
            self.assertEqual(updated['pages'], [1, 2, 3])
            self.assertEqual(updated['sha256'], L.pages_sha256(d, [1, 2, 3]))
            self.assertNotEqual(updated['sha256'], original['sha256'])
            for field in L.STANDARD_FIELDS:
                self.assertEqual(updated.get(field), original.get(field))

    def test_missing_reviewed_page_stops_without_rewriting_outputs(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root)
            review_path = Path(d, '_review.jsonl')
            review = fixture.read_jsonl(str(review_path))
            for r in review:
                if r.get('seq') == 1 and r.get('reason') != 'title':
                    r['pages'] = [1, 4]
            fixture.write(str(review_path), ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in review))
            Path(d, 'pages', 'p0004.txt').unlink()
            before = {name: Path(d, name).read_bytes() for name in ('candidates-commercial.json', '_review.jsonl', '_conflicts.json')}
            code, output = fixture.run_quiet(md_merge.main, args)
            self.assertEqual(code, 2, output)
            self.assertIn('검토 출처 pages/ 쪽 파일 없음', output)
            self.assertEqual({name: Path(d, name).read_bytes() for name in before}, before)


if __name__ == '__main__':
    unittest.main()
