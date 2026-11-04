"""Tests for importing complete retained official API responses."""
import copy
import unittest

from import_lawgo_api import record_from_api


TARGET = {'id': 'cc-test', 'caseNumber': '2020헌마389', 'lookupKey': '2020헌마389',
          'court': '헌법재판소', 'decisionType': '결정', 'decisionDate': '2024-08-29'}
FULL = '【주    문】기각한다.【이    유】이유 원문. 재판관 홍길동 김철수 이영희'
SOURCE = ('=== 결정 명칭 ===\n\n기본 정보:\n  사건번호: 2020헌마389\n'
          '  종국일자: 20240829\n\n판시사항:\n판시 원문\n\n결정요지:\n요지 원문\n\n'
          '전문:\n' + FULL)


def response(text=SOURCE):
    return {'content': [{'type': 'text', 'text': text}], 'isError': False}


class ImportTests(unittest.TestCase):
    def test_constitutional_body_and_sections_preserved(self):
        rec = record_from_api(response(), TARGET, '193039', 'constitutional')
        self.assertEqual(rec['kind'], 'detc')
        self.assertEqual(rec['officialCaseNumber'], '2020헌마389')
        self.assertEqual(rec['retrieval']['domain'], 'constitutional')
        self.assertEqual(rec['sections'], [
            {'heading': '【판시사항】', 'text': '판시 원문\n\n'},
            {'heading': '【결정요지】', 'text': '요지 원문\n\n'},
            {'heading': '【전문】', 'text': FULL}])
        self.assertIn('detcSeq=193039', rec['sourceUrl'])

    def test_truncation_and_cap_rejected_in_all_domains(self):
        for text in (SOURCE + '\n\n⚠️ 응답이 너무 길어 50,000자로 잘렸습니다.',
                     SOURCE + '가' * 50000):
            for domain in ('precedent', 'constitutional'):
                with self.subTest(domain=domain), self.assertRaisesRegex(ValueError, 'truncated'):
                    record_from_api(response(text), TARGET, '1', domain)

    def test_missing_body_parts_are_rejected(self):
        for body in ('【주문】기각한다.', '【주문】기각한다.【이유】일부 이유.'):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, 'partial body'):
                record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')

    def test_annex_after_closing_and_mismatched_bracket_preserve_verbatim(self):
        body = ('【주    문〕기각한다.【이    유】이유 원문. 재판관 홍길동 김철수 이영희'
                '[별지] 관련조항제1조 이를 적용한다.\n')
        rec = record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')
        self.assertEqual(rec['sections'][-1]['text'], body)
        self.assertEqual(rec['retrieval']['bodyQuality'], 'annex_terminal_heuristic_not_proof')

    def test_incomplete_annex_rejected(self):
        for tail in ('[별지] 관련조항 중간에서 잘린', '[별지] 관련조항제1조 및\n'):
            body = '【주문】기각한다.【이유】이유. 재판관 홍길동 김철수 이영희' + tail
            with self.subTest(tail=tail), self.assertRaisesRegex(ValueError, 'annex'):
                record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')

    def test_conclusion_with_separate_presiding_justices_list(self):
        body = '[주문]기각한다.[이유]5. 결론 주문과 같이 결정한다.[/]재판장,이종석,이은애,이영진\n'
        rec = record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')
        self.assertEqual(rec['sections'][-1]['text'], body)
        self.assertEqual(rec['retrieval']['bodyQuality'], 'recognizable_closing')

    def test_presiding_justices_before_annex_and_spaced_reasons(self):
        body = ('[주문]기각한다.[이 유 ]이유 원문.재판장  유남석 이선애 이석태'
                '【별 지】[별지] 청구인 명단담당변호사 김수영[/]\n')
        rec = record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')
        self.assertEqual(rec['sections'][-1]['text'], body)
        self.assertEqual(rec['retrieval']['bodyQuality'], 'annex_terminal_heuristic_not_proof')

    def test_source_omitted_annex_or_external_image_rejected(self):
        for suffix in ('[별지] 내역(별지 생략)\n', '[별지] 관련조항<img src="/image">\n'):
            body = '[주문]기각한다.[이유]이유. 재판관 홍길동 김철수 이영희' + suffix
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'omits an annex|external image'):
                record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')

    def test_presiding_names_with_commas_before_unbracketed_annex(self):
        body = ('[주문]기각한다.[이유]이유. 재판관 홍길동, 김철수, 이영희'
                '별지 관련조항제1조 적용한다.\n')
        rec = record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')
        self.assertEqual(rec['sections'][-1]['text'], body)

    def test_justices_names_without_space_after_label(self):
        body = '[주문]기각한다.[이유]이유.재판관홍길동 김철수 이영희\n'
        rec = record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')
        self.assertEqual(rec['sections'][-1]['text'], body)

    def test_justice_signature_with_source_annotation(self):
        body = ('[주문]기각한다.[이유]이유.재판관홍길동 김철수(공가로 행정전자서명 불능) 이영희'
                '[별지] 관련조항제1조 적용한다.\n')
        rec = record_from_api(response(SOURCE.replace(FULL, body)), TARGET, '1', 'constitutional')
        self.assertEqual(rec['sections'][-1]['text'], body)

    def test_mismatched_identity_is_rejected(self):
        for field, value in [('caseNumber', '2020헌마390'), ('decisionDate', '2024-08-30'),
                             ('court', '대법원'), ('decisionType', '판결')]:
            target = copy.deepcopy(TARGET)
            target[field] = value
            if field == 'caseNumber':
                target['lookupKey'] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                record_from_api(response(), target, '1', 'constitutional')

    def test_precedent_default_still_works(self):
        target = {'id': 'sc-test', 'caseNumber': '2020다123', 'court': '대법원',
                  'decisionType': '판결', 'decisionDate': '2024-08-29'}
        text = ('=== 판결 명칭 ===\n\n기본 정보:\n  사건번호: 2020다123\n  법원: 대법원\n'
                '  선고일: 20240829\n  판결유형: 판결\n\n전문:\n【주 문】기각한다.')
        rec = record_from_api(response(text), target, '123')
        self.assertEqual(rec['kind'], 'prec')
        self.assertEqual(rec['sections'][-1]['text'], '【주 문】기각한다.')


if __name__ == '__main__':
    unittest.main()
