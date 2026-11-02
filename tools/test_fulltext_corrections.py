"""승인된 공식 수집본 정정은 지정한 글자만 바꾸고, 정정 전 문구·출처를 남기며, 서식과 줄 끝을 유지한다."""
import json
import tempfile
import unittest
from pathlib import Path

import apply_fulltext_corrections as tool

APPROVAL = {'approvedBy': '시험 승인', 'approvedAt': '2026-11-02'}


def write(path, obj, eol='\n'):
    path.write_bytes(tool.dump(obj).replace('\n', eol).encode('utf-8'))


class FulltextCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.record = {'id': 'x', 'sections': [
            {'heading': '【판시사항】', 'text': '제3조2의 제2항 / 乙 회사의 의무'},
            {'heading': '【판결요지】', 'text': '乙 회사의 의무와 乙 회사의 책임'}]}
        write(self.dir / 'x.json', self.record, '\r\n')

    def spec(self, *items):
        return {**APPROVAL, 'items': list(items)}

    def item(self, **kw):
        return {'file': 'x', 'section': '【판시사항】', 'before': '제3조2의', 'after': '제3조의2', 'reason': '시험', 'confidence': '높음', **kw}

    def read(self):
        raw = (self.dir / 'x.json').read_bytes().decode('utf-8')
        return raw, json.loads(raw)

    def test_replaces_only_the_named_text_keeps_original_and_crlf(self):
        results, changed = tool.run(self.spec(self.item()), str(self.dir))
        raw, obj = self.read()
        self.assertEqual(results, [('x', '【판시사항】', 'applied')])
        self.assertEqual(obj['sections'][0]['text'], '제3조의2 제2항 / 乙 회사의 의무')
        self.assertEqual(obj['sections'][1], self.record['sections'][1])
        rec = obj['corrections'][0]
        self.assertEqual((rec['before'], rec['after'], rec['approvedBy']), ('제3조2의', '제3조의2', '시험 승인'))
        self.assertEqual(raw.count('\r\n'), raw.count('\n'))   # CRLF 유지
        self.assertTrue(raw.replace('\r\n', '\n') == tool.dump(obj))

    def test_second_run_is_a_no_op_and_check_passes(self):
        tool.run(self.spec(self.item()), str(self.dir))
        before = (self.dir / 'x.json').read_bytes()
        results, changed = tool.run(self.spec(self.item()), str(self.dir))
        self.assertEqual((results[0][2], changed), ('already', []))
        self.assertEqual((self.dir / 'x.json').read_bytes(), before)
        tool.run(self.spec(self.item()), str(self.dir), check=True)

    def test_count_mismatch_or_missing_text_writes_nothing(self):
        before = (self.dir / 'x.json').read_bytes()
        for bad in (self.item(before='乙 회사의', after='甲의', section='【판결요지】'),   # 2회인데 count 1
                    self.item(before='없는 문구'),
                    self.item(before='같음', after='같음'),
                    self.item(section='【없는 섹션】')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tool.run(self.spec(self.item(), bad), str(self.dir))
            self.assertEqual((self.dir / 'x.json').read_bytes(), before)

    def test_explicit_count_allows_repeated_text(self):
        tool.run(self.spec(self.item(before='乙 회사의', after='甲의', section='【판결요지】', count=2)), str(self.dir))
        _, obj = self.read()
        self.assertEqual(obj['sections'][1]['text'], '甲의 의무와 甲의 책임')
        self.assertEqual(obj['corrections'][0]['count'], 2)

    def test_replace_section_keeps_official_text_and_marks_source(self):
        source = {'provider': 'user', 'sourceLabel': '사용자 제공', 'sourceNote': '시험'}
        item = {'file': 'x', 'op': 'replaceSection', 'section': '【판시사항】', 'text': '[1] 가\n[2] 나', 'source': source, 'reason': '시험'}
        tool.run(self.spec(item), str(self.dir))
        _, obj = self.read()
        self.assertEqual(obj['sections'][0]['text'], '[1] 가\n[2] 나')
        self.assertEqual(obj['corrections'][0]['beforeText'], '제3조2의 제2항 / 乙 회사의 의무')
        self.assertEqual(obj['sectionSources']['【판시사항】'], {**source, 'suppliedAt': '2026-11-02'})
        self.assertNotIn('sourceLabel', obj)       # 파일 전체의 출처는 그대로
        results, changed = tool.run(self.spec(item), str(self.dir))
        self.assertEqual((results[0][2], changed), ('already', []))

    def test_lf_files_stay_lf_and_unknown_formatting_is_refused(self):
        write(self.dir / 'y.json', {'id': 'y', 'sections': [{'heading': 'h', 'text': 'abc'}]})
        tool.run(self.spec({'file': 'y', 'section': 'h', 'before': 'b', 'after': 'B', 'reason': '시험'}), str(self.dir))
        self.assertNotIn(b'\r', (self.dir / 'y.json').read_bytes())
        (self.dir / 'z.json').write_text('{"id":"z","sections":[{"heading":"h","text":"abc"}]}', encoding='utf-8')
        with self.assertRaises(ValueError):
            tool.run(self.spec({'file': 'z', 'section': 'h', 'before': 'b', 'after': 'B', 'reason': '시험'}), str(self.dir))


if __name__ == '__main__':
    unittest.main()
