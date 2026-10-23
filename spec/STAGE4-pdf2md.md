# 단계 4 실행 계획 — 표준판례 후보 등록·수집·빌드 (사용자 승인 후 main 작업 폴더에서)

> 작성 2026-10-24. 단계 0~3 결과는 과목별 브랜치(`pdf2md-<subject>`, worktree `.worktrees/pdf2md-<subject>/`)에 커밋되어 있다.
> 아래는 **승인 후** 순서대로 실행하는 명령이다. 각 과목이 끝날 때마다 `validate` 오류 0 을 확인한다. 실패하면 멈추고 보고한다.

## 0. 전제
- 모든 명령은 main 작업 폴더(`E:\Casebook_workspace\casebook-buildspace`)에서, `python -X utf8` 로 실행한다.
- 등록부·목차는 `tools/add_cases.py` 로만 바뀐다(`add --from`, `toc replace`, `set --toc`, `set --standard-source`).
- 과목 순서: 상법 → 헌법 → 행정법 → 민법 → 형법 (상법은 기존 toc.json 과 일치해 목차 교체가 없다).

## 1. 과목별 절차 (헌법 예; 다른 과목은 이름만 바꾼다)
```bash
git merge --no-edit pdf2md-constitution                      # 1) 브랜치 병합: data/standard-cases/헌법/{candidates-constitution.json, toc-proposed.json, md/, entries.jsonl, _review.jsonl …}
```
```bash
python -X utf8 tools/add_cases.py toc replace --subject constitution --from data/standard-cases/헌법/toc-proposed.json   # 2) 시안용 목차를 PDF 목차로 교체(상법은 생략). 경로를 잃는 시안 사건이 출력된다
```
```bash
python -X utf8 tools/md_merge.py --subject 헌법 --check      # 3) 새 목차 기준으로 candidates 재생성(tocPath proposed → resolved). --check 오류 0 확인 후 실제 실행은 --check 없이 한 번 더
```
```bash
python -X utf8 tools/add_cases.py add --from data/standard-cases/헌법/candidates-constitution.json   # 4) status ok 인 후보 등록(이미 있는 재판은 "이미 있음" 으로 건너뜀)
```
```bash
python -X utf8 tools/standard_source_backfill.py --candidates data/standard-cases/헌법/candidates-constitution.json   # 5) 이미 등록돼 있던 같은 재판(시안 3건·전원합의체·헌법재판소 주요결정)에 표준판례 출처 붙이기
```
```bash
python -X utf8 tools/add_cases.py set std-constitution-01 --toc hb-1-1   # 6) 2) 에서 경로를 잃은 시안 사건의 tocPath 를 후보의 tocPath 로 지정(사건별로 출력된 대로)
```
```bash
python -X utf8 tools/add_cases.py validate                     # 7) 오류 0 확인
```

## 2. 전 과목 등록 후
```bash
python -X utf8 tools/fetch_lawgo.py --all-missing              # 공식 텍스트 수집(약 2,700건, 1.5초 간격 → 70분 안팎; 미게재는 .missing 으로 남고 화면은 검증된 표준판례 텍스트로 채워진다)
```
```bash
python tools/make.py validate data build check web webcheck    # 데이터 생성·단일 HTML·웹앱 빌드·검사
```
```bash
python -X utf8 tools/crosscheck.py --subject 상법               # 5단계 교차검증(과목마다): 공식 요지 vs 표준판례 요지 유사도 → _crosscheck.json, 불일치는 판정
```

## 3. 등록되지 않는 것(설계대로)
- `status: skip` — 같은 과목 안의 같은 재판 중복(첫 항목만 등록, 나머지 위치는 memo "함께 실린 곳").
- `status: review` 중 `standardSource` 가 없는 항목 — 판정 reject(다른 재판의 텍스트가 붙은 PDF 오류 등) 또는 대조 미통과. 사건 자체는 등록되지만 표준판례 텍스트 없이 공식 자료만 표시된다. 목록은 각 과목의 `_conflicts.json`(stage3) 과 `_review.jsonl`(verdict reject) 에 있다.
- `multi-case` 항목(한 항목에 재판이 둘 이상, 형법 14건 등) — 첫 재판만 등록되고 나머지는 `_conflicts.json` 에 남는다. 추가 등록은 수동.

## 4. 되돌리기
- 등록 전 상태로 돌아가려면 `git checkout -- data/registry.json data/toc.json` (병합 커밋 전) 또는 병합 커밋을 `git revert`. `fetched/` 에 새로 받은 파일은 지워도 된다(다시 받으면 된다).
