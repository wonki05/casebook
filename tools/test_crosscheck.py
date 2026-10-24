"""tools/crosscheck.py 회귀 시험 — 임시 등록부·fetched·후보 fixture 로 ok / low-similarity / meta-mismatch / missing 을 확인한다.

  python -X utf8 tools/test_crosscheck.py

fixture 는 모두 임시 폴더에 만들며 실제 data/registry.json·fetched·과목 폴더는 읽지도 쓰지도 않는다.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import case_identity as ci  # noqa: E402
import crosscheck as cc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = 'data/standard-cases/표준판례(2023년 개정판)_상법.pdf'


def source(holdings=None, issues=None, pages=(49,)):
    s = {'verified': True, 'book': '표준판례', 'edition': '2023년 개정판', 'file': PDF, 'pages': list(pages),
         'reviewer': 'script+test sample 10%', 'reviewedAt': '2026-10-24', 'sha256': '0' * 64}
    if holdings is not None:
        s['holdings'] = holdings
    if issues is not None:
        s['issues'] = issues
    return s


def cand(seq, case, date, src=None, court='대법원', **kw):
    c = {'caseNumber': case, 'lookupKey': case, 'court': court, 'decisionType': '판결', 'date': date, 'enBanc': False,
         'title': f'시험 {seq}', 'tocPath': ['sb-1'], 'tags': [], 'selectionReason': '', 'keywords': [], 'memo': '',
         'status': 'ok', 'statusReason': '', 'seq': seq, 'no': seq, 'chunk': 'c001', 'pdfPages': [49]}
    if src is not None:
        c['standardSource'] = src
    c.update(kw)
    return c


def reg_case(rid, case, date, court='대법원', **kw):
    c = {'id': rid, 'group': 'standard', 'subject': 'commercial', 'title': rid, 'court': court, 'caseNumber': case,
         'lookupKey': case, 'decisionDate': date, 'enBanc': False, 'tocPath': ['sb-1'], 'tags': [], 'result': '', 'editorial': {}}
    c.update(kw)
    c.update(ci.identity(c))
    return c


def fetched(rid, case, citation, holdings=None, issues=None):
    secs = []
    if issues is not None:
        secs.append({'heading': '【판시사항】', 'text': issues})
    if holdings is not None:
        secs.append({'heading': '【판결요지】', 'text': holdings})
    secs += [{'heading': '【참조조문】', 'text': '상법 제4조'}, {'heading': '【전문】', 'text': ''},
             {'heading': '【주 문】', 'text': '상고를 기각한다.'}]
    return {'id': rid, 'caseNumber': case, 'lookupKey': case, 'kind': 'prec', 'seq': '1',
            'sourceUrl': 'https://www.law.go.kr/LSW/precInfoP.do?precSeq=1', 'pageTitle': '시험', 'citation': citation, 'sections': secs}


# ── fixture 본문 ──
A_OFFICIAL = ('[1] 상인은 자기명의로 상행위를 하는 자를 말하고, 총칙ㆍ상행위 편의 규정은 의사에게 적용되지 않는다. '
              '의사는 상인이 아니다.\n[2] 의사의 급여채권은 상사채권이 아니므로 민법 제163조의 3년 시효가 적용된다.')
A_STD = [{'n': '[1]', 'text': '상인은 자기명의로 상행위를 하는 자를 말하고, 총칙·상행위 편의 규정은\n의사에게 적용되지 않는다. 의사는 상인이 아니다.'},
         {'n': '[2]', 'text': '의사의 급여채권은 상사채권이 아니므로 민법 제163조의 3년 시효가 적용된다.'}]
B_OFFICIAL = ('공동대표이사 중 1인이 다른 공동대표이사와 공동으로 하지 아니하고 단독으로 회사를 대표하여 제3자와 한 '
              '거래는 회사가 이를 추인하지 않는 한 무효이고, 표현대표이사 규정의 유추적용 여부는 별도로 따진다.')
B_STD = [{'n': '', 'text': '보험약관의 뜻이 명백하지 아니한 경우에는 작성자 불이익의 원칙에 따라 고객에게 유리하게 해석하여야 한다는 '
                         '약관규제법 제5조 제2항은 개별 약정에 우선한다.'}]
I_OFFICIAL = ('[1] 주식회사의 이사회는 대표이사의 업무집행을 감독하는 기관이다. '
              '[2] 회사의 대표이사가 이사회 결의 없이 거래한 경우 상대방이 이를 알았거나 알 수 있었을 때에만 무효이다. '
              '[3] 이사회 결의가 필요한 중요한 자산의 처분인지는 회사의 규모와 영업 내용 등을 종합하여 판단한다. '
              '[4] 대표권 제한은 선의의 제3자에게 대항하지 못한다.')
I_STD = [{'n': '[2]', 'text': '회사의 대표이사가 이사회 결의 없이 거래한 경우 상대방이 이를 알았거나 알 수 있었을 경우에만 무효이다.'}]


def build_fixture(root):
    data = os.path.join(root, 'data')
    folder = os.path.join(data, 'standard-cases', '상법')
    fdir = os.path.join(data, 'fetched')
    os.makedirs(folder)
    os.makedirs(fdir)
    reg = {'cases': [
        reg_case('std-commercial-01', '2022다200249', '2022-05-26'),                 # A ok (전부 부분 문자열)
        reg_case('std-commercial-02', '2015다45451', '2021-02-18', enBanc=True),     # B low-similarity
        reg_case('std-commercial-03', '2017다256828', '2018-07-24'),                 # C meta-mismatch (후보 선고일 다름)
        reg_case('std-commercial-04', '2019다1111', '2020-01-01'),                   # D meta-mismatch (공식 인용 선고일 다름)
        reg_case('std-commercial-05', '2018다2222', '2019-03-14'),                   # F missing (미수집)
        reg_case('std-commercial-06', '2016다3333', '2017-06-08'),                   # I ok (일부 항목·작은 차이)
        reg_case('std-commercial-07', '2014다5555', '2015-02-12'),                   # J ok (쟁점 → issues, 비교 생략)
        reg_case('enbanc-2013da7777', '2013다7777', '2014-01-02', group='enbanc', subject='commercial', enBanc=True),  # K alias
    ], 'identityAliases': {'sc-2013da7777-20140101-judgment': 'sc-2013da7777-20140102-judgment'}}
    with open(os.path.join(data, 'registry.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    files = [
        fetched('std-commercial-01', '2022다200249', '[대법원 2022. 5. 26. 선고 2022다200249 판결]', A_OFFICIAL,
                '의사가 의료기관에 대하여 갖는 급여 채권이 상사채권에 해당하는지 여부(소극)'),
        fetched('std-commercial-02', '2015다45451', '[대법원 2021. 2. 18. 선고 2015다45451 전원합의체 판결]', B_OFFICIAL),
        fetched('std-commercial-03', '2017다256828', '[대법원 2018. 7. 24. 선고 2017다256828 판결]', '약관은 고객에게 유리하게 해석한다.'),
        fetched('std-commercial-04', '2019다1111', '[대법원 2020. 1. 2. 선고 2019다1111 판결]', '상호를 속용하는 영업양수인은 양도인의 영업채무를 변제할 책임이 있다.'),
        fetched('std-commercial-06', '2016다3333', '[대법원 2017. 6. 8. 선고 2016다3333 판결]', I_OFFICIAL),
        fetched('std-commercial-07', '2014다5555', '[대법원 2015. 2. 12. 선고 2014다5555 판결]', '익명조합원은 영업자의 행위에 관하여 제3자에게 권리의무가 없다.',
                '익명조합원이 제3자에 대하여 책임을 지는지 여부(소극)'),
        fetched('enbanc-2013da7777', '2013다7777', '[대법원 2014. 1. 2. 선고 2013다7777 전원합의체 판결]', '주주총회 결의 하자의 소는 형성의 소이다.'),
    ]
    for fx in files:
        with open(os.path.join(fdir, fx['id'] + '.json'), 'w', encoding='utf-8', newline='\n') as f:
            json.dump(fx, f, ensure_ascii=False, indent=1)
    with open(os.path.join(fdir, 'std-commercial-05.missing.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'id': 'std-commercial-05', 'reason': '사건번호 불일치 또는 미게재', 'triedUrls': []}, f, ensure_ascii=False)
    candidates = [
        cand(1, '2022다200249', '2022-05-26', source(A_STD, [{'n': '', 'text': '의사가 의료기관에 대하여 갖는 급여 채권이 상사채권에 해당하는지 여부(소극)'}])),
        cand(2, '2015다45451', '2021-02-18', source(B_STD), enBanc=True),
        cand(3, '2017다256828', '2018-07-25', source([{'n': '', 'text': '약관은 고객에게 유리하게 해석한다.'}])),
        cand(4, '2019다1111', '2020-01-01', source([{'n': '', 'text': '상호를 속용하는 영업양수인은 양도인의 영업채무를 변제할 책임이 있다.'}])),
        cand(5, '2023다9999', '2024-04-04', source([{'n': '', 'text': '아직 등록되지 않은 재판의 요지.'}])),
        cand(6, '2018다2222', '2019-03-14', source([{'n': '', 'text': '등록됐으나 수집되지 않은 재판의 요지.'}])),
        cand(7, '2012다8888', '2013-01-01', None),                          # standardSource 없음 → 비교 대상 아님
        cand(8, '2016다3333', '2017-06-08', source(I_STD)),
        cand(9, '2014다5555', '2015-02-12', source(None, [{'n': '', 'text': '익명조합에서 영업자가 파산한 경우 출자금 반환청구권의 성질'}])),
        cand(10, '2013다7777', '2014-01-01', source([{'n': '', 'text': '주주총회 결의 하자의 소는 형성의 소이다.'}]), enBanc=True),
    ]
    for c in candidates:
        ci.validate_standard_source(c.get('standardSource'))   # fixture 도 등록 가능한 형식이어야 한다
    with open(os.path.join(folder, 'candidates-commercial.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'source': PDF, 'subject': 'commercial', 'group': 'standard', 'generatedAt': '2026-10-24T00:00:00+09:00',
                   'candidates': candidates}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(folder, 'entries.jsonl'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'seq': 9, 'no': 9, 'chunk': 'c001', 'sections': {'판시사항': '(없음)', '쟁점': '익명조합에서 영업자가 파산한 경우 출자금 반환청구권의 성질'}},
                           ensure_ascii=False) + '\n')
    return folder


class NormalizeTests(unittest.TestCase):
    def test_contract_rules(self):
        self.assertEqual(cc.base_normalize('【판결 요지】\n가ㅤ나 다ﾠ라 〈참조〉 「법」 １２３ – ４'), '[판결요지]가나다라참조법123-4')
        self.assertEqual(cc.base_normalize('〖1〗 A‐B—C'), '[1]A-B-C')

    def test_crosscheck_folds_dots_and_quotes(self):
        self.assertEqual(cc.normalize('총칙ㆍ상행위'), cc.normalize('총칙 · 상행위'))
        self.assertEqual(cc.normalize('‘교원’ “노조”'), cc.normalize("'교원'\"노조\""))

    def test_heading_key(self):
        self.assertEqual(cc.heading_key('【판결요지】'), '판결요지')
        self.assertEqual(cc.heading_key('[판결 요지]'), '판결요지')
        self.assertEqual(cc.heading_key('【주　　문】'), '주문')


class CitationTests(unittest.TestCase):
    def test_supreme_court(self):
        p = cc.parse_citation('[대법원 2021. 2. 18. 선고 2015다45451 전원합의체 판결]')
        self.assertEqual((p['court'], p['date'], p['caseNumbers'], p['decisionType'], p['enBanc']),
                         ('대법원', '2021-02-18', ['2015다45451'], '판결', True))

    def test_constitutional_court_and_ruling(self):
        p = cc.parse_citation('[전원재판부 2020헌마1134, 2026. 7. 23.]')
        self.assertEqual((p['court'], p['date'], p['decisionType'], p['enBanc']), ('헌법재판소', '2026-07-23', '결정', False))
        q = cc.parse_citation('[대법원 2019. 1. 31.자 2018마123 결정]')
        self.assertEqual((q['court'], q['decisionType']), ('대법원', '결정'))

    def test_unknown_court_is_not_guessed(self):
        p = cc.parse_citation('[서울고법 2019. 1. 9. 선고 2018나2040155 판결]')
        self.assertIsNone(p['court'])
        self.assertEqual(p['courtRaw'], '서울고법')


class WindowTests(unittest.TestCase):
    def test_subset_holding_uses_numbered_window(self):
        r = cc.compare_text(I_STD, I_OFFICIAL)
        self.assertEqual(r['window'], '[2]')
        self.assertFalse(r['contained'])
        self.assertGreater(r['ratio'], 0.9)
        whole = cc.difflib.SequenceMatcher(None, cc.joined_items(I_STD)[0], cc.normalize(I_OFFICIAL), autojunk=False).ratio()
        self.assertLess(whole, 0.6)   # 전체와만 비교했다면 오탐이 났을 것

    def test_full_containment(self):
        r = cc.compare_text(A_STD, A_OFFICIAL)
        self.assertTrue(r['contained'])
        self.assertEqual(r['itemsContained'], '2/2')
        self.assertTrue(r['digitsOk'])

    def test_no_text(self):
        self.assertIsNone(cc.compare_text(A_STD, ''))
        self.assertIsNone(cc.compare_text([], A_OFFICIAL))


class CrosscheckRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        cls.folder = build_fixture(cls.root)
        cls.reg_path = os.path.join(cls.root, 'data', 'registry.json')
        with open(cls.reg_path, 'rb') as f:
            cls.reg_bytes = f.read()
        cls.out = os.path.join(cls.folder, '_crosscheck.json')
        cls.result = cc.run('상법', os.path.join(cls.folder, 'candidates-commercial.json'), cls.reg_path,
                            os.path.join(cls.root, 'data', 'fetched'), cls.out, 0.6, cls.folder, cls.root)
        cls.by_seq = {it['seq']: it for it in cls.result['items']}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ok(self):
        a = self.by_seq[1]
        self.assertEqual(a['flag'], 'ok', a['reasons'])
        self.assertEqual((a['registryId'], a['fetched'], a['matchedBy']), ('std-commercial-01', True, 'decisionId'))
        self.assertEqual(a['decisionId'], 'sc-2022da200249-20220526-judgment')
        self.assertTrue(a['holdingsContained'])
        self.assertEqual(a['holdingsRatio'], 1.0)
        self.assertEqual(a['issuesRatio'], 1.0)
        self.assertTrue(a['metaMatch']['ok'])
        self.assertEqual(a['metaMatch']['date']['official'], '2022-05-26')
        i = self.by_seq[8]
        self.assertEqual((i['flag'], i['holdingsWindow']), ('ok', '[2]'), i['reasons'])

    def test_low_similarity(self):
        b = self.by_seq[2]
        self.assertEqual(b['flag'], 'low-similarity', b['reasons'])
        self.assertLess(b['holdingsRatio'], 0.6)
        self.assertFalse(b['holdingsContained'])
        self.assertTrue(b['metaMatch']['ok'])          # 메타는 맞고 본문만 다르다
        self.assertTrue(b['metaMatch']['enBanc']['ok'])

    def test_meta_mismatch_candidate_date(self):
        c = self.by_seq[3]
        self.assertEqual(c['flag'], 'meta-mismatch', c['reasons'])
        self.assertEqual((c['matchedBy'], c['registryId']), ('caseNumber', 'std-commercial-03'))
        self.assertFalse(c['metaMatch']['date']['ok'])
        self.assertTrue(any('decisionId 불일치' in r for r in c['reasons']))
        self.assertEqual(c['holdingsRatio'], 1.0)      # 본문은 같아도 메타 불일치가 우선

    def test_meta_mismatch_official_citation(self):
        d = self.by_seq[4]
        self.assertEqual(d['flag'], 'meta-mismatch', d['reasons'])
        self.assertEqual(d['matchedBy'], 'decisionId')
        self.assertEqual((d['metaMatch']['date']['registry'], d['metaMatch']['date']['official']), ('2020-01-01', '2020-01-02'))

    def test_meta_mismatch_via_alias(self):
        k = self.by_seq[10]
        self.assertEqual((k['matchedBy'], k['registryId'], k['flag']), ('alias', 'enbanc-2013da7777', 'meta-mismatch'))

    def test_missing(self):
        e = self.by_seq[5]
        self.assertEqual((e['flag'], e['registryId'], e['fetched'], e['metaMatch']), ('missing', None, False, None))
        f = self.by_seq[6]
        self.assertEqual((f['flag'], f['registryId'], f['fetched']), ('missing', 'std-commercial-05', False))
        self.assertTrue(any('미수집' in r and '미게재' in r for r in f['reasons']), f['reasons'])
        self.assertTrue(f['metaMatch']['ok'])          # 등록부와는 대조된다

    def test_issues_from_dispute_not_flagged(self):
        j = self.by_seq[9]
        self.assertEqual((j['flag'], j['issuesFrom'], j['textCompared']), ('ok', '쟁점', False), j['reasons'])
        self.assertIsNotNone(j['issuesRatio'])

    def test_totals_and_file(self):
        t = self.result['totals']
        self.assertEqual((t['candidates'], t['withStandardSource']), (10, 9))
        self.assertEqual((t['ok'], t['low-similarity'], t['meta-mismatch'], t['missing']), (3, 1, 3, 2))
        self.assertNotIn(7, self.by_seq)
        with open(self.out, 'rb') as f:
            raw = f.read()
        self.assertNotIn(b'\r\n', raw)
        saved = json.loads(raw.decode('utf-8'))
        self.assertEqual(saved['totals'], t)
        self.assertEqual(saved['threshold'], 0.6)
        for it in saved['items']:
            self.assertIn(it['flag'], cc.FLAGS)
            for key in ('seq', 'no', 'decisionId', 'registryId', 'fetched', 'holdingsRatio', 'holdingsContained', 'issuesRatio', 'metaMatch', 'flag'):
                self.assertIn(key, it)

    def test_inputs_untouched(self):
        with open(self.reg_path, 'rb') as f:
            self.assertEqual(f.read(), self.reg_bytes)

    def test_threshold_changes_flag(self):
        out = os.path.join(self.root, 'strict.json')
        strict = cc.run('commercial', os.path.join(self.folder, 'candidates-commercial.json'), self.reg_path,
                        os.path.join(self.root, 'data', 'fetched'), out, 0.99, self.folder, self.root)
        by = {it['seq']: it for it in strict['items']}
        self.assertEqual(by[8]['flag'], 'low-similarity')   # 작은 차이도 엄격 기준에서는 걸린다
        self.assertEqual(by[1]['flag'], 'ok')               # 부분 문자열이면 기준과 무관하게 ok


class CliTests(unittest.TestCase):
    def test_cli_writes_report_and_summary(self):
        with tempfile.TemporaryDirectory() as root:
            folder = build_fixture(root)
            run = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(HERE, 'crosscheck.py'), '--subject', '상법', '--root', root],
                                 capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('ok 3 · low-similarity 1 · meta-mismatch 3 · missing 2', run.stdout)
            self.assertIn('low-similarity 하위 1건', run.stdout)
            self.assertIn('2015다45451', run.stdout)
            self.assertTrue(os.path.isfile(os.path.join(folder, '_crosscheck.json')))

    def test_cli_missing_candidates_is_error(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, 'data'))
            with open(os.path.join(root, 'data', 'registry.json'), 'w', encoding='utf-8') as f:
                f.write('{"cases": []}')
            run = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(HERE, 'crosscheck.py'), '--subject', 'commercial', '--root', root],
                                 capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(run.returncode, 2)
            self.assertIn('후보 파일', run.stderr)

    def test_cli_rejects_non_standard_subject(self):
        run = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(HERE, 'crosscheck.py'), '--subject', 'ip'],
                             capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.returncode, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
