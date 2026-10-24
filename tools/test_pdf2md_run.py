"""tools/pdf2md_run.py 시험 — 임시 폴더의 합성 청크 2개로 mock·manual 흐름, 건너뜀(--force 없는 재실행), 실패 시 미기록,
재시도, 네트워크 제공자의 SDK 없음 안내를 확인한다. 네트워크·API 키를 쓰지 않으며 실제 data/ 는 건드리지 않는다.
(anthropic 경로는 가짜 SDK 모듈로 호출 모양·배치 상태 흐름만 확인한다.)

  python -X utf8 tools/test_pdf2md_run.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdf2md_run as run  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pdf2md_run.py')
PROMPT = '# 시험용 지시문\n항목마다 H2 블록 하나를 쓴다.\n'

# 합성 청크(실제 PDF 문장 아님). 쪽 머리글·쪽 번호·본문 속 번호 줄·장 머리글·기대 범위 밖 항목을 일부러 넣었다.
CHUNK1 = """현재 위치: 총칙·상행위 › 제1편 총칙 › 제2장 상인
기대 항목: 1 ~ 3

----- PDF p.11 -----
제1편 제2장 상 인
1. 시험용 첫째 항목
(대법원 2022. 5. 26. 선고 2022다200249 판결)
〈쟁점〉
시험용 쟁점 문장이다.
〈판결요지〉
2. 사건개요
(1) 이 줄은 본문이며 2021. 3. 4. 날짜가 있지만 항목 머리가 아니다.
2021. 3. 4. 선고된 판결(대법원 2020다1 판결 참조)을 인용한 본문 줄이다.
시험용 요지 문장이 다음 쪽으로
----- PDF p.12 -----
변호사시험의 자격시험을 위한 상법표준판례연구
이어진다.
〈선정이유〉
시험용 선정이유.
7
제 3 장 상업사용인
2. 시험용 병합사건 항목
(대법원 1999. 3. 9. 선고 97다7721, 7738 판결)
〈판결요지〉
시험용 요지.
3. 시험용 전원합의체 항목 (대법원 2020. 1. 2. 선고 2019다12345 전원합의체 판결)
〈판결요지〉
시험용 요지.
----- PDF p.13 -----
제1편 제3장 상업사용인
요지가 이 쪽까지 이어진다.
4. 다음 청크의 항목
(헌재 2014. 12. 19. 2013헌다1)
〈결정요지〉
잘린 부분.
"""

CHUNK2 = """현재 위치: 총칙·상행위 › 제1편 총칙 › 제3장 상업사용인
기대 항목: 4 ~ 5  (앞 청크에서 이어진 항목: 3)

----- PDF p.13 -----
제1편 제3장 상업사용인
요지가 이 쪽까지 이어진다.
4. 헌법재판소 시험 항목
(헌재 2014. 12. 19. 2013헌다1)
〈결정요지〉
시험용 결정요지.
----- PDF p.14 -----
변호사시험의 자격시험을 위한 상법표준판례연구
Ⅰ. 시험용 절
5. 결정 표기 시험
(대법원 2010. 7. 22.자 2010마123 결정; 서울고등법원 2009. 1. 2. 선고 2008나1234 판결)
〈판결요지〉
시험용.
"""


def blocks(md):
    """md → {머리줄: 블록 본문}."""
    out = {}
    for part in re.split(r'(?m)^(?=## )', md):
        if part.startswith('## '):
            head, _, body = part.partition('\n')
            out[head] = body
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sdir = os.path.join(self.tmp.name, '상법')
        os.makedirs(os.path.join(self.sdir, 'chunks'))
        for name, text in (('c001_p0011-p0013.txt', CHUNK1), ('c002_p0013-p0014.txt', CHUNK2)):
            with open(os.path.join(self.sdir, 'chunks', name), 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
        self.prompt = os.path.join(self.tmp.name, 'prompt.md')
        with open(self.prompt, 'w', encoding='utf-8', newline='\n') as f:
            f.write(PROMPT)

    def main(self, *extra):
        """pdf2md_run.main(...) → (종료코드, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run.main(['--subject', '상법', '--dir', self.sdir, '--prompt', self.prompt, '--concurrency', '2', *extra])
        return code, out.getvalue(), err.getvalue()

    def md(self, cid):
        return os.path.join(self.sdir, 'md', f'{cid}.md')

    def read(self, path):
        with open(path, 'rb') as f:
            return f.read().decode('utf-8')

    def log_lines(self):
        return self.read(os.path.join(self.sdir, '_run.log')).splitlines()


class MockProviderTests(Base):
    def test_mock_writes_markdown_per_chunk(self):
        code, out, _ = self.main('--provider', 'mock')
        self.assertEqual(code, 0, out)
        self.assertIn('성공 2 · 건너뜀 0 · 실패 0', out)
        self.assertEqual(sorted(os.listdir(os.path.join(self.sdir, 'md'))), ['c001.md', 'c002.md'])
        with open(self.md('c001'), 'rb') as f:
            raw = f.read()
        self.assertNotIn(b'\r\n', raw)
        self.assertTrue(raw.endswith(b'\n'))
        b1 = blocks(raw.decode('utf-8'))
        self.assertEqual(list(b1), ['## 1. 시험용 첫째 항목', '## 2. 시험용 병합사건 항목', '## 3. 시험용 전원합의체 항목'])   # 4 는 기대 범위 밖
        first = b1['## 1. 시험용 첫째 항목']
        self.assertIn('- 출처: 대법원 2022. 5. 26. 선고 2022다200249 판결\n', first)
        self.assertIn('- 사건: 2022다200249 | 2022-05-26 | 대법원 | 판결 | 전원합의체 아니오\n', first)
        self.assertIn('- 위치: 총칙·상행위 > 제1편 총칙 > 제2장 상인 > (절 없음)\n', first)
        self.assertIn('- 쪽: 11-12\n', first)
        for sec in ('주제', '쟁점', '판시사항', '판결요지', '참조조문', '선정이유'):
            self.assertIn(f'### {sec}\n(없음)\n', first)
        self.assertIn('### 검토메모\n- (없음)', first)
        merged = b1['## 2. 시험용 병합사건 항목']
        self.assertIn('- 사건: 97다7721·7738 | 1999-03-09 | 대법원 | 판결 | 전원합의체 아니오\n', merged)
        self.assertIn('- 위치: 총칙·상행위 > 제1편 총칙 > 제3장 상업사용인 > (절 없음)\n', merged)
        self.assertIn('- 쪽: 12\n', merged)
        enbanc = b1['## 3. 시험용 전원합의체 항목']
        self.assertIn('- 사건: 2019다12345 | 2020-01-02 | 대법원 | 판결 | 전원합의체 예\n', enbanc)
        self.assertIn('- 쪽: 12-13\n', enbanc)

        b2 = blocks(self.read(self.md('c002')))
        self.assertEqual(list(b2), ['## (이어짐) 3. (제목 앞 청크)', '## 4. 헌법재판소 시험 항목', '## 5. 결정 표기 시험'])
        tail = b2['## (이어짐) 3. (제목 앞 청크)']
        self.assertNotIn('- 출처:', tail)
        self.assertNotIn('- 사건:', tail)
        self.assertIn('- 쪽: 13\n', tail)
        self.assertIn('- 사건: 2013헌다1 | 2014-12-19 | 헌법재판소 | 결정 | 전원합의체 아니오\n', b2['## 4. 헌법재판소 시험 항목'])
        two = b2['## 5. 결정 표기 시험']
        self.assertEqual(re.findall(r'(?m)^- 사건: (.*)$', two),
                         ['2010마123 | 2010-07-22 | 대법원 | 결정 | 전원합의체 아니오',
                          '2008나1234 | 2009-01-02 | 서울고등법원 | 판결 | 전원합의체 아니오'])
        self.assertIn('- 위치: 총칙·상행위 > 제1편 총칙 > 제3장 상업사용인 > Ⅰ. 시험용 절\n', two)

        log = self.log_lines()
        self.assertTrue(any('\trun-start\t' in l and 'provider=mock' in l for l in log))
        oks = [l for l in log if '\tok\t' in l]
        self.assertEqual(sorted(l.split('\t')[1] for l in oks), ['c001', 'c002'])
        self.assertTrue(all('model=mock' in l and 'sec=' in l and 'blocks=' in l for l in oks))
        self.assertTrue(any('\trun-end\t' in l and 'ok=2' in l for l in log))
        self.assertFalse(any('effort=' in l for l in log))   # mock 은 effort 를 기록하지 않는다

    def test_mock_head_layouts_seen_in_real_pdf_text(self):
        """pdfplumber 추출에서 실제로 보이는 머리 모양: 두 줄 제목이 '앞부분 / N. / 뒷부분' 으로 갈림, 부제 괄호, 점 누락,
        1960년 이전 사건번호, 인용 안의 '(병합)' 괄호, 사건번호가 빠진 인용."""
        text = '\n'.join([
            '현재 위치: 회사 › 제2편 주식회사', '기대 항목: 10 ~ 15', '', '----- PDF p.21 -----',
            '앞 항목 본문이 끝났다.',
            '상법 제23조에 규정된 상호에',
            '10.',
            '해당하는지의 판단 기준',
            '(대법원 2016. 1. 28. 선고 2013다76635 판결)',
            '〈쟁점〉', '본문.',
            '11.',
            '(간접거래, 겸임이사)',
            '(대법원 2014. 6. 26. 선고 2012다73530 판결)',
            '본문.',
            '12 회사의 심사의무',
            '(대법원 2019. 8. 14. 선고 2017다231980 판결)',
            '13. 보증의 상행위',
            '(대법원 1959. 8. 27. 선고 4291민상407 판결)',
            '14. 2차영업양도와 경업금지',
            '(대법원 2019. 9. 10. 선고 2015다30886, 2015다30893(병합) 판결)',
            '15. 금융리스',
            '(대법원 2013. 7. 12. 선고 판결)',
            '본문.', ''])
        b = blocks(run.mock_markdown(text))
        self.assertEqual(list(b), ['## 10. 상법 제23조에 규정된 상호에 해당하는지의 판단 기준', '## 11. (간접거래, 겸임이사)',
                                   '## 12. 회사의 심사의무', '## 13. 보증의 상행위', '## 14. 2차영업양도와 경업금지', '## 15. 금융리스'])
        self.assertIn('- 사건: 4291민상407 | 1959-08-27 | 대법원 | 판결 |', b['## 13. 보증의 상행위'])
        merged = b['## 14. 2차영업양도와 경업금지']
        self.assertIn('- 출처: 대법원 2019. 9. 10. 선고 2015다30886, 2015다30893(병합) 판결\n', merged)
        self.assertIn('- 사건: 2015다30886 | 2019-09-10 | 대법원 | 판결 |', merged)
        self.assertIn('- 사건: (사건번호 없음) | 2013-07-12 | 대법원 | 판결 |', b['## 15. 금융리스'])
        self.assertIn('- 위치: 회사 > 제2편 주식회사 > (절 없음)\n', b['## 12. 회사의 심사의무'])

    def test_rerun_without_force_skips_and_force_rewrites(self):
        self.assertEqual(self.main('--provider', 'mock')[0], 0)
        with open(self.md('c001'), 'w', encoding='utf-8', newline='\n') as f:
            f.write('## 손으로 고친 표시\n')
        code, out, _ = self.main('--provider', 'mock')
        self.assertEqual(code, 0)
        self.assertIn('성공 0 · 건너뜀 2 · 실패 0', out)
        self.assertEqual(self.read(self.md('c001')), '## 손으로 고친 표시\n')
        self.assertEqual(sum('\tskip\t' in l for l in self.log_lines()), 2)
        # --only 로 고른 청크만 --force 로 다시 만든다
        code, out, _ = self.main('--provider', 'mock', '--only', '2', '--force')
        self.assertEqual(code, 0)
        self.assertIn('성공 1 · 건너뜀 0 · 실패 0', out)
        self.assertEqual(self.read(self.md('c001')), '## 손으로 고친 표시\n')
        code, out, _ = self.main('--provider', 'mock', '--only', 'c001', '--force')
        self.assertIn('## 1. 시험용 첫째 항목', self.read(self.md('c001')))

    def test_cli_entrypoint(self):
        p = subprocess.run([sys.executable, '-X', 'utf8', SCRIPT, '--subject', 'commercial', '--provider', 'mock', '--dir', self.sdir,
                            '--prompt', self.prompt, '--only', 'c001'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('[c001] 성공', p.stdout)
        self.assertTrue(os.path.exists(self.md('c001')))
        self.assertFalse(os.path.exists(self.md('c002')))

    def test_setup_errors(self):
        code, _, err = self.main('--provider', 'mock', '--only', 'c009')
        self.assertEqual(code, 2)
        self.assertIn('없는 청크: c009', err)
        code, _, err = self.main('--provider', 'mock', '--batch')
        self.assertEqual(code, 2)
        self.assertIn('--batch 는 --provider anthropic', err)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = run.main(['--subject', '지식재산권법', '--provider', 'mock', '--dir', self.sdir, '--prompt', self.prompt])
        self.assertEqual(code, 2)
        self.assertIn('표준판례 과목이 아닙니다', err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(self.sdir, 'md')))


class ManualProviderTests(Base):
    def test_manual_writes_prompts_only_and_skips_on_rerun(self):
        code, out, _ = self.main('--provider', 'manual')
        self.assertEqual(code, 0, out)
        pdir = os.path.join(self.sdir, 'md', '_prompts')
        self.assertEqual(sorted(os.listdir(pdir)), ['c001.txt', 'c002.txt'])
        self.assertEqual(sorted(os.listdir(os.path.join(self.sdir, 'md'))), ['_prompts'])   # md 는 쓰지 않는다
        text = self.read(os.path.join(pdir, 'c001.txt'))
        self.assertEqual(text, f'=== SYSTEM ===\n{PROMPT.rstrip()}\n=== USER ===\n{CHUNK1.rstrip()}\n')
        self.assertEqual(sum('\tprompt\t' in l for l in self.log_lines()), 2)

        with open(os.path.join(pdir, 'c001.txt'), 'w', encoding='utf-8', newline='\n') as f:
            f.write('표시')
        code, out, _ = self.main('--provider', 'manual')
        self.assertIn('성공 0 · 건너뜀 2 · 실패 0', out)
        self.assertEqual(self.read(os.path.join(pdir, 'c001.txt')), '표시')
        code, out, _ = self.main('--provider', 'manual', '--force')
        self.assertIn('성공 2', out)
        self.assertTrue(self.read(os.path.join(pdir, 'c001.txt')).startswith('=== SYSTEM ===\n'))

    def test_manual_skips_chunk_whose_md_exists(self):
        os.makedirs(os.path.join(self.sdir, 'md'))
        with open(self.md('c002'), 'w', encoding='utf-8') as f:
            f.write('## 2. 이미 전사됨\n')
        code, out, _ = self.main('--provider', 'manual')
        self.assertIn('성공 1 · 건너뜀 1', out)
        self.assertFalse(os.path.exists(os.path.join(self.sdir, 'md', '_prompts', 'c002.txt')))


class NetworkProviderImportTests(Base):
    def test_anthropic_missing_sdk_message(self):
        with patch.dict(sys.modules, {'anthropic': None}):     # 설치되어 있어도 import 가 실패하게 한다
            code, _, err = self.main('--provider', 'anthropic')
        self.assertEqual(code, 2)
        self.assertIn('anthropic SDK 가 설치되어 있지 않습니다', err)
        self.assertIn('pip install anthropic', err)
        self.assertFalse(os.path.exists(os.path.join(self.sdir, 'md')))

    def test_openai_missing_sdk_message(self):
        with patch.dict(sys.modules, {'openai': None}):
            code, _, err = self.main('--provider', 'openai', '--model', 'gpt-test')
        self.assertEqual(code, 2)
        self.assertIn('pip install openai', err)


class CheckAndRetryTests(Base):
    def test_check_markdown(self):
        self.assertEqual(run.check_markdown('')[2], '빈 응답')
        self.assertEqual(run.check_markdown('  \n\n')[2], '빈 응답')
        self.assertEqual(run.check_markdown('### 주제\n(없음)\n')[2], "'## ' 블록 0개")
        body, n, why = run.check_markdown('```markdown\n## 1. 가\n- 쪽: 3\n\n## 2. 나\n```\n')
        self.assertEqual((body, n, why), ('## 1. 가\n- 쪽: 3\n\n## 2. 나\n', 2, ''))
        body, n, why = run.check_markdown('## 1. 가\r\n본문')
        self.assertEqual((body, n, why), ('## 1. 가\n본문\n', 1, ''))

    def ctx(self):
        os.makedirs(os.path.join(self.sdir, 'md'), exist_ok=True)
        return run.Ctx(self.sdir, 'anthropic', 'claude-sonnet-5-5', 'medium', PROMPT, run.RunLog(os.path.join(self.sdir, '_run.log')), False)

    def test_finalize_rejects_bad_responses_without_writing(self):
        ctx = self.ctx()
        cases = [run.Response('', 'end_turn'), run.Response('본문만 있음', 'end_turn'),
                 run.Response('## 1. 가\n잘린', 'max_tokens'), run.Response('## 1. 가', 'refusal', note='category=cyber')]
        for resp in cases:
            status, why = run.finalize(ctx, 'c001', resp, force=False)
            self.assertEqual(status, 'failed', why)
        self.assertFalse(os.path.exists(self.md('c001')))
        fails = [l for l in self.log_lines() if '\tfail\t' in l]
        self.assertEqual(len(fails), 4)
        self.assertIn('잘림', fails[2])
        self.assertIn('거절', fails[3])
        status, _ = run.finalize(ctx, 'c001', run.Response('## 1. 가\n', 'end_turn', usage={'in': 10, 'out': 5}), force=False)
        self.assertEqual(status, 'ok')
        last = self.log_lines()[-1]
        self.assertIn('in=10', last)
        self.assertIn('out=5', last)
        self.assertIn('effort=medium', last)

    def test_retry_policy(self):
        class Err(Exception):
            def __init__(self, status):
                super().__init__(f'status {status}')
                self.status_code = status
                self.response = SimpleNamespace(status_code=status, headers={})

        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise Err(529 if len(calls) == 1 else 429)
            return 'ok'

        with patch.object(run.time, 'sleep') as sleep:
            self.assertEqual(run.with_retry(flaky), 'ok')
            self.assertEqual(len(calls), 3)
            self.assertEqual(sleep.call_count, 2)
            with self.assertRaises(Err):        # 400 은 다시 시도하지 않는다
                run.with_retry(lambda: (_ for _ in ()).throw(Err(400)))
            self.assertEqual(sleep.call_count, 2)
            always = []
            with self.assertRaises(Err):        # 3회 재시도 후 포기(총 4번 호출)
                run.with_retry(lambda: always.append(1) or (_ for _ in ()).throw(Err(503)))
            self.assertEqual(len(always), 4)
        self.assertTrue(run.is_fatal(Err(401)))
        self.assertFalse(run.is_fatal(Err(400)))
        self.assertTrue(run.is_fatal(TypeError('자격증명 없음')))


def fake_message(text, stop='end_turn'):
    return SimpleNamespace(content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=text)],
                           stop_reason=stop, model='claude-sonnet-5-5', stop_details=None,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=0, cache_creation_input_tokens=90))


class FakeAnthropic:
    """anthropic SDK 의 쓰는 부분만 흉내 낸다(네트워크 없음). 응답 본문은 mock 생성기로 만든다."""
    instances = []

    def __init__(self, **kw):
        self.kw = kw
        self.stream_calls, self.batch_requests = [], []
        self.batch_status = 'in_progress'
        self.batch_fail = set()
        self.messages = SimpleNamespace(stream=self._stream, batches=SimpleNamespace(create=self._create, retrieve=self._retrieve, results=self._results))
        FakeAnthropic.instances.append(self)

    def _stream(self, **params):
        self.stream_calls.append(params)
        msg = fake_message(run.mock_markdown(params['messages'][0]['content']))

        class S:
            def __enter__(s):
                return s

            def __exit__(s, *a):
                return False

            def get_final_message(s):
                return msg
        return S()

    def _create(self, requests):
        self.batch_requests.append(requests)
        return SimpleNamespace(id=f'msgbatch_{len(self.batch_requests)}', processing_status='in_progress')

    def _retrieve(self, batch_id):
        return SimpleNamespace(processing_status=self.batch_status, request_counts=SimpleNamespace(processing=0, succeeded=2, errored=0, canceled=0, expired=0))

    def _results(self, batch_id):
        reqs = self.batch_requests[int(batch_id.split('_')[1]) - 1]
        for r in reqs:
            cid = r['custom_id']
            if cid in self.batch_fail:
                yield SimpleNamespace(custom_id=cid, result=SimpleNamespace(type='errored', error=SimpleNamespace(error=SimpleNamespace(type='api_error', message='시험'))))
            else:
                yield SimpleNamespace(custom_id=cid, result=SimpleNamespace(type='succeeded', message=fake_message(run.mock_markdown(r['params']['messages'][0]['content']))))


class FakeAnthropicTests(Base):
    def setUp(self):
        super().setUp()
        FakeAnthropic.instances = []
        self.fake = types.ModuleType('anthropic')
        self.fake.Anthropic = FakeAnthropic
        p = patch.dict(sys.modules, {'anthropic': self.fake})
        p.start()
        self.addCleanup(p.stop)

    def test_streaming_request_shape(self):
        code, out, _ = self.main('--provider', 'anthropic', '--only', 'c001')
        self.assertEqual(code, 0, out)
        client = FakeAnthropic.instances[-1]
        self.assertEqual(client.kw, {'max_retries': 0})
        (params,) = client.stream_calls
        self.assertEqual(params['model'], 'claude-sonnet-5-5')
        self.assertEqual(params['max_tokens'], 32000)
        self.assertEqual(params['output_config'], {'effort': 'medium'})
        self.assertNotIn('thinking', params)
        self.assertEqual(params['system'][0]['text'], PROMPT)
        self.assertEqual(params['messages'], [{'role': 'user', 'content': CHUNK1}])
        self.assertIn('## 1. 시험용 첫째 항목', self.read(self.md('c001')))
        ok = [l for l in self.log_lines() if '\tok\t' in l][0]
        for kv in ('provider=anthropic', 'model=claude-sonnet-5-5', 'effort=medium', 'in=100', 'out=50', 'cacheWrite=90'):
            self.assertIn(kv, ok)
        self.assertIn('토큰 in=100 out=50', out)

    def test_truncated_stream_writes_nothing(self):
        def truncated(**params):
            class S:
                def __enter__(s):
                    return s

                def __exit__(s, *a):
                    return False

                def get_final_message(s):
                    return fake_message('## 1. 시험용\n잘린 본', stop='max_tokens')
            return S()
        with patch.object(FakeAnthropic, '_stream', lambda self, **p: truncated(**p)):
            code, out, _ = self.main('--provider', 'anthropic', '--only', 'c001')
        self.assertEqual(code, 1)
        self.assertIn('실패 1', out)
        self.assertFalse(os.path.exists(self.md('c001')))

    def test_batch_submit_poll_collect(self):
        code, out, _ = self.main('--provider', 'anthropic', '--batch')
        self.assertEqual(code, 0, out)
        state = json.loads(self.read(os.path.join(self.sdir, '_batch.json')))
        self.assertEqual([(b['id'], b['chunks'], b['status']) for b in state['batches']], [('msgbatch_1', ['c001', 'c002'], 'submitted')])
        req = FakeAnthropic.instances[-1].batch_requests[0][0]
        self.assertEqual(req['custom_id'], 'c001')
        self.assertEqual(req['params']['output_config'], {'effort': 'medium'})
        self.assertFalse(os.path.exists(self.md('c001')))

        # 아직 처리 중: 다시 제출하지 않는다
        with patch.object(FakeAnthropic, '_create', side_effect=AssertionError('재제출')):
            code, out, _ = self.main('--provider', 'anthropic', '--batch')
        self.assertEqual(code, 0)
        self.assertIn('대기 2', out)

        # 끝남: 결과를 거둬 md 를 쓴다(c002 는 오류 → 같은 실행에서는 다시 내지 않음)
        def ended_init(self, **kw):
            FakeAnthropic.__init__(self, **kw)
            self.batch_status = 'ended'
            self.batch_requests = [state_requests]
            self.batch_fail = {'c002'}
        state_requests = FakeAnthropic.instances[0].batch_requests[0]
        self.fake.Anthropic = type('Ended', (FakeAnthropic,), {'__init__': ended_init})
        code, out, _ = self.main('--provider', 'anthropic', '--batch')
        self.assertEqual(code, 1)
        self.assertIn('성공 1', out)
        self.assertIn('실패 1', out)
        self.assertIn('배치 제출 0', out)
        self.assertTrue(os.path.exists(self.md('c001')))
        self.assertFalse(os.path.exists(self.md('c002')))
        state = json.loads(self.read(os.path.join(self.sdir, '_batch.json')))
        b = state['batches'][0]
        self.assertEqual(b['status'], 'collected')
        self.assertEqual(b['results']['c001'], 'ok')
        self.assertTrue(b['results']['c002'].startswith('failed'))

        # 다음 실행: 실패한 c002 만 새 배치로 제출
        self.fake.Anthropic = FakeAnthropic
        code, out, _ = self.main('--provider', 'anthropic', '--batch')
        state = json.loads(self.read(os.path.join(self.sdir, '_batch.json')))
        self.assertEqual(state['batches'][-1]['chunks'], ['c002'])
        self.assertIn('건너뜀 1', out)


if __name__ == '__main__':
    unittest.main()
