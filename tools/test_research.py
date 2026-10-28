"""Research placements retain source titles and share only identical decisions."""
import copy
import contextlib
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
import build_data
from case_identity import identity


def record(cid='standard-existing', group='standard', **overrides):
    result = {
        'id': cid, 'group': group, 'subject': 'civil', 'title': '기존 화면 제목',
        'court': '대법원', 'caseNumber': '2020다1', 'lookupKey': '2020다1',
        'decisionDate': '2020-01-01', 'decisionType': '판결', 'enBanc': False,
        'tocPath': ['std-root'], 'tags': [], 'result': '', 'editorial': {},
    }
    result.update(overrides)
    result.update(identity(result))
    return result


def catalog():
    return {
        'collection': 'civil-research',
        'source': {'kind': 'user-supplied-toc', 'file': 'fixture.txt'},
        'toc': [{'id': 'research-v1', 'label': '1권', 'children': [
            {'id': 'research-v1-ch1', 'label': '제1장', 'children': []}]}],
        'candidates': [{
            'status': 'ok', 'title': '목차 원제목', 'caseNumber': '2020다1',
            'date': '2020-01-01', 'court': '대법원', 'decisionType': '판결',
            'tocPath': ['research-v1', 'research-v1-ch1'],
            'research': {'order': 1, 'sourcePage': 3, 'volume': 1,
                         'sourceCitation': '(사용자 제공 인용문)'},
        }],
    }


class ResearchImportTests(unittest.TestCase):
    def setUp(self):
        self.reg = {'cases': [record()], 'identityAliases': {'old': 'keep-me'}}
        self.toc = {'civil': [{'id': 'std-root', 'label': '기존 목차', 'children': []}]}
        self.catalog = catalog()

    def run_import(self, catalog_=None, reg=None, toc=None):
        return add_cases.import_research_catalog(
            self.reg if reg is None else reg, self.toc if toc is None else toc,
            self.catalog if catalog_ is None else catalog_)

    def test_save_preserves_each_loaded_files_indentation_and_final_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_file, toc_file = Path(directory) / 'registry.json', Path(directory) / 'toc.json'
            registry_file.write_bytes((json.dumps(self.reg, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            toc_file.write_bytes(json.dumps(self.toc, ensure_ascii=False, indent=1).replace('\n', '\r\n').encode('utf-8'))
            with patch.multiple(add_cases, REG=str(registry_file), TOC=str(toc_file), _loaded_bytes={}):
                registry, toc = add_cases.load()
                registry['cases'][0]['title'] = '변경된 제목'
                toc['civil'][0]['label'] = '변경된 목차'
                add_cases.save(registry, toc)
                self.assertEqual(registry_file.read_bytes(), (json.dumps(registry, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
                self.assertEqual(toc_file.read_bytes(), json.dumps(toc, ensure_ascii=False, indent=1).replace('\n', '\r\n').encode('utf-8'))
                first = registry_file.read_bytes(), toc_file.read_bytes()
                add_cases.save(registry, toc)
                self.assertEqual((registry_file.read_bytes(), toc_file.read_bytes()), first)

    def test_import_preserves_prior_placements_and_uses_collection_title(self):
        before = copy.deepcopy((self.reg, self.toc, self.catalog))
        updated, toc, result = self.run_import()
        self.assertEqual((self.reg, self.toc, self.catalog), before)
        self.assertEqual(updated['cases'][0], self.reg['cases'][0])
        self.assertEqual(updated['identityAliases'], self.reg['identityAliases'])
        research = updated['cases'][1]
        self.assertEqual(research['group'], 'research')
        self.assertEqual(research['title'], '목차 원제목')
        self.assertEqual(research['decisionId'], self.reg['cases'][0]['decisionId'])
        self.assertNotEqual(research['id'], self.reg['cases'][0]['id'])
        self.assertEqual(research['research']['sourcePage'], 3)
        self.assertEqual(research['research']['source'], self.catalog['source'])
        self.assertEqual(add_cases.research_toc_key(research), 'research-civil')
        self.assertEqual(toc['civil'], self.toc['civil'])
        self.assertEqual(result, {'added': [research['id']], 'changed': [], 'pending': []})

    def test_reimport_is_idempotent_and_title_updates_stay_in_research(self):
        first, toc, _ = self.run_import()
        second, second_toc, result = self.run_import(reg=first, toc=toc)
        self.assertEqual(first, second)
        self.assertEqual(toc, second_toc)
        self.assertEqual(result, {'added': [], 'changed': [], 'pending': []})
        edited = copy.deepcopy(self.catalog)
        edited['candidates'][0]['title'] = '목차에서 수정된 제목'
        third, _, result = self.run_import(edited, reg=first, toc=toc)
        self.assertEqual(third['cases'][0], self.reg['cases'][0])
        self.assertEqual(third['cases'][1]['title'], '목차에서 수정된 제목')
        self.assertEqual(result['changed'], [first['cases'][1]['id']])

    def test_same_decision_may_have_separate_numbered_entries(self):
        second = copy.deepcopy(self.catalog['candidates'][0])
        second['research']['order'] = 2
        second['title'] = '다른 장의 별도 제목'
        self.catalog['candidates'].append(second)
        updated, _, result = self.run_import()
        self.assertEqual(len(result['added']), 2)
        first, second = updated['cases'][1:]
        self.assertEqual(first['decisionId'], second['decisionId'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['research']['entryId'], second['research']['entryId'])
        self.assertEqual([first['title'], second['title']], ['목차 원제목', '다른 장의 별도 제목'])

    def test_existing_entry_identity_cannot_be_changed_by_reimport(self):
        initial, toc, _ = self.run_import()
        for field, value in (('caseNumber', '2020다2'), ('court', '서울고등법원'),
                             ('date', '2020-01-02'), ('decisionType', '결정')):
            with self.subTest(field=field):
                edited = copy.deepcopy(self.catalog)
                edited['candidates'][0][field] = value
                before = copy.deepcopy(initial)
                with self.assertRaises((ValueError, SystemExit)):
                    self.run_import(edited, reg=initial, toc=toc)
                self.assertEqual(initial, before)

    def test_unresolved_identity_is_retained_in_catalog_without_registration(self):
        unresolved = copy.deepcopy(self.catalog['candidates'][0])
        unresolved.update(status='pending', caseNumber='2016므0000', title='확인 대기 제목')
        unresolved['research']['order'] = 2
        self.catalog['candidates'].append(unresolved)
        updated, _, result = self.run_import()
        self.assertEqual(len(updated['cases']), 2)
        self.assertEqual(result['pending'], ['2016므0000'])
        self.assertEqual(self.catalog['candidates'][1], unresolved)

    def test_duplicate_entry_numbers_and_source_order_are_rejected(self):
        for duplicate_field in ('order', 'entryId'):
            with self.subTest(field=duplicate_field):
                edited = copy.deepcopy(self.catalog)
                original = edited['candidates'][0]
                original['research']['entryId'] = 'chapter-a'
                second = copy.deepcopy(original)
                if duplicate_field == 'order':
                    second['research']['entryId'] = 'chapter-b'
                else:
                    second['research']['order'] = 2
                edited['candidates'].append(second)
                with self.assertRaises(ValueError):
                    self.run_import(edited)

    def test_source_order_must_be_positive_integer(self):
        for value in (None, 0, -1, True, '1', 1.5):
            with self.subTest(value=value):
                edited = copy.deepcopy(self.catalog)
                edited['candidates'][0]['research']['order'] = value
                with self.assertRaises(ValueError):
                    self.run_import(edited)

    def test_requires_explicit_court_type_and_nonempty_original_title(self):
        for field in ('court', 'decisionType', 'title'):
            with self.subTest(field=field):
                edited = copy.deepcopy(self.catalog)
                del edited['candidates'][0][field]
                with self.assertRaises(ValueError):
                    self.run_import(edited)

    def test_research_paths_must_follow_research_namespace_and_full_ancestry(self):
        for path in ([], ['std-root'], ['research-v1-ch1'], ['research-v1-ch1', 'research-v1']):
            with self.subTest(path=path):
                edited = copy.deepcopy(self.catalog)
                edited['candidates'][0]['tocPath'] = path
                with self.assertRaises((ValueError, SystemExit)):
                    self.run_import(edited)

    def test_tree_cannot_reuse_other_toc_identifiers(self):
        self.catalog['toc'][0]['id'] = 'std-root'
        with self.assertRaises(ValueError):
            self.run_import()

    def test_toc_replacement_cannot_orphan_retained_research_entries(self):
        initial, toc, _ = self.run_import()
        edited = copy.deepcopy(self.catalog)
        edited['toc'][0]['children'][0]['id'] = 'research-v1-ch2'
        edited['candidates'][0]['status'] = 'pending'
        with self.assertRaises(ValueError):
            self.run_import(edited, reg=initial, toc=toc)


class SharedDecisionTests(unittest.TestCase):
    def make_records(self):
        return [
            record(),
            record('research-match', 'research', title='연구 제목'),
            record('latest-match', 'annual', title='최신판례 제목'),
            record('other-date', 'research', decisionDate='2020-01-02'),
            record('other-court', 'research', court='서울고등법원'),
            record('other-type', 'research', decisionType='결정'),
            record('other-docket', 'research', caseNumber='2020다2', lookupKey='2020다2'),
        ]

    def test_badge_membership_requires_same_court_docket_date_and_type(self):
        records = self.make_records()
        identities = {item['id']: identity(item) for item in records}
        standards = build_data.standard_decision_ids(records, identities)
        self.assertEqual([identities[item['id']]['decisionId'] in standards for item in records],
                         [True, True, True, False, False, False, False])

    def test_source_metadata_alone_does_not_make_standard_membership(self):
        research = record('only-research', 'research')
        research['standardSource'] = {'verified': True}
        self.assertEqual(build_data.standard_decision_ids(
            [research], {research['id']: identity(research)}), set())

    def test_official_source_is_shared_unchanged_only_for_exact_decisions(self):
        records = self.make_records()
        identities = {item['id']: identity(item) for item in records}
        fetched = {'sourceUrl': 'https://www.law.go.kr/fixture',
                   'citation': '[대법원 2020. 1. 1. 선고 2020다1 판결]',
                   'sections': [{'heading': '[주문]', 'text': '원문 ▒▒▒\n  그대로'}]}
        before = copy.deepcopy(fetched)
        shared = build_data.shared_fetched_by_decision(
            records, identities, {records[0]['id']: fetched})
        self.assertEqual(fetched, before)
        key = identities['research-match']['decisionId']
        self.assertEqual(shared[key][0], records[0]['id'])
        self.assertIs(shared[key][1], fetched)
        for item in records[3:]:
            self.assertNotIn(identities[item['id']]['decisionId'], shared)

    def test_missing_or_empty_extractions_do_not_count_as_official_sources(self):
        records = self.make_records()
        identities = {item['id']: identity(item) for item in records}
        shared = build_data.shared_fetched_by_decision(
            records, identities, {'standard-existing': {'sections': []}, 'research-match': None})
        self.assertEqual(shared, {})

    def test_borrowing_rejects_contradictory_or_incomplete_official_citations(self):
        source = record()
        identities = {source['id']: identity(source)}
        for citation in (
            '[대법원 2020. 1. 2. 선고 2020다1 판결]',
            '[서울고등법원 2020. 1. 1. 선고 2020다1 판결]',
            '[대법원 2020. 1. 1. 선고 2020다2 판결]',
            '[대법원 2020. 1. 1.자 2020다1 결정]',
            '[대법원 2020다1 판결]', '',
        ):
            with self.subTest(citation=citation):
                fetched = {'citation': citation, 'sections': [{'heading': '[이유]', 'text': '원문'}]}
                self.assertEqual(build_data.shared_fetched_by_decision(
                    [source], identities, {source['id']: fetched}), {})

    def test_constitutional_bench_format_requires_detc_source_and_correct_date(self):
        source = record(court='헌법재판소', caseNumber='95헌바3', lookupKey='95헌바3',
                        decisionDate='1995-12-28', decisionType='결정')
        fetched = {'kind': 'detc', 'citation': '[전원재판부 95헌바3, 1995. 12. 28.]'}
        self.assertTrue(build_data.fetched_citation_matches_record(source, fetched))
        fetched['citation'] = '[전원재판부 95헌바3, 1995. 12. 8.]'
        self.assertFalse(build_data.fetched_citation_matches_record(source, fetched))
        fetched['citation'] = '[전원재판부 95헌바3, 1995. 12. 28.]'
        for kind in ('prec', None):
            fetched['kind'] = kind
            self.assertFalse(build_data.fetched_citation_matches_record(source, fetched))

    def test_borrowing_guard_does_not_change_own_placement_rendering(self):
        source = record()
        research = record('research-one', 'research', title='연구 제목', tocPath=['research-root'],
                          research={'collection': 'civil-research', 'entryId': '1', 'order': 1})
        fetched = {'citation': '[대법원 2020. 1. 2. 선고 2020다1 판결]',
                   'sections': [{'heading': '[이유]', 'text': '기존 원문'}]}
        original = copy.deepcopy(fetched)
        with tempfile.TemporaryDirectory() as directory:
            registry_file, out_file = Path(directory) / 'registry.json', Path(directory) / 'cases.json'
            registry_file.write_text(json.dumps({'cases': [source, research]}, ensure_ascii=False), encoding='utf-8')
            with patch.multiple(build_data, REG=str(registry_file), OUT=str(out_file)), \
                    patch.object(build_data, 'load_toc', return_value={}), \
                    patch.object(build_data, 'load_fetched_records', return_value={source['id']: fetched, research['id']: None}), \
                    contextlib.redirect_stdout(io.StringIO()):
                build_data.build()
            cases = {item['id']: item for item in json.loads(out_file.read_text(encoding='utf-8'))['cases']}
        self.assertEqual(fetched, original)
        self.assertEqual(cases[source['id']]['fullText'], [{'heading': '[이유]', 'text': '기존 원문'}])
        self.assertIsNone(cases[research['id']]['fullText'])
        self.assertIsNone(cases[research['id']]['officialSourceId'])

    def test_canonical_merged_member_is_verified_in_abbreviated_citation(self):
        source = record(court='헌법재판소', decisionType='결정', decisionDate='2014-10-30',
                        caseNumber='2011헌바129,172(병합)', lookupKey='2011헌바172')
        fetched = {'kind': 'detc', 'citation': '[전원재판부 2011헌바129,172(병합), 2014. 10. 30.]'}
        self.assertEqual(identity(source)['decisionId'], 'cc-2011heonba172-20141030-decision')
        self.assertTrue(build_data.fetched_citation_matches_record(source, fetched))
        for wrong in (
            '[전원재판부 2011헌바129,173(병합), 2014. 10. 30.]',
            '[전원재판부 2011헌바129,172(병합), 2014. 10. 31.]',
        ):
            with self.subTest(citation=wrong):
                self.assertFalse(build_data.fetched_citation_matches_record(source, dict(fetched, citation=wrong)))

    def test_borrowing_prefers_official_source_over_longer_supplement(self):
        supplemental_record, official_record = record('supplement'), record('official')
        identities = {item['id']: identity(item) for item in (supplemental_record, official_record)}
        official = {'kind': 'prec', 'citation': '[대법원 2020. 1. 1. 선고 2020다1 판결]',
                    'sections': [{'heading': '[이유]', 'text': '공식 원문'}]}
        supplemental = dict(official, provider='user-provided', sourceLabel='사용자 제공 보충 자료',
                            sections=[{'heading': '[이유]', 'text': '길이가 더 긴 보충 자료의 원문' * 10}])
        before = copy.deepcopy((official, supplemental))
        for records in ([supplemental_record, official_record], [official_record, supplemental_record]):
            shared = build_data.shared_fetched_by_decision(records, identities,
                {'official': official, 'supplement': supplemental})
            self.assertEqual(shared[identities['official']['decisionId']][0], 'official')
            self.assertIs(shared[identities['official']['decisionId']][1], official)
        self.assertEqual((official, supplemental), before)

    def test_borrowed_supplement_keeps_its_source_label_and_field_type(self):
        source = record()
        research = record('research-one', 'research', title='연구 제목', tocPath=['research-root'],
                          research={'collection': 'civil-research', 'entryId': '1', 'order': 1})
        fetched = {'kind': 'prec', 'citation': '[대법원 2020. 1. 1. 선고 2020다1 판결]',
                   'provider': 'user-provided', 'sourceLabel': '사용자 제공 보충 자료',
                   'sourceUrl': 'https://example.test/supplied',
                   'sections': [{'heading': '[판결요지]', 'text': '보충 자료의 요지'},
                                {'heading': '[이유]', 'text': '보충 자료의 원문 ▒▒▒'}]}
        original = copy.deepcopy(fetched)
        with tempfile.TemporaryDirectory() as directory:
            registry_file, out_file = Path(directory) / 'registry.json', Path(directory) / 'cases.json'
            registry_file.write_text(json.dumps({'cases': [source, research]}, ensure_ascii=False), encoding='utf-8')
            with patch.multiple(build_data, REG=str(registry_file), OUT=str(out_file)), \
                    patch.object(build_data, 'load_toc', return_value={}), \
                    patch.object(build_data, 'load_fetched_records', return_value={source['id']: fetched, research['id']: None}), \
                    contextlib.redirect_stdout(io.StringIO()):
                build_data.build()
            cases = {item['id']: item for item in json.loads(out_file.read_text(encoding='utf-8'))['cases']}
        self.assertEqual(fetched, original)
        borrowed = cases['research-one']
        self.assertEqual(borrowed['officialSourceId'], source['id'])
        self.assertEqual(borrowed['source'], {'label': fetched['sourceLabel'], 'url': fetched['sourceUrl']})
        self.assertEqual(borrowed['fieldSources']['holdings']['type'], 'supplemental')
        self.assertEqual(borrowed['fieldSources']['holdings']['label'], fetched['sourceLabel'])
        self.assertNotEqual(borrowed['summaryType'], 'official')
        self.assertEqual(borrowed['fullText'], [{'heading': '[이유]', 'text': '보충 자료의 원문 ▒▒▒'}])

    def test_source_index_preserves_part_order_and_is_fresh_for_each_build(self):
        records = [record('source'), record('parts-only'), record('new-source')]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            files = {
                'source.json': {'citation': 'original', 'sections': [{'text': 'base'}]},
                'source.part2.json': {'sections': [{'text': 'part 2'}]},
                'source.part10.json': {'sections': [{'text': 'part 10'}]},
                'source.missing.json': {'sections': [{'text': 'must not appear'}]},
                'parts-only.part1.json': {'sections': [{'text': 'only part'}]},
            }
            for name, value in files.items():
                (folder / name).write_text(json.dumps(value), encoding='utf-8')
            before = {name: (folder / name).read_bytes() for name in files}
            with patch.object(build_data, 'FETCHED', directory):
                expected = {item['id']: build_data.load_fetched(item['id']) for item in records}
                with patch.object(build_data.os, 'scandir', wraps=os.scandir) as scandir:
                    actual = build_data.load_fetched_records(records)
                    self.assertEqual(scandir.call_count, 1)
                self.assertEqual(actual, expected)
                self.assertEqual([item['text'] for item in actual['source']['sections']], ['base', 'part 10', 'part 2'])
                self.assertIsNone(actual['new-source'])
                new_value = {'sections': [{'text': 'fresh source'}]}
                (folder / 'new-source.json').write_text(json.dumps(new_value), encoding='utf-8')
                fresh = build_data.load_fetched_records(records)
                self.assertEqual(fresh['new-source'], new_value)
            self.assertEqual(before, {name: (folder / name).read_bytes() for name in files})

    def test_build_keeps_collection_titles_and_shares_precedence_and_fulltext(self):
        standard = record()
        standard['standardSource'] = {
            'verified': True, 'book': 'fixture book', 'edition': 'test',
            'file': 'fixture.pdf', 'pages': [1],
            'holdings': [{'n': '', 'text': '검증된 표준판례 문구'}],
        }
        research = record('research-one', 'research', title='연구 목록 원제목',
                          tocPath=['research-root'],
                          research={'collection': 'civil-research', 'entryId': '1', 'order': 1})
        latest = record('latest-one', 'enbanc', title='최신판례 원제목', tocPath=[])
        fetched = {
            'sourceUrl': 'https://www.law.go.kr/fixture', 'pageTitle': '공식 사건명',
            'citation': '대법원 2020. 1. 1. 선고 2020다1 판결',
            'sections': [
                {'heading': '[판시사항]', 'text': '공식 판시사항'},
                {'heading': '[판결요지]', 'text': '공식 요지'},
                {'heading': '[전문]', 'text': ''},
                {'heading': '[주문]', 'text': '상고를 기각한다.'},
                {'heading': '[이유]', 'text': '원문 ▒▒▒\n  그대로'},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fetched_dir = root / 'fetched'
            fetched_dir.mkdir()
            official_file = fetched_dir / 'standard-existing.json'
            official_file.write_text(json.dumps(fetched, ensure_ascii=False), encoding='utf-8')
            official_bytes = official_file.read_bytes()
            registry_file, toc_file, out_file = root / 'registry.json', root / 'toc.json', root / 'cases.json'
            registry_file.write_text(json.dumps({'cases': [standard, research, latest]}, ensure_ascii=False), encoding='utf-8')
            toc_file.write_text(json.dumps({
                'civil': [{'id': 'std-root', 'label': '표준 목차'}],
                'research-civil': [{'id': 'research-root', 'label': '연구 목차'}],
            }, ensure_ascii=False), encoding='utf-8')
            with patch.multiple(build_data, REG=str(registry_file), TOC_FILE=str(toc_file),
                                FETCHED=str(fetched_dir), OUT=str(out_file)), contextlib.redirect_stdout(io.StringIO()):
                build_data.build()
            data = json.loads(out_file.read_text(encoding='utf-8'))
            self.assertEqual(official_file.read_bytes(), official_bytes)
        by_id = {item['id']: item for item in data['cases']}
        self.assertEqual(by_id['research-one']['page'], 'research-civil')
        self.assertEqual(by_id['research-one']['title'], '연구 목록 원제목')
        self.assertEqual(by_id['latest-one']['title'], '최신판례 원제목')
        self.assertEqual(by_id['standard-existing']['title'], '기존 화면 제목')
        for item in data['cases']:
            self.assertTrue(item['isStandard'])
            self.assertEqual(item['officialSourceId'], 'standard-existing')
            self.assertEqual(item['fieldSources']['holdings']['type'], 'standard')
            self.assertEqual(item['holdings'], standard['standardSource']['holdings'])
            self.assertEqual(item['officialSummary']['holdings'], [{'n': '', 'text': '공식 요지'}])
            self.assertEqual(item['fullText'], by_id['standard-existing']['fullText'])
            self.assertEqual(item['result'], '상고기각')
        page_ids = [page['id'] for page in data['pages']]
        self.assertLess(page_ids.index('std-commercial'), page_ids.index('research-civil'))
        self.assertLess(page_ids.index('research-criminal'), page_ids.index('annual'))


if __name__ == '__main__':
    unittest.main()
