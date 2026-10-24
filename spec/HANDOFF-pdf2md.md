# 인수인계 — 표준판례 PDF 일괄 전사 파이프라인 (2026-10-24 중단 시점)

> **2026-10-24 Codex 후속 상태:** 사용자가 이 세션에서 계속 진행하도록 지시하여 모델을 대체했다. 아래 내용은 이전 중단 시점 기록이다. 현재 등록·검증·환경 제약은 [PDF2MD-CODEX-STATUS.md](PDF2MD-CODEX-STATUS.md)를 먼저 확인한다.

> 이 문서는 **이 작업을 이어받는 에이전트(Claude Code 또는 Codex)** 가 처음 읽는 문서다. 규칙은 `CLAUDE.md`(= `AGENTS.md`), 절차는 `spec/TASK-pdf2md.md`, 설계는 `spec/PIPELINE-pdf2md.md`, 단계 4 실행은 `spec/STAGE4-pdf2md.md`. 이 문서는 "지금 어디까지 되어 있고, 다음에 무엇을 어떤 순서로 하는가"만 적는다.
> 사용자 지시(2026-10-24): 겹침 재판 종합·검증을 끝낸 뒤, 남은 작업(단계 4 전체)은 **Opus 5.5, effort max** 에이전트가 수행한다. 모든 등록·수집·빌드는 main 작업 폴더에서만 한다.

## 0. 환경 메모 (먼저 확인)
- 작업 폴더 `E:\Casebook_workspace\casebook-buildspace`(main). Windows: `python`(3.12) 사용, `python3`·`make` 없음. 한글 출력은 `python -X utf8 …`, 빌드는 `python tools/make.py <타깃…>`. `pdfplumber`·`playwright(chromium)` 설치됨. law.go.kr 접속 가능.
- **다른 세션이 같은 폴더에서 동시에 작업 중**(규칙 8): main 작업 트리에 `src/design-d.html`·`tools/build_data.py`·`tools/subjects.py`·`tools/sweep.py`·`CLAUDE.md` 등 **다른 세션의 미커밋 변경**이 있다. 건드리지 말고, 커밋할 때는 자기 파일만 `git add <경로>` 로 지정한다(`git add -A` 금지). 수정 직전에 대상 파일을 다시 읽는다.
- git worktree 관례: `.worktrees/<브랜치>/`. 파이프라인 worktree 는 `pdf2md-constitution·administrative·civil·criminal·commercial·overlaps`(브랜치 이름 동일). 법률신문 작업의 `annual-*` worktree 도 있다(다른 세션 소유).
- Bash 도구에서 heredoc 안의 백슬래시가 깨지는 일이 있었다. 긴 파이썬 패치는 파일로 써서 `python 파일` 로 실행하는 편이 안전하다.
- PDF 원본(`data/standard-cases/*.pdf`)과 `pages/`·`chunks/` 는 git 이 추적하지 않는다. worktree 에서 `pdf_chunks.py` 를 돌리면 PDF 는 main 폴더에서 읽는다. `pages/`·`chunks/` 는 각 과목 worktree 에 이미 생성돼 있다(없으면 `python -X utf8 tools/pdf_chunks.py <과목> --out data/standard-cases/<과목>` 으로 다시 만들 수 있다).

## 1. 현재 상태 (모두 커밋됨)
| 과목 | 브랜치 / worktree | 항목 | 검증 pass/fail | Opus 판정 | standardSource(검증된 표준판례 텍스트) | 후보 상태 |
|---|---|---|---|---|---|---|
| 헌법 | `pdf2md-constitution` | 329 | 319 / 8 (skip 2) | 완료, 판정 대기 0 | 284건 (99.0%) | review 287 / skip 42 — 모두 "tocPath proposed"(목차 교체 후 ok 로 바뀜) |
| 행정법 | `pdf2md-administrative` | 485 | 480 / 5 | 완료, 판정 대기 0 | 454건 (99.6%) | review 456 / skip 30 — 위와 같음 |
| 민법 | `pdf2md-civil` | 930 | 925 / 5 | 완료, 판정 대기 0 | 912건 (99.5%) | review 917 / skip 17 — 위와 같음 |
| 형법 | `pdf2md-criminal` | 498 | 493 / 5 | 완료, 판정 대기 0 | 457건 (96.8%) | review 472 / skip 33 — 위와 같음 |
| 상법 | `pdf2md-commercial` | 516 | 503 / 13 | 완료, 판정 대기 0 | 483건 (99.4%) | **ok 484** / review 2 / skip 31 (상법은 toc.json 이 이미 PDF 목차) |
- 표본(과목당 pass 의 10%, 최소 20건) 결함률은 다섯 과목 모두 0%.
- 과목 폴더(`data/standard-cases/<과목>/`)의 파일: `skeleton.json`·`00_toc.md`·`toc-proposed.json`·`md/cNNN.md`(전사)·`entries.jsonl`·`_report.json`·`_review.jsonl`(판정 기록)·`_review_in/`·`_review_parts/`·`candidates-<subject>.json`·`_conflicts.json`.
- 도구(모두 main 에 커밋, 시험 63건 통과): `pdf_chunks.py`(단계 0) · `prompts/pdf2md.md` · `pdf2md_run.py`(API 실행기; 이번엔 서브에이전트로 전사) · `pdf2md_lib.py` · `md_validate.py` · `md_merge.py`(`--overlap-final` 포함) · `review_prep.py` · `review_collect.py` · `crosscheck.py` · `standard_source_backfill.py` · `overlap_prep.py` · `overlap_check.py` · `overlap_apply.py` · `stage4_subject.py` · `add_cases.py`(`toc replace` 추가, 표준판례 중복 판정을 과목 단위로 완화).
- main 등록부는 다른 세션의 법률신문 수집이 병합되어 현재 634건(검증 오류 0).

## 2. 겹침 재판 22건 (두 과목 PDF 에 같은 재판) — **진행 중, 여기서 이어받는다**
- 위치: `.worktrees/pdf2md-overlaps/data/standard-cases/_overlaps/` (브랜치 `pdf2md-overlaps`, 커밋 f89f19b).
  - `overlaps.json` 목록 · `in/<decisionId>.json` 입력 묶음 22건(두 책 절 텍스트·쪽 원문·공식 판시사항/요지/전문) · `in/PROMPT.md` 종합 지시문 · `official/` 공식 텍스트(20건; 2011헌바172등·2015다236820은 law.go.kr 미게재) · `out/` 종합 결과 · `final/` 검증 통과 결과(두 과목 배치용 standardSource).
  - **완료 14건**(`final/*.json`, 글자 대조 통과, 버린 구절 0): 96헌가2, 2019다293449, 2006다24438, 98헌바70, 95누4810, 2011헌바172등, 2007헌라4, 96다18076, 2009다19864, 2011다104246, 99다16378, 89헌마214, 95다38677, 93헌마186.
  - **남은 8건**: `cc-2002heonma337-20030626-decision`, `cc-93heonba21-19941229-decision`, `sc-2000da13887-20020329-judgment`, `sc-2000da37937-20030124-judgment`, `sc-2012do235-20151210-judgment`, `sc-2015da236820-20171222-judgment`, `sc-2020da208621-20210624-judgment`, `sc-90daka23899-19911224-judgment`.
- 이어서 할 일(8건): 사용자 지시대로 **Fable 5.1, effort max** 로 한 재판에 하나씩 — "`in/PROMPT.md` 를 읽고 `in/<id>.json` 을 읽어 `out/<id>.json` 과 `out/<id>.md` 를 쓴다" 는 지시만 주면 된다(다른 파일 접근 금지). 끝나면
  `python -X utf8 tools/overlap_check.py --dir data/standard-cases/_overlaps`(worktree 안에서) → `final/` 22건 확인 → `git add data/standard-cases/_overlaps && git commit`.
- 종합 원칙(변경 금지): 새 문장 금지, 두 PDF 구절의 **글자 그대로 합집합**, 순서·번호는 공식 판결문 기준, 공식 전문에 없는 구절은 제외하고 보고서에 기록. `overlap_check.py` 가 구절마다 PDF 원문과 대조해 다른 것은 버린다.

## 3. 단계 4 — 등록·수집·빌드 (사용자 승인 완료, Opus 5.5 max 가 수행)
`spec/STAGE4-pdf2md.md` 가 기준. 요약:
1. main 에서 과목 브랜치를 순서대로 병합·실행(상법 → 헌법 → 행정법 → 민법 → 형법). `pdf2md-overlaps` 브랜치도 먼저 병합해 `data/standard-cases/_overlaps/final/` 이 main 에 있어야 한다(없으면 겹침 재판이 과목 간 텍스트 충돌로 review 에 남는다).
   ```bash
   git merge --no-edit pdf2md-overlaps
   git merge --no-edit pdf2md-commercial
   python -X utf8 tools/stage4_subject.py --subject 상법 --overlap-final data/standard-cases/_overlaps/final --dry-run
   python -X utf8 tools/stage4_subject.py --subject 상법 --overlap-final data/standard-cases/_overlaps/final
   ```
   실행기는 toc 교체(헌법·행정법·민법·형법만; `toc-proposed.json` → `add_cases.py toc replace`) → `md_merge`(겹침 종합 적용) → `--check` → `add --from` → `standard_source_backfill` → 경로를 잃은 시안 사건 `set --toc` → `validate` 를 돌리고 JSON 요약을 낸다. 과목마다 `validate` 오류 0 을 확인하고 커밋(`data/registry.json data/toc.json data/standard-cases/<과목>` 만 add).
2. 다섯 과목이 끝나면 `python -X utf8 tools/overlap_apply.py --final data/standard-cases/_overlaps/final --dry-run` 으로 두 과목 배치가 같은 종합 텍스트를 갖는지 확인(이미 md_merge 가 넣었으므로 "적용 0 / 미등록 0" 이 정상; 아니면 실제 실행).
3. 수집: `python -X utf8 tools/fetch_lawgo.py --all-missing`(약 2,700건, 1.5초 간격 → 70분 안팎; 백그라운드). 미게재는 `.missing.json` 으로 남는다(정상).
4. 빌드·검사: `python tools/make.py validate data build check web webcheck`. 수록 사건이 48건 → 약 3,400건(법률신문 포함)으로 늘어 `cases.json`·단일 HTML 이 커지고 sweep 이 오래 걸린다. errors(Google Fonts 제외)·overflow·empty 0 확인.
5. 교차검증: 과목마다 `python -X utf8 tools/crosscheck.py --subject <과목>` → `_crosscheck.json` 의 low-similarity·meta-mismatch 를 판정(사건번호 오인·병합사건·다른 재판).
6. 보고: 과목별 등록 건수, standardSource 부여 건수, 수집 성공/실패, validate/check 수치, 교차검증 불일치 목록, 실제 배포(GitHub Pages) 여부는 사용자 지시가 있을 때만.

## 4. 알려진 문제·결정 사항 (이어받는 쪽이 알아야 할 것)
- **목차 교체**: 헌법·행정법·민법·형법의 `toc.json` 은 시안 초안이라 `toc-proposed.json`(PDF 머리글 트리, 유령 노드 제거됨)으로 교체한다. 헌법 `hb-3-4-6/7` 은 제6절 헌법소원심판 아래 로마숫자 절이 절 자리로 올라온 것(기능상 문제 없음). 교체 시 시안 사건 3건/과목의 tocPath 가 비워지고 실행기가 같은 재판 후보의 tocPath 로 다시 지정한다.
- **겹침 재판**은 과목마다 각 책의 제목으로 배치된다(`add_cases.duplicate` 가 표준판례를 과목 단위로 판정). 두 배치의 standardSource 는 종합 텍스트로 **동일**해야 build 가 통과한다(`standard_sources_by_decision` 이 다르면 오류).
- **판정 거부·실패**: 헌법 seq 146(PDF 자체가 다른 재판의 본문을 붙임 → 표준판례 텍스트 없이 등록), 헌법 seq 135·321(fix 재대조 실패), 형법 reject 9건, 상법 reject 3건 등은 `_review.jsonl`(verdict reject)·`_conflicts.json`(stage3) 에 있다. 이들은 사건은 등록되되 표준판례 텍스트 없이 공식 자료만 표시된다.
- **multi-case 항목**(한 항목에 재판이 둘, 형법 14·민법 8·상법 2·행정법 2): 첫 재판만 후보로 들어간다. 나머지는 `_conflicts.json` 에 남아 있으며 추가 등록은 수동.
- **제목 20자 초과**는 Opus 판정의 축약안(`_review.jsonl` reason title, `title` 필드)이 후보 제목에 반영돼 있다.
- `_review.jsonl` 에는 같은 판정이 재수거로 중복 기록된 줄이 있다(마지막 줄이 유효). `review_collect.py` 는 이제 중복을 넣지 않는다.
- 전사 지시문 `tools/prompts/pdf2md.md` 에 `<판결요지(다수의견)>`·`<판결이유>` 같은 변형 절 제목 규칙이 없다(검증기는 허용). 다음 판본 작업 전에 보강 권장.
- `tools/casenum.py`·`case_identity.CASE_SYMBOLS` 에 추·무·부·드·재도 등 사건부호가 없어 `pdf_chunks.py` 가 자체 보조 정규식으로 처리한다. 등록 시 그런 사건번호는 x-hex 인코딩 id 를 받는다(허용된 규칙). 공유 모듈 보강은 요청으로 남긴다.
- 토큰 실측: Sonnet 5.5 medium 전사 152청크 ≈ 출력 7M 토큰(서브에이전트 오버헤드 포함 약 20M); Opus 5.5 판정 ≈ 330묶음; Fable 5.1 종합 14건. 상세는 `spec/PIPELINE-pdf2md.md` §7.

## 5. 되돌리기
- main 등록부·목차는 단계 4 를 시작하기 전까지 변하지 않았다(현재 634건은 법률신문 수집분). 단계 4 는 과목마다 커밋하므로 `git revert` 로 되돌린다. 새로 받은 `data/fetched/<id>.json` 은 지워도 된다.
