import json
import os
import shutil
import subprocess
import tempfile
import unittest

from bs4 import BeautifulSoup

import fetch_lawgo as fetch

HTML = ('<div id="conScroll"><h5>【전문】</h5><p>사건 2018헌마155</p>'
        '<h5>[이 유]</h5><p>첫 문단 <img src="/LSW/flDownload.do?flSeq=1" alt="img1"> 이어지는 글</p>'
        '<p><img src="/LSW/flDownload.do?flSeq=2" alt="img2"></p><p>마지막</p></div>')


class ImageOmissionTests(unittest.TestCase):
    def root(self, html=HTML):
        return BeautifulSoup(html, 'html.parser').select_one('#conScroll')

    def test_text_is_identical_with_or_without_images_and_positions_are_recorded(self):
        sections, images = fetch.soup_sections_with_images(self.root())
        self.assertEqual(sections, [{'heading': '【전문】', 'text': '사건 2018헌마155'},
                                    {'heading': '[이 유]', 'text': '첫 문단  이어지는 글\n\n마지막'}])
        self.assertEqual(fetch.soup_sections(self.root()), sections)
        self.assertNotIn(fetch.IMG_MARK, json.dumps(sections, ensure_ascii=False))
        self.assertEqual([(i['section'], i['offset'], i['before'], i['src']) for i in images],
                         [('[이 유]', 3, '첫 문단', '/LSW/flDownload.do?flSeq=1'),
                          ('[이 유]', 8, '첫 문단 이어지는 글', '/LSW/flDownload.do?flSeq=2')])
        self.assertEqual(images[0]['alt'], 'img1')

    def test_page_without_images_records_nothing(self):
        root = self.root('<div id="conScroll"><h5>【전문】</h5><p>글만</p></div>')
        self.assertEqual(fetch.soup_sections_with_images(root), ([{'heading': '【전문】', 'text': '글만'}], []))

    def test_image_only_section_and_heading_image_are_still_recorded(self):
        root = self.root('<div id="conScroll"><img src="a.png"><h5>별지<img src="b.png"></h5><img src="c.png"></div>')
        sections, images = fetch.soup_sections_with_images(root)
        self.assertEqual(sections, [{'heading': '별지', 'text': ''}])
        self.assertEqual([(i['section'], i['src'], i.get('inHeading')) for i in images],
                         [('', 'a.png', None), ('별지', 'b.png', True), ('별지', 'c.png', None)])

    def test_finish_keeps_omitted_images_in_retrieval_and_leaves_text_unchanged(self):
        sections, images = fetch.soup_sections_with_images(self.root())
        target = {'id': 'cc-x', 'caseNumber': '2018헌마155', 'lookupKey': '2018헌마155'}
        data = {'pageTitle': '시험', 'citation': '[전원재판부 2018헌마155, 2020. 2. 27., 인용]', 'sections': sections, 'omittedImages': images}
        rec = fetch.finish(target, 'detc', '156161', fetch.direct_url('detc', '156161'), data, [])['rec']
        self.assertEqual(rec['sections'], sections)
        self.assertEqual(rec['retrieval']['omittedImageCount'], 2)
        self.assertEqual(rec['retrieval']['omittedImages'], images)
        data.pop('omittedImages')
        self.assertNotIn('retrieval', fetch.finish(target, 'detc', '156161', fetch.direct_url('detc', '156161'), data, [])['rec'])

    @unittest.skipUnless(shutil.which('node') or os.environ.get('CODEX_PRIMARY_RUNTIME_NODE'), 'Node.js is unavailable')
    def test_browser_extractor_reports_the_same_images_as_python(self):
        script = r"""
const vm=require('node:vm'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const text=value=>({nodeType:3,nodeValue:value,get textContent(){return value;}});
const el=(tag,attrs,...children)=>({nodeType:1,tagName:tag,childNodes:children,
  getAttribute:n=>(attrs||{})[n]===undefined?null:attrs[n],
  get textContent(){return children.map(c=>c.textContent||'').join('');},
  getElementsByTagName(t){const out=[];const walk=n=>{(n.childNodes||[]).forEach(c=>{if(c.tagName===t.toUpperCase())out.push(c);walk(c);});};walk(this);return out;}});
const img=(src,alt)=>el('IMG',{src,alt});
const root=el('DIV',null,el('H5',null,text('【전문】')),el('P',null,text('사건 2018헌마155')),
 el('H5',null,text('[이 유]')),el('P',null,text('첫 문단 '),img('/LSW/flDownload.do?flSeq=1','img1'),text(' 이어지는 글')),
 el('P',null,img('/LSW/flDownload.do?flSeq=2','img2')),el('P',null,text('마지막')));
const document={title:'시험',querySelector:q=>q==='#conScroll'?root:null};
const result=vm.runInNewContext('('+input.source+')()',{document,location:{href:'https://www.law.go.kr/example'},Set,Object});
process.stdout.write(JSON.stringify({sections:result.sections,images:result.omittedImages}));
"""
        node = shutil.which('node') or os.environ['CODEX_PRIMARY_RUNTIME_NODE']
        result = subprocess.run([node, '-e', script], input=json.dumps({'source': fetch.EXTRACT_JS}, ensure_ascii=False),
                                text=True, encoding='utf-8', capture_output=True, check=True)
        browser = json.loads(result.stdout)
        sections, images = fetch.soup_sections_with_images(self.root())
        self.assertEqual(browser['sections'], sections)
        self.assertEqual(browser['images'], images)


class MissingRecordTests(unittest.TestCase):
    def target(self):
        return {'id': 'cc-2018heolma155', 'caseNumber': '2018헌마155', 'lookupKey': '2018헌마155'}

    def test_api_serial_is_only_a_lookup_hint_for_the_same_id(self):
        record = {'id': 'cc-2018heolma155', 'apiSeq': '156161'}
        self.assertEqual(fetch.missing_record_location(self.target(), record), {'kind': 'detc', 'seq': '156161'})
        self.assertIsNone(fetch.missing_record_location(self.target(), dict(record, id='other')))
        self.assertIsNone(fetch.missing_record_location(self.target(), {'id': record['id'], 'apiSeq': 'abc'}))
        self.assertIsNone(fetch.missing_record_location(self.target(), {'id': record['id']}))

    def test_failure_update_keeps_api_fields_and_refreshes_reason(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'x.missing.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump({'id': 'x', 'reason': '옛 사유', 'triedUrls': [], 'apiSource': 'event-1.json', 'apiSeq': '1'}, handle)
            record = fetch.write_missing(path, {'id': 'x', 'reason': '새 사유', 'triedUrls': ['u']}, now='2026-11-07')
            with open(path, encoding='utf-8') as handle:
                saved = json.load(handle)
        self.assertEqual(saved, record)
        self.assertEqual((saved['reason'], saved['previousReason'], saved['apiSource'], saved['apiSeq'], saved['retriedAt']),
                         ('새 사유', '옛 사유', 'event-1.json', '1', '2026-11-07'))


if __name__ == '__main__':
    unittest.main()
