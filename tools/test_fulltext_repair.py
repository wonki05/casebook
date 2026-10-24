import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from bs4 import BeautifulSoup
from case_identity import identity
import fetch_lawgo as fetch
from import_lawgo_api import record_from_api


HTML = '<div id="conScroll"><h5>【판시사항】</h5>직접 쟁점<a>민법</a> 연결<h5>【전문】</h5>첫 문장 <a>위 법 제7조</a>에 따라 판단한다.<br>다음 줄<p>대법관 갑 을 병</p>마지막 문장<!--누락할 주석--><script>숨김</script></div>'
EXPECTED = [{'heading': '【판시사항】', 'text': '직접 쟁점민법 연결'},
            {'heading': '【전문】', 'text': '첫 문장 위 법 제7조에 따라 판단한다.\n다음 줄\n대법관 갑 을 병\n마지막 문장'}]


def target():
    item = {'id': 'test-case', 'caseNumber': '93다2636', 'lookupKey': '93다2636',
            'court': '대법원', 'decisionDate': '1993-10-26', 'decisionType': '판결'}
    item.update(identity(item))
    return item


def api_response():
    text = ('=== 시험 사건 ===\n\n기본 정보:\n  사건번호: 93다2629, 2636(병합)\n'
            '  법원: 대법원\n  선고일: 19931026\n  사건종류: 민사\n  판결유형: 판결\n\n'
            '판시사항:\n쟁점 원문\n\n판결요지:\n요지 원문\n\n참조조문:\n민법 제105조\n\n'
            '전문:\n【주 문】\n시험 주문\n\n【이 유】 시험 문장 <원문> & 인용\n마지막 줄\n')
    return {'content': [{'type': 'text', 'text': text}], 'structuredContent': None, 'isError': False}


class TextExtractionTests(unittest.TestCase):
    def test_direct_text_and_inline_anchor_are_not_dropped_or_split(self):
        root = BeautifulSoup(HTML, 'html.parser').select_one('#conScroll')
        self.assertEqual(fetch.soup_sections(root), EXPECTED)

    def test_nested_blocks_and_breaks_keep_paragraph_boundaries(self):
        root = BeautifulSoup('<div><h5>【전문】</h5><div><p>첫 문단<b>강조</b></p><p>둘째<br>계속</p></div></div>', 'html.parser').div
        self.assertEqual(fetch.soup_sections(root), [{'heading': '【전문】', 'text': '첫 문단강조\n\n둘째\n계속'}])

    def test_direct_text_without_any_wrapper_or_heading_survives(self):
        root = BeautifulSoup('<div>앞<a>중간</a>뒤</div>', 'html.parser').div
        self.assertEqual(fetch.soup_sections(root), [{'heading': '', 'text': '앞중간뒤'}])

    def test_existing_structured_sections_keep_their_headings(self):
        root = BeautifulSoup('<div><h5>【판시사항】</h5><p>쟁점</p><h5>【전문】</h5><p>판결문</p></div>', 'html.parser').div
        self.assertEqual(fetch.soup_sections(root), [{'heading': '【판시사항】', 'text': '쟁점'}, {'heading': '【전문】', 'text': '판결문'}])

    @unittest.skipUnless(shutil.which('node') or os.environ.get('CODEX_PRIMARY_RUNTIME_NODE'), 'Node.js is unavailable')
    def test_browser_extractor_matches_python_for_direct_dom_nodes(self):
        # A minimal DOM fixture: standard nodeType/tagName/childNodes/textContent.
        script = r"""
const vm=require('node:vm'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const text=value=>({nodeType:3,nodeValue:value,get textContent(){return value;}});
const el=(tag,...children)=>({nodeType:1,tagName:tag,childNodes:children,
  get textContent(){return children.map(c=>c.textContent||'').join('');},
  get children(){return children.filter(c=>c.nodeType===1);}});
const root=el('DIV',el('H5',text('【판시사항】')),text('직접 쟁점'),el('A',text('민법')),text(' 연결'),
 el('H5',text('【전문】')),text('첫 문장 '),el('A',text('위 법 제7조')),text('에 따라 판단한다.'),
 el('BR'),text('다음 줄'),el('P',text('대법관 갑 을 병')),text('마지막 문장'),
 {nodeType:8,nodeValue:'누락할 주석'},el('SCRIPT',text('숨김')));
const document={title:'시험',querySelector:q=>q==='#conScroll'?root:null};
const result=vm.runInNewContext('('+input.source+')()',{document,location:{href:'https://www.law.go.kr/example'},Set});
process.stdout.write(JSON.stringify(result.sections));
"""
        node = shutil.which('node') or os.environ['CODEX_PRIMARY_RUNTIME_NODE']
        result = subprocess.run([node, '-e', script], input=json.dumps({'source': fetch.EXTRACT_JS}, ensure_ascii=False),
                                text=True, encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), EXPECTED)


class OfficialIdentityTests(unittest.TestCase):
    def data(self, citation='[대법원 1993. 10. 26. 선고 93다2629, 2636(병합) 판결]'):
        return {'citation': citation, 'pageTitle': '시험', 'sections': [{'heading': '【전문】', 'text': '시험 원문'}]}

    def test_abbreviated_second_merged_member_is_accepted(self):
        result = fetch.finish(target(), 'prec', '201416', fetch.direct_url('prec', '201416'), self.data(), [])
        self.assertTrue(result['ok'])
        self.assertEqual(result['rec']['lookupKey'], '93다2636')

    def test_neighbor_number_date_court_and_type_are_rejected(self):
        for citation in ['[대법원 1993. 10. 26. 선고 93다2629, 2637(병합) 판결]',
                         '[대법원 1993. 10. 27. 선고 93다2629, 2636(병합) 판결]',
                         '[서울고등법원 1993. 10. 26. 선고 93다2629, 2636(병합) 판결]',
                         '[대법원 1993. 10. 26.자 93다2629, 2636(병합) 결정]']:
            with self.subTest(citation=citation):
                self.assertFalse(fetch.finish(target(), 'prec', '201416', '', self.data(citation), [])['ok'])

    def test_unknown_citation_is_rejected_when_registered_identity_exists(self):
        self.assertFalse(fetch.finish(target(), 'prec', '201416', '', self.data('93다2636'), [])['ok'])

    def test_reuse_serial_only_from_matching_official_cache(self):
        t = target(); url = fetch.direct_url('prec', '201416')
        rec = fetch.finish(t, 'prec', '201416', url, self.data(), [])['rec']
        self.assertEqual(fetch.cached_official_location(t, rec), {'kind': 'prec', 'seq': '201416'})
        for changed in [dict(rec, sourceUrl='https://other.example/case'), dict(rec, sourceLabel='보충본'), dict(rec, id='other')]:
            self.assertIsNone(fetch.cached_official_location(t, changed))


class OfficialApiImportTests(unittest.TestCase):
    def test_body_substrings_and_registered_identity_are_preserved(self):
        raw = api_response(); original = copy.deepcopy(raw); item = target()
        record = record_from_api(raw, item, '201416')
        self.assertEqual(raw, original)
        self.assertEqual(record['id'], item['id']); self.assertEqual(record['caseNumber'], item['caseNumber'])
        self.assertEqual(record['lookupKey'], item['lookupKey'])
        self.assertEqual(record['sections'][-1]['text'], raw['content'][0]['text'].split('전문:\n', 1)[1])
        self.assertEqual(record['sections'][0]['text'], '쟁점 원문\n\n')
        self.assertEqual(record['officialCaseNumber'], '93다2629, 2636(병합)')
        self.assertEqual(record['sourceUrl'], 'https://www.law.go.kr/LSW/precInfoP.do?precSeq=201416')

    def test_wrong_metadata_and_partial_error_response_are_rejected(self):
        raw = api_response()
        for before, after in [('93다2629, 2636(병합)', '93다2629, 2637(병합)'), ('19931026', '19931027'), ('법원: 대법원', '법원: 서울고등법원'), ('판결유형: 판결', '판결유형: 결정'), ('전문:\n', '전문(요약):\n')]:
            changed = copy.deepcopy(raw); changed['content'][0]['text'] = changed['content'][0]['text'].replace(before, after)
            with self.subTest(after=after), self.assertRaises(ValueError): record_from_api(changed, target(), '201416')
        with self.assertRaises(ValueError): record_from_api(dict(raw, isError=True), target(), '201416')


class ConstitutionalIdentityTests(unittest.TestCase):
    def target(self, number='2011헌바172', date='2014-10-30'):
        item = {'id': 'cc-fixture', 'caseNumber': number, 'lookupKey': number,
                'court': '헌법재판소', 'decisionDate': date, 'decisionType': '결정'}
        item.update(identity(item))
        return item

    def data(self, citation):
        return {'citation': citation, 'pageTitle': '문법 시험',
                'sections': [{'heading': '【전문】', 'text': '시험 원문'}]}

    def test_docket_first_panels_and_merged_second_member_are_accepted(self):
        pairs = [(self.target(), '[전원재판부 2011헌바129,172(병합), 2014. 10. 30.]'),
                 (self.target('2001헌아3', '2001-09-25'), '[지정재판부 2001헌아3, 2001. 9. 25., 각하]')]
        for item, citation in pairs:
            with self.subTest(citation=citation):
                metadata = fetch.citation_identity(citation)
                self.assertEqual(metadata['court'], '헌법재판소')
                self.assertEqual(metadata['decisionType'], '결정')
                self.assertTrue(fetch.finish(item, 'detc', '123456', '', self.data(citation), [])['ok'])

    def test_wrong_constitutional_member_date_court_and_type_are_rejected(self):
        citation = '[전원재판부 2011헌바129,172(병합), 2014. 10. 30.]'
        changed = [self.target('2011헌바173'), self.target(date='2014-10-31'),
                   dict(self.target(), court='대법원', courtId='sc'),
                   dict(self.target(), decisionType='판결')]
        for item in changed:
            with self.subTest(item=item):
                self.assertFalse(fetch.finish(item, 'detc', '123456', '', self.data(citation), [])['ok'])

    def test_matching_constitutional_official_serial_is_reusable(self):
        item = self.target()
        citation = '[전원재판부 2011헌바129,172(병합), 2014. 10. 30.]'
        url = fetch.direct_url('detc', '123456')
        record = fetch.finish(item, 'detc', '123456', url, self.data(citation), [])['rec']
        self.assertEqual(fetch.cached_official_location(item, record), {'kind': 'detc', 'seq': '123456'})


if __name__ == '__main__':
    unittest.main()
