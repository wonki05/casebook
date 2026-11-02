"""위치로 지정하는 정정(replaceAt)과 구역 나누기(splitSection)는 지정한 글자·표지만 바꾸고, 정정 전 글자를 남기며, 멱등이다."""
import json
import tempfile
import unittest
from pathlib import Path

import apply_fulltext_edits as tool

APPROVAL = {'approvedBy': '시험 승인', 'approvedAt': '2026-11-03'}
BODY = '가?나 와 다?라 그리고 마?바'
OLD = ('경범죄처벌법\n\n[주　　문]\n\n헌법에 위반되지 아니한다.\n\n[이　　유]\n\n'
       '1. 사건의 개요\n\n가. 개요 내용\n\n재판관　홍길동')


def write(path, obj, eol='\n'):
    path.write_bytes(tool.base.dump(obj).replace('\n', eol).encode('utf-8'))


def offsets(text, char='?'):
    return [i for i, c in enumerate(text) if c == char]


class EditToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.original = {'id': 'x', 'sections': [
            {'heading': '【판시사항】', 'text': '남북합의서 위반 / 북합의서 위반'},
            {'heading': '【결정요지】', 'text': BODY},
            {'heading': '[당 사 자]', 'text': OLD}]}
        write(self.dir / 'x.json', self.original, '\r\n')

    def spec(self, *items):
        return {**APPROVAL, 'items': list(items)}

    def dots(self, **kw):
        return {'file': 'x', 'op': 'replaceAt', 'section': '【결정요지】', 'sectionSha256': tool.sha256(BODY),
                'edits': [{'offset': i, 'before': '?', 'after': 'ㆍ'} for i in offsets(BODY)],
                'reason': '깨진 가운뎃점', 'confidence': '높음', **kw}

    def split(self, **kw):
        return {'file': 'x', 'op': 'splitSection', 'section': '[당 사 자]', 'markers': ['[주　　문]', '[이　　유]'],
                'headings': ['【당 사 자】', '【주 문】', '【이 유】'], 'reason': '구 형식 페이지', **kw}

    def read(self):
        raw = (self.dir / 'x.json').read_bytes().decode('utf-8')
        return raw, json.loads(raw)

    def test_replace_at_changes_only_the_listed_positions_and_keeps_the_original(self):
        results, changed = tool.run(self.spec(self.dots()), str(self.dir))
        raw, obj = self.read()
        self.assertEqual(results, [('x', '【결정요지】', 'applied')])
        self.assertEqual(obj['sections'][1]['text'], '가ㆍ나 와 다ㆍ라 그리고 마ㆍ바')
        self.assertEqual(obj['sections'][0], self.original['sections'][0])
        record = obj['corrections'][0]
        self.assertEqual((record['op'], record['sectionSha256']), ('replaceAt', tool.sha256(BODY)))
        self.assertEqual([e['before'] for e in record['edits']], ['?', '?', '?'])
        self.assertEqual(record['afterSha256'], tool.sha256(obj['sections'][1]['text']))
        # 정정 전 글자는 기록한 위치·글자로 되돌릴 수 있다.
        restored = list(obj['sections'][1]['text'])
        for edit in record['edits']:
            restored[edit['offset']] = edit['before']
        self.assertEqual(''.join(restored), BODY)
        self.assertEqual(raw.count('\r\n'), raw.count('\n'))   # CRLF 유지
        self.assertEqual(raw.replace('\r\n', '\n'), tool.base.dump(obj))

    def test_replace_at_inserts_a_missing_character(self):
        text = self.original['sections'][0]['text']
        at = text.rindex('북합의서')   # 뒤쪽이 '남'이 빠진 쪽이다(앞쪽 '남북합의서' 안에도 같은 글자가 있다)
        item ={'file': 'x', 'op': 'replaceAt', 'section': '【판시사항】', 'sectionSha256': tool.sha256(text),
                'edits': [{'offset': at, 'before': '북합의서', 'after': '남북합의서'}], 'reason': '한 글자 누락', 'confidence': '높음'}
        tool.run(self.spec(item), str(self.dir))
        _, obj = self.read()
        self.assertEqual(obj['sections'][0]['text'], '남북합의서 위반 / 남북합의서 위반')

    def test_second_run_is_a_no_op_and_a_refetch_reapplies(self):
        tool.run(self.spec(self.dots(), self.split()), str(self.dir))
        done = (self.dir / 'x.json').read_bytes()
        results, changed = tool.run(self.spec(self.dots(), self.split()), str(self.dir))
        self.assertEqual(([r[2] for r in results], changed), (['already', 'already'], []))
        self.assertEqual((self.dir / 'x.json').read_bytes(), done)
        tool.run(self.spec(self.dots(), self.split()), str(self.dir), check=True)
        # 재수집(fetch_lawgo.py --force)이 정정을 덮어쓰면 같은 목록이 다시 적용된다.
        write(self.dir / 'x.json', self.original, '\r\n')
        results, _ = tool.run(self.spec(self.dots(), self.split()), str(self.dir))
        self.assertEqual([r[2] for r in results], ['applied', 'applied'])
        self.assertEqual((self.dir / 'x.json').read_bytes(), done)

    def test_changed_text_wrong_character_overlap_and_missing_hash_write_nothing(self):
        before = (self.dir / 'x.json').read_bytes()
        bad = [
            self.dots(sectionSha256=tool.sha256('다른 글자')),   # 재수집으로 글자가 달라짐
            self.dots(edits=[{'offset': 0, 'before': '?', 'after': 'ㆍ'}]),   # 위치 0 은 '가' 이다
            self.dots(edits=[{'offset': 0, 'before': '가?', 'after': 'x'}, {'offset': 1, 'before': '?', 'after': 'y'}]),   # 겹침
            self.dots(edits=[{'offset': 1, 'before': '?', 'after': '?'}]),   # 정정 전후가 같음
            {k: v for k, v in self.dots().items() if k != 'sectionSha256'},
            self.dots(section='【없는 섹션】'),
        ]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                tool.run(self.spec(self.dots(), item), str(self.dir))
            self.assertEqual((self.dir / 'x.json').read_bytes(), before)

    def test_two_replace_at_items_on_one_section_must_be_merged(self):
        first = self.dots(edits=[{'offset': 1, 'before': '?', 'after': 'ㆍ'}])
        second = self.dots(edits=[{'offset': 6, 'before': '?', 'after': 'ㆍ'}])
        with self.assertRaisesRegex(ValueError, '한 항목으로 합치세요'):
            tool.run(self.spec(first, second), str(self.dir))

    def test_split_section_cuts_at_the_marker_lines_in_place(self):
        tool.run(self.spec(self.split()), str(self.dir))
        raw, obj = self.read()
        headings = [s['heading'] for s in obj['sections']]
        self.assertEqual(headings, ['【판시사항】', '【결정요지】', '【당 사 자】', '【주 문】', '【이 유】'])   # 제자리에서 셋으로
        by = {i: s['text'] for i, s in enumerate(obj['sections'])}
        self.assertEqual(by[2], '경범죄처벌법')
        self.assertEqual(by[3], '헌법에 위반되지 아니한다.')
        self.assertEqual(by[4], '1. 사건의 개요\n\n가. 개요 내용\n\n재판관　홍길동')
        record = obj['corrections'][0]
        self.assertEqual((record['op'], record['beforeText']), ('splitSection', OLD))
        self.assertEqual(raw.count('\r\n'), raw.count('\n'))

    def test_split_section_refuses_missing_duplicate_misordered_or_empty_markers(self):
        before = (self.dir / 'x.json').read_bytes()
        two = {**self.original, 'sections': [{'heading': '[당 사 자]', 'text': OLD + '\n[이　　유]\n끝'}]}
        write(self.dir / 'two.json', two)
        bad = [
            self.split(markers=['[주　　문]', '[없는 표지]']),
            self.split(markers=['[이　　유]', '[주　　문]']),   # 순서가 바뀜
            self.split(headings=['【당 사 자】', '【주 문】']),   # 구역 이름이 모자람
            self.split(file='two'),   # 이유 표지가 두 번
            self.split(markers=['[주　　문]', '재판관　홍길동']),   # 마지막 구역이 비는 표지
            self.split(headings=['【당 사 자】', '【결정요지】', '【이 유】']),   # 이미 있는 구역 이름
        ]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ValueError):
                tool.run(self.spec(item), str(self.dir))
            self.assertEqual((self.dir / 'x.json').read_bytes(), before)

    def test_plain_item_whose_result_contains_its_own_before_text_is_refused(self):
        item = {'file': 'x', 'section': '【판시사항】', 'before': '북합의서 위반 /', 'after': '남북합의서 위반 /', 'reason': '시험'}
        with self.assertRaisesRegex(ValueError, '멱등하지 않습니다'):
            tool.run(self.spec(item), str(self.dir))

    def test_plain_and_replace_section_items_still_go_through_the_base_tool(self):
        item = {'file': 'x', 'section': '【결정요지】', 'before': '다?라', 'after': '다ㆍ라', 'reason': '시험', 'confidence': '높음'}
        results, _ = tool.run(self.spec(item), str(self.dir))
        _, obj = self.read()
        self.assertEqual((results[0][2], obj['sections'][1]['text']), ('applied', '가?나 와 다ㆍ라 그리고 마?바'))


if __name__ == '__main__':
    unittest.main()
