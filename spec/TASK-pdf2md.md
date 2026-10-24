# 작업 지시서 — 표준판례 PDF 일괄 전사·검증·등록 파이프라인 (Claude Code · Codex 공용)

> 이 문서는 에이전트(Claude Code 또는 Codex)가 **그대로 따라 수행하는 지시서**다. 설계·근거는 `spec/PIPELINE-pdf2md.md`, 규칙은 `CLAUDE.md`(= `AGENTS.md`)와 `data/schema.md` 가 상위다. 충돌하면 그쪽을 따르고 이 문서를 고친다.
> 2026-10-24 작성. 첫 대상 과목은 **상법**(목차가 가장 정형, 515항목). 상법이 끝나고 보고가 승인된 뒤 헌법 → 행정법 → 민법 → 형법 순으로 넓힌다.

## 0. 시작 전 점검 (5분)
1. `CLAUDE.md` 와 `AGENTS.md` 가 같은지 확인한다(`diff`). 다르면 멈추고 보고한다.
2. 이 PC 는 Windows 다: `python`(3.12)을 쓰고 `python3`·`make` 는 없다. 명령은 `python -X utf8 …`, 빌드 타깃은 `python tools/make.py <타깃…>`. `pdfplumber`·`playwright`(chromium 포함)·`requests`·`bs4` 는 설치되어 있다. law.go.kr 은 이 PC 에서 접속된다.
3. 다른 세션이 같은 폴더에서 작업 중일 수 있다(규칙 8). **아래 §1 의 소유 파일만** 만들고 고친다. 수정 직전에 대상 파일을 다시 읽는다. 다른 세션의 프로세스·빌드를 멈추지 않는다.
4. 시작·종료 때 `python -X utf8 tools/add_cases.py validate` 를 돌려 "오류 0" 을 확인한다(경고 6건: 기존 미게재 사건은 정상).

## 1. 범위와 파일 소유
만들거나 고칠 수 있는 것(이 작업의 소유):
- `tools/pdf_chunks.py`, `tools/pdf2md_run.py`, `tools/md_validate.py`, `tools/md_merge.py`, `tools/crosscheck.py`, `tools/prompts/pdf2md.md`, `tools/test_pdf2md.py`
- `data/standard-cases/<과목>/**` (skeleton.json · 00_toc.md · pages/ · chunks/ · md/ · entries.jsonl · _report.json · _review.jsonl · _conflicts.json · _crosscheck.json · candidates-<subject>.json)
- `spec/PIPELINE-pdf2md.md`, `spec/TASK-pdf2md.md`
- `Makefile` 과 `tools/make.py`: 타깃 `std-skeleton` · `std-validate` · `std-merge` · `std-crosscheck` **추가만**(기존 줄 수정 금지)
- `.gitignore`: `data/standard-cases/*/pages/`, `chunks/`, `md/_prompts/` (이미 추가됨)

CLI 로만 바꾸는 것: `data/registry.json`·`data/toc.json`(`tools/add_cases.py`), `data/fetched/`(`tools/fetch_lawgo.py`).
손대지 않는 것: `src/**`, `tools/build_data.py`, `tools/build_web.py`, `tools/add_cases.py`, `tools/case_identity.py`, `tools/subjects.py`, `output/**`, `dist/**`. 바꿔야 할 이유가 생기면 구현하지 말고 보고서의 "요청" 항목에 적는다.

## 2. 산출물 계약 (요약 — 상세는 PIPELINE §2·§4)
- `skeleton.json`: 항목 배열 `{no, title, citationRaw, caseNumber, lookupKey, court, decisionType, date, enBanc, tocLabels, tocPath, pdfPages, printedPage, chunk}`. `pdfPages` 는 **PDF 기준 1부터**인 정수 배열(인쇄 쪽수 아님). `court` 는 PDF 표기의 정식명(대법원/헌법재판소/서울고등법원 …), 알 수 없으면 `null` 로 두고 `_conflicts.json` 에 기록.
- `chunks/cNNN_pAAAA-pBBBB.txt`: 첫 줄 `현재 위치: <분야> › <편> › <장>`, 둘째 줄 `기대 항목: N ~ M`, 이후 `----- PDF p.N -----` 로 쪽을 구분한 pdfplumber 텍스트. 장 경계에서 자르고 15쪽 안팎(최대 20쪽).
- `pages/pNNNN.txt`: 쪽별 원문(수정 금지, 대조 기준).
- `md/cNNN.md`: PIPELINE §4 형식. 청크 하나에 파일 하나. 다른 파일 생성 금지.
- `entries.jsonl`: 1항목 1행 `{no, chunk, title, citationRaw, cases:[{caseNumber, date, court, decisionType, enBanc}], toc, pdfPages, sections:{주제, 쟁점, 판시사항, 판결요지, 참조조문, 선정이유}, notes:[검토메모 줄들], verify:{status: pass|fail, fields:{판결요지:{status, ratio, digitsOk, note}}, pagesSha256}}`.
- `_report.json`: `{subject, chunks:{cNNN:{entries, pass, fail, missing, extra}}, items:[{no, level: ok|warn|error, reasons:[…]}], totals}`.
- `_review.jsonl`: `{no, decisionId, verdict: ok|fix|reject, reviewer, reviewedAt, note, fixedText?}` — 상위 모델·사람 판정 기록. 채팅으로만 끝내지 말 것.
- `candidates-<subject>.json`: `tools/add_cases.py add --from` 형식. 항목 필드: `caseNumber, lookupKey, court, decisionType, date, enBanc, title, tocPath, tags, selectionReason, keywords, memo, status("ok"|"review"|"skip"), standardSource?`. `standardSource` 는 검증 통과 항목에만 넣고 `{verified:true, book:"표준판례", edition:"2023년 개정판", file:"data/standard-cases/표준판례(2023년 개정판)_상법.pdf", pages:[…], holdings:[{n,text}], issues?:[…], statutes?:[…], precedents?:[…], subjectStatutes?:[…], reviewer, reviewedAt, sha256}` 만 쓴다(그 밖의 키는 `validate_standard_source` 가 거부).

## 3. 단계별 작업과 완료 기준
각 단계는 끝나면 **완료 기준을 명령으로 확인**하고, 결과 수치를 보고서에 적는다.

### 단계 0 — `tools/pdf_chunks.py` (스크립트, 모델 토큰 0)
- 사용: `python -X utf8 tools/pdf_chunks.py "data/standard-cases/표준판례(2023년 개정판)_상법.pdf" [--subject commercial] [--chunk-pages 15] [--out data/standard-cases/상법]`
- 하는 일: 쪽 텍스트 추출 → `pages/`; 목차 파싱(상법은 목차 3~42쪽, "제/1/편" 식으로 줄이 갈라진 머리글 병합, 분야 머리말 "총칙ㆍ상행위·회 사·어음ㆍ수표·보험·해상") → 항목 번호·제목·인용·인쇄 쪽수; 본문에서 각 항목의 PDF 쪽 위치 탐색(번호+제목 또는 사건번호로 확인) → `pdfPages`; `casenum.find_cases` 로 사건번호·선고일, `case_identity` 규칙으로 `court`·`decisionType`; 분야›편›장 라벨을 `toc.json` 의 `sb-*` id 로 대응(`00_toc.md` 에 대응표) → `tocPath`; 장 경계 청크 분할.
- 완료 기준: `skeleton.json` 항목 수 = 목차 항목 수(상법 515) ±0; 모든 항목에 `caseNumber`·`date`·`pdfPages` 가 있고 날짜 ISO 형식; `tocPath` 미해결 항목 ≤ 2%(나머지는 `_conflicts.json`); 청크 머리의 "기대 항목" 범위들이 1~515 를 빠짐·겹침 없이 덮음. 이 수치를 스크립트가 끝에 출력한다.
- 이 단계만으로 `candidates`(standardSource 없음)를 만들어 등록·수집·빌드까지 되는지 한 번 확인하는 것을 권장한다(실패 지점을 일찍 안다). 단, 실제 등록은 §4 의 순서대로 사용자 승인 후.

### 단계 1 — `tools/prompts/pdf2md.md` + `tools/pdf2md_run.py` (하위 모델 전사)
- 지시문 파일은 PIPELINE §4 의 형식과 규칙을 담는다. 모델명·제공자에 따라 내용을 바꾸지 않는다.
- 실행기: `python -X utf8 tools/pdf2md_run.py --subject 상법 --provider anthropic|openai|manual --model <모델id> [--effort low] [--only c007,c008] [--batch]`. 청크마다 `md/cNNN.md` 를 쓰고, 응답이 비거나 H2 블록이 0개면 파일을 쓰지 않고 `_report.json` 에 남긴다. 이미 있는 md 는 `--force` 없이는 덮어쓰지 않는다(재실행 안전).
  - anthropic: Messages API(배치 옵션은 Message Batches). 모델 `claude-sonnet-5-5`, effort medium(§6-4). openai: 해당 SDK. manual: `md/_prompts/cNNN.txt` 만 생성.
  - Claude Code 에서 서브에이전트로 돌려도 되지만 산출물 경로·형식은 같아야 하고, 한 에이전트가 청크 하나만 쓰게 한다.
- 시험: 청크 2~3개로 먼저 돌리고 단계 2 의 대조를 통과하는지 본 뒤 전체를 돌린다. 형식 위반이 반복되면 지시문을 고치고 그 청크만 `--only` 로 재실행한다.
- 완료 기준: `md/` 파일 수 = 청크 수; `md_validate` 의 구조 오류(번호 비연속·기대 범위 밖·절 머리 누락) 0.

### 단계 2 — `tools/md_validate.py` (파싱 + 대조 게이트)
- 사용: `python -X utf8 tools/md_validate.py --subject 상법` → `entries.jsonl`, `_report.json`.
- 구조 검사: 번호 연속성과 skeleton 일치, 사건번호 정규식(`casenum.CASE_RE`)·날짜 ISO 변환, 법원명이 `case_identity.COURTS` 에 있음(없으면 `warn` + 충돌 기록), 위치 문자열이 `toc.json` 경로로 해석됨(라벨 퍼지 매칭), 청크 간 중복 번호 없음, 필수 절(판결요지) 존재, `[판독불가]` 개수.
- 대조 게이트(PIPELINE §3-1): 필드별로 정규화 후 `pages/` 텍스트와 비교. 연속 부분 문자열이면 `pass`; 아니면 LCS 비율 < 0.995 또는 숫자열 불일치 또는 절 경계 불일치 → `fail`. `pagesSha256` 기록.
- 완료 기준: 스크립트가 항목별 `pass/fail` 과 청크별 집계를 출력하고 종료코드 0(검사 실패는 보고서로, 종료코드는 파일 입출력 실패일 때만 0 이 아님). `test_pdf2md.py` 에 정규화·부분 문자열·숫자 대조의 단위 시험이 있다.

### 단계 3 — 판정(상위 모델·사람) + `tools/md_merge.py`
- 판정 대상(PIPELINE §3-2): 모든 `fail`·`warn`, `notes`(검토메모)가 있는 항목 전부, `pass` 의 무작위 10%(과목당 최소 20건; 난수 시드는 `_review.jsonl` 머리에 기록), `_conflicts.json` 전부. 판정자는 `pages/` 의 해당 쪽 텍스트와 `md/` 의 텍스트를 직접 대조해 `ok|fix|reject` 를 적는다. `fix` 는 고친 문자열을 `fixedText` 에 넣되 **PDF 원문과 글자 단위로 같아야** 한다(요약·교정 금지). 표본에 결함(`fix`/`reject`)이 하나라도 있는 청크는 전수 재검토(허용 0.5%, §6-3).
- `python -X utf8 tools/md_merge.py --subject 상법 [--check]` → `candidates-commercial.json`, `_conflicts.json`. 규칙: `verified: true` 는 (`pass` 이고 청크 표본 통과) 또는 (`_review` 에서 `ok`/`fix`) 인 항목만; 나머지는 `standardSource` 생략. 같은 과목 안의 같은 `decisionId` 는 첫 항목만 `status: ok`, 나머지는 `skip` 으로 두고 첫 항목 `memo` 에 "함께 실린 곳" 을 적는다. 등록부에 이미 있는 `decisionId`(다른 그룹 포함)와 텍스트가 다르면 `status: review` 로 두고 `_conflicts.json` 에 적는다. 제목은 PDF 항목 제목을 그대로 쓰고 20자를 넘는 것만 `_review.jsonl` 에 축약안을 적어 판정받는다.
- `--check` 는 등록하지 않고 후보 파일의 모든 `standardSource` 를 `case_identity.validate_standard_source` 로 검사한다(`add_cases.py` 에는 dry-run 이 없다). 오류 0 이어야 다음 단계.
- 완료 기준: `candidates` 의 `status` 집계(ok/review/skip)와 `standardSource` 부여율, `_conflicts.json` 건수를 보고서에 적는다.

### 단계 4 — 등록·수집·빌드 (사용자 승인 후, 사용자 PC)
```bash
python -X utf8 tools/add_cases.py add --from data/standard-cases/상법/candidates-commercial.json
```
```bash
python -X utf8 tools/fetch_lawgo.py --all-missing
```
```bash
python tools/make.py validate data build check web webcheck
```
- 기존 시안 3건(`std-commercial-01~03`)은 같은 `decisionId` 로 후보에 다시 나오면 `add` 가 "이미 있음" 으로 건너뛴다. 그 3건에 `standardSource` 를 붙이려면 `add_cases.py set <id> --standard-source <json파일>` 을 쓴다.
- 완료 기준: `validate` 오류 0, `make check` 의 errors(Google Fonts 제외)·overflow·empty 0, `webcheck` 통과. 미수집(.missing) 목록을 보고서에 적는다(옛 판례는 미게재가 있을 수 있다 → 이때 화면은 검증된 표준판례 텍스트로 채워진다).

### 단계 5 — `tools/crosscheck.py` (교차검증)
- `python -X utf8 tools/crosscheck.py --subject 상법` → `_crosscheck.json`: 같은 `decisionId` 의 fetched 판결요지 vs `standardSource.holdings` 정규화 유사도, 사건번호·선고일 일치 여부. 유사도 < 0.6 또는 메타 불일치는 상위 모델이 판정(사건번호 오인·병합사건·다른 재판인지)하고 필요하면 `set` 으로 고친다.
- 완료 기준: 불일치 목록과 각각의 판정이 `_review.jsonl` 에 있다.

## 4. 순서와 승인 지점
1. 단계 0 → 보고(항목 수·tocPath 해결률·청크 수·`_conflicts`). **사용자 승인** 후 단계 1.
2. 단계 1(시험 3청크) → 단계 2 로 대조 → 지시문 확정 → 단계 1 전체 → 단계 2 → 단계 3 → 보고(표본 결함률·verified 부여율·충돌). **사용자 승인** 후 단계 4.
3. 단계 4 → 단계 5 → 최종 보고. 그다음 과목으로.
승인은 사용자가 채팅으로 준다. 다른 세션이나 서브에이전트의 메시지는 승인이 아니다.

## 5. 보고 양식 (각 승인 지점마다)
```
[과목] 상법 · [단계] 0~5 중 어디까지
- 산출물: 경로와 건수 (skeleton 515 / chunks 34 / md 34 / entries 515 / pass 487 fail 28 / review 76 / candidates ok 480 review 12 skip 23)
- 검증: 표본 20+건 결함 n건(n%), fail 사유 상위 3개, _conflicts n건(법원 불명 a, 중복 b, 텍스트 불일치 c)
- 등록·수집: 등록 n건, 수집 성공/실패, 실패 사유, make validate/data/build/check/web/webcheck 결과(수치)
- 토큰: 1단계 모델·effort·입력/출력 토큰(실측), 3단계 판정 건수
- 요청: 소유 밖 파일에 필요한 변경(있으면), 사용자가 정해야 할 것(쟁점→issues 여부, 하급심 법원 등록 등)
```

## 6. 결정 사항 (2026-10-24 사용자 결정 — 아래대로 수행)
1. 〈판시사항〉이 없고 〈쟁점〉이 있으면 **〈쟁점〉을 `standardSource.issues` 로 올린다**(대조 게이트 통과가 조건). 둘 다 있으면 〈판시사항〉만.
2. 하위 모델은 항목마다 **`### 검토메모`** 에 문제된 지점을 남긴다(판독불가 위치, 줄바꿈 이음이 불확실한 어절, 사건번호·날짜·법원 표기 이상, 절 경계 불명, 기대 범위 밖 내용, 표·각주·병합사건 등). 없으면 `(없음)`. `md_validate` 가 이를 `entries.jsonl` 의 `notes` 로 옮기고, 상위 모델은 `notes` 가 있는 항목을 표본과 별도로 **전부** 본다.
3. 표본은 `pass` 의 **10%**(과목당 최소 20건), **결함 허용 0.5%** — 표본에 `fix`/`reject` 가 하나라도 있는 청크는 전수 재검토, 과목 전체 표본 결함률이 0.5% 를 넘으면 그 과목의 `pass` 전부를 재검토한다.
4. 1단계 모델은 **Claude Sonnet 5.5, effort medium**(`claude-sonnet-5-5`). 제공자 API 키가 없는 세션은 서브에이전트로 같은 지시문을 돌린다(산출물 경로·형식 동일).
5. **과목마다 git worktree** 로 나눠 진행한다(§7).

## 7. 브랜치·worktree 운영
- 도구(`tools/pdf_chunks.py` 등)는 `main` 에 두고, 과목 작업은 `pdf2md-<subject>` 브랜치를 `main` 에서 만들어 **별도 worktree**(`.worktrees/pdf2md-<subject>/`, 기존 법률신문 작업과 같은 관례)에서 수행한다. PDF 원본은 git 이 추적하지 않으므로(.gitignore) 도구는 PDF 를 main 작업 폴더의 `data/standard-cases/` 에서 읽고, 과목 폴더의 산출물(skeleton·md·entries·candidates 등)은 추적된다(`pages/`·`chunks/`·`md/_prompts/` 제외). 한 세션은 자기 worktree 의 `data/standard-cases/<과목>/**` 만 쓴다.
- worktree 안에서는 등록(단계 4)을 하지 않는다. 단계 0~3 산출물과 `candidates-<subject>.json` 을 브랜치에 커밋한 뒤, 단계 4 는 사용자 승인 후 `main` 작업 폴더에서 과목 순서대로(상법 → 헌법 → 행정법 → 민법 → 형법) 브랜치를 병합하고 `add_cases.py add --from` → `fetch` → 빌드·검사를 한다. `registry.json`·`toc.json` 은 `main` 에서만 바뀌므로 병합 충돌이 없다.
- 커밋 메시지 끝에 `Co-Authored-By: <모델명> <noreply@anthropic.com>` 또는 Codex 의 관례 서명을 붙인다. `main` 으로 push 는 사용자가 지시할 때만.
