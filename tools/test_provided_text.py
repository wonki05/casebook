"""provided_text.py: 사용자 제공 판결문 텍스트의 정제(parse)와 fetched 저장(import) 검사. 합성 fixture 만 쓴다."""
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
import provided_text as pt

CASENOTE = '''7번. 대판 2099도1



    기관: 어느대학교
    홍길동

대법원 2099. 1. 2. 선고 2099도1 전원합의체 판결 [사기, 횡령(인정된 죄명 : 횡령미수)] [공2099상,1]
판시사항

[1] 첫째 쟁점

[2] 둘째 쟁점
판결요지

[1] 첫째 요지입니다.

[2] 둘째 요지입니다.
참조조문

[1] 형법 제1조 / [2] 형법 제2조
사 건 \t

2099도1 가. 사기

나. 횡령
피고인 \t

A
상고인 \t

검사
원심판결 \t

서울고등법원 2098. 5. 1. 선고 2098노1 판결
판결선고 \t

2099. 1. 2.

주 문

상고를 기각한다.

이 유

상고이유를 판단한다.

1. 사교적 의례의 형식을 빌려 금품을 주고받았다

고 하더라도 뇌물이 된다.

2. 그러므로 상고를 기각하기로 하여 주문과 같이 판결한다.
재판장
대법관
갑돌이
주심
대법관
을순이

대법관
병수

많이 하이라이트된 문장 표시

소송경과

    서울고등법원 2098. 5. 1. 선고 2098노1 판결

인용판례
유사판례

    대법원 2090. 1. 1. 선고 2090도1 판결

주식회사 엘박스
'''

PLAIN = '''<pasted_content id="x">
대법원
제2부
판결
사건
69도1 가.살인 나.사체유기
피고인
, 상고인 가.나. ▒▒▒
변호인
변호사 ▒▒▒
원판결
서울고등법원 1969. 11.13. 선고 69노1 판결
주 문
상고를 기각한다.
이 유
피고인의 상고 이유를 검토한다. 상고는 이유 없다. 1970. 3. 10.
대법원판사 갑 을 병
</pasted_content id="x">
'''


class ParseTests(unittest.TestCase):
    def test_casenote_keeps_only_the_judgment(self):
        spec, cut, warnings = pt.parse(CASENOTE)
        self.assertEqual(spec['citation'], '[대법원 2099. 1. 2. 선고 2099도1 전원합의체 판결]')
        self.assertEqual(spec['pageTitle'], '사기, 횡령(인정된 죄명 : 횡령미수)')
        self.assertTrue(spec['sourceHeader'].endswith('[공2099상,1]'))
        sections = {s['heading']: s['text'] for s in spec['sections']}
        self.assertEqual([s['heading'] for s in spec['sections']],
                         ['【판시사항】', '【판결요지】', '【참조조문】', '【사건】', '【피고인】', '【상고인】', '【원심판결】', '【판결선고】', '【주문】', '【이유】'])
        self.assertEqual(sections['【판시사항】'], '[1] 첫째 쟁점\n[2] 둘째 쟁점')
        self.assertEqual(sections['【사건】'], '2099도1 가. 사기\n나. 횡령')
        self.assertEqual(sections['【판결선고】'], '2099. 1. 2.')
        self.assertEqual(sections['【주문】'], '상고를 기각한다.')
        self.assertTrue(sections['【이유】'].endswith('재판장 대법관 갑돌이\n주심 대법관 을순이\n대법관 병수'))
        joined = '\n'.join(sum((s['text'].split('\n') for s in spec['sections']), []))
        for chrome in ('홍길동', '어느대학교', '하이라이트', '엘박스', '인용판례', '소송경과'):
            self.assertNotIn(chrome, joined)
        self.assertTrue(any('홍길동' in l for l in cut['pre']))
        self.assertTrue(any('엘박스' in l for l in cut['post']))

    def test_page_break_inside_a_word_is_joined_and_reported(self):
        spec, _, warnings = pt.parse(CASENOTE)
        text = [s for s in spec['sections'] if s['heading'] == '【이유】'][0]['text']
        self.assertIn('주고받았다고 하더라도 뇌물이 된다.', text)
        self.assertEqual(len([w for w in warnings if w.startswith('JOIN')]), 1)

    def test_numbered_paragraphs_are_not_joined(self):
        spec, _, _ = pt.parse(CASENOTE)
        text = [s for s in spec['sections'] if s['heading'] == '【이유】'][0]['text']
        self.assertIn('\n2. 그러므로', text)

    def test_plain_mode(self):
        spec, cut, _ = pt.parse(PLAIN, mode='plain')
        sections = {s['heading']: s['text'] for s in spec['sections']}
        self.assertEqual(sections['【전문】'], '대법원\n제2부\n판결')
        self.assertEqual(sections['【피고인】'], ', 상고인 가.나. ▒▒▒')
        self.assertEqual(sections['【원판결】'], '서울고등법원 1969. 11.13. 선고 69노1 판결')
        self.assertTrue(sections['【이유】'].endswith('1970. 3. 10.\n대법원판사 갑 을 병'))
        self.assertNotIn('pasted_content', json.dumps(spec, ensure_ascii=False))

    def test_missing_header_is_an_error(self):
        with self.assertRaises(ValueError):
            pt.parse('아무 머리글도 없는 텍스트\n주 문\n상고를 기각한다.\n')

    def test_signature_split_needs_roles_before_names(self):
        self.assertEqual(pt.split_signature(['본문입니다.', '재판장', '대법관', '갑돌이', '대법관', '을순이'])[1], ['재판장 대법관 갑돌이', '대법관 을순이'])
        self.assertEqual(pt.split_signature(['본문입니다.', '그러므로 판결한다.'])[1], [])


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg, self.fetched = root / 'registry.json', root / 'fetched'
        self.fetched.mkdir()
        case = {'id': 'std-x-1', 'group': 'standard', 'subject': 'criminal', 'court': '대법원', 'caseNumber': '2099도1', 'lookupKey': '2099도1',
                'decisionDate': '2099-01-02', 'decisionType': '판결', 'enBanc': True, 'title': 't', 'tocPath': ['a']}
        self.reg.write_text(json.dumps({'cases': [case], 'identityAliases': {}}, ensure_ascii=False), encoding='utf-8')
        (self.fetched / 'std-x-1.missing.json').write_text('{"id":"std-x-1","reason":"x"}', encoding='utf-8')
        spec, _, _ = pt.parse(CASENOTE)
        spec.update({'provider': 'casenote', 'sourceLabel': pt.CASENOTE_LABEL, 'sourceNote': pt.kept_note(spec['sections']), 'suppliedAt': '2099-01-03'})
        self.spec = spec
        self.spec_file = root / 'spec.json'
        self.write_spec(spec)
        patcher = patch.multiple(pt, REG=str(self.reg), FETCHED=str(self.fetched))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_spec(self, spec):
        self.spec_file.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')

    def run_import(self, force=False):
        args = type('A', (), {'id': 'std-x-1', 'spec': str(self.spec_file), 'force': force})()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            pt.cmd_import(args)
        return out.getvalue()

    def test_import_writes_record_and_clears_missing_marker(self):
        self.run_import()
        rec = json.loads((self.fetched / 'std-x-1.json').read_text(encoding='utf-8'))
        self.assertEqual((rec['id'], rec['caseNumber'], rec['kind'], rec['seq']), ('std-x-1', '2099도1', 'prec', ''))
        self.assertEqual(rec['sourceLabel'], pt.CASENOTE_LABEL)
        self.assertEqual(rec['suppliedAt'], '2099-01-03')
        self.assertFalse((self.fetched / 'std-x-1.missing.json').exists())

    def test_refuses_site_extras_left_in_the_text(self):
        self.spec['sections'][-1]['text'] += '\n주식회사 엘박스'
        self.write_spec(self.spec)
        with self.assertRaises(SystemExit) as ctx:
            self.run_import()
        self.assertIn('부가정보', str(ctx.exception))
        self.assertFalse((self.fetched / 'std-x-1.json').exists())

    def test_refuses_citation_that_disagrees_with_the_registry(self):
        self.spec['citation'] = '[대법원 2099. 1. 3. 선고 2099도1 전원합의체 판결]'
        self.write_spec(self.spec)
        with self.assertRaises(SystemExit) as ctx:
            self.run_import()
        self.assertIn('선고일', str(ctx.exception))

    def test_refuses_missing_provenance(self):
        del self.spec['sourceLabel']
        self.write_spec(self.spec)
        with self.assertRaises(SystemExit):
            self.run_import()

    def test_does_not_overwrite_an_official_record_without_force(self):
        official = {'id': 'std-x-1', 'citation': '[대법원 2099. 1. 2. 선고 2099도1 전원합의체 판결]', 'sections': [{'heading': '【이유】', 'text': '공식 ' * 100}]}
        (self.fetched / 'std-x-1.json').write_text(json.dumps(official, ensure_ascii=False), encoding='utf-8')
        with self.assertRaises(SystemExit) as ctx:
            self.run_import()
        self.assertIn('공식 수집본', str(ctx.exception))
        self.assertEqual(json.loads((self.fetched / 'std-x-1.json').read_text(encoding='utf-8'))['sections'][0]['text'], '공식 ' * 100)
        self.run_import(force=True)
        self.assertEqual(json.loads((self.fetched / 'std-x-1.json').read_text(encoding='utf-8'))['provider'], 'casenote')


if __name__ == '__main__':
    unittest.main()
