#!/usr/bin/env python3
"""표준판례 청크 → Markdown 전사 실행기 (제공자 중립, spec/PIPELINE-pdf2md.md 단계 1).

  python -X utf8 tools/pdf2md_run.py --subject 상법 --provider anthropic [--model claude-sonnet-5-5] [--effort medium]
         [--only c007,c008] [--force] [--batch [--wait]] [--concurrency 4]
  --provider openai --model <모델id>   OpenAI(호환) Chat Completions. 키는 OPENAI_API_KEY
  --provider manual                    md/_prompts/cNNN.txt 에 보낼 메시지(=== SYSTEM === / === USER ===)만 써 둔다
  --provider mock                      네트워크 없이 흐름 시험용 최소 md 를 만든다(본문은 '(없음)')

입력  data/standard-cases/<과목>/chunks/cNNN_pAAAA-pBBBB.txt (tools/pdf_chunks.py 산출)
      시스템 지시문 tools/prompts/pdf2md.md (통째로, 모델·제공자 무관 단일 출처)
출력  <과목>/md/cNNN.md — 이미 있으면 --force 없이는 건너뛴다(재실행 안전). 응답이 비었거나 '## ' 블록이 0개이거나
      출력 한도에서 잘렸거나 거절되면 파일을 쓰지 않고 <과목>/_run.log 에 사유를 남긴다.
기록  <과목>/_run.log   1행 1사건(탭 구분): 시각 · 청크 · 사건(ok/skip/fail/retry/prompt/batch-…) · provider · model · effort
                       · 입력/출력/캐시 토큰(usage 가 있으면) · 소요시간 · 사유
      <과목>/_batch.json (--batch) 제출한 배치 id·청크·상태. 같은 명령에 --batch 를 붙여 다시 실행하면 끝난 배치를 거둬 md 를 쓴다.
종료코드  0 = 실패 없음, 1 = 실패한 청크가 있음, 2 = 설정 오류(SDK 없음·청크 없음·잘못된 인자)
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
from casenum import CASE_RE, DATE_RE, norm_date  # noqa: E402
from subjects import BY_ID, resolve_standard  # noqa: E402

PROVIDERS = ('anthropic', 'openai', 'manual', 'mock')
DEFAULT_MODELS = {'anthropic': 'claude-sonnet-5-5', 'manual': 'manual', 'mock': 'mock'}   # openai 는 --model 필수
DEFAULT_EFFORT = 'medium'
MAX_TOKENS = 32000
RETRIES = 3                 # 429·5xx·연결 오류: 지수 백오프로 3회까지 다시 시도
BATCH_POLL_SEC = 60         # --batch --wait 확인 간격
CHUNK_RE = re.compile(r'^(c\d{3,})_p(\d{4,})-p(\d{4,})\.txt$')
H2_RE = re.compile(r'^##[ \t]+\S', re.M)
FENCE_RE = re.compile(r'^\s*```[A-Za-z0-9_-]*[ \t]*\n(.*?)\n[ \t]*```\s*$', re.S)
TRUNCATED = {'max_tokens', 'length'}
REFUSED = {'refusal', 'content_filter'}
STATUS_LABEL = {'ok': '성공', 'skipped': '건너뜀', 'failed': '실패'}


class SetupError(Exception):
    """실행 전에 멈춰야 하는 설정 오류(SDK 없음·청크 없음·잘못된 인자). 종료코드 2."""


@dataclass
class Response:
    text: str
    stop: str = ''
    model: str = ''
    usage: dict = field(default_factory=dict)
    note: str = ''


# ---------------------------------------------------------------- 경로·입출력

def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def read_text(path):
    with open(path, encoding='utf-8-sig') as f:
        return f.read().replace('\r\n', '\n').replace('\r', '\n')


def write_text(path, text):
    """UTF-8·LF 로 원자적 쓰기(임시 파일 → os.replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp{os.getpid()}-{threading.get_ident()}'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def main_root():
    """worktree 안에서 실행하면 main 작업 폴더(공용 .git 의 부모)를 돌려준다. git 이 없으면 ROOT."""
    try:
        out = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        if out:
            common = out if os.path.isabs(out) else os.path.join(ROOT, out)
            return os.path.abspath(os.path.join(common, '..'))
    except (OSError, subprocess.SubprocessError):
        pass
    return ROOT


def find_prompt(arg):
    if arg:
        if not os.path.isfile(arg):
            raise SetupError(f'지시문 파일이 없습니다: {arg}')
        return os.path.abspath(arg)
    for base in dict.fromkeys((ROOT, main_root())):
        p = os.path.join(base, 'tools', 'prompts', 'pdf2md.md')
        if os.path.isfile(p):
            return p
    raise SetupError('지시문 tools/prompts/pdf2md.md 가 없습니다 (--prompt 로 지정할 수 있습니다)')


def rel(path, base):
    try:
        return os.path.relpath(path, base).replace('\\', '/')
    except ValueError:      # Windows: 드라이브가 다르면 상대 경로가 없다
        return path.replace('\\', '/')


def norm_chunk_id(s):
    s = s.strip().lower()
    m = re.fullmatch(r'c?(\d+)', s)
    if not m:
        raise SetupError(f'청크 id 형식이 아닙니다: {s!r} (예: c007 또는 7)')
    return f'c{int(m.group(1)):03d}'


def list_chunks(sdir, only=None):
    """[(cNNN, 청크 파일 경로)] — 파일명 cNNN_pAAAA-pBBBB.txt 의 cNNN 이 md 이름이 된다."""
    cdir = os.path.join(sdir, 'chunks')
    if not os.path.isdir(cdir):
        raise SetupError(f'청크 폴더가 없습니다: {cdir} (먼저 python -X utf8 tools/pdf_chunks.py 를 실행)')
    found = {}
    for name in os.listdir(cdir):
        m = CHUNK_RE.match(name)
        if not m:
            continue
        cid = norm_chunk_id(m.group(1))
        if cid in found:
            raise SetupError(f'같은 청크 id 의 파일이 둘 있습니다: {os.path.basename(found[cid])}, {name}')
        found[cid] = os.path.join(cdir, name)
    if not found:
        raise SetupError(f'청크 파일(cNNN_pAAAA-pBBBB.txt)이 없습니다: {cdir}')
    if only:
        ids = list(dict.fromkeys(norm_chunk_id(x) for x in only.split(',') if x.strip()))
        missing = [i for i in ids if i not in found]
        if missing:
            raise SetupError(f'없는 청크: {", ".join(missing)} (있는 청크: {min(found)} ~ {max(found)})')
        found = {i: found[i] for i in ids}
    return sorted(found.items(), key=lambda kv: int(kv[0][1:]))


class RunLog:
    """<과목>/_run.log 에 1행 1사건을 덧붙인다(탭 구분, key=value). 여러 스레드에서 써도 행이 섞이지 않는다."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, chunk, event, **kv):
        fields = [now(), chunk or '-', event]
        for k, v in kv.items():
            if v is None or v == '' or v is False:
                continue
            v = re.sub(r'[\t\r\n]+', ' ', str(v))
            fields.append(f'{k}={v[:400]}')
        with self.lock:
            with open(self.path, 'a', encoding='utf-8', newline='\n') as f:
                f.write('\t'.join(fields) + '\n')


class Ctx:
    def __init__(self, sdir, provider_name, model, effort, system, log, force):
        self.sdir, self.provider_name, self.model, self.effort = sdir, provider_name, model, effort
        self.system, self.log, self.force = system, log, force
        self.lock = threading.Lock()
        self.tokens = Counter()
        self.fatal = None       # 인증 실패 등: 남은 청크는 호출하지 않는다

    def md_path(self, cid):
        return os.path.join(self.sdir, 'md', f'{cid}.md')

    def meta(self, **extra):
        net = self.provider_name in ('anthropic', 'openai')
        return dict(provider=self.provider_name, model=self.model, effort=self.effort if net else None, **extra)

    def add_usage(self, usage):
        with self.lock:
            for k, v in (usage or {}).items():
                if isinstance(v, int):
                    self.tokens[k] += v

    def say(self, cid, status, detail=''):
        with self.lock:
            print(f'[{cid}] {STATUS_LABEL.get(status, status)}' + (f' — {detail}' if detail else ''), flush=True)


def fmt_sec(sec):
    return None if sec is None else f'{sec:.1f}'


def usage_fields(usage):
    names = {'in': 'in', 'out': 'out', 'cache_read': 'cacheRead', 'cache_write': 'cacheWrite', 'reasoning': 'reasoning'}
    return {names[k]: v for k, v in (usage or {}).items() if k in names and v is not None}


# ---------------------------------------------------------------- 응답 검사·저장

def check_markdown(text):
    """응답 → (저장할 본문, H2 블록 수, 거부 사유 또는 ''). 응답 전체를 감싼 코드펜스 한 겹만 벗기고 내용은 바꾸지 않는다."""
    t = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    m = FENCE_RE.match(t)
    if m:
        t = m.group(1)
    t = t.strip('\n')
    if not t.strip():
        return '', 0, '빈 응답'
    n = len(H2_RE.findall(t))
    if n == 0:
        return t, 0, "'## ' 블록 0개"
    return t + '\n', n, ''


def finalize(ctx, cid, resp, *, force, sec=None, via=None):
    """모델 응답을 검사해 md/cNNN.md 로 쓴다. 반환 (status, 설명)."""
    ctx.add_usage(resp.usage)
    meta = ctx.meta(servedBy=resp.model if resp.model and resp.model != ctx.model else None, via=via, sec=fmt_sec(sec), **usage_fields(resp.usage))
    if resp.stop in TRUNCATED:
        reason = f'출력 한도에서 잘림(stop={resp.stop}, max_tokens={MAX_TOKENS})'
    elif resp.stop in REFUSED:
        reason = f'거절(stop={resp.stop}' + (f', {resp.note}' if resp.note else '') + ')'
    else:
        body, n, reason = check_markdown(resp.text)
    if reason:
        ctx.log.write(cid, 'fail', reason=reason, chars=len(resp.text or ''), stop=resp.stop, **meta)
        return 'failed', reason
    path = ctx.md_path(cid)
    if os.path.exists(path) and not force:
        ctx.log.write(cid, 'skip', reason='md 가 이미 있음(응답은 버림)', **meta)
        return 'skipped', 'md 가 이미 있음(응답은 버림)'
    write_text(path, body)
    ctx.log.write(cid, 'ok', file=rel(path, ctx.sdir), blocks=n, chars=len(body), stop=resp.stop, note=resp.note, **meta)
    tok = usage_fields(resp.usage)
    return 'ok', f'{n}블록' + (f' · 입력 {tok["in"]} · 출력 {tok["out"]} 토큰' if 'in' in tok and 'out' in tok else '') + (f' · {sec:.1f}s' if sec else '')


# ---------------------------------------------------------------- 재시도

def status_of(e):
    st = getattr(e, 'status_code', None)
    if st is None:
        st = getattr(getattr(e, 'response', None), 'status_code', None)
    return st if isinstance(st, int) else None


def error_type(e):
    body = getattr(e, 'body', None)
    if isinstance(body, dict):
        err = body.get('error')
        if isinstance(err, dict):
            return err.get('type')
        return body.get('type')
    return None


def is_retryable(e):
    if type(e).__name__ in ('APIConnectionError', 'APITimeoutError'):
        return True
    st = status_of(e)
    if st is not None and (st == 429 or st >= 500):
        return True
    return error_type(e) in ('overloaded_error', 'rate_limit_error', 'api_error')   # 스트림 도중의 오류 이벤트


def is_fatal(e):
    """이후 청크도 똑같이 실패할 오류(인증·권한·모델 없음, 상태코드 없는 비 API 오류)."""
    st = status_of(e)
    return st in (401, 403, 404) or (st is None and not is_retryable(e))


def retry_delay(e, attempt):
    headers = getattr(getattr(e, 'response', None), 'headers', None)
    try:
        ra = headers.get('retry-after') if headers is not None else None
        if ra is not None:
            return min(120.0, max(0.0, float(ra)))
    except (TypeError, ValueError, AttributeError):
        pass
    return min(60.0, 2.0 * 2 ** (attempt - 1)) + random.uniform(0, 1)


def with_retry(fn, *, retries=RETRIES, on_retry=None):
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — 재시도 대상만 다시, 나머지는 그대로 올린다
            if attempt >= retries or not is_retryable(e):
                raise
            attempt += 1
            delay = retry_delay(e, attempt)
            if on_retry:
                on_retry(attempt, delay, e)
            time.sleep(delay)


def describe_error(e):
    st = status_of(e)
    msg = getattr(e, 'message', None) or str(e)
    return (f'{type(e).__name__}' + (f' {st}' if st is not None else '') + f': {msg}')[:300]


# ---------------------------------------------------------------- 제공자

def anthropic_response(msg):
    content = getattr(msg, 'content', None) or []
    text = ''.join(getattr(b, 'text', '') or '' for b in content if getattr(b, 'type', '') == 'text')
    u = getattr(msg, 'usage', None)
    usage = {}
    if u is not None:
        usage = {'in': getattr(u, 'input_tokens', None), 'out': getattr(u, 'output_tokens', None),
                 'cache_read': getattr(u, 'cache_read_input_tokens', None), 'cache_write': getattr(u, 'cache_creation_input_tokens', None)}
    stop = getattr(msg, 'stop_reason', '') or ''
    note = ''
    if stop == 'refusal':
        sd = getattr(msg, 'stop_details', None)
        note = f'category={getattr(sd, "category", None)}' if sd is not None else ''
    return Response(text=text, stop=stop, model=getattr(msg, 'model', '') or '', usage=usage, note=note)


class AnthropicProvider:
    """Messages API 스트리밍(messages.stream → get_final_message) 또는 Message Batches. thinking 파라미터는 보내지 않는다(기본 adaptive)."""
    name = 'anthropic'

    def __init__(self, model, effort):
        try:
            import anthropic
        except ImportError:
            raise SetupError('anthropic SDK 가 설치되어 있지 않습니다. 설치: python -m pip install anthropic '
                             '(키는 ANTHROPIC_API_KEY 환경변수, 없으면 SDK 기본 자격증명을 씁니다)') from None
        self.model, self.effort = model, effort
        try:
            self.client = anthropic.Anthropic(max_retries=0)   # 재시도는 with_retry 가 맡는다(429/5xx 지수 백오프 3회)
        except Exception as e:  # noqa: BLE001
            raise SetupError(f'Anthropic 클라이언트를 만들 수 없습니다: {e}') from None

    def params(self, system, user):
        p = {'model': self.model, 'max_tokens': MAX_TOKENS,
             # 지시문은 모든 청크에 같으므로 캐시 지점을 둔다(최소 길이 미만이면 API 가 조용히 캐시하지 않음)
             'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
             'messages': [{'role': 'user', 'content': user}]}
        if self.effort:
            p['output_config'] = {'effort': self.effort}
        return p

    def complete(self, system, user):
        with self.client.messages.stream(**self.params(system, user)) as stream:
            msg = stream.get_final_message()
        return anthropic_response(msg)

    def batch_create(self, requests):
        return self.client.messages.batches.create(requests=requests)

    def batch_retrieve(self, batch_id):
        return self.client.messages.batches.retrieve(batch_id)

    def batch_results(self, batch_id):
        return list(self.client.messages.batches.results(batch_id))


class OpenAIProvider:
    """Chat Completions. effort 를 reasoning_effort 로 보내고, 모델이 거부(400)하면 빼고 다시 보낸 뒤 이후에도 뺀다."""
    name = 'openai'

    def __init__(self, model, effort):
        try:
            import openai
        except ImportError:
            raise SetupError('openai SDK 가 설치되어 있지 않습니다. 설치: python -m pip install openai (키는 OPENAI_API_KEY 환경변수)') from None
        if not model:
            raise SetupError('--provider openai 는 --model 이 필요합니다')
        self.sdk, self.model, self.effort = openai, model, effort
        self.reasoning = bool(effort)
        try:
            self.client = openai.OpenAI(max_retries=0)
        except Exception as e:  # noqa: BLE001
            raise SetupError(f'OpenAI 클라이언트를 만들 수 없습니다: {e}') from None

    def complete(self, system, user):
        kw = {'model': self.model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}
        note = ''
        if self.reasoning:
            try:
                resp = self.client.chat.completions.create(**kw, reasoning_effort=self.effort)
            except self.sdk.BadRequestError as e:
                self.reasoning = False
                note = f'reasoning_effort 거부 → 빼고 다시 보냄 ({describe_error(e)[:120]})'
                resp = self.client.chat.completions.create(**kw)
        else:
            resp = self.client.chat.completions.create(**kw)
        choice = resp.choices[0]
        msg = choice.message
        stop = choice.finish_reason or ''
        if getattr(msg, 'refusal', None):
            stop, note = 'refusal', (note + ' ' if note else '') + str(msg.refusal)[:200]
        u = getattr(resp, 'usage', None)
        usage = {}
        if u is not None:
            usage = {'in': getattr(u, 'prompt_tokens', None), 'out': getattr(u, 'completion_tokens', None),
                     'cache_read': getattr(getattr(u, 'prompt_tokens_details', None), 'cached_tokens', None),
                     'reasoning': getattr(getattr(u, 'completion_tokens_details', None), 'reasoning_tokens', None)}
        return Response(text=msg.content or '', stop=stop, model=getattr(resp, 'model', '') or '', usage=usage, note=note)


class MockProvider:
    name = 'mock'

    def __init__(self, model):
        self.model = model or 'mock'

    def complete(self, system, user):
        return Response(text=mock_markdown(user), stop='end_turn', model=self.model)


def make_provider(name, model, effort):
    if name == 'anthropic':
        return AnthropicProvider(model, effort)
    if name == 'openai':
        return OpenAIProvider(model, effort)
    if name == 'mock':
        return MockProvider(model)
    return None     # manual


# ---------------------------------------------------------------- mock: 청크 머리에서 형식만 맞춘 최소 md

SEP_RE = re.compile(r'^-{3,}\s*PDF p\.(\d+)\s*-{3,}$')
HEAD_LINE_RE = re.compile(r'^(\d{1,4})(?:\s*\.\s*|\s+(?=[^\d\s.]))(.*)$')   # '17. 제목' · '17.' · '127 제목'(점 누락)
OLD_CASE_RE = re.compile(r'(?<![0-9])(\d{4})(민상|민공|민재항|민항|민신|형상|형항|행상)(\d{1,6})(?![0-9])')   # 1960년 이전 '4291민상407'
DATE_HEAD_RE = re.compile(r'^\d{1,2}\s*\.')        # '2021. 3. 4. …' 같은 날짜 줄은 항목 머리가 아니다
EXPECT_RE = re.compile(r'기대 항목:\s*(\d+)\s*~\s*(\d+)')
CONT_RE = re.compile(r'앞 청크에서 이어진 항목:\s*(\d+)')
LOC_RE = re.compile(r'^현재 위치:\s*(.*)$')
STRUCT_RE = re.compile(r'^제\s*(\d+)\s*(편|장|절|관)\s+(\S.{0,40})$')
ROMAN_RE = re.compile(r'^([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+)\s*\.\s*(\S.{0,40})$')
COURT_WORD_RE = re.compile(r'(헌법재판소|헌재|대법원|대판|대결|특허법원|[가-힣]+(?:고등|지방|가정|행정|회생)법원(?:\s*[가-힣]+지원)?)')
MOCK_SECTIONS = ('주제', '쟁점', '판시사항', '판결요지', '참조조문', '선정이유')


def _has_case(text):
    compact = re.sub(r'\s+', '', text)
    return CASE_RE.search(compact) is not None or OLD_CASE_RE.search(compact) is not None


def _is_citation(text):
    """괄호 안이 판례 인용인가: 사건번호가 있거나, 없더라도 법원명과 선고일이 있으면('대법원 2013. 7. 12. 선고 판결')."""
    return _has_case(text) or (COURT_WORD_RE.search(text) is not None and DATE_RE.search(text) is not None)


def _close_at(text):
    """여는 괄호 바로 뒤의 text 에서 그 괄호를 닫는 위치(안쪽 '(병합)' 같은 괄호는 건너뜀). 아직 안 닫혔으면 -1."""
    depth = 1
    for k, ch in enumerate(text):
        if ch in '(（':
            depth += 1
        elif ch in ')）':
            depth -= 1
            if depth == 0:
                return k
    return -1


def _clean_cit(text):
    end = _close_at(text)
    return re.sub(r'\s+', ' ', text if end < 0 else text[:end]).strip()


def _find_citation(lines, i):
    """lines[i] 가 '번호.' 로 시작하는 줄일 때 같은 줄 또는 아래(제목이 이어지는 줄 2개까지 건너) 괄호 인용을 찾는다.
    → (인용 또는 None, 더 소비한 줄 수, 번호 뒤 제목 조각 목록). 인용에 사건번호가 없으면 항목 머리가 아니다."""
    rest = HEAD_LINE_RE.match(lines[i].strip()).group(2).strip()
    m = re.search(r'[\(（](.*)$', rest)
    if m and _is_citation(m.group(1)):
        text, used = m.group(1), 0
        while _close_at(text) < 0 and used < 2 and i + used + 1 < len(lines):
            used += 1
            text += ' ' + lines[i + used].strip()
        return _clean_cit(text), used, [rest[:m.start()].strip()]
    title = [rest] if rest else []
    for j in range(i + 1, min(len(lines), i + 5)):
        l = lines[j].strip()
        if not l:
            continue
        if l[0] in '(（':
            text, k = l[1:], j
            while _close_at(text) < 0 and k + 1 < len(lines) and k - j < 2:
                k += 1
                text += ' ' + lines[k].strip()
            if _is_citation(text):
                return _clean_cit(text), k - i, title
            if k == j and len(title) < 2 and len(l) <= 40:      # '(간접거래, 겸임이사)' 같은 부제: 제목으로 보고 계속
                title.append(l)
                continue
            return None, 0, []
        if SEP_RE.match(l) or l[0] in '〈<' or HEAD_LINE_RE.match(l) or len(title) >= 2:
            return None, 0, []
        title.append(l)
    return None, 0, []


def _struct_heading(l):
    """'제 3 장 상업사용인' → (2, '제3장 상업사용인'), 'Ⅰ. 총설' → (3, 'Ⅰ. 총설'). 쪽 머리글처럼 제N편·제N장이 둘이면 None."""
    if len(re.findall(r'제\s*\d+\s*[편장절관]', l)) != 1:
        m = ROMAN_RE.match(l)
        return (3, f'{m.group(1)}. {m.group(2).strip()}') if m else None
    m = STRUCT_RE.match(l)
    if not m or re.search(r'[다요음함]\s*\.?$', l):
        return None
    n, kind, rest = m.groups()
    rest = re.sub(r'\s+', ' ', rest).strip()
    return {'편': 1, '장': 2, '절': 3, '관': 3}[kind], f'제{n}{kind} {rest}'


def _level_of(label):
    m = re.match(r'^제\s*\d+\s*(편|장|절|관)', label)
    if m:
        return {'편': 1, '장': 2, '절': 3, '관': 3}[m.group(1)]
    return 3 if ROMAN_RE.match(label) else 0


def _loc_string(parts):
    main = [p for p in parts if _level_of(p) < 3]
    sec = [p for p in parts if _level_of(p) == 3]
    return ' > '.join(main + [sec[-1] if sec else '(절 없음)'])


def _is_running_head(l):
    return '표준판례' in l or len(re.findall(r'제\s*\d+\s*[편장절]', l)) >= 2


def _case_lines(cit):
    out = []
    for part in [p for p in re.split(r'[;；]', cit) if p.strip()] or [cit]:
        compact = re.sub(r'\s+', '', part)
        cm = COURT_WORD_RE.search(part)
        court = ''
        if cm:
            c = re.sub(r'\s+', ' ', cm.group(1)).strip()
            court = '헌법재판소' if c in ('헌재', '헌법재판소') else '대법원' if c in ('대법원', '대판', '대결') else c
        dm = DATE_RE.search(part)
        date = norm_date(*dm.groups()) if dm else '????-??-??'
        if court == '헌법재판소' or '결정' in compact:
            dtype = '결정'
        else:
            dtype = '판결' if '판결' in compact else '판결?'
        enb = '예' if '전원합의체' in compact else '아니오'
        found = list(CASE_RE.finditer(compact)) or list(OLD_CASE_RE.finditer(compact))
        if not found:
            out.append(f'(사건번호 없음) | {date} | {court or "법원?"} | {dtype} | 전원합의체 {enb}')
        for m in found:
            cn = f'{m.group(1)}{m.group(2)}{m.group(3)}'
            # 병합사건 '97다7721, 7738' → '97다7721·7738' (뒤 번호가 '2014도123' 처럼 연도+부호이면 별개 사건)
            tail = re.match(r'((?:[,·]\d{1,7}(?!\d)(?!헌?[가-힣]{1,2}\d))+)', compact[m.end():])
            if tail:
                cn += '·' + '·'.join(re.findall(r'\d+', tail.group(1)))
            out.append(f'{cn} | {date} | {court or "법원?"} | {dtype} | 전원합의체 {enb}')
    return out


def _page_range(pages):
    ps = sorted(p for p in pages if p is not None)
    if not ps:
        return '?'
    return f'{ps[0]}' if ps[0] == ps[-1] else f'{ps[0]}-{ps[-1]}'


def _render_block(head, cit, loc, pages):
    out = [head]
    if cit is not None:
        out.append(f'- 출처: {cit}')
        out += [f'- 사건: {c}' for c in _case_lines(cit)]
    out += [f'- 위치: {loc}', f'- 쪽: {_page_range(pages)}', '']
    for s in MOCK_SECTIONS:
        out += [f'### {s}', '(없음)']
    out += ['### 검토메모', '- (없음)']
    return '\n'.join(out)


def mock_markdown(chunk_text):
    """청크 텍스트에서 항목 머리(번호. 제목 + 괄호 인용)만 찾아 tools/prompts/pdf2md.md 형식의 최소 블록을 만든다.
    본문 절은 모두 '(없음)', 검토메모는 '- (없음)'. 기대 범위 밖 번호는 쓰지 않고, 머리에 '앞 청크에서 이어진 항목'이 있으면 (이어짐) 블록을 둔다."""
    lines = chunk_text.replace('\r\n', '\n').split('\n')
    start = next((k for k, l in enumerate(lines) if SEP_RE.match(l.strip())), len(lines))
    parts, lo, hi, cont = [], None, None, None
    for l in lines[:start]:
        m = LOC_RE.match(l.strip())
        if m and m.group(1).strip() not in ('', '(없음)'):
            parts = [p.strip() for p in re.split(r'\s*[›>]\s*', m.group(1)) if p.strip()]
        m = EXPECT_RE.search(l)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
        m = CONT_RE.search(l)
        if m:
            cont = int(m.group(1))
    items, pre_pages, cur, page, fresh, closed, last_no, prev = [], set(), None, None, False, False, 0, None
    cont_loc = _loc_string(parts)
    i = start
    while i < len(lines):
        l = lines[i].strip()
        m = SEP_RE.match(l)
        if m:
            page, fresh, prev = int(m.group(1)), True, None
            i += 1
            continue
        if not l:
            i += 1
            continue
        if fresh:
            fresh = False
            if _is_running_head(l):
                i += 1
                continue
        if re.fullmatch(r'\d{1,4}', l):     # 쪽 번호
            i += 1
            continue
        h = _struct_heading(l)
        if h and not HEAD_LINE_RE.match(l):
            level, label = h
            parts = [p for p in parts if _level_of(p) < level] + [label]
            prev = None
            i += 1
            continue
        hm = HEAD_LINE_RE.match(l)
        if hm and not DATE_HEAD_RE.match(hm.group(2)):
            no = int(hm.group(1))
            cit, used, title_parts = _find_citation(lines, i)
            if cit is not None and no > last_no:
                if (lo is not None and no < lo) or (hi is not None and no > hi):
                    cur, closed = None, True        # 기대 범위 밖(다음 청크 항목): 이후 줄은 쓰지 않는다
                else:
                    # 두 줄 제목은 '제목 앞부분 / N. / 제목 뒷부분' 으로 추출되기도 한다(번호만 있는 줄)
                    if not hm.group(2).strip() and prev and not re.search(r'[.。)）다]$', prev) and prev[0] not in '〈<':
                        title_parts = [prev] + title_parts
                    title = ' '.join(t for t in title_parts if t) or '(제목 없음)'
                    cur = {'no': no, 'title': title, 'cit': cit, 'pages': {page}, 'loc': _loc_string(parts)}
                    items.append(cur)
                last_no, prev = no, None
                i += 1 + used
                continue
        if cur is not None:
            cur['pages'].add(page)
        elif not items and not closed:
            pre_pages.add(page)
        prev = l
        i += 1
    blocks = []
    if cont is not None:
        first_page = next((int(SEP_RE.match(l.strip()).group(1)) for l in lines[start:start + 1] if SEP_RE.match(l.strip())), None)
        blocks.append(_render_block(f'## (이어짐) {cont}. (제목 앞 청크)', None, cont_loc, pre_pages or {first_page}))
    for it in items:
        blocks.append(_render_block(f'## {it["no"]}. {it["title"]}', it['cit'], it['loc'], it['pages']))
    return '\n\n'.join(blocks) + '\n' if blocks else ''


# ---------------------------------------------------------------- 실행

def write_manual(ctx, cid, path):
    out = os.path.join(ctx.sdir, 'md', '_prompts', f'{cid}.txt')
    if not ctx.force and (os.path.exists(out) or os.path.exists(ctx.md_path(cid))):
        why = 'md 가 이미 있음' if os.path.exists(ctx.md_path(cid)) else '_prompts 파일이 이미 있음'
        ctx.log.write(cid, 'skip', reason=why, **ctx.meta())
        return 'skipped', why
    user = read_text(path)
    write_text(out, f'=== SYSTEM ===\n{ctx.system.rstrip()}\n=== USER ===\n{user.rstrip()}\n')
    ctx.log.write(cid, 'prompt', file=rel(out, ctx.sdir), chars=len(user), **ctx.meta())
    return 'ok', f'{rel(out, ctx.sdir)} 작성'


def process_chunk(ctx, provider, cid, path):
    if provider is None:
        return write_manual(ctx, cid, path)
    if os.path.exists(ctx.md_path(cid)) and not ctx.force:
        ctx.log.write(cid, 'skip', reason='md 가 이미 있음', **ctx.meta())
        return 'skipped', 'md 가 이미 있음'
    if ctx.fatal:
        ctx.log.write(cid, 'fail', reason=f'앞 오류로 호출하지 않음: {ctx.fatal}', **ctx.meta())
        return 'failed', '앞 오류로 호출하지 않음'
    user = read_text(path)
    t0 = time.monotonic()

    def on_retry(n, delay, e):
        ctx.log.write(cid, 'retry', attempt=n, wait=f'{delay:.1f}', error=describe_error(e), **ctx.meta())

    try:
        resp = with_retry(lambda: provider.complete(ctx.system, user), on_retry=on_retry)
    except Exception as e:  # noqa: BLE001 — 청크 하나의 실패로 전체를 멈추지 않는다(인증 등은 ctx.fatal)
        reason = describe_error(e)
        if is_fatal(e):
            ctx.fatal = reason
        ctx.log.write(cid, 'fail', reason=reason, sec=fmt_sec(time.monotonic() - t0), **ctx.meta())
        return 'failed', reason
    return finalize(ctx, cid, resp, force=ctx.force, sec=time.monotonic() - t0)


def run_chunks(ctx, provider, chunks, concurrency):
    tally = Counter()

    def job(item):
        cid, path = item
        status, detail = process_chunk(ctx, provider, cid, path)
        ctx.say(cid, status, detail)
        return status

    if concurrency <= 1 or len(chunks) <= 1:
        for item in chunks:
            tally[job(item)] += 1
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            for status in ex.map(job, chunks):
                tally[status] += 1
    return tally


# ---- Message Batches (anthropic)

def batch_state_path(sdir):
    return os.path.join(sdir, '_batch.json')


def load_batch_state(sdir):
    p = batch_state_path(sdir)
    if not os.path.exists(p):
        return {'batches': []}
    try:
        state = json.loads(read_text(p))
    except json.JSONDecodeError as e:
        raise SetupError(f'_batch.json 을 읽을 수 없습니다: {e}') from None
    state.setdefault('batches', [])
    return state


def save_batch_state(sdir, state):
    write_text(batch_state_path(sdir), json.dumps(state, ensure_ascii=False, indent=1) + '\n')


def _counts(rc):
    return {k: getattr(rc, k, None) for k in ('processing', 'succeeded', 'errored', 'canceled', 'expired')} if rc is not None else None


def _batch_error(result):
    err = getattr(result, 'error', None)
    inner = getattr(err, 'error', err)
    return ' '.join(str(x) for x in (getattr(inner, 'type', None), getattr(inner, 'message', None)) if x)[:200]


def _elapsed_since(iso):
    try:
        return (datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return None


def collect_batch(ctx, provider, b, tally, collected):
    results = {}
    for r in with_retry(lambda: provider.batch_results(b['id'])):
        cid = r.custom_id
        rtype = getattr(r.result, 'type', '')
        if rtype == 'succeeded':
            status, detail = finalize(ctx, cid, anthropic_response(r.result.message), force=b.get('force', False), via=f'batch:{b["id"]}')
        else:
            detail = f'배치 결과 {rtype}' + (f' ({_batch_error(r.result)})' if _batch_error(r.result) else '')
            ctx.log.write(cid, 'fail', reason=detail, via=f'batch:{b["id"]}', **ctx.meta())
            status = 'failed'
        results[cid] = status if status != 'failed' else f'failed: {detail}'
        tally[status] += 1
        collected.add(cid)
        ctx.say(cid, status, detail)
    for cid in b.get('chunks', []):
        if cid not in results:
            results[cid] = 'failed: 배치 결과에 없음'
            ctx.log.write(cid, 'fail', reason='배치 결과에 없음', via=f'batch:{b["id"]}', **ctx.meta())
            tally['failed'] += 1
            collected.add(cid)
            ctx.say(cid, 'failed', '배치 결과에 없음')
    b.update(status='collected', collectedAt=now(), results=results)
    ok = sum(1 for v in results.values() if v == 'ok')
    ctx.log.write('-', 'batch-collect', id=b['id'], ok=ok, failed=sum(1 for v in results.values() if v.startswith('failed')),
                  sec=fmt_sec(_elapsed_since(b.get('submittedAt'))), **ctx.meta())


def poll_batches(ctx, provider, state, tally, collected):
    for b in [b for b in state['batches'] if b.get('status') == 'submitted']:
        bt = with_retry(lambda: provider.batch_retrieve(b['id']))
        b.update(processingStatus=getattr(bt, 'processing_status', None), requestCounts=_counts(getattr(bt, 'request_counts', None)), checkedAt=now())
        if b['processingStatus'] == 'ended':
            collect_batch(ctx, provider, b, tally, collected)
        else:
            print(f'배치 {b["id"]}: {b["processingStatus"]} {b["requestCounts"] or ""}', flush=True)
        save_batch_state(ctx.sdir, state)


def pending_chunks(state):
    return {cid for b in state['batches'] if b.get('status') == 'submitted' for cid in b.get('chunks', [])}


def run_batch(ctx, provider, chunks, wait):
    state = load_batch_state(ctx.sdir)
    tally, collected = Counter(), set()
    poll_batches(ctx, provider, state, tally, collected)
    pending = pending_chunks(state)
    todo = []
    for cid, path in chunks:
        if cid in pending:
            tally['pending'] += 1
            continue
        if cid in collected:
            continue            # 방금 거둔 청크: 실패했으면 다음 실행에서 다시 제출된다
        if os.path.exists(ctx.md_path(cid)) and not ctx.force:
            ctx.log.write(cid, 'skip', reason='md 가 이미 있음', **ctx.meta())
            tally['skipped'] += 1
            ctx.say(cid, 'skipped', 'md 가 이미 있음')
            continue
        todo.append((cid, path))
    if todo:
        requests = [{'custom_id': cid, 'params': provider.params(ctx.system, read_text(path))} for cid, path in todo]
        bt = with_retry(lambda: provider.batch_create(requests))
        entry = {'id': bt.id, 'provider': 'anthropic', 'model': ctx.model, 'effort': ctx.effort, 'chunks': [c for c, _ in todo],
                 'force': bool(ctx.force), 'submittedAt': now(), 'status': 'submitted', 'processingStatus': getattr(bt, 'processing_status', None)}
        state['batches'].append(entry)
        save_batch_state(ctx.sdir, state)
        ctx.log.write('-', 'batch-submit', id=bt.id, chunks=','.join(entry['chunks']), force=ctx.force, **ctx.meta())
        tally['submitted'] += len(todo)
        print(f'배치 제출: {bt.id} ({len(todo)}청크) — 끝나면 같은 명령을 --batch 로 다시 실행해 결과를 거둡니다', flush=True)
    if wait:
        try:
            while any(b.get('status') == 'submitted' for b in state['batches']):
                time.sleep(BATCH_POLL_SEC)
                poll_batches(ctx, provider, state, tally, collected)
        except KeyboardInterrupt:
            print('대기를 멈춥니다 — 배치는 서버에서 계속 처리됩니다. 나중에 --batch 로 다시 실행하세요.', flush=True)
    tally['pending'] = len(pending_chunks(state) & {c for c, _ in chunks})
    return tally


# ---------------------------------------------------------------- main

def parse_args(argv):
    ap = argparse.ArgumentParser(description='표준판례 청크 → md/cNNN.md 전사 실행기 (제공자 중립)',
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('--subject', required=True, help='과목 id 또는 한글명 (상법 · commercial …)')
    ap.add_argument('--provider', required=True, choices=PROVIDERS)
    ap.add_argument('--model', help=f'모델 id (anthropic 기본 {DEFAULT_MODELS["anthropic"]}, openai 는 필수)')
    ap.add_argument('--effort', default=DEFAULT_EFFORT, help=f"effort (기본 {DEFAULT_EFFORT}; 'none' 이면 보내지 않음)")
    ap.add_argument('--only', help='청크 id 목록: c007,c008 (또는 7,8)')
    ap.add_argument('--force', action='store_true', help='이미 있는 md(manual 은 _prompts)도 다시 만든다')
    ap.add_argument('--batch', action='store_true', help='anthropic Message Batches 로 제출 / 다시 실행하면 끝난 배치를 거둔다')
    ap.add_argument('--wait', action='store_true', help=f'--batch: 모든 배치가 끝날 때까지 {BATCH_POLL_SEC}초마다 확인')
    ap.add_argument('--concurrency', type=int, default=4, help='동시에 처리할 청크 수(기본 4)')
    ap.add_argument('--dir', help='과목 폴더를 직접 지정(기본 data/standard-cases/<과목>)')
    ap.add_argument('--prompt', help='지시문 파일(기본 tools/prompts/pdf2md.md)')
    return ap.parse_args(argv)


def run(a):
    try:
        sid = resolve_standard(a.subject)
    except ValueError as e:
        raise SetupError(str(e)) from None
    sdir = os.path.abspath(a.dir) if a.dir else os.path.join(ROOT, 'data', 'standard-cases', BY_ID[sid]['folder'])
    if a.concurrency < 1:
        raise SetupError('--concurrency 는 1 이상이어야 합니다')
    if a.batch and a.provider != 'anthropic':
        raise SetupError('--batch 는 --provider anthropic 에서만 쓸 수 있습니다')
    if a.wait and not a.batch:
        raise SetupError('--wait 는 --batch 와 함께 씁니다')
    chunks = list_chunks(sdir, a.only)
    prompt_path = find_prompt(a.prompt)
    system = read_text(prompt_path)
    if not system.strip():
        raise SetupError(f'지시문이 비어 있습니다: {prompt_path}')
    model = a.model or DEFAULT_MODELS.get(a.provider)
    effort = None if (a.effort or '').strip().lower() in ('', 'none') else a.effort.strip()
    provider = make_provider(a.provider, model, effort)
    os.makedirs(os.path.join(sdir, 'md'), exist_ok=True)
    log = RunLog(os.path.join(sdir, '_run.log'))
    ctx = Ctx(sdir, a.provider, model, effort, system, log, a.force)
    log.write('-', 'run-start', subject=sid, chunks=len(chunks), only=a.only, force=a.force, batch=a.batch, concurrency=a.concurrency,
              prompt=rel(prompt_path, ROOT), promptSha256=hashlib.sha256(system.encode('utf-8')).hexdigest()[:16], **ctx.meta())
    print(f'{BY_ID[sid]["label"]} · 청크 {len(chunks)}개 · {a.provider}' + (f' {model}' if a.provider in ('anthropic', 'openai') else '')
          + (f' effort={effort}' if a.provider in ('anthropic', 'openai') and effort else '') + (' · 배치' if a.batch else '') + f' → {sdir}', flush=True)
    t0 = time.monotonic()
    tally = run_batch(ctx, provider, chunks, a.wait) if a.batch else run_chunks(ctx, provider, chunks, a.concurrency)
    sec = time.monotonic() - t0
    tok = usage_fields(dict(ctx.tokens))
    log.write('-', 'run-end', ok=tally['ok'], skipped=tally['skipped'], failed=tally['failed'], submitted=tally['submitted'] or None,
              pending=tally['pending'] or None, sec=fmt_sec(sec), **{f'total{k[0].upper()}{k[1:]}': v for k, v in tok.items()}, **ctx.meta())
    line = f'완료: 성공 {tally["ok"]} · 건너뜀 {tally["skipped"]} · 실패 {tally["failed"]}'
    if a.batch:
        line += f' · 배치 제출 {tally["submitted"]} · 대기 {tally["pending"]}'
    if tok:
        line += ' · 토큰 ' + ' '.join(f'{k}={v}' for k, v in tok.items())
    print(line + f' · {sec:.1f}s — 기록 {rel(log.path, ROOT)}', flush=True)
    if ctx.fatal:
        print(f'중단된 오류: {ctx.fatal}', file=sys.stderr)
    return 1 if tally['failed'] else 0


def main(argv=None):
    a = parse_args(argv)
    try:
        return run(a)
    except SetupError as e:
        print(f'오류: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
