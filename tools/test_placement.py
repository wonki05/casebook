"""같은 재판의 중복 배치 허용과 대표 사건번호 정정(--correct-case) 시험."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import add_cases
from case_identity import identity


def standard(cid, number, title, toc, subject='civil', court='대법원', date='2020-01-01'):
    case = dict(id=cid, group='standard', subject=subject, caseNumber=number, lookupKey=number, court=court,
                decisionType='판결', decisionDate=date, title=title, tocPath=toc, tags=[], enBanc=False, editorial={})
    case.update(identity(case))
    return case


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg, self.toc, self.fetched = root / 'registry.json', root / 'toc.json', root / 'fetched'
        self.fetched.mkdir()
        self.reg.write_text(json.dumps({'cases': [
            standard('std-civil-01', '2020다10', '불공정한 법률행위 (3)', ['mb-1', 'mb-1-1']),
            standard('std-civil-02', '2020다99', '무효행위의 전환 (1)', ['mb-1', 'mb-1-2']),
        ]}, ensure_ascii=False), encoding='utf-8')
        self.toc.write_text(json.dumps({'civil': [{'id': 'mb-1', 'label': 'Civil', 'children': [
            {'id': 'mb-1-1', 'label': 'A', 'children': []}, {'id': 'mb-1-2', 'label': 'B', 'children': []},
            {'id': 'mb-1-3', 'label': 'C', 'children': []}]}]}), encoding='utf-8')
        self.addCleanup(patch.stopall)
        patch.multiple(add_cases, REG=str(self.reg), TOC=str(self.toc), FETCHED=str(self.fetched)).start()

    def cli(self, *args):
        out = io.StringIO()
        with patch.object(sys, 'argv', ['add_cases.py', *args]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            add_cases.main()
        return out.getvalue()

    def rejected(self, *args):
        before = self.reg.read_bytes()
        with self.assertRaises(SystemExit):
            self.cli(*args)
        self.assertEqual(self.reg.read_bytes(), before)

    def cases(self):
        return {c['id']: c for c in json.loads(self.reg.read_text(encoding='utf-8'))['cases']}

    def test_same_subject_other_unit_with_other_title_is_allowed(self):
        out = self.cli('add', '--group', 'standard', '--subject', 'civil', '--case', '2020다10', '--date', '2020-01-01',
                       '--title', '강행규정 위반의 법률행위', '--toc', 'mb-1/mb-1-3')
        self.assertIn('같은 재판의 다른 배치로 등록', out)
        placed = [c for c in self.cases().values() if c['caseNumber'] == '2020다10']
        self.assertEqual(len(placed), 2)
        self.assertEqual(placed[0]['decisionId'], placed[1]['decisionId'])

    def test_same_title_or_same_unit_or_unplaced_is_still_a_duplicate(self):
        base = ('add', '--group', 'standard', '--subject', 'civil', '--case', '2020다10', '--date', '2020-01-01')
        self.rejected(*base, '--title', '불공정한 법률행위 (3)', '--toc', 'mb-1/mb-1-3')   # 같은 제목
        self.rejected(*base, '--title', '다른 제목', '--toc', 'mb-1/mb-1-1')               # 같은 단원
        self.rejected(*base)                                                               # 배치 정보 없음

    def test_other_subject_is_always_allowed(self):
        e = standard('x', '2020다10', '불공정한 법률행위 (3)', ['mb-1', 'mb-1-1'], subject='administrative')
        self.assertFalse(add_cases.duplicate(add_cases.load()[0], e))

    def test_correct_case_recomputes_identity_and_keeps_alias(self):
        old = self.cases()['std-civil-02']
        out = self.cli('set', 'std-civil-02', '--correct-case', '2020다11')
        new = self.cases()['std-civil-02']
        self.assertEqual((new['caseNumber'], new['lookupKey'], new['caseNumberId'], new['caseId']), ('2020다11', '2020다11', '2020da11', 'sc-2020da11'))
        self.assertEqual(new['decisionId'], 'sc-2020da11-20200101-judgment')
        reg = json.loads(self.reg.read_text(encoding='utf-8'))
        self.assertEqual(reg['identityAliases'], {'std-civil-02': new['decisionId'], old['decisionId']: new['decisionId']})
        self.assertEqual({k: v for k, v in new.items() if k not in ('caseNumber', 'lookupKey', 'caseNumberId', 'caseId', 'decisionId')},
                         {k: v for k, v in old.items() if k not in ('caseNumber', 'lookupKey', 'caseNumberId', 'caseId', 'decisionId')})
        self.assertNotIn('같은 재판의 다른 배치', out)

    def test_correct_case_onto_another_unit_reports_sibling_but_same_unit_is_refused(self):
        out = self.cli('set', 'std-civil-02', '--correct-case', '2020다10')
        self.assertIn('같은 재판의 다른 배치: std-civil-01', out)
        self.assertEqual(self.cases()['std-civil-02']['decisionId'], self.cases()['std-civil-01']['decisionId'])
        reg = json.loads(self.reg.read_text(encoding='utf-8'))
        reg['cases'][1] = standard('std-civil-02', '2020다99', '무효행위의 전환 (1)', ['mb-1', 'mb-1-1'])   # 이제 같은 단원
        self.reg.write_text(json.dumps(reg, ensure_ascii=False), encoding='utf-8')
        self.rejected('set', 'std-civil-02', '--correct-case', '2020다10')

    def test_correct_case_validations(self):
        self.rejected('set', 'std-civil-02', '--correct-case', '2020다99')            # 같은 번호
        self.rejected('set', 'std-civil-02', '--correct-case', 'abc')                 # 형식 오류
        self.rejected('set', 'std-civil-02', '--correct-case', '2020다11', '--case', '2020다11')
        (self.fetched / 'std-civil-02.json').write_text('{"citation": "[대법원 2020. 1. 1. 선고 2020다99 판결]"}', encoding='utf-8')
        self.rejected('set', 'std-civil-02', '--correct-case', '2020다11')            # 수집본 인용문에 새 번호 없음
        (self.fetched / 'std-civil-02.json').write_text('{"citation": "[대법원 2020. 1. 1. 선고 2020다11 판결]"}', encoding='utf-8')
        self.cli('set', 'std-civil-02', '--correct-case', '2020다11')                 # 인용문에 새 번호가 있으면 허용
        self.assertEqual(self.cases()['std-civil-02']['caseNumber'], '2020다11')


if __name__ == '__main__':
    unittest.main()
