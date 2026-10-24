# 설계 — 표준판례 PDF → Markdown(하위 모델) → 대조·병합(스크립트) → 판정(상위 모델) → 등록·빌드

> 상태: **설계 확정안(미구현)**, 2026-10-24 개정 2판. 작업 지시서는 `spec/TASK-pdf2md.md`. 이 문서는 "왜 이렇게 나누는가"와 산출물 계약을 적는다.
> 적용 규칙: `CLAUDE.md`(= `AGENTS.md`) 절대 규칙 1·3·4·5·6·8, `data/schema.md` §1-2(재판 ID)·§1-3(`standardSource`).
> 대상: 표준판례(2023년 개정판) PDF 5건 — 헌법 323쪽 · 행정법 442쪽 · 민법 659쪽 · 형법 454쪽 · 상법 548쪽, 본문 약 320만 자, 항목 약 2,900건(상법 515·형법 498 확정, 나머지 근사).

## 0. 무엇이 바뀌었나 — PDF 텍스트는 이제 "대체물"이 아니라 "우선 출처"다
개정 전 규칙에서는 PDF 본문이 편집 요약(`editorial`) 재료였다. 개정 규칙에서는 **검증된(`verified: true`) 표준판례 추출문이 해당 필드에서 공식 자료보다 우선 표시**된다(규칙 1·3, schema §1-3). 따라서 하위 모델의 전사 결과는 곧 화면에 나갈 수 있는 텍스트이고, 파이프라인의 핵심은 전사가 아니라 **대조(검증)** 다.

| PDF 의 절 | 등록부에서 가는 곳 | 성격 |
|---|---|---|
| 〈판시사항〉 | `standardSource.issues` | 검증 후 화면 우선 표시 |
| 〈판결요지〉·〈결정요지〉 | `standardSource.holdings` | 검증 후 화면 우선 표시 |
| 〈참조조문〉·〈참조판례〉·〈심판대상조문〉 | `standardSource.statutes` · `precedents` · `subjectStatutes` | 검증 후 화면 우선 표시 |
| 〈주제〉 | `keywords` | 학습 메타(검증 대상 아님) |
| 〈선정이유〉 | `selectionReason` | 학습 메타 |
| 〈쟁점〉 | 〈판시사항〉이 없으면 `standardSource.issues`, 있으면 `memo`("쟁점: …") | 사용자 결정(2026-10-24): 판시사항 부재 시 쟁점이 그 자리를 채운다(대조 게이트 적용) |
| 번호·제목·(법원 선고일 사건번호 판결) | `title`·`court`·`decisionDate`·`caseNumber`·`decisionType`·`enBanc` | 재판 정체성(schema §1-2) |
| 쪽 | `standardSource.pages`(PDF 기준 1부터) | 출처 표시·재검증용 |

`verified: true` 가 아닌 `standardSource` 는 등록이 거부된다(`validate_standard_source`). 검증을 통과하지 못한 항목은 **`standardSource` 를 아예 생략**하고 공식 자료만으로 표시한다(`editorial` 로 내려보내지 않는다 — 오류 가능성이 있는 PDF 문장을 "편집 요약"으로 보이게 하는 것도 출처 혼동이다).

## 1. 역할 분담 (누가 무엇을 만드는가)
| 단계 | 담당 | 입력 → 출력 | 비고 |
|---|---|---|---|
| 0 뼈대·청크 | 스크립트 `tools/pdf_chunks.py` | PDF → `skeleton.json` · `00_toc.md` · `pages/pNNNN.txt` · `chunks/cNNN_pAAAA-pBBBB.txt` | 모델 토큰 0. 뼈대만으로도 등록·수집·빌드 가능 |
| 1 전사 | 하위 모델 **Sonnet 5.5 medium**(사용자 결정; Haiku·GPT 계열도 같은 지시문) | `chunks/*.txt` → `md/cNNN.md` | 제공자 중립 실행기 `tools/pdf2md_run.py` 또는 각 에이전트의 서브에이전트 |
| 2 파싱·대조 | 스크립트 `tools/md_validate.py` | `md/*.md` + `pages/*.txt` + `skeleton.json` → `entries.jsonl` · `_report.json` | 구조 검사 + **문자 대조 게이트**(§3) |
| 3 판정·병합 | 상위 모델(또는 사람) + 스크립트 `tools/md_merge.py` | `_report.json` 의 error/warn/표본 → 판정 기록 → `candidates-<subject>.json` | 상위 모델은 전수 재독이 아니라 불합격·표본·충돌만 본다 |
| 4 등록·수집·빌드 | 기존 CLI | `add_cases.py add --from` → `fetch_lawgo.py --all-missing` → `make data build check web webcheck` | 사용자 PC(law.go.kr) |
| 5 교차검증 | 스크립트 `tools/crosscheck.py` → 상위 모델 | fetched 요지 vs standardSource 요지 유사도 → `_crosscheck.json` | 낮은 유사도 = 사건번호 오인·병합사건·다른 재판 가능성 |

## 2. 폴더·파일 계약 (`data/standard-cases/<과목>/`)
```
data/standard-cases/
  표준판례(2023년 개정판)_상법.pdf
  상법/
    skeleton.json          # [0] 항목 뼈대 배열. 항목: {no, title, citationRaw, caseNumber, lookupKey, court(정식명), decisionType, date, enBanc,
                           #     tocLabels:[분야,편,장,(절)], tocPath:[sb-…] 또는 null, pdfPages:[…](1부터), printedPage, chunk:"c007"}
    00_toc.md              # [0] PDF 목차 트리 ↔ toc.json id 대응표 (사람이 한 번 확정)
    pages/p0049.txt        # [0] pdfplumber 쪽별 원문(대조용 기준 텍스트, 수정 금지)
    chunks/c007_p0049-p0063.txt   # [0] 장 경계에서 자른 15쪽 안팎 본문. 머리에 "현재 위치"·"기대 항목 N~M"·쪽 구분선 "----- PDF p.N -----"
    md/c007.md             # [1] 하위 모델 산출 (§4 형식). 한 청크 = 한 파일. 파일 외 산출 금지
    entries.jsonl          # [2] md 파싱 결과 1항목 1행 (+ 대조 결과 verify: pass|fail, diffs)
    _report.json           # [2] 항목별 ok/warn/error 와 사유, 청크별 통계
    _review.jsonl          # [3] 상위 모델·사람 판정 기록 {no, decisionId, verdict, reviewer, reviewedAt, note}
    candidates-commercial.json    # [3] add_cases.py add --from 입력 (status ok 인 항목만 등록됨)
    _conflicts.json        # [3] 같은 decisionId 의 중복·텍스트 불일치·법원 불명 등 사람이 정할 것
    _crosscheck.json       # [5] 공식 요지 vs 표준판례 요지 유사도
```
PDF 원본·`pages/`·`chunks/`·`md/` 는 배포물(`output/web/`)에 절대 들어가지 않는다(규칙 6).

## 3. 검증 게이트 — `verified: true` 의 정의 (규칙 1·3, schema §1-3)
schema 는 "자동 PDF 텍스트 추출만으로 검토 완료 처리하지 않는다", "모델 요약을 원문으로 표시하지 않는다"고 못 박는다. 그래서 두 개의 **서로 독립한** 추출(pdfplumber 쪽 텍스트, 하위 모델 전사)을 스크립트로 대조하고, 그 위에 상위 모델(또는 사람)의 표본 검토를 얹는다.

1. **스크립트 대조(`md_validate.py`, 항목·필드 단위)** — 모델 텍스트와 `pages/` 텍스트를 같은 방식으로 정규화(공백·줄바꿈 제거, 【】〈〉 등 괄호 통일, 전각 숫자·구두점 반각화)한 뒤
   - 정규화된 모델 텍스트가 해당 쪽(들)의 정규화 텍스트에 **연속 부분 문자열로 존재**해야 한다(허용: 쪽 경계 1곳, 하이픈·머리글 제거로 생긴 1~2자 차이). 부분 문자열이 아니면 최장 공통 부분열 비율을 계산해 0.995 미만이면 `fail`.
   - 숫자열(사건번호·연월일·조문 번호·금액)은 **완전 일치**해야 한다. 하나라도 다르면 `fail`.
   - 절 경계(〈판결요지〉 다음 줄부터 다음 꺾쇠 제목 전까지)가 PDF 와 같아야 한다. 절 누락·절 추가는 `fail`.
   - 통과 = `pass`. `pass` 는 "기계 대조 통과"이지 아직 `verified` 가 아니다.
2. **상위 모델·사람 검토(3단계)** — 다음을 PDF 쪽 텍스트(`pages/`)와 직접 대조해 `_review.jsonl` 에 기록한다: (a) 모든 `fail`·`warn`, (b) `pass` 중 과목당 무작위 10%(최소 20건), (c) `### 검토메모` 가 비어 있지 않은 항목 전부, (d) `_conflicts.json` 전부. 표본에 결함이 하나라도 있는 청크는 전수 재검토하고, 과목 전체 표본 결함률이 0.5% 를 넘으면 그 과목의 `pass` 전부를 재검토한다.
3. **`verified: true` 부여** — `pass` 이고 소속 청크의 표본 검토가 통과한 항목, 또는 개별 검토에서 `ok` 판정을 받은 항목. `standardSource` 에 `reviewer`(예: `"script+claude-fable-5-1 sample 10%"` 또는 사람 이름)·`reviewedAt`(ISO 날짜)·`sha256`(대조에 쓴 `pages/` 텍스트 해시)을 함께 기록한다. 그 밖의 항목은 `standardSource` 없이 등록한다.
4. **검증 대상이 아닌 필드** — `keywords`·`selectionReason`·`memo` 는 대조 없이 그대로 등록하되 원문 그대로 옮긴다(요약 금지).

## 4. 하위 모델 산출 형식 (항목 1개 = H2 블록 1개; 기계가 파싱)
```markdown
## 4. 의사나 의료기관의 상인 여부
- 출처: 대법원 2022. 5. 26. 선고 2022다200249 판결        ← PDF 괄호 표기 그대로
- 사건: 2022다200249 | 2022-05-26 | 대법원 | 판결 | 전원합의체 아니오   ← 정규화. 둘 이상이면 줄 반복(첫 줄이 대표). 법원은 PDF 표기 그대로(하급심은 "서울고등법원" 처럼 정식명)
- 위치: 총칙·상행위 > 제1편 총칙 > 제2장 상인 > (절 없음)
- 쪽: 5-6                                                   ← PDF 쪽 번호(구분선 기준), 걸치면 범위

### 주제
(없음)
### 쟁점
(PDF 그대로)
### 판시사항
(없으면 "(없음)")
### 판결요지
(PDF 그대로. 번호 [1] [2] 가 있으면 줄머리에 그대로 둔다)
### 참조조문
(없으면 "(없음)")
### 선정이유
(PDF 그대로)
### 검토메모
- (없음)  ← 문제된 지점: 판독불가 위치, 이음이 불확실한 어절, 사건번호·날짜·법원 표기 이상, 절 경계 불명, 기대 범위 밖 내용, 표·각주·병합사건
```
지시문은 `tools/prompts/pdf2md.md` 한 파일이 단일 출처다(모델·제공자 무관). 핵심 규칙: 요약·의역·교정 금지, 줄바꿈으로 끊긴 어절만 붙임, 쪽 머리글·쪽 번호 제거, 없는 절은 `(없음)`, 판독 불가는 `[판독불가 p.N]`, 기대 항목 범위 밖은 쓰지 않음, 앞 청크에서 이어진 꼬리는 `## (이어짐) N. 제목`.

## 5. 재판 정체성·중복·충돌 (schema §1-2)
- 후보 항목마다 `court`(정식 법원명)·`decisionType`(판결/결정)·`caseNumber`(병합사건은 전체 표기)·`lookupKey`(대표번호)를 채운다. `case_identity.COURTS` 에 없는 법원이 나오면 임의로 대법원 처리하지 말고 `_conflicts.json` 에 올린다(새 법원은 정확한 명칭 확인 후 등록).
- 같은 재판이 한 과목에 여러 항목으로 실리면(상법 97다48319 는 수표 편에 3회) **첫 항목만 등록**하고 나머지 위치는 `memo` 에 "함께 실린 곳: … (364·368)" 로 남긴다. 다른 과목·그룹(전원합의체 등)에 이미 같은 `decisionId` 가 있으면 `standardSource` 텍스트가 같을 때만 추가하고, 다르면 등록하지 않고 `_conflicts.json` 으로 보고한다(`standard_sources_by_decision` 이 충돌을 오류로 막는다).
- 한 항목에 재판이 둘(형법에 흔함: "헌법재판소 91헌가4; 대법원 2013도1685")이면 각각 별도 항목으로 등록하되 `standardSource` 는 본문이 어느 재판의 요지인지 확인된 쪽에만 붙인다. 확인되지 않으면 둘 다 `standardSource` 없이 등록하고 보고한다.
- 선고일 표기 불규칙("2001.02.13.", "2008.11. 27.")과 "판결" 누락은 스크립트가 정규화하고 원문은 `출처:` 줄에 남긴다. 결정(`자 … 결정`)은 `decisionType: 결정`.

## 6. 실행 방식 — Claude Code 와 Codex 어느 쪽이든 같다
- 모든 단계의 입출력은 **파일**이다. 에이전트 고유 기능(서브에이전트·워크플로)은 1단계 전사를 병렬로 돌리는 편의일 뿐, 산출물은 반드시 `md/cNNN.md` 로 떨어진다.
- `tools/pdf2md_run.py --subject 상법 --provider anthropic|openai|manual [--only c007,c008]`: 청크마다 지시문 + 청크 텍스트를 보내고 응답을 `md/` 에 쓴다. 키는 환경변수(`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). `manual` 은 보낼 메시지를 `md/_prompts/cNNN.txt` 로 떨어뜨리기만 한다(채팅창에 붙여 넣는 방식). 배치 API 를 쓰면 비용이 절반이다.
- 상위 모델 판정(3단계)은 그 세션을 운전하는 모델이 한다(Claude Code 면 Fable/Opus, Codex 면 GPT). 판정은 `_review.jsonl` 에 남아야 하며 채팅 텍스트로만 끝내지 않는다.
- 동시 작업(규칙 8): 이 파이프라인 세션이 쓰는 파일은 `tools/pdf_chunks.py` · `md_validate.py` · `md_merge.py` · `crosscheck.py` · `pdf2md_run.py` · `tools/prompts/` · `tools/test_pdf2md.py` · `data/standard-cases/<과목>/**` · 이 문서와 `TASK-pdf2md.md` 뿐이다. 등록부·목차는 `add_cases.py` CLI 로만, `Makefile`/`tools/make.py` 는 타깃 한 줄 추가만, `src/`·`build_data.py`·`build_web.py`·`add_cases.py` 본체는 손대지 않고 필요하면 요청으로 남긴다.

## 7. 실측 기반 토큰 추정 (2026-10-24; 샘플 = 상법 PDF 49~56쪽, 본문 10,303자 → Markdown 약 7,300자, 7항목)
서브에이전트 트랜스크립트의 usage 로 잰 값. 7가지 설정 모두 사건번호·쪽수가 일치했고 본문은 95~98% 동일 — **effort 는 품질을 바꾸지 않고 토큰만 늘렸다.**

| 설정 | 샘플 출력 토큰 | 5과목 출력 토큰 | API 입력 | API 정가 | 배치(50%) |
|---|---|---|---|---|---|
| haiku-5.5 low | 22,509 | 7.0M | 4.3M | $4 | $2 |
| haiku-5.5 medium | 24,659 | 7.6M | 4.3M | $4 | $2 |
| haiku-5.5 high | 37,145 | 11.5M | 4.3M | $6 | $3 |
| sonnet-5.5 low | 8,711 | 2.7M | 4.3M | $36 | $18 |
| sonnet-5.5 medium | 9,006 | 2.8M | 4.3M | $36 | $18 |
| sonnet-5.5 high | 16,273 | 5.0M | 4.3M | $59 | $30 |
| sonnet-5.5 xhigh | 24,961 | 7.7M | 4.3M | $86 | $43 |
| opus-5.5 medium | 13,788 | 4.3M | 4.3M | $103 | $51 |

- 밀도: 한글 본문 1자 ≈ 1.19 토큰(Sonnet 5.5). 입력 = 본문 3.8M + 청크당 지시문 3k(15쪽 청크 159개).
- Claude Code 서브에이전트로 돌리면 청크마다 하네스 오버헤드(캐시쓰기 약 5~8만, 캐시읽기 약 18만 토큰)가 붙어 API 환산 Sonnet 약 $62, Haiku 약 $6 이 된다. 배치 API 직접 호출이 가장 싸고 플랜 한도를 쓰지 않는다.
- 3단계 판정(상위 모델)은 재검토율 12% 가정 시 약 350건 × (입력 6k + 출력 1.5k + 생각) ≈ 3~4M 토큰(fable medium 기준 API 환산 약 $100). 표본 검토(§3-2)를 10% 로 잡으면 여기에 약 300건이 더해진다.
- 결정: 1단계 Sonnet 5.5 medium(≈7.1M 토큰, 배치 ≈$18) + 3단계 상위 모델. 상법 한 과목을 먼저 끝내고 실제 재검토율로 나머지를 다시 가늠한다.

## 8. 구현 순서는 `spec/TASK-pdf2md.md`
