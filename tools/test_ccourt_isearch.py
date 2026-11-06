import unittest

import ccourt_isearch as ci
import fetch_lawgo as fetch

CHROME = '화면 내 검색    Go page Off 각주 Off 인용복사 유사판례\n검색결과 만족도        \n2024헌마569\n불기소처분취소 (시험 사건)\n종국일자 2026. 5. 21. 종국결과 인용(취소)\n'
CASEBOOK = (CHROME + '헌재 2026. 5. 21. 2024헌마569, 판례집 38-1, 648\n\n#해시태그\n\n  2024헌마569 go\n \n\n불기소처분취소\n\n[2026. 5. 21. 2024헌마569]\n\n'
            '【판시사항】\n\n시험 판시사항ㆍ가운뎃점\n\n【결정요지】\n\n시험 요지\n\n【심판대상조항】\n\n제27조\n\n【당 사 자】\n\n청 구 인 박○○\n\n'
            '【주    문】\n\n피청구인이 한 불기소처분을 취소한다.\n\n【이    유】\n\n1. 사건개요\n\n첫 문단   공백\n\n\n\n둘째 문단\n\n\n\n재판관  김상환 김형두\n\n\n')
DECISION = (CHROME.replace('2024헌마569', '2024헌마990') + '헌재 2026. 10. 22. 2024헌마990등, 결정문\n  2024헌마990 go\n \n \n헌  법  재  판  소\n\n결         정\n\n'
            '사           건          2024헌마990    공무원연금법 부칙 위헌확인\n\n                          2026헌바197(병합)    위헌소원\n\n'
            '청    구    인          [별지] 청구인 명단과 같음\n\n선    고    일          2026. 10. 22.\n\n\n\n주           문\n\n1. 기각한다.\n\n\n\n'
            '이           유\n\n1. 사건개요\n\n본문\n\n재판관  유남석 이선애\n\n[별지]\n\n명단\n')


class ParseTests(unittest.TestCase):
    def test_casebook_view_keeps_headings_normalized_and_text_unchanged(self):
        parsed = ci.parse_view(CASEBOOK)
        self.assertEqual((parsed['kind'], parsed['date'], parsed['numbers'], parsed['title']), ('casebook', '2026-05-21', ['2024헌마569'], '불기소처분취소'))
        self.assertEqual([s['heading'] for s in parsed['sections']],
                         ['【판시사항】', '【결정요지】', '【심판대상조문】', '【당 사 자】', '【주 문】', '【이 유】'])
        by = {s['heading']: s['text'] for s in parsed['sections']}
        self.assertEqual(by['【판시사항】'], '시험 판시사항ㆍ가운뎃점')
        self.assertEqual(by['【이 유】'], '1. 사건개요\n\n첫 문단 공백\n\n둘째 문단\n\n재판관 김상환 김형두')

    def test_decision_view_splits_header_order_and_reason(self):
        parsed = ci.parse_view(DECISION)
        self.assertEqual((parsed['kind'], parsed['date'], parsed['numbers']), ('decision', '2026-10-22', ['2024헌마990']))
        self.assertEqual(parsed['title'], '공무원연금법 부칙 위헌확인')
        by = {s['heading']: s['text'] for s in parsed['sections']}
        self.assertTrue(by['【전문】'].startswith('헌 법 재 판 소\n\n결 정\n\n사 건 2024헌마990 공무원연금법 부칙 위헌확인'))
        self.assertTrue(by['【전문】'].endswith('선 고 일 2026. 10. 22.'))
        self.assertEqual(by['【주 문】'], '1. 기각한다.')
        self.assertTrue(by['【이 유】'].endswith('[별지]\n\n명단'))

    def test_missing_meta_or_sections_are_rejected(self):
        with self.assertRaises(ValueError):
            ci.parse_view('판례검색 머리 줄 없음')
        with self.assertRaises(ValueError):
            ci.parse_view(CHROME + '헌재 2026. 5. 21. 2024헌마569, 판례집 38-1, 648\n\n불기소처분취소\n\n【판시사항】\n\n요지만\n')


class IdentityAndRecordTests(unittest.TestCase):
    target = {'id': 'cc-2024heolma569', 'caseNumber': '2024헌마569', 'lookupKey': '2024헌마569', 'decisionDate': '2026-05-21'}

    def test_registered_date_and_number_must_match(self):
        parsed = ci.parse_view(CASEBOOK)
        ci.check_identity(self.target, parsed)
        with self.assertRaises(ValueError):
            ci.check_identity(dict(self.target, decisionDate='2026-05-20'), parsed)
        with self.assertRaises(ValueError):
            ci.check_identity(dict(self.target, lookupKey='2024헌마570'), parsed)

    def test_full_record_citation_passes_the_official_identity_check(self):
        parsed = ci.parse_view(CASEBOOK)
        record = ci.full_record(self.target, parsed, '82202_010300', '2024헌마569', '2026-11-07', 'abc')
        self.assertEqual(record['citation'], '[전원재판부 2024헌마569, 2026. 5. 21.]')
        meta = fetch.citation_identity(record['citation'])
        self.assertEqual((meta['decisionDate'], meta['members'], meta['decisionType']), ('2026-05-21', ['2024헌마569'], '결정'))
        for key in ('provider', 'sourceLabel', 'sourceHeader', 'sourceNote', 'suppliedAt'):
            self.assertTrue(record[key], key)
        self.assertEqual(record['retrieval']['link'], '82202_010300')

    def test_supplement_adds_only_missing_sections_after_matching_the_official_summary(self):
        parsed = ci.parse_view(CASEBOOK)
        official = {'sections': [{'heading': '【판시사항】', 'text': '시험 판시사항·가운뎃점'}, {'heading': '【결정요지】', 'text': '시험 요지'}]}
        record = ci.supplement_record(self.target, parsed, official, '82202_010300', 'q', '2026-11-07', 'abc')
        self.assertEqual([s['heading'] for s in record['sections']], ['【심판대상조문】', '【당 사 자】', '【주 문】', '【이 유】'])
        self.assertEqual(record['retrieval']['verifiedAgainstOfficial'], ['판시사항', '결정요지'])
        self.assertNotIn('officialDiffers', record['retrieval'])
        # 공식 요지 페이지가 가운뎃점을 빠뜨려도 같은 재판이며, 참조조문 등 다른 공통 구역은 공식본을 쓰고 차이만 남긴다
        loose_official = {'sections': [{'heading': '【판시사항】', 'text': '시험 판시사항가운뎃점'}, {'heading': '【결정요지】', 'text': '시험 요지'},
                                       {'heading': '【참조조문】', 'text': '공식 참조조문'}]}
        parsed_with_ref = ci.parse_view(CASEBOOK.replace('【당 사 자】', '【참조조문】\n\n판례검색 참조조문\n\n【당 사 자】'))
        again = ci.supplement_record(self.target, parsed_with_ref, loose_official, 'l', 'q', 'd', 's')
        self.assertEqual(again['retrieval']['officialDiffers'], ['참조조문'])
        self.assertNotIn('【참조조문】', [s['heading'] for s in again['sections']])
        with self.assertRaises(ValueError):
            ci.supplement_record(self.target, parsed, {'sections': [{'heading': '【판시사항】', 'text': '다른 재판'}]}, 'l', 'q', 'd', 's')
        with self.assertRaises(ValueError):
            ci.supplement_record(self.target, parsed, {'sections': [{'heading': '【사건】', 'text': 'x'}]}, 'l', 'q', 'd', 's')
        with self.assertRaises(ValueError):
            ci.supplement_record(self.target, parsed, {'sections': [{'heading': '【판시사항】', 'text': '시험 판시사항·가운뎃점'}, {'heading': '【이 유】', 'text': '이미 있음'}]}, 'l', 'q', 'd', 's')


if __name__ == '__main__':
    unittest.main()
