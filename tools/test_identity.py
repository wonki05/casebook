"""Identity, source precedence, migration and registration regression tests.

Fixtures are synthetic and never written into the real case registry.
"""
import argparse
import copy
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import add_cases
import build_data
import case_identity as ci


def record(**changes):
    base = {'id': 'fixture-standard', 'group': 'standard', 'subject': 'civil',
            'court': '대법원', 'caseNumber': '2024다12345', 'lookupKey': '2024다12345',
            'decisionDate': '2025-01-02', 'decisionType': '판결', 'title': '테스트',
            'tocPath': ['mb-test'], 'enBanc': True, 'editorial': {}}
    base.update(changes)
    return base


def standard(**fields):
    return {'verified': True, 'book': '테스트용 표준판례', 'edition': 'fixture',
            'file': 'fixture.pdf', 'pages': [12], **fields}


class IdentityTests(unittest.TestCase):
    def test_court_and_docket_identity(self):
        self.assertEqual(ci.identity(record())['caseId'], 'sc-2024da12345')
        lower = record(court='서울중앙지방법원', caseNumber='2024가합12345', lookupKey='2024가합12345')
        self.assertEqual(ci.identity(lower)['caseId'], 'dcseoulcentral-2024gahap12345')
        self.assertNotEqual(ci.court_id('수원지방법원'), ci.court_id('수원지방법원 성남지원'))

    def test_unknown_court_never_becomes_supreme(self):
        for court in ('지방법원', '고등법원', '없는법원', ''):
            with self.subTest(court=court), self.assertRaises(ValueError):
                ci.identity(record(court=court))
        with self.assertRaises(ValueError):
            ci.identity(record(courtId='dcseoulcentral'))

    def test_number_symbol_roundtrip_and_historical_year(self):
        self.assertEqual(ci.case_number_id('88헌가5'), '88heonga5')
        unknown = ci.case_number_id('2024재가합123')
        self.assertRegex(unknown, r'^[a-z0-9]+$')
        self.assertEqual(ci.decode_case_number_id(unknown), '2024재가합123')
        self.assertNotEqual(unknown, ci.case_number_id('2024가합123'))
        self.assertEqual(ci.primary_case_number('2024 다 12345·23456'), '2024다12345')

    def test_decision_identity_is_separate_from_placement(self):
        a = ci.identity(record())
        b = ci.identity(record(id='enbanc-other', group='enbanc'))
        self.assertEqual(a, b)
        c = ci.identity(record(decisionDate='2025-02-02'))
        d = ci.identity(record(decisionType='결정'))
        self.assertEqual(a['caseId'], c['caseId'])
        self.assertEqual(a['caseId'], d['caseId'])
        self.assertNotEqual(a['decisionId'], c['decisionId'])
        self.assertNotEqual(a['decisionId'], d['decisionId'])

    def test_merged_display_may_list_representative_after_first_number(self):
        merged = record(court='헌법재판소', caseNumber='2011헌바129,172(병합)', lookupKey='2011헌바172',
                        caseNumberId='2011heonba172', decisionDate='2014-10-30', decisionType='결정')
        got = ci.identity(merged)
        self.assertEqual(got['decisionId'], 'cc-2011heonba172-20141030-decision')
        self.assertEqual(ci.case_number_list('2011헌바129,172(병합)'), ['2011헌바129', '2011헌바172'])
        self.assertEqual(ci.case_number_list('97므513·520'), ['97므513', '97므520'])
        self.assertEqual(ci.case_number_list('2010헌가95등'), ['2010헌가95'])
        unrelated = record(court='헌법재판소', caseNumber='2011헌바129,173(병합)', lookupKey='2011헌바172',
                           decisionType='결정')
        with self.assertRaises(ValueError):
            ci.identity(unrelated)
        self.assertEqual(add_cases.checked_case_display('2011헌바129,172(병합)', merged), '2011헌바129,172(병합)')
        with self.assertRaises(ValueError):
            add_cases.checked_case_display('2011헌바129,173(병합)', merged)
        with self.assertRaises(ValueError):
            add_cases.checked_case_display('2011헌바129,172', merged)
        reordered = record(court='헌법재판소', caseNumber='2011헌바129,172', lookupKey='2011헌바172', decisionType='결정')
        with self.assertRaises(ValueError):
            ci.identity(reordered)

    def test_wrong_type_date_and_lookup_are_rejected(self):
        with self.assertRaises(ValueError):
            ci.identity(record(), '대법원 2025. 1. 2.자 2024다12345 결정')
        with self.assertRaises(ValueError):
            ci.identity(record(decisionDate='2025-02-30'))
        with self.assertRaises(ValueError):
            ci.identity(record(lookupKey='2024다9999'))

    def test_lower_court_citation(self):
        result = build_data.parse_citation('', '서울중앙지방법원', '2025-01-02', '2024가합12345', False, '결정')
        self.assertEqual(result[2], '서울중앙지방법원 2025. 1. 2.자 2024가합12345 결정')
        self.assertNotIn('헌법재판소', result[3])
        self.assertNotIn('대결', result[3])


class SourceTests(unittest.TestCase):
    def test_field_precedence_and_original_preserved(self):
        official = {key: [] for key in ci.STANDARD_FIELDS}
        official['issues'] = [{'n': '[1]', 'text': '공식 쟁점 fixture'}]
        official['holdings'] = [{'n': '[1]', 'text': '공식 요지 fixture'}]
        original = copy.deepcopy(official)
        r = {'source': {'url': 'https://example.invalid/official'}}
        source = standard(holdings=[{'n': '[1]', 'text': '표준판례 요지 fixture'}])
        records = [record(standardSource=source)]
        by = ci.standard_sources_by_decision(records, {records[0]['id']: ci.identity(records[0])})
        build_data.apply_source_precedence(r, by[ci.identity(records[0])['decisionId']], official, {'statutes': ['편집 조문 fixture']})
        self.assertEqual(r['holdings'], source['holdings'])
        self.assertEqual(r['issues'], official['issues'])
        self.assertEqual(r['fieldSources']['holdings']['type'], 'standard')
        self.assertEqual(r['fieldSources']['issues']['type'], 'official')
        self.assertEqual(r['fieldSources']['statutes']['type'], 'editorial')
        self.assertEqual(r['summaryType'], 'mixed')
        self.assertEqual(official, original)
        self.assertEqual(r['officialSummary'], original)

    def test_standard_shared_across_placements(self):
        a = record(standardSource=standard(holdings=[{'n': '', 'text': '검토된 텍스트 fixture'}]))
        b = record(id='fixture-enbanc', group='enbanc')
        identities = {r['id']: ci.identity(r) for r in (a, b)}
        by = ci.standard_sources_by_decision([a, b], identities)
        self.assertIn(identities[b['id']]['decisionId'], by)

    def test_provenance_conflict_and_unverified_rejected(self):
        for invalid in (standard(holdings=[] , verified=False), standard(holdings=[], pages=[]), {'verified': True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ci.validate_standard_source(invalid)
        a = record(standardSource=standard(holdings=[{'n': '', 'text': 'A'}]))
        b = record(id='second', standardSource=standard(holdings=[{'n': '', 'text': 'B'}]))
        with self.assertRaises(ValueError):
            ci.standard_sources_by_decision([a,b], {r['id']: ci.identity(r) for r in (a,b)})

    def test_explicit_empty_is_not_missing(self):
        r = {'source': {}}
        build_data.apply_source_precedence(r, {'holdings': {'value': [], 'sources': [standard(holdings=[])]}},
                                         {'holdings': [{'n': '', 'text': '공식 fixture'}]}, {})
        self.assertEqual(r['holdings'], [])
        self.assertEqual(r['fieldSources']['holdings']['type'], 'standard')


class CliAndBuildTests(unittest.TestCase):
    def fixture(self, root, records):
        root = Path(root)
        reg, toc, fetched, out = root/'registry.json', root/'toc.json', root/'fetched', root/'cases.json'
        fetched.mkdir()
        reg.write_text(json.dumps({'cases': records}, ensure_ascii=False), encoding='utf-8')
        toc.write_text(json.dumps({'civil': [{'id': 'mb-test', 'label': '테스트', 'children': []}]}), encoding='utf-8')
        return reg, toc, fetched, out

    def test_import_preserves_source_id_and_standard(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg, toc, fetched, out = self.fixture(tmp, [])
            candidate = Path(tmp)/'candidates.json'
            source = standard(holdings=[{'n': '', 'text': '검토된 fixture'}])
            candidate.write_text(json.dumps({'group':'standard','subject':'civil','candidates':[
                {'status':'ok','caseNumber':'2024가합12345','court':'서울중앙지방법원',
                 'date':'2025-01-02','title':'테스트','tocPath':['mb-test'],
                 'lawgo':{'kind':'prec','seq':'123'},'decisionType':'판결','standardSource':source}
            ]}, ensure_ascii=False),encoding='utf-8')
            with patch.multiple(add_cases, REG=str(reg), TOC=str(toc), FETCHED=str(fetched)), redirect_stdout(io.StringIO()):
                with patch.object(sys, 'argv', ['add_cases.py', 'add', '--from', str(candidate)]):
                    add_cases.main()
            result = json.loads(reg.read_text(encoding='utf-8'))['cases'][0]
            self.assertEqual(result['lawgo']['seq'], '123')
            self.assertEqual(result['standardSource'], source)
            self.assertEqual(result['caseId'], 'dcseoulcentral-2024gahap12345')

    def test_migration_is_idempotent_and_preserves_placement(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = record()
            reg, toc, fetched, out = self.fixture(tmp, [item])
            with patch.multiple(add_cases, REG=str(reg), TOC=str(toc), FETCHED=str(fetched)), redirect_stdout(io.StringIO()):
                add_cases.cmd_migrate_identities(argparse.Namespace())
                once = reg.read_bytes()
                add_cases.cmd_migrate_identities(argparse.Namespace())
                self.assertEqual(once,reg.read_bytes())
            result = json.loads(reg.read_text(encoding='utf-8'))
            self.assertEqual(result['cases'][0]['id'], item['id'])
            self.assertEqual(result['identityAliases'][item['id']], ci.identity(item)['decisionId'])
            self.assertEqual(list(fetched.iterdir()), [])

    def test_validate_structure_errors_exit_but_missing_only_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg, toc, fetched, out = self.fixture(tmp, [record()])
            with patch.multiple(add_cases, REG=str(reg), TOC=str(toc), FETCHED=str(fetched)), redirect_stdout(io.StringIO()):
                add_cases.cmd_validate(argparse.Namespace())
                wrong = {'cases':[record(court='지방법원')]}
                reg.write_text(json.dumps(wrong,ensure_ascii=False),encoding='utf-8')
                with self.assertRaises(SystemExit) as ctx:
                    add_cases.cmd_validate(argparse.Namespace())
                self.assertEqual(ctx.exception.code,1)

    def test_stale_registry_save_preserves_other_session_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg, toc, fetched, out = self.fixture(tmp, [record()])
            with patch.multiple(add_cases, REG=str(reg), TOC=str(toc), FETCHED=str(fetched)):
                loaded, _ = add_cases.load()
                concurrent = {'cases': [record(title='다른 세션 수정')]}
                reg.write_text(json.dumps(concurrent, ensure_ascii=False), encoding='utf-8')
                with self.assertRaises(SystemExit):
                    add_cases.save(reg=loaded)
                self.assertEqual(json.loads(reg.read_text(encoding='utf-8')), concurrent)

    def test_build_shares_verified_book_and_preserves_official_full_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = record(standardSource=standard(holdings=[{'n':'','text':'표준 요지 fixture'}]))
            b = record(id='fixture-enbanc',group='enbanc')
            reg,toc,fetched,out=self.fixture(tmp,[a,b])
            raw={'citation':'대법원 2025. 1. 2. 선고 2024다12345 전원합의체 판결',
                 'pageTitle':'테스트','sourceUrl':'https://example.invalid',
                 'sections':[{'heading':'【판시사항】','text':'공식 쟁점 fixture'},
                             {'heading':'【판결요지】','text':'공식 요지 fixture'},
                             {'heading':'【이 유】','text':'공식 전문 fixture'}]}
            for r in (a,b):
                (fetched/(r['id']+'.json')).write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8')
            originals={p.name:p.read_bytes() for p in fetched.iterdir()}
            with patch.multiple(build_data, REG=str(reg), TOC_FILE=str(toc), FETCHED=str(fetched), OUT=str(out)), redirect_stdout(io.StringIO()):
                build_data.build()
            data=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(len(data['cases']),2)
            for r in data['cases']:
                self.assertEqual(r['holdings'],a['standardSource']['holdings'])
                self.assertEqual(r['officialSummary']['holdings'][0]['text'],'공식 요지 fixture')
                self.assertEqual(r['fullText'][0]['text'],'공식 전문 fixture')
                self.assertEqual(r['decisionId'],ci.identity(a)['decisionId'])
            self.assertEqual(originals,{p.name:p.read_bytes() for p in fetched.iterdir()})


if __name__ == '__main__':
    unittest.main()
