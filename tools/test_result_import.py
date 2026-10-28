"""Result evidence imports stay within criminal standard placements and fail atomically."""
import copy
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import add_cases
from case_identity import identity


def record(cid='std-criminal-01', **changes):
    item = {'id': cid, 'group': 'standard', 'subject': 'criminal',
            'court': '대법원', 'caseNumber': '2020도1', 'lookupKey': '2020도1',
            'decisionDate': '2020-01-02', 'decisionType': '판결',
            'title': '기존 제목', 'result': '', 'editorial': {'keep': 'original'}}
    item.update(changes)
    item.update(identity(item))
    return item


def entry(item=None, **changes):
    item = item or record()
    value = {'id': item['id'], 'decisionId': item['decisionId'], 'result': '상고기각',
             'resultSource': {'type': 'official', 'label': '국가법령정보센터',
                              'url': 'https://www.law.go.kr/LSW/precInfoP.do?precSeq=123',
                              'citation': '[대법원 2020. 1. 2. 선고 2020도1 판결]',
                              'order': '  상고를 기각한다.\n상고비용은 피고인이 부담한다.  ',
                              'sourceSha256': 'a' * 64, 'verified': True}}
    value.update(changes)
    return value


def catalog(*entries):
    return {'scope': {'group': 'standard', 'subject': 'criminal'},
            'cases': list(entries) if entries else [entry()]}


class ResultImportTests(unittest.TestCase):
    def setUp(self):
        self.reg = {'cases': [record(), record('std-civil-01', subject='civil'),
                              record('research-criminal-001', group='research')],
                    'identityAliases': {'legacy': 'preserve'}}

    def test_changes_only_empty_target_result_and_preserves_verbatim_evidence(self):
        payload = catalog()
        before = copy.deepcopy((self.reg, payload))
        result, report = add_cases.import_results(self.reg, payload)
        expected = copy.deepcopy(self.reg)
        expected['cases'][0].update(result=payload['cases'][0]['result'],
                                    resultSource=payload['cases'][0]['resultSource'])
        self.assertEqual(result, expected)
        self.assertEqual((self.reg, payload), before)
        self.assertEqual(report, {'changed': ['std-criminal-01'], 'unchanged': []})
        payload['cases'][0]['resultSource']['order'] = 'changed input'
        self.assertEqual(result['cases'][0]['resultSource']['order'], before[1]['cases'][0]['resultSource']['order'])

    def test_same_import_is_idempotent(self):
        first, _ = add_cases.import_results(self.reg, catalog())
        second, report = add_cases.import_results(first, catalog())
        self.assertEqual(first, second)
        self.assertEqual(report, {'changed': [], 'unchanged': ['std-criminal-01']})

    def test_existing_same_result_without_evidence_is_not_modified(self):
        self.reg['cases'][0]['result'] = '상고기각'
        result, report = add_cases.import_results(self.reg, catalog())
        self.assertEqual(result, self.reg)
        self.assertEqual(report['changed'], [])

    def test_existing_different_result_and_different_source_are_rejected(self):
        for existing in ({'result': '파기환송'},
                         {'result': '상고기각', 'resultSource': {'order': 'keep existing'}},
                         {'resultSource': {'order': 'keep existing'}}):
            with self.subTest(existing=existing):
                reg = copy.deepcopy(self.reg)
                reg['cases'][0].update(existing)
                before = copy.deepcopy(reg)
                with self.assertRaises(ValueError):
                    add_cases.import_results(reg, catalog())
                self.assertEqual(reg, before)

    def test_scope_and_nonstandard_targets_are_rejected(self):
        for scope in (None, {'group': 'research', 'subject': 'criminal'},
                      {'group': 'standard', 'subject': 'civil'},
                      {'group': 'standard', 'subject': 'criminal', 'all': True}):
            with self.subTest(scope=scope):
                payload = catalog()
                payload['scope'] = scope
                with self.assertRaises(ValueError):
                    add_cases.import_results(self.reg, payload)
        for item in self.reg['cases'][1:]:
            with self.subTest(id=item['id']), self.assertRaises(ValueError):
                add_cases.import_results(self.reg, catalog(entry(item)))

    def test_unknown_duplicate_and_wrong_decision_ids_are_rejected(self):
        for payload in (catalog(entry(id='missing')), catalog(entry(), entry()),
                        catalog(entry(decisionId='sc-2020do2-20200102-judgment'))):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                add_cases.import_results(self.reg, payload)
        self.reg['cases'][0]['decisionId'] = 'stored-wrong-id'
        with self.assertRaises(ValueError):
            add_cases.import_results(self.reg, catalog(entry(self.reg['cases'][0])))

    def test_source_identity_conflicts_are_rejected(self):
        citations = ['[대법원 2020. 1. 3. 선고 2020도1 판결]',
                     '[대법원 2020. 1. 2. 선고 2020도2 판결]',
                     '[대법원 2020. 1. 2. 자 2020도1 결정]',
                     '[서울고등법원 2020. 1. 2. 선고 2020도1 판결]', '인용문 없음']
        for citation in citations:
            with self.subTest(citation=citation):
                payload = catalog()
                payload['cases'][0]['resultSource']['citation'] = citation
                with self.assertRaises(ValueError):
                    add_cases.import_results(self.reg, payload)

    def test_known_reporter_aliases_and_chamber_labels_preserve_raw_citation(self):
        examples = [
            ('std-criminal-339', '서울고등법원', '73노179', '1973-04-20',
             '[서울고법 1973. 4. 20. 선고 73노179 제3형사부판결 : 상고]'),
            ('std-criminal-439', '서울남부지방법원', '2010고합331', '2010-12-30',
             '[서울남부지법 2010. 12. 30. 선고 2010고합331 판결 : 항소]'),
        ]
        for cid, court, number, date, citation in examples:
            with self.subTest(id=cid):
                target = record(cid, court=court, caseNumber=number, lookupKey=number,
                                decisionDate=date)
                payload = catalog(entry(target))
                payload['cases'][0]['resultSource']['citation'] = citation
                original = copy.deepcopy(payload)
                updated, report = add_cases.import_results({'cases': [target]}, payload)
                self.assertEqual(report['changed'], [cid])
                self.assertEqual(updated['cases'][0]['resultSource']['citation'], citation)
                self.assertEqual(payload, original)

    def test_unknown_reporter_court_aliases_are_not_guessed(self):
        target = record(court='서울고등법원', caseNumber='73노179', lookupKey='73노179',
                        decisionDate='1973-04-20')
        for alias in ('고법', '서울고법원', '서울지법', '부산고법'):
            with self.subTest(alias=alias):
                payload = catalog(entry(target))
                payload['cases'][0]['resultSource']['citation'] = f'[{alias} 1973. 4. 20. 선고 73노179 판결]'
                with self.assertRaises(ValueError):
                    add_cases.import_results({'cases': [target]}, payload)

    def test_expanded_aliases_still_require_matching_court_date_case_and_type(self):
        target = record(court='서울고등법원', caseNumber='73노179', lookupKey='73노179',
                        decisionDate='1973-04-20')
        citations = [
            '[서울고법 1973. 4. 21. 선고 73노179 제3형사부판결 : 상고]',
            '[서울고법 1973. 4. 20. 선고 73노180 제3형사부판결 : 상고]',
            '[서울고법 1973. 4. 20. 자 73노179 결정]',
            '[서울남부지법 1973. 4. 20. 선고 73노179 판결]',
        ]
        for citation in citations:
            with self.subTest(citation=citation):
                payload = catalog(entry(target))
                payload['cases'][0]['resultSource']['citation'] = citation
                original = copy.deepcopy(payload)
                with self.assertRaises(ValueError):
                    add_cases.import_results({'cases': [target]}, payload)
                self.assertEqual(payload, original)

    def merged_evidence_fixture(self):
        target = record('std-criminal-174', caseNumber='2007감도22', lookupKey='2007감도22',
                        decisionDate='2007-11-29')
        payload = catalog(entry(target))
        payload['cases'][0]['resultSource']['citation'] = '[대법원 2007. 11. 29. 선고 2007도8333 판결]'
        payload['cases'][0]['resultSource']['mergedIdentityEvidence'] = {
            'type': 'standard', 'book': '표준판례', 'edition': '2023년 개정판',
            'file': 'data/standard-cases/표준판례(2023년 개정판)_형법.pdf', 'pages': [197],
            'citation': '(대법원 2007.11.29. 선고 2007도8333, 2007감도22 판결)',
            'sourceSha256': 'b' * 64, 'verified': True}
        return {'cases': [target], 'identityAliases': {'legacy': 'keep'}}, payload

    def test_merged_book_citation_can_verify_unlisted_member_without_identity_changes(self):
        reg, payload = self.merged_evidence_fixture()
        before = copy.deepcopy((reg, payload))
        updated, report = add_cases.import_results(reg, payload)
        expected = copy.deepcopy(reg)
        expected['cases'][0].update(result=payload['cases'][0]['result'],
                                    resultSource=payload['cases'][0]['resultSource'])
        self.assertEqual(updated, expected)
        self.assertEqual((reg, payload), before)
        self.assertEqual(report['changed'], ['std-criminal-174'])
        repeated, report = add_cases.import_results(updated, payload)
        self.assertEqual(repeated, updated)
        self.assertEqual(report['changed'], [])

    def test_missing_or_unverified_merged_evidence_is_rejected(self):
        reg, payload = self.merged_evidence_fixture()
        evidence = payload['cases'][0]['resultSource'].pop('mergedIdentityEvidence')
        with self.assertRaises(ValueError):
            add_cases.import_results(reg, payload)
        invalid = {'type': ['provided', None], 'book': ['', None], 'edition': ['', None],
                   'file': ['', None], 'citation': ['', '인용문 없음', None],
                   'pages': [[], [0], [-1], [True], ['197'], None],
                   'sourceSha256': ['', 'x' * 64, 'a' * 63, None], 'verified': [False, 1, None]}
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    changed = copy.deepcopy(evidence)
                    changed[key] = value
                    payload['cases'][0]['resultSource']['mergedIdentityEvidence'] = changed
                    with self.assertRaises(ValueError):
                        add_cases.import_results(reg, payload)

    def test_merged_evidence_must_match_court_date_type_and_all_official_members(self):
        reg, payload = self.merged_evidence_fixture()
        citations = [
            '(대법원 2007.11.30. 선고 2007도8333, 2007감도22 판결)',
            '(서울고등법원 2007.11.29. 선고 2007도8333, 2007감도22 판결)',
            '(대법원 2007.11.29. 자 2007도8333, 2007감도22 결정)',
            '(대법원 2007.11.29. 선고 2007도8333 판결)',
            '(대법원 2007.11.29. 선고 2007감도22 판결)',
            '(대법원 2007.11.29. 선고 2007도8333, 2007감도23 판결)',
        ]
        for citation in citations:
            with self.subTest(citation=citation):
                payload['cases'][0]['resultSource']['mergedIdentityEvidence']['citation'] = citation
                before = copy.deepcopy((reg, payload))
                with self.assertRaises(ValueError):
                    add_cases.import_results(reg, payload)
                self.assertEqual((reg, payload), before)

    def test_merged_evidence_cannot_override_official_court_date_or_type(self):
        reg, payload = self.merged_evidence_fixture()
        citations = [
            '[대법원 2007. 11. 30. 선고 2007도8333 판결]',
            '[서울고등법원 2007. 11. 29. 선고 2007도8333 판결]',
            '[대법원 2007. 11. 29. 자 2007도8333 결정]',
        ]
        for citation in citations:
            with self.subTest(citation=citation):
                payload['cases'][0]['resultSource']['citation'] = citation
                with self.assertRaises(ValueError):
                    add_cases.import_results(reg, payload)

    def test_book_merged_member_exception_is_only_for_official_sources(self):
        reg, payload = self.merged_evidence_fixture()
        payload['cases'][0]['resultSource'].update(type='provided', label='사용자 제공', url='')
        with self.assertRaises(ValueError):
            add_cases.import_results(reg, payload)

    def test_source_structure_is_required(self):
        invalid = {'type': ['editorial', None], 'label': ['', None],
                   'citation': ['', None], 'order': ['', '  ', None],
                   'sourceSha256': ['', 'x' * 64, 'a' * 63, None],
                   'verified': [False, 1, None],
                   'url': ['', 'https://example.com/case', 'https://www.law.go.kr.example.com/',
                           'https://user:secret@www.law.go.kr/', None]}
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = catalog()
                    payload['cases'][0]['resultSource'][field] = value
                    with self.assertRaises(ValueError):
                        add_cases.import_results(self.reg, payload)
        for result in ('', ' 상고기각', '상고기각\n파기환송', None):
            with self.subTest(result=result), self.assertRaises(ValueError):
                add_cases.import_results(self.reg, catalog(entry(result=result)))

    def test_provided_source_can_preserve_absent_original_url(self):
        payload = catalog()
        payload['cases'][0]['resultSource'].update(type='provided', label='사용자 제공 판결문', url='')
        result, _ = add_cases.import_results(self.reg, payload)
        self.assertEqual(result['cases'][0]['resultSource'], payload['cases'][0]['resultSource'])

    def test_later_failure_leaves_original_registry_untouched(self):
        before = copy.deepcopy(self.reg)
        with self.assertRaises(ValueError):
            add_cases.import_results(self.reg, catalog(entry(), entry(id='missing')))
        self.assertEqual(self.reg, before)

    def test_cli_dry_run_atomic_failure_and_single_guarded_save(self):
        with tempfile.TemporaryDirectory() as directory:
            registry, toc, payload = (Path(directory) / name for name in ('registry.json', 'toc.json', 'input.json'))
            initial_registry = (json.dumps(self.reg, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            initial_toc = b'{\r\n "criminal": []\r\n}\r\n'
            registry.write_bytes(initial_registry)
            toc.write_bytes(initial_toc)
            payload.write_text(json.dumps(catalog(), ensure_ascii=False), encoding='utf-8')
            args = ['add_cases.py', 'result-import', '--from', str(payload)]
            with patch.multiple(add_cases, REG=str(registry), TOC=str(toc), _loaded_bytes={}):
                with patch.object(sys, 'argv', args + ['--dry-run']), contextlib.redirect_stdout(io.StringIO()):
                    add_cases.main()
                self.assertEqual(registry.read_bytes(), initial_registry)
                self.assertEqual(toc.read_bytes(), initial_toc)
                payload.write_text(json.dumps(catalog(entry(), entry(id='missing'))), encoding='utf-8')
                with patch.object(sys, 'argv', args), self.assertRaises(SystemExit):
                    add_cases.main()
                self.assertEqual(registry.read_bytes(), initial_registry)
                payload.write_text(json.dumps(catalog()), encoding='utf-8')
                with patch.object(add_cases, 'save', wraps=add_cases.save) as save:
                    with patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()):
                        add_cases.main()
                    self.assertEqual(save.call_count, 1)
                self.assertEqual(toc.read_bytes(), initial_toc)
                self.assertEqual(json.loads(registry.read_bytes())['cases'][0]['result'], '상고기각')
                saved = registry.read_bytes()
                with patch.object(add_cases, 'save', wraps=add_cases.save) as save:
                    with patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()):
                        add_cases.main()
                    save.assert_not_called()
                self.assertEqual(registry.read_bytes(), saved)

    def test_concurrent_toc_change_prevents_any_registry_write(self):
        with tempfile.TemporaryDirectory() as directory:
            registry, toc = Path(directory) / 'registry.json', Path(directory) / 'toc.json'
            registry.write_text(json.dumps(self.reg), encoding='utf-8')
            toc.write_text('{}', encoding='utf-8')
            before = registry.read_bytes()
            with patch.multiple(add_cases, REG=str(registry), TOC=str(toc), _loaded_bytes={}):
                reg, tree = add_cases.load()
                updated, _ = add_cases.import_results(reg, catalog())
                toc.write_text('{"changed": true}', encoding='utf-8')
                with self.assertRaises(SystemExit):
                    add_cases.save(reg=updated, toc=tree)
            self.assertEqual(registry.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
