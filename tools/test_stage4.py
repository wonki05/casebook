"""단계 4 회귀검사: 목차 채택, 읽기 전용 사전 검사, 실패 시 등록 중단."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md_merge
import md_validate
import stage4_subject as stage4
import test_pdf2md as fixture


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in Path(root).rglob('*') if p.is_file()}


def prepare(root, proposed=False):
    data = Path(root) / 'data'
    d, argv = fixture.bulk_fixture(str(data / 'standard-cases'), n=3)
    fixture.run_quiet(md_validate.main, ['--dir', d])
    fixture.run_quiet(md_merge.main, argv)
    fixture.set_verdicts(os.path.join(d, '_review.jsonl'), lambda r: {'verdict': 'ok'})
    fixture.write(str(data / 'registry.json'), '{"cases": []}')
    toc = copy.deepcopy(fixture.TOC)
    if proposed:
        toc['commercial'][0]['label'] = '기존 시안 목차'
        skel = fixture.load_json(os.path.join(d, 'skeleton.json'))
        for e in skel['entries']:
            e['tocPathStatus'] = 'proposed'
        fixture.write(os.path.join(d, 'skeleton.json'), json.dumps(skel, ensure_ascii=False))
        fixture.write(os.path.join(d, 'toc-proposed.json'), json.dumps({'proposed': fixture.TOC['commercial']}, ensure_ascii=False))
    fixture.write(str(data / 'toc.json'), json.dumps(toc, ensure_ascii=False))
    args = SimpleNamespace(registry=str(data / 'registry.json'), toc=str(data / 'toc.json'),
                           overlap_final=None, seed=None, reviewer=None)
    return d, args


class TocTests(unittest.TestCase):
    def test_proposed_requires_adopted_tree_and_complete_path(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root, proposed=True)
            before = md_merge.run(args, 'commercial', d)
            self.assertTrue(all(c['status'] == 'review' for c in before['candidates']))
            self.assertTrue(all('제안 목차 미반영' in c['statusReason'] for c in before['candidates']))
            adopted = md_merge.run(args, 'commercial', d, toc_override=fixture.TOC)
            self.assertTrue(all(c['status'] == 'ok' for c in adopted['candidates']))
            skel_path = os.path.join(d, 'skeleton.json')
            skel = fixture.load_json(skel_path)
            skel['entries'][0]['tocPath'] = ['sb-1', 'sb-1-1-1']
            fixture.write(skel_path, json.dumps(skel, ensure_ascii=False))
            broken = md_merge.run(args, 'commercial', d, toc_override=fixture.TOC)
            self.assertEqual(broken['candidates'][0]['status'], 'review')
            self.assertIn('부모·자식 경로 불일치', broken['candidates'][0]['statusReason'])
            self.assertEqual(broken['candidates'][1]['status'], 'ok')

    def test_check_rejects_existing_ids_in_wrong_path(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root)
            result = md_merge.run(args, 'commercial', d)
            result['candidates'][0]['tocPath'] = ['sb-1', 'sb-1-1-1']
            _, errors = md_merge.check(result['candidates'], result['tids'])
            self.assertEqual(len(errors), 1)
            self.assertIn('전체 경로', errors[0])

    def test_missing_fix_page_aborts_before_output_writes(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root)
            review_path = os.path.join(d, '_review.jsonl')
            review = fixture.read_jsonl(review_path)
            target = next(r for r in review if r.get('seq') == 1 and r.get('reason') != 'title')
            target['verdict'] = 'fix'
            target['fixedSections'] = {}
            fixture.write(review_path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in review))
            Path(d, 'pages', 'p0001.txt').unlink()
            before = snapshot(root)
            code, output = fixture.run_quiet(md_merge.main, ['--subject', 'commercial', '--dir', d,
                                                            '--registry', args.registry, '--toc', args.toc])
            self.assertEqual(code, 2, output)
            self.assertIn('fix 재대조에 필요한 pages/', output)
            self.assertEqual(snapshot(root), before)


class Stage4Tests(unittest.TestCase):
    def test_dry_run_previews_adopted_toc_without_writing(self):
        with tempfile.TemporaryDirectory() as root:
            d, _ = prepare(root, proposed=True)
            before = snapshot(root)
            with patch.object(stage4, 'ROOT', root), patch.object(stage4, 'run', return_value='목차 검사 통과') as runner:
                code, output = fixture.run_quiet(stage4.main, ['--subject', 'commercial', '--dry-run'])
            self.assertEqual(code, 0, output)
            self.assertIn('후보 ok 3 / review 0 / skip 0', output)
            self.assertEqual(snapshot(root), before)
            runner.assert_called_once()
            self.assertEqual(runner.call_args.args[0][-1], '--dry-run')
            old = fixture.load_json(os.path.join(d, 'candidates-commercial.json'))
            self.assertEqual(old['summary']['review'], 3)

    def test_all_review_stops_before_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            prepare(root, proposed=True)
            before = snapshot(root)
            with patch.object(stage4, 'ROOT', root), patch.object(stage4, 'run') as runner, redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, '등록 가능한 후보가 0건'):
                    stage4.main(['--subject', 'commercial', '--skip-toc'])
            runner.assert_not_called()
            self.assertEqual(snapshot(root), before)

    def test_missing_fix_pages_stop_before_toc_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            d, _ = prepare(root, proposed=True)
            review = fixture.read_jsonl(os.path.join(d, '_review.jsonl'))
            target = next(r for r in review if r.get('seq') == 1 and r.get('reason') != 'title')
            target['verdict'] = 'fix'
            fixture.write(os.path.join(d, '_review.jsonl'), ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in review))
            Path(d, 'pages', 'p0001.txt').unlink()
            before = snapshot(root)
            with patch.object(stage4, 'ROOT', root), patch.object(stage4, 'run', return_value='목차 검사 통과') as runner, redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, 'fix 재대조에 필요한 pages/'):
                    stage4.main(['--subject', 'commercial'])
            runner.assert_called_once()
            self.assertEqual(runner.call_args.args[0][-1], '--dry-run')
            self.assertEqual(snapshot(root), before)

    def test_backfill_failure_halts_before_validate(self):
        with tempfile.TemporaryDirectory() as root:
            d, args = prepare(root)
            fixture.run_quiet(md_merge.main, ['--subject', 'commercial', '--dir', d,
                                              '--registry', args.registry, '--toc', args.toc])
            commands = []

            def execute(cmd, **kwargs):
                commands.append(cmd)
                failed = any(str(part).endswith('standard_source_backfill.py') for part in cmd)
                return subprocess.CompletedProcess(cmd, 1 if failed else 0,
                                                   'standardSource 보충: 충돌 1건' if failed else '', '')

            with patch.object(stage4, 'ROOT', root), patch.object(stage4.subprocess, 'run', side_effect=execute), redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit, '실패'):
                    stage4.main(['--subject', 'commercial'])
            self.assertTrue(any(any(str(p).endswith('standard_source_backfill.py') for p in cmd) for cmd in commands))
            self.assertFalse(any(cmd[-1] == 'validate' for cmd in commands))

    def test_new_review_is_not_silently_ignored(self):
        summary = {}
        candidates = [{'seq': 1, 'decisionId': 'd1', 'status': 'ok', 'statusReason': 'verified'},
                      {'seq': 2, 'decisionId': 'd2', 'status': 'review', 'statusReason': '판정 대기(conflict)'}]
        with redirect_stdout(io.StringIO()) as out:
            with self.assertRaisesRegex(SystemExit, '새 판정 대상 1건'):
                stage4.report_candidates(candidates, summary, new_reviews=1)
        self.assertIn('등록 보류 seq 2 d2', out.getvalue())
        self.assertEqual(summary['review'][0]['decisionId'], 'd2')


if __name__ == '__main__':
    unittest.main()
