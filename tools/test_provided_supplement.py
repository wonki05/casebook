"""사용자 제공 판례 검색 사이트 텍스트로 공식 수집본의 빠진 구역을 보충하는 흐름: 파싱(글자 보존)·대상 찾기·구역 선택, build_data 병합과 출처 표기, 구조 검사."""
import argparse
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import add_cases
import build_data
import provided_cc

HEADER = '헌법재판소 2018. 8. 30. 선고 2016헌마263 전원재판부 결정 [통신제한조치 허가 위헌확인 등] [헌집30-2, 1]'
OTHER_HEADER = '헌법재판소 2019. 11. 28. 선고 2017헌마1356 전원재판부 결정 [학생인권조례 위헌확인] [헌집31-2, 1]'
REASON_LINE = '청구인은 국가정보원장의 감청 집행에 관하여 이 사건 심판을 청구하였는데 사실관계가 길어서 쪽이'


def raw_doc(header=HEADER, reason_extra=()):
    return '\n'.join([
        header,
        '판시사항', '', '가.첫째 쟁점(적극)', '',
        '결정요지', '', '첫째 요지 문장이 아주 길어서 한 줄로 이어지다가 쪽이', '넘어가며 끊겼다. 이어지는 문장이다.', '',
        '심판대상조문', '', '통신비밀보호법 제5조 제2항', '통신비밀보호법 제6조', '',
        '청구인 \t', '', '홍길동대리인 변호사 김갑동 ',
        '피청구인 \t', '', '1. 서울중앙지방법원 판사', '2. 국가정보원장', '',
        '주    문', '', '1. 통신비밀보호법 제5조 제2항은 헌법에 합치되지 아니한다.', '2. 나머지 심판청구를 각하한다.', '',
        '이유', '', '1. 사건개요', '', REASON_LINE, '넘어가며 끊겼다.', '', '2. 판단', '', '이 사건 조항은 헌법에 위반된다.', *reason_extra, '',
        '재판장', '재판관', '이을순', '재판관', '김철수',
        '[별지1] 관련조항', '통신비밀보호법 제5조 제2항', '',
        '많이 하이라이트된 문장 표시', '소송경과', '2016. 1. 1.',
        '  ' + OTHER_HEADER,    # 인용판례 목록의 들여쓴 줄: 새 결정문의 머리글이 아니다
    ])


class ParseTests(unittest.TestCase):
    def test_sections_keep_every_character_and_drop_site_chrome(self):
        doc, cut, warnings = provided_cc.parse(raw_doc())
        self.assertEqual((doc['date'], doc['nums'], doc['pageTitle']), ('2018. 8. 30.', '2016헌마263', '통신제한조치 허가 위헌확인 등'))
        self.assertEqual(doc['sourceHeader'], HEADER)
        by = {s['heading']: s['text'] for s in doc['sections']}
        self.assertEqual([s['heading'] for s in doc['sections']],
                         ['【판시사항】', '【결정요지】', '【심판대상조문】', '【청구인】', '【피청구인】', '【주문】', '【이유】', '【별지1】'])
        self.assertEqual(by['【판시사항】'], '가.첫째 쟁점(적극)')
        self.assertEqual(by['【결정요지】'], '첫째 요지 문장이 아주 길어서 한 줄로 이어지다가 쪽이 넘어가며 끊겼다. 이어지는 문장이다.')
        self.assertEqual(by['【심판대상조문】'], '통신비밀보호법 제5조 제2항\n통신비밀보호법 제6조')    # 조문 목록은 줄을 잇지 않는다
        self.assertEqual(by['【청구인】'], '홍길동대리인 변호사 김갑동')
        self.assertEqual(by['【피청구인】'], '1. 서울중앙지방법원 판사\n2. 국가정보원장')
        self.assertEqual(by['【주문】'], '1. 통신비밀보호법 제5조 제2항은 헌법에 합치되지 아니한다.\n2. 나머지 심판청구를 각하한다.')
        self.assertEqual(by['【이유】'], '\n'.join(['1. 사건개요', REASON_LINE + ' 넘어가며 끊겼다.', '2. 판단', '이 사건 조항은 헌법에 위반된다.',
                                               '재판장 재판관 이을순', '재판관 김철수']))
        self.assertEqual(by['【별지1】'], '관련조항\n통신비밀보호법 제5조 제2항')
        self.assertEqual(cut['post'][0], '많이 하이라이트된 문장 표시')
        self.assertEqual(len([w for w in warnings if w.startswith('JOIN')]), 2)   # 쪽 나눔으로 끊긴 줄 2곳을 이었다
        everything = ''.join(provided_cc.compact(s['text']) for s in doc['sections'])
        for chrome in provided_cc.CHROME:
            self.assertNotIn(chrome, everything)

    def test_words_cut_in_the_middle_are_joined_without_a_space_and_signatures_in_one_line_per_judge(self):
        extra = ('국가는 개인의 통신비밀을 보호하여야 하고 위 조항이 위헌이라는 점은 의문의 여지가 없으므로 과잉금지원', '칙을 위반한다.')
        doc, _, _ = provided_cc.parse(raw_doc(reason_extra=extra))
        reason = next(s['text'] for s in doc['sections'] if s['heading'] == '【이유】')
        self.assertIn('과잉금지원칙을 위반한다.', reason)    # 낱말 중간에서 끊긴 줄은 띄우지 않고 붙인다
        self.assertNotIn('원 칙', reason)
        self.assertTrue(reason.endswith('재판장 재판관 이을순\n재판관 김철수'))

    def test_guard_stops_when_the_cleaned_text_differs_from_the_source(self):
        with patch.object(provided_cc, 'join_broken', lambda lines, warnings, where: [x.strip()[:-1] for x in lines if x.strip()]):
            with self.assertRaisesRegex(ValueError, '글자가 어긋납니다'):
                provided_cc.parse(raw_doc())

    def test_missing_header_unknown_lines_and_pasted_wrappers(self):
        with self.assertRaises(ValueError):
            provided_cc.parse('판시사항\n본문')
        with self.assertRaisesRegex(ValueError, '구역 제목 없는 줄'):
            provided_cc.parse(HEADER + '\n구역 제목 없는 줄\n주문\n내용\n이유\n본문')
        wrapped = '<pasted_content id="abc">\n' + raw_doc() + '\n</pasted_content>'
        doc, _, _ = provided_cc.parse(wrapped)
        self.assertEqual(doc['nums'], '2016헌마263')

    def test_split_documents_cuts_at_column_zero_headers_only(self):
        raw = raw_doc() + '\n' + raw_doc(header=OTHER_HEADER)
        docs = provided_cc.split_documents(raw)
        self.assertEqual(len(docs), 2)    # 들여쓴 머리글 모양 줄은 나누는 자리가 아니다
        (start1, end1, chunk1), (start2, end2, chunk2) = docs
        self.assertEqual((start1, end1 + 1 == start2), (1, True))
        self.assertTrue(chunk2.startswith(OTHER_HEADER))
        self.assertTrue(chunk1.startswith(HEADER))
        with self.assertRaises(ValueError):
            provided_cc.split_documents('머리글 없음')


class AttachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.fetched = self.dir / 'fetched'
        self.fetched.mkdir()
        self.registry = [
            self.case('std-constitution-1'), self.case('std-constitution-2'),
            self.case('std-constitution-3', lookupKey='2016헌마2630', caseNumber='2016헌마2630'),
            self.case('annual-2018-1', group='annual')]
        self.official = {'id': 'std-constitution-1', 'citation': '[전원재판부 2016헌마263, 2018. 8. 30.]', 'kind': 'detc',
                         'sections': [{'heading': '【판시사항】', 'text': '가.첫째  쟁점(적극)'},
                                      {'heading': '【결정요지】', 'text': '공식 요지는 다르게 적혀 있다'},
                                      {'heading': '【심판대상조문】', 'text': '통신비밀보호법 제5조 제2항\n통신비밀보호법 제6조'}]}
        (self.dir / 'registry.json').write_text(json.dumps({'cases': self.registry}, ensure_ascii=False), encoding='utf-8')
        self.write_official('std-constitution-1', self.official)
        self.raw = self.dir / 'provided.txt'
        self.raw.write_text(raw_doc(), encoding='utf-8')

    @staticmethod
    def case(cid, **kw):
        return {'id': cid, 'group': 'standard', 'court': '헌법재판소', 'decisionDate': '2018-08-30',
                'lookupKey': '2016헌마263', 'caseNumber': '2016헌마263', **kw}

    def write_official(self, cid, obj):
        (self.fetched / (cid + '.json')).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')

    def attach(self, **kw):
        args = argparse.Namespace(raw=str(self.raw), dry_run=False, supplied_at='2026-11-02', **kw)
        out = io.StringIO()
        with patch.multiple(provided_cc, REG=str(self.dir / 'registry.json'), FETCHED=str(self.fetched)), redirect_stdout(out):
            provided_cc.cmd_attach(args)
        return out.getvalue()

    def test_find_host_needs_the_exact_decision_and_a_collected_official_file(self):
        doc, _, _ = provided_cc.parse(raw_doc())
        with patch.object(provided_cc, 'FETCHED', str(self.fetched)):
            matches, hosts = provided_cc.find_host(self.registry, doc)
        self.assertEqual([c['id'] for c in matches], ['std-constitution-1', 'std-constitution-2'])   # 번호 2016헌마2630·표준판례가 아닌 배치 제외
        self.assertEqual([c['id'] for c in hosts], ['std-constitution-1'])
        self.assertTrue(provided_cc.docket_present('2012헌마191, 550(병합)', '2012헌마191'))
        self.assertFalse(provided_cc.docket_present('2016헌마2630', '2016헌마263'))

    def test_attach_writes_only_the_missing_sections_with_provenance(self):
        output = self.attach()
        self.assertIn('std-constitution-1', output)
        path = self.fetched / 'std-constitution-1.supplement.json'
        record = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([s['heading'] for s in record['sections']], ['【청구인】', '【피청구인】', '【주문】', '【이유】', '【별지1】'])
        self.assertEqual((record['id'], record['kind'], record['provider'], record['suppliedAt']),
                         ('std-constitution-1', 'supplement', 'casenote', '2026-11-02'))
        self.assertEqual(record['sourceLabel'], provided_cc.LABEL)
        self.assertEqual(record['sourceHeader'], HEADER)
        self.assertIn('국가법령정보센터 공식 원문이 아니다', record['sourceNote'])
        self.assertIn('판시사항', record['sourceNote'])   # 공식본에 이미 있어 쓰지 않은 구역을 밝힌다
        chunk = provided_cc.split_documents(raw_doc())[0][2]
        self.assertEqual(record['retrieval']['sourceTextSha256'], hashlib.sha256(chunk.encode('utf-8')).hexdigest())
        self.assertEqual(record['retrieval']['sourceLineRange'][0], 1)
        self.assertIn('공식본에 있어 건너뜀 【결정요지】: 공식본과 글자가 다름', output)
        self.assertIn('공식본에 있어 건너뜀 【판시사항】: 공식본과 글자 같음(공백 제외)', output)
        # 공식 수집본은 그대로, 다시 실행해도 같은 결과
        self.assertEqual(json.loads((self.fetched / 'std-constitution-1.json').read_text(encoding='utf-8')), self.official)
        first = path.read_bytes()
        self.attach()
        self.assertEqual(path.read_bytes(), first)

    def test_dry_run_writes_nothing_and_ambiguous_or_missing_hosts_stop(self):
        args = argparse.Namespace(raw=str(self.raw), dry_run=True, supplied_at='2026-11-02')
        with patch.multiple(provided_cc, REG=str(self.dir / 'registry.json'), FETCHED=str(self.fetched)), redirect_stdout(io.StringIO()):
            provided_cc.cmd_attach(args)
        self.assertFalse((self.fetched / 'std-constitution-1.supplement.json').exists())
        self.write_official('std-constitution-2', {**self.official, 'id': 'std-constitution-2'})
        with self.assertRaises(SystemExit) as ctx:       # 공식 수집본이 있는 배치가 둘이면 고르지 않는다
            self.attach()
        self.assertIn('하나가 아닙니다', str(ctx.exception))
        (self.fetched / 'std-constitution-1.json').unlink()
        (self.fetched / 'std-constitution-2.json').unlink()
        with self.assertRaises(SystemExit):
            self.attach()

    def test_build_supplement_refuses_duplicates_of_the_official_body_and_site_chrome(self):
        doc, _, _ = provided_cc.parse(raw_doc())
        host = {'id': 'std-constitution-1'}
        with self.assertRaisesRegex(ValueError, '같은 본문이 이미 있습니다'):    # 구역 제목만 다르게 수집된 공식 본문(예: 368번)
            body = next(s['text'] for s in doc['sections'] if s['heading'] == '【이유】')
            provided_cc.build_supplement(host, {'sections': [{'heading': '[당 사 자]', 'text': body}]}, doc, 'raw', 'f.txt', (1, 2), '2026-11-02')
        with self.assertRaisesRegex(ValueError, '보충할 것이 없습니다'):
            provided_cc.build_supplement(host, {'sections': [{'heading': '【이 유】', 'text': '다른 본문'}]}, doc, 'raw', 'f.txt', (1, 2), '2026-11-02')
        dirty, _, _ = provided_cc.parse(raw_doc(reason_extra=('유사판례 목록이 본문에 섞였다.',)))
        with self.assertRaisesRegex(ValueError, '부가정보'):
            provided_cc.build_supplement(host, {'sections': []}, dirty, 'raw', 'f.txt', (1, 2), '2026-11-02')


class BuildMergeTests(unittest.TestCase):
    SUPPLEMENT_NOTE = '빠진 구역을 사용자가 제공한 텍스트로 보충했다.'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.fetched = self.dir / 'fetched'
        self.fetched.mkdir()

    @staticmethod
    def record(cid):
        return {'id': cid, 'group': 'standard', 'subject': 'constitution', 'court': '헌법재판소', 'caseNumber': '2016헌마263',
                'lookupKey': '2016헌마263', 'decisionDate': '2018-08-30', 'decisionType': '결정', 'title': '테스트',
                'tocPath': ['hb-test'], 'enBanc': False, 'editorial': {}}

    def put(self, name, obj):
        (self.fetched / name).write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')

    def official(self):
        return {'citation': '[전원재판부 2016헌마263, 2018. 8. 30.]', 'kind': 'detc', 'pageTitle': '통신제한조치 허가 위헌확인 등',
                'sourceUrl': 'https://example.invalid/detc', 'sections': [
                    {'heading': '【판시사항】', 'text': '공식 쟁점 fixture'},
                    {'heading': '【결정요지】', 'text': '공식 요지 fixture'}]}

    def supplement(self, cid='a'):
        return {'id': cid, 'kind': 'supplement', 'provider': 'casenote', 'sourceLabel': '판례 검색 사이트 수록본 · 사용자 제공 보충 자료',
                'sourceHeader': 'header', 'sourceNote': self.SUPPLEMENT_NOTE, 'suppliedAt': '2026-11-02', 'sections': [
                    {'heading': '【판시사항】', 'text': '제공본 쟁점은 쓰지 않는다'},
                    {'heading': '【심판대상조문】', 'text': '통신비밀보호법 제5조 제2항'},
                    {'heading': '【청구인】', 'text': '홍길동'},
                    {'heading': '【주문】', 'text': '심판청구를 기각한다.'},
                    {'heading': '【이유】', 'text': '제공본 이유 fixture'}]}

    def build(self, records):
        reg = self.dir / 'registry.json'
        toc = self.dir / 'toc.json'
        out = self.dir / 'cases.json'
        reg.write_text(json.dumps({'cases': records}, ensure_ascii=False), encoding='utf-8')
        toc.write_text(json.dumps({'constitution': [{'id': 'hb-test', 'label': '테스트', 'children': []}]}), encoding='utf-8')
        with patch.multiple(build_data, REG=str(reg), TOC_FILE=str(toc), FETCHED=str(self.fetched), OUT=str(out)), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            build_data.build()
        return {c['id']: c for c in json.loads(out.read_text(encoding='utf-8'))['cases']}

    def test_supplement_sections_follow_the_official_ones_and_official_wins_on_the_same_heading(self):
        self.put('a.json', self.official())
        self.put('a.supplement.json', self.supplement())
        before = {p.name: p.read_bytes() for p in self.fetched.iterdir()}
        merged = build_data.load_fetched_paths(sorted(str(p) for p in self.fetched.iterdir()))
        self.assertEqual([s['heading'] for s in merged['sections']], ['【판시사항】', '【결정요지】', '【심판대상조문】', '【청구인】', '【주문】', '【이유】'])
        self.assertEqual(merged['sections'][0]['text'], '공식 쟁점 fixture')   # 같은 제목은 공식본
        self.assertEqual(merged['supplements'][0]['headings'], ['【심판대상조문】', '【청구인】', '【주문】', '【이유】'])
        data = self.build([self.record('a')])['a']
        self.assertEqual([s['heading'] for s in data['fullText']], ['[청구인]', '[주문]', '[이유]'])
        self.assertEqual(data['fullText'][-1]['text'], '제공본 이유 fixture')
        self.assertEqual(data['issues'][0]['text'], '공식 쟁점 fixture')
        self.assertEqual(data['subjectStatutes'], ['통신비밀보호법 제5조 제2항'])
        self.assertEqual(data['fieldSources']['issues']['type'], 'official')
        self.assertEqual(data['fieldSources']['subjectStatutes']['type'], 'supplemental')   # 공식 원문이라고 표시하지 않는다
        self.assertEqual(data['fieldSources']['subjectStatutes']['label'], self.supplement()['sourceLabel'])
        self.assertEqual(data['source']['label'], '국가법령정보센터 · ' + self.supplement()['sourceLabel'])
        self.assertEqual(data['source']['url'], 'https://example.invalid/detc')
        self.assertEqual(data['supplements'][0]['suppliedAt'], '2026-11-02')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.fetched.iterdir()})   # 수집 파일은 바뀌지 않는다

    def test_a_placement_without_its_own_file_shares_the_merged_text_of_the_same_decision(self):
        self.put('a.json', self.official())
        self.put('a.supplement.json', self.supplement())
        built = self.build([self.record('a'), self.record('b')])
        self.assertEqual(built['b']['officialSourceId'], 'a')
        self.assertEqual(built['b']['fullText'], built['a']['fullText'])
        self.assertEqual(built['b']['source'], built['a']['source'])

    def test_official_only_cases_keep_the_plain_source_label(self):
        self.put('a.json', {**self.official(), 'sections': self.official()['sections'] + [{'heading': '【이 유】', 'text': '공식 이유'}]})
        data = self.build([self.record('a')])['a']
        self.assertEqual(data['source']['label'], '국가법령정보센터')
        self.assertNotIn('supplemental', {v['type'] for v in data['fieldSources'].values()})
        self.assertFalse(data.get('supplements'))

    def test_supplement_without_an_official_file_is_ignored(self):
        self.put('a.supplement.json', self.supplement())
        with redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(build_data.load_fetched_paths([str(self.fetched / 'a.supplement.json')]))
        self.assertIn('공식 수집본이 없음', err.getvalue())


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fetched = Path(self.temp.name)

    def good(self, **kw):
        return {'id': 'a', 'provider': 'casenote', 'sourceLabel': '라벨', 'sourceHeader': '머리글', 'sourceNote': '설명',
                'suppliedAt': '2026-11-02', 'sections': [{'heading': '【이유】', 'text': '본문'}, {'heading': '[별지1]', 'text': '표'}], **kw}

    def errors(self, supplement, main=True, name='a.supplement.json'):
        if main:
            (self.fetched / 'a.json').write_text('{}', encoding='utf-8')
        (self.fetched / name).write_text(json.dumps(supplement, ensure_ascii=False), encoding='utf-8')
        with patch.object(add_cases, 'FETCHED', str(self.fetched)):
            return add_cases.supplement_errors()

    def test_well_formed_supplement_passes(self):
        self.assertEqual(self.errors(self.good()), [])

    def test_missing_main_file_provenance_id_and_headings_are_reported(self):
        self.assertIn('공식 수집본 a.json 이 없습니다', ''.join(self.errors(self.good(), main=False)))
        bad_id = self.errors(self.good(id='b'))
        self.assertTrue(any('파일명과 다릅니다' in e for e in bad_id))
        missing = self.good()
        del missing['sourceNote'], missing['suppliedAt']
        found = ''.join(self.errors(missing))
        self.assertIn('sourceNote', found)
        self.assertIn('suppliedAt', found)
        self.assertTrue(any('구역 제목은' in e for e in self.errors(self.good(sections=[{'heading': '이유', 'text': 'x'}]))))
        self.assertTrue(any('구역 제목은' in e for e in self.errors(self.good(sections=[{'heading': '【이유】', 'text': 3}]))))
        self.assertTrue(any('sections 가 없습니다' in e for e in self.errors(self.good(sections=[]))))


if __name__ == '__main__':
    unittest.main()
