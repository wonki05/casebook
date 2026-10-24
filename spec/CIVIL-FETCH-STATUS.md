# 민법 표준판례 공식 전문 수집 상태 — 2026-10-24

law.go.kr 에서 민법 표준판례 917건의 공식 전문을 `tools/fetch_lawgo.py` 로 추출해 `data/fetched/` 에 보존했다. 수집 단계에서는 등록부·목차·`standardSource`·기존 공식 수집 파일을 수정하지 않았고, 이후 아래 "등록부 정정"의 6건만 `add_cases.py` 로 고쳤다.

## 결과
| 구분 | 건수 |
|---|---:|
| 민법 표준판례 등록 | 934 (PDF 항목 917 + 같은 과목 중복 배치 17) |
| 공식 전문 수집 | **925** (917 중 909 + 중복 배치 16) |
| 미수집 | 9 (모두 `.missing.json` 기록, 아래 표) |

아래 "미수집" 표와 단원 표는 PDF 항목 917건 기준이고, 중복 배치 17건의 수집은 마지막 절에 따로 적었다.

단원 11개를 각각 별도 worktree·브랜치(`fetch-civil-uNN-*`, 폴더 `.worktrees/`)에서 병렬 수집했다. 단원 구성과 id 목록은 `spec/fetch-units-civil.json`, 단원별 결과는 `spec/fetch-reports/civil-*.json`.

| 단원 | 범위 | 건수 |
|---|---|---:|
| u01-general | 총칙 통칙·인·법인·물건 | 59 |
| u02-juristic-act | 총칙 법률행위 | 72 |
| u03-prescription-basics | 소멸시효·물권 총칙·점유권 | 73 |
| u04-ownership | 소유권·지상권 | 99 |
| u05-real-security | 지역권·전세권·유치권·질권·저당권 | 80 |
| u06-obligation-a | 채권총칙 채권의 목적·효력 | 87 |
| u07-obligation-b | 채권총칙 다수당사자·양도·소멸 | 99 |
| u08-contracts | 계약·사무관리 | 99 |
| u09-unjust-tort | 부당이득·불법행위 | 96 |
| u10-family | 친족 | 76 |
| u11-succession | 상속 | 77 |

## 수집 방식과 모델 사용
- **수집 자체는 모델이 필요 없다.** `tools/fetch_unit.py run` 이 청크(15건)별로 `fetch_lawgo.py` 를 돌리고 실패 건을 한 번 더 시도한 뒤 검사·보고서·커밋까지 한다(단원당 8~14분, 11개 동시). 모델 토큰은 쓰지 않았다.
- 한글주소(`/판례/(사건번호)`) 조회는 병합사건(`2013다79887·2013다79894`)과 일부 구 사건에서 실패해 98건이 미게재로 남았다. `fetch_unit.py resolve` 가 law.go.kr 검색으로 **사건번호와 선고일이 등록부와 모두 일치하는 결과가 하나일 때만** 다시 수집해 86건을 되찾았다(남은 12건).
- 판단이 필요한 단계에만 하위 모델을 썼다. 쓰기 권한은 주지 않고 결과를 파일로만 받았다.
  - Sonnet 5.5 medium ×1 — 남은 미게재 9건의 원인 분류(검색 도우미로 읽기 전용): `data/standard-cases/_reports/fetch-civil-miss-triage.json`
  - Haiku high ×2 — crosscheck low-similarity 23건의 "같은 재판의 표기 차이 / 다른 쟁점" 1차 판정, 다르다고 나온 2건은 Sonnet 5.5 가 공식 전문에서 다시 확인: `data/standard-cases/_reports/crosscheck-civil-fetch-review.json`
- 미게재 12건 중 2건(std-civil-810·858)은 위 분류에서 병합사건 조회키 문제로 밝혀져, 확인된 precSeq 로 같은 추출 함수(`fetch_one_pw`)를 호출해 수집했다.

## 미수집 8건 (PDF 항목 917건 중) + 중복 배치 1건(std-civil-918, 91다32053)
| id | 사건번호 | 원인 | 처리 |
|---|---|---|---|
| std-civil-62 | 93다2636 | std-civil-61(93다2629·93다2636)과 같은 재판이 별도 등록됨 | 61 에 공식 본문 있음. 병합·삭제는 확인 후(같은 과목 중복 배치는 허용되나 같은 단원·같은 제목은 중복) |
| std-civil-70 | 2013다79894 | std-civil-69 와 같은 재판 | 위와 같음 |
| std-civil-95 | 93다31641 | std-civil-94 와 같은 재판 | 위와 같음 |
| std-civil-141 | 91다32053 | law.go.kr 미게재(검색 8회). 같은 판결이 PDF 에 두 항목(소멸시효의 기산점·중단사유)으로 수록 | 미게재 유지 |
| std-civil-379 | 91다44407 | law.go.kr 미게재(검색 6회) | 미게재 유지 |
| std-civil-398 | 72다1159 | law.go.kr 미게재(검색 7회) | 미게재 유지 |
| std-civil-731 | 75다396 | law.go.kr 미게재(검색 5회), PDF 출처줄 비정형 | 미게재 유지 |
| std-civil-850 | 2000다64502 | law.go.kr 미게재(검색 9회) | 미게재 유지 |

미게재는 나중에 `python -X utf8 tools/fetch_lawgo.py --all-missing --retry-missing` 로 재시도할 수 있다. 다른 사이트의 텍스트는 규칙 1에 따라 `fetched/` 에 넣지 않았다.

## 검증
- `make validate`: 오류 0. `make data build web` 성공(수록 3,389건, 전문 1,498건). `make webcheck`(HTTP·오프라인·갱신 거부 등) 통과. `tools/` 의 Python 시험 140건 통과. **`make check`(화면 전수 sweep)는 45분 이상 돌았으나 끝나지 않아 중단했다 — 통과로 보고하지 않는다.** 필요하면 사용자가 직접 `python tools/make.py check` 를 실행한다.
- 공식 인용문 ↔ 등록부 메타 대조(`fetch_unit.py audit`): 법원·선고일·유형·사건번호·전원합의체가 일치 908건, 불일치 1건(std-civil-840, 아래).
- crosscheck(민법): ok 872 · low-similarity 26 · meta-mismatch 6 · missing 8. meta-mismatch 6건 중 5건(399·815·424·827·78의 후보 행)은 정정 전 PDF 값을 담은 후보 파일(`candidates-civil.json`, 원전 기록이라 고치지 않음)과 정정된 등록부·공식이 다르다는 뜻이고, 나머지 1건이 std-civil-840이다. low-similarity 26건은 모두 사건번호·선고일·법원·유형이 일치한다. 기존 검토 3건과 이번 23건 모두 같은 재판이며 요지의 서술 범위·표현이 다른 것으로 판정했다(다른 재판 오결합 0).
  - 다만 Haiku 1차 판정은 원문 대조가 필요하다고 따로 적은 곳이 있다: 표준판례 판결요지 문장 누락 의심(std-civil-573, "승낙함으로써 당해 근로관계를" 앞뒤), 오기 의심(std-civil-834 "자(자)"). 표준판례 PDF 원쪽 대조는 하지 않았고 `standardSource` 는 그대로다.

## 등록부 정정 (`add_cases.py`)
| id | 수정 | 변경 전 → 후 | 근거 |
|---|---|---|---|
| std-civil-399 | `set --enbanc yes` | 전원합의체 아님 → 전원합의체 | 공식 인용문 "전원합의체 판결", PDF 285쪽만 표기 없음 |
| std-civil-815 | `set --enbanc yes` | 전원합의체 아님 → 전원합의체 | 공식 인용문 "전원합의체 판결", 2019 전원합의체(2016므2510)가 같은 날짜로 인용, PDF 561쪽만 표기 없음 |
| std-civil-424 | `set --date 2013-12-26` | 선고일 2013-12-16 → 2013-12-26 · decisionId `…20131216…` → `…20131226…` | 공식 페이지와 이를 인용한 공식 판결 5건이 모두 12. 26., PDF 298쪽만 12. 16. |
| std-civil-827 | `set --correct-case 2015므8351` | 2015드8351 → 2015므8351 · caseNumberId `2015x00b4dcz8351` → `2015meu8351` · decisionId `…2015meu8351-20200618-judgment` | PDF 569쪽 출처줄의 '드' 오기. 공식 2015므8351 전원합의체 판결(precSeq 226415). 법률신문 `annual-2020-91` 과 같은 재판 |
| std-civil-122 | `set --correct-case 2009다50308` | 2009다50398 → 2009다50308 · caseNumberId `2009da50398` → `2009da50308` · decisionId `…2009da50308-20100715-judgment` | PDF 86쪽 출처줄의 오기. 공식 2009다50308(precSeq 144851). 같은 과목 `std-civil-78` 과 같은 재판 → 다른 단원·다른 제목의 중복 배치로 허용 |
| std-civil-78·122 | `set --standard-source` | 두 배치의 issues·holdings 를 같은 텍스트로 | 검증된 구절의 글자 그대로의 합집합(issues 2 · holdings 4, 새 문장 없음). 쪽수는 각자(57,58 / 86). sha256 은 텍스트가 바뀌어 비움 |
| std-civil-840 | 변경 없음 | 선고일 2006-07-04 유지 | PDF 580쪽과 이후 공식 판결 6건은 7. 4., 2건과 공식 페이지 머리말만 7. 13. |
이전 decisionId 는 모두 `identityAliases` 에 새 ID 로 이어 두었다. 공식 전문은 std-civil-122·827 만 새로 수집했고(각각 78·`annual-2020-91` 과 본문 동일) 399·815·424 는 본문이 같아 다시 받지 않았다. 웹 묶음의 전문은 해시로 저장되어 같은 재판의 배치가 늘어도 한 번만 들어간다.

## 같은 과목 중복 배치 (정책 변경과 등록)
`add_cases.py` 는 같은 과목에서 같은 재판을 단원에 맞는 다른 제목으로 한 번 더 배치하는 것을 허용한다(제목이 같을 때만 중복). 이전에는 거절해서 PDF 가 같은 재판을 여러 항목에 실은 경우 첫 항목만 등록했다. 그렇게 건너뛴 항목(`_conflicts.json` 의 `duplicate`)을 `tools/dup_placements.py` 로 등록했다.

| 과목 | 등록 | id 범위 | 같은 단원 안(제목만 다름) |
|---|---:|---|---:|
| 민법 | 17 | std-civil-918~934 | 4 |
| 상법 | 31 | std-commercial-486~516 | 9 |
| 행정법 | 30 | std-administrative-457~486 | 8 |
| 헌법 | 42 | std-constitution-288~329 | 11 |
| 형법 | 33 | std-criminal-473~505 | 9 |
| 합계 | **153** | 건너뜀 0 | 41 |

- 배치 정보(PDF 제목·목차 경로·선정이유·키워드)만 등록하고 `standardSource` 는 붙이지 않았다. 표준판례 텍스트는 같은 `decisionId` 의 첫 배치에 한 번만 있고 `build_data` 가 모든 배치에 적용한다. 따라서 이 배치들의 표준판례 출처 쪽수는 첫 배치의 쪽수로 표시된다.
- 건너뛴 항목에만 있는 문구(주로 그 항목의 쟁점)는 검토메모 판정(Opus) 없이 쓰지 않았다. 필요하면 판정 후 합집합으로 더한다(std-civil-78·122 처럼).
- 제목이 첫 배치와 같은 1건(민법 639번)은 "제목：단원이름"으로 구별했다. 각 배치의 memo 에 "같은 재판의 다른 배치: 첫 배치 제목(id) — PDF n번 항목, p.m"을 남겼다.
- 공식 전문은 민법 17건만 수집했다(16건 성공, std-civil-918 은 std-civil-141 과 같은 재판으로 law.go.kr 미게재). 나머지 136건은 그 과목의 공식 전문 수집 때 `fetch_lawgo.py --all-missing` 이 받는다. 웹 묶음의 전문은 해시로 한 번만 저장된다.
- 보고서: `data/standard-cases/_reports/dup-placements-<과목>.json`, 민법 수집 `spec/fetch-reports/civil-dup-placements.json`.

## 재현
```bash
python -X utf8 tools/fetch_unit.py plan --subject civil --spec <units-spec.json> --out spec/fetch-units-civil.json
python -X utf8 tools/fetch_unit.py run --plan spec/fetch-units-civil.json --unit u01-general --commit     # worktree 마다
python -X utf8 tools/fetch_unit.py resolve --plan spec/fetch-units-civil.json --unit u01-general --commit
python -X utf8 tools/fetch_unit.py audit --plan spec/fetch-units-civil.json
```
