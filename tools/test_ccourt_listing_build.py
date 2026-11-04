"""List results remain attributable and never replace a decision's official text."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_data


class CcourtListingBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.reg, self.toc, self.output = root / 'registry.json', root / 'toc.json', root / 'cases.json'
        self.fetched = root / 'fetched'
        self.fetched.mkdir()
        self.toc.write_text('{}', encoding='utf-8')
        self.patches = patch.multiple(build_data, REG=str(self.reg), TOC_FILE=str(self.toc),
                                      OUT=str(self.output), FETCHED=str(self.fetched))
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.source = dict(provider='헌법재판소', boardId='1195', eventId='4268005',
                           listUrl='https://www.ccourt.go.kr/list', sourceUrl='https://www.ccourt.go.kr/view',
                           sourceFile='page-001.html', sourceSha256='a' * 64, page=1, result='합헌,기각')
        self.record = dict(id='cc-fixture', group='ccourt', subject='constitution',
                           court='헌법재판소', caseNumber='2020헌마1', decisionDate='2020-01-30',
                           decisionType='결정', title='목록 제목', result='', editorial={},
                           ccourtSource=self.source)

    def build_record(self, fetched=None):
        self.reg.write_text(json.dumps({'cases': [self.record]}, ensure_ascii=False), encoding='utf-8')
        if fetched is not None:
            (self.fetched / 'cc-fixture.json').write_text(json.dumps(fetched, ensure_ascii=False), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            build_data.build()
        return json.loads(self.output.read_text(encoding='utf-8'))['cases'][0]

    def test_list_result_with_provenance_and_no_invented_text(self):
        self.record['resultSource'] = {'label': '기존 출처', 'order': '다른 근거'}
        rec = self.build_record()
        self.assertEqual(rec['ccourtSource'], self.source)
        self.assertEqual(rec['result'], '합헌,기각')
        self.assertEqual(rec['source'], {'label': '헌법재판소 최근 주요결정 목록', 'url': self.source['sourceUrl']})
        self.assertEqual(rec['resultListingSource'], rec['source'])
        self.assertNotIn('resultSource', rec)
        self.assertEqual(rec['issues'], [])
        self.assertEqual(rec['holdings'], [])
        self.assertIsNone(rec['fullText'])

    def test_official_order_result_wins_and_official_source_is_unchanged(self):
        fetched = {'citation': '[헌법재판소 2020. 1. 30. 선고 2020헌마1 결정]',
                   'sourceUrl': 'https://www.law.go.kr/example',
                   'sections': [{'heading': '[주문]', 'text': '심판청구를 각하한다.'}]}
        rec = self.build_record(fetched)
        self.assertEqual(rec['result'], '각하')
        self.assertNotIn('resultListingSource', rec)
        self.assertEqual(rec['source']['label'], '국가법령정보센터')
        self.assertEqual(rec['ccourtSource'], self.source)

    def test_listing_fallback_when_official_source_has_no_order(self):
        self.source.pop('sourceUrl')
        fetched = {'citation': '[헌법재판소 2020. 1. 30. 선고 2020헌마1 결정]',
                   'sections': [{'heading': '[결정요지]', 'text': '공식 요지'}]}
        rec = self.build_record(fetched)
        self.assertEqual(rec['result'], '합헌,기각')
        self.assertEqual(rec['resultListingSource']['url'], self.source['listUrl'])
        self.assertEqual(rec['source']['label'], '국가법령정보센터')
        self.assertEqual(rec['holdings'][0]['text'], '공식 요지')

    def test_explicit_record_result_retains_precedence(self):
        self.record['result'] = '기각'
        self.record['resultSource'] = {'label': '기존 출처', 'order': '기각한다.'}
        rec = self.build_record()
        self.assertEqual(rec['result'], '기각')
        self.assertEqual(rec['resultSource'], self.record['resultSource'])
        self.assertNotIn('resultListingSource', rec)


if __name__ == '__main__':
    unittest.main()
