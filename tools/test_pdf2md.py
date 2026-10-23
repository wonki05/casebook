"""표준판례 PDF→Markdown 파이프라인(pdf2md_lib · md_validate · md_merge) 시험.

  python -X utf8 -m unittest tools.test_pdf2md
  python -X utf8 tools/test_pdf2md.py

fixture 는 모두 임시 폴더의 합성 자료다(실제 등록부·목차·과목 폴더를 읽거나 쓰지 않는다).
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_lib as L  # noqa: E402
import md_merge  # noqa: E402
import md_validate  # noqa: E402

PDF = 'data/standard-cases/표준판례(2023년 개정판)_상법.pdf'
EVEN_HEAD = '변호사시험의 자격시험을 위한 상법표준판례연구'
TOC = {'commercial': [{'id': 'sb-1', 'label': '총칙·상행위', 'children': [
    {'id': 'sb-1-1', 'label': '제1편 총칙', 'children': [{'id': 'sb-1-1-1', 'label': '제1장 상인', 'children': []}]}]}]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def case(number, date, court='대법원', dtype='판결', en_banc=False):
    return {'caseNumber': number, 'lookupKey': number.split('·')[0], 'date': date, 'court': court, 'decisionType': dtype, 'enBanc': en_banc}


def md_block(no, title, cases, sections, pages, notes=None, location='제1편 총칙 > 제1장 상인 > (절 없음)', continued=False, citation=None):
    out = [f'## {"(이어짐) " if continued else ""}{no}. {title}']
    if not continued:
        c0 = cases[0]
        out.append(f'- 출처: {citation or c0["court"] + " " + c0["date"] + " 선고 " + c0["caseNumber"] + " " + c0["decisionType"]}')
        for c in cases:
            out.append(f'- 사건: {c["caseNumber"]} | {c["date"]} | {c["court"]} | {c["decisionType"]} | 전원합의체 {"예" if c["enBanc"] else "아니오"}')
        out.append(f'- 위치: {location}')
    out.append(f'- 쪽: {pages}')
    out.append('')
    for name in ('주제', '쟁점', '판시사항', '판결요지', '참조조문', '선정이유'):
        out.append(f'### {name}')
        out.append(sections.get(name) or '(없음)')
    out.append('### 검토메모')
    out.extend(f'- {n}' for n in (notes or ['(없음)']))
    out.append('')
    return '\n'.join(out)


def run_quiet(fn, argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(argv)
    return code, buf.getvalue()


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def set_verdicts(path, decide):
    """_review.jsonl 의 pending 줄에 decide(record) → dict|None 을 적용(상위 모델·사람 판정 흉내)."""
    rows = read_jsonl(path)
    for r in rows[1:]:
        if r.get('verdict') == 'pending':
            upd = decide(r)
            if upd:
                r.update({'reviewer': 'tester', 'reviewedAt': '2026-10-24'}, **upd)
    write(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


# ---------------------------------------------------------------- 정규화
class NormalizeTests(unittest.TestCase):
    def test_whitespace_and_fillers(self):
        self.assertEqual(L.normalize('가 나\n다\t라ㅤ마ﾠ바 사　아​자'), '가나다라마바사아자')

    def test_brackets_and_widths(self):
        self.assertEqual(L.normalize('【판결요지】 〈쟁점〉 《책》 「법」 『법』 <꺾쇠>'), '[판결요지]쟁점책법법꺾쇠')
        self.assertEqual(L.normalize('１２３ （가） ［１］ ＡＢ'), '123(가)[1]AB')

    def test_hyphen_and_middot(self):
        self.assertEqual(L.normalize('ㆍ・·∙‧'), '·····')
        self.assertEqual(L.normalize('‐‑‒–—―−﹣－'), '-' * 9)
        self.assertEqual(L.normalize('1∼2 3〜4'), '1~23~4')
        self.assertEqual(L.normalize('총칙ㆍ상행위'), L.normalize('총칙·상행위'))

    def test_digit_seq(self):
        self.assertEqual(L.digit_seq('대법원 2022. 5. 26. 선고 2022다200249 판결'), ['2022', '5', '26', '2022', '200249'])
        self.assertEqual(L.digit_seq('상법 제２３조 제1항'), ['23', '1'])
        self.assertNotEqual(L.digit_seq('제23조 제1항'), L.digit_seq('제23조 제2항'))


# ---------------------------------------------------------------- md 파싱
class ParseTests(unittest.TestCase):
    def test_case_line(self):
        c = L.parse_case_line('- 사건: 2022다200249 | 2022-05-26 | 대법원 | 판결 | 전원합의체 아니오')
        self.assertEqual((c['caseNumber'], c['lookupKey'], c['date'], c['court'], c['decisionType'], c['enBanc']),
                         ('2022다200249', '2022다200249', '2022-05-26', '대법원', '판결', False))
        self.assertEqual(c['errors'] + c['warnings'], [])
        merged = L.parse_case_line('2010다78135·78142 | 2011-01-13 | 대법원 | 판결 | 전원합의체 예')
        self.assertEqual((merged['lookupKey'], merged['enBanc']), ('2010다78135', True))
        unsure = L.parse_case_line('91헌가4 | ????-??-?? | 헌법재판소 | 판결? | 전원합의체 아니오')
        self.assertIsNone(unsure['date'])
        self.assertIsNone(unsure['decisionType'])
        self.assertTrue(unsure['errors'] and unsure['warnings'])
        lower = L.parse_case_line('2018가합1 | 2019-01-02 | 춘천지방법원 강릉지원 | 판결 | 전원합의체 아니오')
        self.assertTrue(any('COURTS' in w for w in lower['warnings']))
        dotted = L.parse_case_line('96다3449 | 1996.5.14. | 대법원 | 판결 | 전원합의체 아니오')
        self.assertEqual(dotted['date'], '1996-05-14')
        self.assertTrue(L.parse_case_line('2022다1 | 2022-02-30 | 대법원 | 판결 | 아니오')['errors'])
        self.assertTrue(L.parse_case_line('2022다1 | 2022-02-03 | 대법원')['errors'])

    def test_pages_spec(self):
        self.assertEqual(L.parse_pages_spec('49-50'), [49, 50])
        self.assertEqual(L.parse_pages_spec('49'), [49])
        self.assertEqual(L.parse_pages_spec('49, 51~52'), [49, 51, 52])
        self.assertEqual(L.parse_pages_spec('쪽 모름'), [])

    def test_parse_md(self):
        text = '\n'.join([
            '```markdown',
            '## (이어짐) 22. 앞 청크의 항목',
            '- 쪽: 61',
            '### 참조조문',
            '상법 제39조',
            '### 선정이유',
            '부실등기 책임을 밝혔다.',
            '### 검토메모',
            '- (없음)',
            '',
            '## 23. 두 재판이 실린 항목',
            '- 출처: 헌재 1991. 4. 1. 89헌마160; 대법원 2013. 1. 2. 선고 2013도1685 판결',
            '- 사건: 89헌마160 | 1991-04-01 | 헌법재판소 | 결정 | 전원합의체 아니오',
            '- 사건: 2013도1685 | 2013-01-02 | 대법원 | 판결 | 전원합의체 아니오',
            '- 위치: 총칙·상행위 > 제1편 총칙 > 제5장 상업등기 > (절 없음)',
            '- 쪽: 62-63',
            '',
            '### 주제',
            '상업등기, 부실등기',
            '### 쟁점',
            '첫 줄',
            '둘째 줄 [판독불가 p.62]',
            '### 판시사항',
            '(없음)',
            '### 결정요지',
            '[1] 요지 하나',
            '[2] 요지 둘',
            '### 참조조문',
            '(없음)',
            '### 선정이유',
            '(없음)',
            '### 기타',
            '참조판례: 대법원 1990. 1. 1. 선고 89다1 판결',
            '### 해설',
            '알 수 없는 절',
            '### 검토메모',
            '- 둘째 줄 끝 어절 이음 불확실(원문: 줄\\n)',
            '- 병합사건 아님, 재판 두 건',
            '```',
        ])
        blocks = L.parse_md(text)
        self.assertEqual([(b['no'], b['continued']) for b in blocks], [(22, True), (23, False)])
        cont, item = blocks
        self.assertEqual(cont['sections']['참조조문'], '상법 제39조')
        self.assertEqual(cont['pages'], [61])
        self.assertEqual(cont['errors'], [])          # 이어짐 블록은 출처·사건 줄 생략 가능
        self.assertEqual(len(item['cases']), 2)
        self.assertEqual(item['cases'][0]['court'], '헌법재판소')
        self.assertEqual(item['cases'][1]['caseNumber'], '2013도1685')
        self.assertIsNone(item['sections']['판시사항'])
        self.assertEqual(item['sections']['판결요지'], '[1] 요지 하나\n[2] 요지 둘')   # 결정요지 → 판결요지
        self.assertEqual(item['sections']['쟁점'], '첫 줄\n둘째 줄 [판독불가 p.62]')
        self.assertIn('참조판례', item['sections']['기타'])
        self.assertEqual(item['unknownSections'], {'해설': '알 수 없는 절'})
        self.assertEqual(item['illegible'], 1)
        self.assertEqual(len(item['notes']), 2)
        self.assertEqual(cont['notes'], [])
        self.assertEqual(item['pages'], [62, 63])
        self.assertTrue(any('코드펜스' in w for w in blocks[0]['warnings']))

    def test_parse_md_preamble_and_bad_header(self):
        blocks = L.parse_md('머리말\n## 제목만 있는 줄\n- 쪽: 3\n')
        self.assertTrue(blocks[0].get('preamble'))
        self.assertIsNone(blocks[1]['no'])
        self.assertTrue(blocks[1]['errors'])


# ---------------------------------------------------------------- 대조 게이트
HOLD = ('관습법이란 사회의 거듭된 관행으로 생성한 사회생활규범이 사회의 법적 확신과 인식에 의하여 법적 규범으로 승인·강행되기에 '
        '이른 것을 말하고, 사실인 관습은 사회의 관행에 의하여 발생한 사회생활규범인 점에서 관습법과 같으나 사회의 법적 확신이나 '
        '인식에 의하여 법적 규범으로서 승인된 정도에 이르지 않은 것을 말하는 바, 관습법은 바로 법원으로서 법령과 같은 효력을 갖는 '
        '관습으로서 법령에 저촉되지 않는 한 법칙으로서의 효력이 있는 것이며, 이에 반하여 사실인 관습은 법령으로서의 효력이 없는 '
        '단순한 관행으로서 법률행위의 당사자의 의사를 보충함에 그치는 것이다(상법 제1조, 민법 제106조 참조).')


def wrap(text, width=45):
    return '\n'.join(text[i:i + width] for i in range(0, len(text), width))


def gate_pages():
    half = len(HOLD) // 2
    p1 = '\n'.join([EVEN_HEAD, '제 1 편 총칙', '1. 상관습과 관습법', '(대법원 1983. 6. 14. 선고 80다3231 판결)', '<쟁점>',
                    '관습과 관습법의 구별 기준', '<판결요지>', wrap(HOLD[:half]), '3'])
    p2 = '\n'.join(['제1편 제1장 서 론', wrap(HOLD[half:]), '<참조조문>', '상법 제1조', '<선정이유>', '상관습법은 상법의 법원이 된다.',
                    '2. 다음 항목', '(대법원 1993. 6. 11. 선고 93다7174 판결)', '〈쟁점〉', '다음 쟁점', '4'])
    return {1: p1, 2: p2}


class GateTests(unittest.TestCase):
    def verify(self, **sections):
        base = {'쟁점': '관습과 관습법의 구별 기준', '판결요지': HOLD, '참조조문': '상법 제1조', '판시사항': None}
        base.update(sections)
        return L.verify_sections(base, gate_pages(), 1, '상관습과 관습법', 1, {'no': 2, 'title': '다음 항목'})

    def test_exact_pass_across_page_with_running_heads(self):
        v = self.verify()
        self.assertEqual(v['status'], 'pass', v)
        self.assertEqual({f: r['method'] for f, r in v['fields'].items()}, {'쟁점': 'substring', '판결요지': 'substring', '참조조문': 'substring'})
        self.assertEqual(v['pages'], [1, 2])
        self.assertEqual(v['citations'], 1)

    def test_whitespace_and_linebreak_variants_pass(self):
        self.assertEqual(self.verify(판결요지=HOLD.replace(' ', '\n', 5).replace('·', 'ㆍ'))['status'], 'pass')

    def test_one_char_change_is_lcs_with_diff(self):
        k = len(HOLD) // 3
        changed = HOLD[:k] + ('가' if HOLD[k] != '가' else '나') + HOLD[k + 1:]
        r = self.verify(판결요지=changed)['fields']['판결요지']
        self.assertEqual((r['status'], r['method']), ('pass', 'lcs'))   # 비율 기준 통과(계약) — md_validate 가 warn 으로 올린다
        self.assertTrue(r['diff'])

    def test_digit_change_fails(self):
        r = self.verify(판결요지=HOLD.replace('제106조', '제107조'))['fields']['판결요지']
        self.assertEqual(r['status'], 'fail')
        self.assertFalse(r['digitsOk'])

    def test_truncation_fails_on_boundary(self):
        r = self.verify(판결요지=HOLD[:-30])['fields']['판결요지']
        self.assertEqual(r['status'], 'fail')
        self.assertIn('절 경계', r['note'])

    def test_extra_text_fails(self):
        r = self.verify(참조조문='상법 제1조\n상관습법은 상법의 법원이 된다.')['fields']['참조조문']
        self.assertEqual(r['status'], 'fail')

    def test_section_missing_in_md_fails(self):
        v = self.verify(참조조문=None)
        self.assertEqual(v['fields']['참조조문']['method'], 'absent')
        self.assertEqual(v['status'], 'fail')

    def test_issue_substitute_and_skip(self):
        self.assertIn('쟁점', self.verify()['fields'])          # 판시사항 없음 → 쟁점이 issues 자리
        self.assertEqual(L.display_fields({'판시사항': '가', '쟁점': '나'}), ['판시사항', '판결요지', '참조조문'])
        self.assertEqual(L.display_fields({'쟁점': '나'}), ['쟁점', '판결요지', '참조조문'])
        pages = {1: '1. 항목\n(대법원 2000. 1. 1. 선고 99다1 판결)\n<선정이유>\n이유만 있다.'}
        self.assertEqual(L.verify_sections({'선정이유': '이유만 있다.'}, pages, 1, '항목', 1)['status'], 'skip')

    def test_qualified_header_and_missed_entry_line(self):
        pages = {7: '\n'.join(['202. 대표이사의 전단적 대표행위', '(대법원 2021. 2. 18. 선고 2015다45451 전원합의체 판결)', '<쟁점>', '대표권 제한',
                               '<판결요지(다수의견)>', '거래 상대방이 알았다면 무효이다.', '<선정이유>', '판례 변경.',
                               '상법 제23조에 규정된', '203.', '해당하는지의 판단', '(대법원 2016. 1. 28. 선고 2013다76635 판결)',
                               '<쟁점>', '다른 쟁점', '<판결요지>', '다른 요지이다.'])}
        for text in ('[다수의견] 거래 상대방이 알았다면 무효이다.', '(다수의견) 거래 상대방이 알았다면 무효이다.', '거래 상대방이 알았다면 무효이다.'):
            v = L.verify_sections({'쟁점': '대표권 제한', '판결요지': text}, pages, 202, '대표이사의 전단적 대표행위', 7, None)
            self.assertEqual(v['status'], 'pass', (text, v))
        # 'N.' 만 있는 줄도 항목 머리 — 다음 항목의 요지를 이어 붙이면 fail
        v = L.verify_sections({'쟁점': '대표권 제한', '판결요지': '(다수의견) 거래 상대방이 알았다면 무효이다. 다른 요지이다.'},
                              pages, 202, '대표이사의 전단적 대표행위', 7, None)
        self.assertEqual(v['status'], 'fail')


# ---------------------------------------------------------------- 병합 규칙
class RuleTests(unittest.TestCase):
    def test_sample_size_and_pick(self):
        self.assertEqual(L.sample_size(380), 38)
        self.assertEqual(L.sample_size(50), 20)
        self.assertEqual(L.sample_size(5), 5)
        self.assertEqual(L.sample_size(0), 0)
        keys = [(i, f'd{i}') for i in range(1, 101)]
        first = L.pick_sample(keys, set(), 20, seed=20261024)
        self.assertEqual(first, L.pick_sample(list(reversed(keys)), set(), 20, seed=20261024))   # 입력 순서와 무관
        self.assertEqual(len(first), 20)
        more = L.pick_sample(keys, set(first), 25, seed=20261024)
        self.assertEqual(len(more), 5)
        self.assertFalse(set(more) & set(first))
        self.assertEqual(L.pick_sample(keys, set(first), 20, seed=20261024), [])
        self.assertNotEqual(first, L.pick_sample(keys, set(), 20, seed=1))

    def test_issue_substitution_in_source(self):
        kw = dict(file=PDF, pages=[45], reviewer='script+tester sample 10%', reviewed_at='2026-10-24', sha256='ab' * 32)
        src = L.standard_source_from_sections({'쟁점': '[1] 첫 쟁점\n[2] 둘째 쟁점', '판결요지': '[1] 요지\n[2] 요지2', '참조조문': '상법 제1조\n민법 제106조'},
                                              ['쟁점', '판결요지', '참조조문'], **kw)
        self.assertEqual(src['issues'], [{'n': '[1]', 'text': '첫 쟁점'}, {'n': '[2]', 'text': '둘째 쟁점'}])
        self.assertEqual(src['holdings'][1], {'n': '[2]', 'text': '요지2'})
        self.assertEqual(src['statutes'], ['상법 제1조', '민법 제106조'])
        self.assertEqual(L.check_standard_source(src), [])
        both = L.standard_source_from_sections({'판시사항': '판시', '쟁점': '쟁점', '판결요지': '요지'}, ['판시사항', '쟁점', '판결요지'], **kw)
        self.assertEqual(both['issues'], [{'n': '', 'text': '판시'}])         # 판시사항이 있으면 쟁점은 issues 가 아님
        self.assertIsNone(L.standard_source_from_sections({'판결요지': '요지'}, [], **kw))

    def test_standard_source_keys(self):
        src = {'verified': True, 'book': L.BOOK, 'edition': L.EDITION, 'file': PDF, 'pages': [3], 'holdings': [{'n': '', 'text': '요지'}],
               'reviewer': 'x', 'reviewedAt': '2026-10-24', 'sha256': 'f' * 64}
        self.assertEqual(L.check_standard_source(src), [])
        self.assertTrue(L.check_standard_source(dict(src, seq=3)))             # 허용되지 않는 키
        self.assertTrue(L.check_standard_source(dict(src, verified=False)))
        self.assertTrue(L.check_standard_source(dict(src, pages=[0])))
        self.assertTrue(L.check_standard_source(dict(src, reviewedAt='2026/10/24')))
        self.assertEqual(L.SOURCE_KEYS, frozenset({'issues', 'holdings', 'statutes', 'precedents', 'subjectStatutes', 'verified', 'book',
                                                   'edition', 'file', 'pages', 'url', 'reviewedAt', 'reviewer', 'sha256'}))


# ---------------------------------------------------------------- 통합: md_validate → md_merge
P1 = '\n'.join([EVEN_HEAD, '제 1 편 총칙', '제 1 장 상인',
                '1. 의사의 상인 여부', '(대법원 2022. 5. 26. 선고 2022다200249 판결)',
                '<쟁점>', '의사나 의료기관을 상인으로', '볼 수 있는지 여부',
                '<판결요지>', '[1] 의사가 영리를 목적으로 의료행위를 하는 것은 상법 제46조의', '행위에 해당하지 않는다.',
                '[2] 의료법 제33조 제2항에 비추어 의사는 상인이 아니다.',
                '<선정이유>', '의사의 상인성을 처음 밝힌 판결이다.',
                '2. 변호사의 상인성 여부와 의제상인 해당성에 관한 판단', '(대법원 2007. 7. 26. 자 2006마334 결정)',
                '〈쟁점〉', '변호사를 상인으로 볼 수 있는지', '3'])
P2 = '\n'.join(['제1편 제1장 상 인',
                '〈판결요지〉', '변호사는 상법 제5조 제1항이 규정하는 의제상인에 해당하지 않는다. 변호사의 영리추구 활동을 엄격',
                '히 제한하는 법률의 규정에 비추어 그러하다.',
                '〈선정이유〉', '변호사의 상인성을 부정하였다.',
                '3. 상호의 역혼동', '(대법원 2002. 2. 26. 선고 2001다73879 판결)',
                '<쟁점>', '후발 상호를 통한 역혼동', '<판결요지>', '역혼동으로 인한 손해배상은 영업의 종류가 다르면 인정할 수 없다.', '4'])
P3 = '\n'.join([EVEN_HEAD,
                '<참조조문>', '상법 제23조 제1항, 제4항', '<선정이유>', '역혼동 법리를 처음 인정하였다.',
                '4. 대표이사의 전단적 대표행위', '(대법원 2021. 2. 18. 선고 2015다45451 전원합의체 판결)',
                '<쟁점>', '대표권 제한 위반 거래의 효력', '<판결요지(다수의견)>',
                '주식회사의 대표이사가 이사회 결의를 거치지 않고 거래한 경우 거래 상대방이 이를 알았거나 중대한 과',
                '실로 알지 못한 때에는 무효이다.', '<선정이유>', '판례를 변경하였다.', '5'])
P4 = '\n'.join(['제1편 제1장 상 인',
                '5. 의사의 상인성 다시 보기', '(대법원 2022. 5. 26. 선고 2022다200249 판결)',
                '<쟁점>', '의사나 의료기관을 상인으로 볼 수 있는지 여부', '<판결요지>', '의료법 제33조 제2항에 비추어 의사는 상인이 아니다.',
                '<선정이유>', '같은 판결을 다른 각도에서 보았다.',
                '6. 하급심 판결', '(춘천지방법원 강릉지원 2019. 1. 2. 선고 2018가합1 판결)',
                '<쟁점>', '하급심 쟁점', '<판결요지>', '하급심 판결요지이다.', '6'])

LABELS = ['제1편 총칙', '제1장 상인']
C1 = case('2022다200249', '2022-05-26')
C2 = case('2006마334', '2007-07-26', dtype='결정')
C3 = case('2001다73879', '2002-02-26')
C4 = case('2015다45451', '2021-02-18', en_banc=True)
C6 = case('2018가합1', '2019-01-02', court='춘천지방법원 강릉지원')
T2 = '변호사의 상인성 여부와 의제상인 해당성에 관한 판단'


def skeleton_entry(seq, no, title, cases, pages, chunk, toc=('sb-1', 'sb-1-1', 'sb-1-1-1'), status='resolved'):
    return {'seq': seq, 'no': no, 'title': title, 'citationRaw': '', 'cases': cases, 'tocLabels': LABELS, 'tocPath': list(toc),
            'tocPathStatus': status, 'pdfPages': pages, 'printedPage': None, 'chunk': chunk}


def build_fixture(root, registry=None):
    d = os.path.join(root, '상법')
    for i, text in enumerate((P1, P2, P3, P4), 1):
        write(os.path.join(d, 'pages', f'p{i:04d}.txt'), text)
    skel = {'subject': 'commercial', 'pdf': PDF, 'pages': 4, 'bodyStart': 1, 'entries': [
        skeleton_entry(1, 1, '의사의 상인 여부', [C1], [1], 'c001'),
        skeleton_entry(2, 2, T2, [C2], [1, 2], 'c001'),
        skeleton_entry(3, 3, '상호의 역혼동', [C3], [2, 3], 'c001'),
        skeleton_entry(4, 4, '대표이사의 전단적 대표행위', [C4], [3], 'c002', toc=('sb-2',), status='proposed'),
        skeleton_entry(5, 5, '의사의 상인성 다시 보기', [C1], [4], 'c002'),
        skeleton_entry(6, 6, '하급심 판결', [C6], [4], 'c002')],
        'chunks': [{'id': 'c001', 'file': 'chunks/c001_p0001-p0002.txt', 'pages': [1, 2], 'expected': [1, 3], 'continued': None,
                    'location': '제1편 총칙 › 제1장 상인'},
                   {'id': 'c002', 'file': 'chunks/c002_p0003-p0004.txt', 'pages': [3, 4], 'expected': [4, 6], 'continued': 3,
                    'location': '제1편 총칙 › 제1장 상인'}]}
    write(os.path.join(d, 'skeleton.json'), json.dumps(skel, ensure_ascii=False))
    write(os.path.join(d, '_conflicts.json'), json.dumps({'stage0': [{'kind': 'toc', 'seq': 4}]}, ensure_ascii=False))
    c001 = '\n'.join([
        md_block(1, '의사의 상인 여부', [C1], {'쟁점': '의사나 의료기관을 상인으로 볼 수 있는지 여부',
                 '판결요지': '[1] 의사가 영리를 목적으로 의료행위를 하는 것은 상법 제46조의 행위에 해당하지 않는다.\n'
                             '[2] 의료법 제33조 제2항에 비추어 의사는 상인이 아니다.', '선정이유': '의사의 상인성을 처음 밝힌 판결이다.'}, '1'),
        md_block(2, T2, [C2], {'쟁점': '변호사를 상인으로 볼 수 있는지',
                 '판결요지': '변호사는 상법 제5조 제1항이 규정하는 의제상인에 해당하지 않는다. 변호사의 영리추구 활동을 엄격히 제한하는 법률의 규정에 비추어 그러하다.',
                 '선정이유': '변호사의 상인성을 부정하였다.'}, '1-2', notes=["'엄격 / 히' 를 '엄격히' 로 이음"],
                 citation='대법원 2007. 7. 26. 자 2006마334 결정'),
        md_block(3, '상호의 역혼동', [C3], {'쟁점': '후발 상호를 통한 역혼동', '판결요지': '역혼동으로 인한 손해배상은 영업의 종류가 다르면 인정할 수 없다.'}, '2')])
    c002 = '\n'.join([
        md_block(3, '상호의 역혼동', [], {'참조조문': '상법 제23조 제1항, 제5항', '선정이유': '역혼동 법리를 처음 인정하였다.'}, '3', continued=True),
        md_block(4, '대표이사의 전단적 대표행위', [C4], {'쟁점': '대표권 제한 위반 거래의 효력',
                 '판결요지': '[다수의견] 주식회사의 대표이사가 이사회 결의를 거치지 않고 거래한 경우 거래 상대방이 이를 알았거나 중대한 과실로 알지 못한 때에는 무효이다.',
                 '선정이유': '판례를 변경하였다.'}, '3'),
        md_block(5, '의사의 상인성 다시 보기', [C1], {'쟁점': '의사나 의료기관을 상인으로 볼 수 있는지 여부',
                 '판결요지': '의료법 제33조 제2항에 비추어 의사는 상인이 아니다.', '선정이유': '같은 판결을 다른 각도에서 보았다.'}, '4'),
        md_block(6, '하급심 판결', [C6], {'쟁점': '하급심 쟁점', '판결요지': '하급심 판결요지이다.'}, '4')])
    write(os.path.join(d, 'md', 'c001.md'), c001)
    write(os.path.join(d, 'md', 'c002.md'), c002)
    reg_path, toc_path = os.path.join(root, 'registry.json'), os.path.join(root, 'toc.json')
    write(reg_path, json.dumps(registry or {'cases': []}, ensure_ascii=False))
    write(toc_path, json.dumps(TOC, ensure_ascii=False))
    return d, ['--dir', d, '--subject', '상법', '--registry', reg_path, '--toc', toc_path]


class PipelineTests(unittest.TestCase):
    def test_validate_then_merge_end_to_end(self):
        with tempfile.TemporaryDirectory() as root:
            d, margs = build_fixture(root)
            code, out = run_quiet(md_validate.main, ['--dir', d, '--subject', '상법'])
            self.assertEqual(code, 0, out)
            rows = read_jsonl(os.path.join(d, 'entries.jsonl'))
            self.assertEqual([r['seq'] for r in rows], [1, 2, 3, 4, 5, 6])
            st = {r['seq']: r['verify']['status'] for r in rows}
            self.assertEqual(st, {1: 'pass', 2: 'pass', 3: 'fail', 4: 'pass', 5: 'pass', 6: 'pass'}, [r['verify'] for r in rows])
            by = {r['seq']: r for r in rows}
            self.assertTrue(by[3]['continued'])
            self.assertEqual(by[3]['sections']['참조조문'], '상법 제23조 제1항, 제5항')
            self.assertFalse(by[3]['verify']['fields']['참조조문']['digitsOk'])
            self.assertEqual(by[2]['notes'], ["'엄격 / 히' 를 '엄격히' 로 이음"])
            self.assertEqual(by[2]['verify']['pages'], [1, 2])
            self.assertEqual(by[1]['level'], 'ok')
            self.assertEqual(by[6]['level'], 'warn')                          # COURTS 에 없는 법원
            self.assertRegex(by[1]['verify']['pagesSha256'], r'^[0-9a-f]{64}$')
            report = load_json(os.path.join(d, '_report.json'))
            self.assertEqual(report['chunks']['c001']['missing'], [])
            self.assertEqual(report['chunks']['c002']['entries'], 3)
            self.assertEqual((report['totals']['pass'], report['totals']['fail'], report['totals']['notes']), (5, 1, 1))

            # 1차 병합: 판정 대상이 _review.jsonl 에 pending 으로, 후보는 review/skip
            code, out = run_quiet(md_merge.main, margs + ['--check'])
            self.assertEqual(code, 0, out)
            review = read_jsonl(os.path.join(d, '_review.jsonl'))
            self.assertTrue(review[0]['meta'])
            self.assertEqual((review[0]['seed'], review[0]['sampleRate'], review[0]['minSample']), (20261024, 0.1, 20))
            reasons = {(r['seq'], r['reason']) for r in review[1:]}
            self.assertEqual(reasons, {(1, 'sample'), (4, 'sample'), (2, 'notes'), (2, 'title'), (3, 'fail'), (6, 'conflict')})
            self.assertTrue(all(r['verdict'] == 'pending' for r in review[1:]))
            cands = load_json(os.path.join(d, 'candidates-commercial.json'))
            self.assertEqual(cands['group'], 'standard')
            status = {c['seq']: c['status'] for c in cands['candidates']}
            self.assertEqual(status, {1: 'review', 2: 'review', 3: 'review', 4: 'review', 5: 'skip', 6: 'review'})
            self.assertFalse(any('standardSource' in c for c in cands['candidates']))
            first = cands['candidates'][0]
            self.assertIn('함께 실린 곳: 의사의 상인성 다시 보기 (5번, p.4)', first['memo'])
            self.assertEqual(first['keywords'], [])
            conflicts = load_json(os.path.join(d, '_conflicts.json'))
            self.assertEqual(conflicts['stage0'], [{'kind': 'toc', 'seq': 4}])      # 0단계 기록은 그대로
            self.assertEqual({c['kind'] for c in conflicts['stage3']}, {'duplicate', 'identity'})

            # 다시 돌려도 판정 줄이 늘지 않는다
            run_quiet(md_merge.main, margs)
            self.assertEqual(len(read_jsonl(os.path.join(d, '_review.jsonl'))), len(review))

            # 판정: 표본 ok, 검토메모 ok, fail 은 fix(PDF 원문대로), 하급심은 reject, 제목 축약
            def decide(r):
                if r['reason'] == 'title':
                    return {'verdict': 'ok', 'title': '변호사의 상인성'}
                if r['seq'] == 3:
                    return {'verdict': 'fix', 'fixedSections': {'참조조문': '상법 제23조 제1항, 제4항'}}
                if r['seq'] == 6:
                    return {'verdict': 'reject'}
                return {'verdict': 'ok'}
            set_verdicts(os.path.join(d, '_review.jsonl'), decide)
            code, out = run_quiet(md_merge.main, margs + ['--check'])
            self.assertEqual(code, 0, out)
            self.assertIn('오류 0개', out)
            cands = {c['seq']: c for c in load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']}
            self.assertEqual({k: c['status'] for k, c in cands.items()}, {1: 'ok', 2: 'ok', 3: 'ok', 4: 'review', 5: 'skip', 6: 'review'})
            s1 = cands[1]['standardSource']
            self.assertEqual(s1['issues'], [{'n': '', 'text': '의사나 의료기관을 상인으로 볼 수 있는지 여부'}])   # 쟁점 → issues
            self.assertEqual([h['n'] for h in s1['holdings']], ['[1]', '[2]'])
            self.assertEqual((s1['book'], s1['edition'], s1['file'], s1['pages'], s1['reviewer']), (L.BOOK, L.EDITION, PDF, [1], 'tester'))
            self.assertEqual(cands[2]['title'], '변호사의 상인성')
            self.assertEqual(cands[2]['decisionType'], '결정')
            self.assertEqual(cands[2]['standardSource']['pages'], [1, 2])
            self.assertEqual(cands[3]['standardSource']['statutes'], ['상법 제23조 제1항, 제4항'])   # fix 가 다시 대조 통과
            self.assertEqual(cands[3]['standardSource']['pages'], [2, 3])
            self.assertIn('standardSource', cands[4])                                           # 검증됐지만 tocPath 제안 상태라 review
            self.assertIn('tocPath proposed', cands[4]['statusReason'])
            self.assertTrue(cands[4]['enBanc'])
            self.assertNotIn('standardSource', cands[5])
            self.assertNotIn('standardSource', cands[6])
            for c in cands.values():
                if 'standardSource' in c:
                    self.assertEqual(L.check_standard_source(c['standardSource']), [])

    def test_fix_that_does_not_match_pdf_stays_in_review(self):
        with tempfile.TemporaryDirectory() as root:
            d, margs = build_fixture(root)
            run_quiet(md_validate.main, ['--dir', d])
            run_quiet(md_merge.main, margs)
            set_verdicts(os.path.join(d, '_review.jsonl'),
                         lambda r: {'verdict': 'fix', 'fixedSections': {'참조조문': '상법 제23조'}} if r['seq'] == 3 and r['reason'] == 'fail' else None)
            run_quiet(md_merge.main, margs)
            cands = {c['seq']: c for c in load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']}
            self.assertEqual(cands[3]['status'], 'review')
            self.assertNotIn('standardSource', cands[3])
            kinds = {c['kind'] for c in load_json(os.path.join(d, '_conflicts.json'))['stage3']}
            self.assertIn('fix-failed', kinds)

    def test_regenerated_md_invalidates_old_verdict(self):
        with tempfile.TemporaryDirectory() as root:
            d, margs = build_fixture(root)
            run_quiet(md_validate.main, ['--dir', d])
            run_quiet(md_merge.main, margs)
            set_verdicts(os.path.join(d, '_review.jsonl'), lambda r: {'verdict': 'ok'})
            path = os.path.join(d, 'md', 'c001.md')
            text = read_text(path).replace('변호사의 상인성을 부정하였다.', '변호사의 상인성을 부정한 판결이다.')   # md 를 다시 만듦
            write(path, text)
            run_quiet(md_validate.main, ['--dir', d])
            run_quiet(md_merge.main, margs)
            rows = [r for r in read_jsonl(os.path.join(d, '_review.jsonl'))[1:] if r['seq'] == 2 and r['reason'] != 'title']
            self.assertEqual([r['verdict'] for r in rows], ['ok', 'pending'])
            cands = {c['seq']: c for c in load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']}
            self.assertEqual(cands[2]['status'], 'review')

    def test_registry_text_conflict(self):
        reg = {'cases': [{'id': 'enbanc-2015da45451', 'group': 'enbanc', 'subject': 'commercial', 'court': '대법원', 'caseNumber': '2015다45451',
                          'lookupKey': '2015다45451', 'decisionDate': '2021-02-18', 'decisionType': '판결',
                          'decisionId': 'sc-2015da45451-20210218-judgment',
                          'standardSource': {'verified': True, 'book': L.BOOK, 'edition': L.EDITION, 'file': PDF, 'pages': [3],
                                             'holdings': [{'n': '', 'text': '다른 요지'}]}}]}
        with tempfile.TemporaryDirectory() as root:
            d, margs = build_fixture(root, registry=reg)
            run_quiet(md_validate.main, ['--dir', d])
            run_quiet(md_merge.main, margs)
            conflicts = load_json(os.path.join(d, '_conflicts.json'))['stage3']
            hit = [c for c in conflicts if c['kind'] == 'registry-text']
            self.assertEqual([c['registryIds'] for c in hit], [['enbanc-2015da45451']])
            cands = {c['seq']: c for c in load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']}
            self.assertIn('등록부', cands[4]['statusReason'])
            review = read_jsonl(os.path.join(d, '_review.jsonl'))
            self.assertIn((4, 'conflict'), {(r['seq'], r['reason']) for r in review[1:]})


def bulk_fixture(root, n=30, per_chunk=10):
    """n 개 항목(한 쪽에 하나), per_chunk 개씩 청크 — 표본 규칙 시험용."""
    d = os.path.join(root, '상법')
    entries, chunks, md = [], [], {}
    for i in range(1, n + 1):
        cid = f'c{(i - 1) // per_chunk + 1:03d}'
        number = f'2020다{1000 + i}'
        hold = f'제{i}조의 요지이다. 이 판결은 시험용 항목 {i}번의 판결요지를 담고 있다.'
        write(os.path.join(d, 'pages', f'p{i:04d}.txt'),
              '\n'.join([EVEN_HEAD, f'{i}. 시험 항목 {i}', f'(대법원 2020. 1. {i % 28 + 1}. 선고 {number} 판결)', '<쟁점>', f'쟁점 {i}',
                         '<판결요지>', hold, '<선정이유>', '시험.', str(i)]))
        c = case(number, f'2020-01-{i % 28 + 1:02d}')
        entries.append(skeleton_entry(i, i, f'시험 항목 {i}', [c], [i], cid))
        md.setdefault(cid, []).append(md_block(i, f'시험 항목 {i}', [c], {'쟁점': f'쟁점 {i}', '판결요지': hold, '선정이유': '시험.'}, str(i)))
    for k in range(0, n, per_chunk):
        cid = f'c{k // per_chunk + 1:03d}'
        chunks.append({'id': cid, 'file': '', 'pages': [k + 1, min(n, k + per_chunk)], 'expected': [k + 1, min(n, k + per_chunk)],
                       'continued': None, 'location': '제1편 총칙 › 제1장 상인'})
        write(os.path.join(d, 'md', cid + '.md'), '\n'.join(md[cid]))
    write(os.path.join(d, 'skeleton.json'), json.dumps({'subject': 'commercial', 'pdf': PDF, 'pages': n, 'entries': entries, 'chunks': chunks},
                                                       ensure_ascii=False))
    reg_path, toc_path = os.path.join(root, 'registry.json'), os.path.join(root, 'toc.json')
    write(reg_path, '{"cases": []}')
    write(toc_path, json.dumps(TOC, ensure_ascii=False))
    return d, ['--dir', d, '--registry', reg_path, '--toc', toc_path]


class SampleRuleTests(unittest.TestCase):
    def test_clean_sample_verifies_unsampled_pass(self):
        with tempfile.TemporaryDirectory() as root:
            d, margs = bulk_fixture(root)
            run_quiet(md_validate.main, ['--dir', d])
            run_quiet(md_merge.main, margs)
            review = read_jsonl(os.path.join(d, '_review.jsonl'))[1:]
            self.assertEqual(len(review), 20)                                  # 30 의 10% < 최소 20
            self.assertTrue(all(r['reason'] == 'sample' and r['sampleKind'] == 'random' for r in review))
            cands = load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']
            self.assertTrue(all(c['status'] == 'review' for c in cands))          # 표본 판정 전에는 아무것도 검증되지 않음
            set_verdicts(os.path.join(d, '_review.jsonl'), lambda r: {'verdict': 'ok'})
            code, out = run_quiet(md_merge.main, margs + ['--check', '--reviewer', 'script+claude-opus-5-5 sample 10%'])
            self.assertEqual(code, 0, out)
            cands = load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']
            self.assertTrue(all(c['status'] == 'ok' and 'standardSource' in c for c in cands))
            sampled = {r['seq'] for r in review}
            unsampled = [c for c in cands if c['seq'] not in sampled]
            self.assertEqual(len(unsampled), 10)
            self.assertTrue(all(c['standardSource']['reviewer'] == 'script+claude-opus-5-5 sample 10%' for c in unsampled))
            self.assertTrue(all(c['standardSource']['reviewer'] == 'tester' for c in cands if c['seq'] in sampled))

    def test_sample_defect_triggers_chunk_and_subject_review(self):
        with tempfile.TemporaryDirectory() as root:
            d, margs = bulk_fixture(root)
            run_quiet(md_validate.main, ['--dir', d])
            run_quiet(md_merge.main, margs)
            review = read_jsonl(os.path.join(d, '_review.jsonl'))[1:]
            bad = sorted(r['seq'] for r in review)[0]
            bad_chunk = next(r['chunk'] for r in review if r['seq'] == bad)
            set_verdicts(os.path.join(d, '_review.jsonl'), lambda r: {'verdict': 'reject' if r['seq'] == bad else 'ok'})
            code, out = run_quiet(md_merge.main, margs)
            self.assertIn('결함률 5.00%', out)
            rows = read_jsonl(os.path.join(d, '_review.jsonl'))[1:]
            added = rows[len(review):]
            kinds = {r['seq']: r['sampleKind'] for r in added}
            sampled = {r['seq'] for r in review}
            unsampled = set(range(1, 31)) - sampled
            self.assertEqual(set(kinds), unsampled)                              # 결함률 1/20 > 0.5% → 과목 pass 전부 재검토
            chunk_of = {r['seq']: r['chunk'] for r in rows}
            self.assertTrue(all(k == 'chunk' for s, k in kinds.items() if chunk_of[s] == bad_chunk))
            self.assertTrue(all(k == 'subject' for s, k in kinds.items() if chunk_of[s] != bad_chunk))
            cands = {c['seq']: c for c in load_json(os.path.join(d, 'candidates-commercial.json'))['candidates']}
            self.assertNotIn('standardSource', cands[bad])
            self.assertTrue(all(cands[s]['status'] == 'review' and 'standardSource' not in cands[s] for s in unsampled))
            self.assertTrue(all(cands[s]['status'] == 'ok' and 'standardSource' in cands[s] for s in sampled - {bad}))


if __name__ == '__main__':
    unittest.main()
