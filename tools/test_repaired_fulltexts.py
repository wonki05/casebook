"""Regression guards for the full texts reported missing in seven screenshots."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
RESOLVED = ('std-civil-25', 'std-civil-62', 'std-civil-70', 'std-civil-141', 'std-civil-918', 'std-civil-379')

def load(case_id):
    return json.loads((ROOT / 'data/fetched' / (case_id + '.json')).read_text(encoding='utf-8'))

def full_text(record):
    sections = record['sections']
    for index, section in enumerate(sections):
        label = ''.join(section.get('heading', '').split()).strip('[]【】〖〗')
        if label == '전문':
            return '\n'.join(part.get('text', '') for part in sections[index:])
    return ''

class ReportedFullTextTests(unittest.TestCase):
    def test_reported_records_have_substantive_full_text(self):
        for case_id in RESOLVED:
            with self.subTest(case_id=case_id):
                record = load(case_id)
                self.assertEqual(record['id'], case_id)
                self.assertGreater(len(full_text(record)), 500)
                self.assertFalse((ROOT / 'data/fetched' / (case_id + '.missing.json')).exists())

    def test_verified_merged_official_records_retain_the_registered_member(self):
        self.assertEqual(load('std-civil-62')['lookupKey'], '93다2636')
        self.assertEqual(load('std-civil-62')['seq'], '201416')
        self.assertEqual(load('std-civil-70')['lookupKey'], '2013다79894')
        self.assertEqual(load('std-civil-70')['seq'], '184528')
        for case_id in ('std-civil-25', 'std-civil-62', 'std-civil-70', 'std-civil-379'):
            self.assertTrue(load(case_id)['sourceUrl'].startswith('https://www.law.go.kr/'))
            self.assertNotIn('sourceLabel', load(case_id))

    def test_supplemental_copy_has_provenance_and_the_complete_shared_body(self):
        a, b = load('std-civil-141'), load('std-civil-918')
        self.assertEqual(full_text(a), full_text(b))
        self.assertGreater(len(full_text(a)), 12000)
        self.assertIn('반대의견', full_text(a))
        for record in (a, b):
            self.assertEqual(record['provider'], 'nepla')
            self.assertIn('네플라', record['sourceLabel'])
            self.assertIn('보충', record['sourceLabel'])
            self.assertTrue(record['sourceUrl'].startswith('https://www.nepla.ai/'))

if __name__ == '__main__':
    unittest.main()
