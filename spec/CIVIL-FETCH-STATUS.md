# 민법 표준판례 공식 전문 수집 상태 — 2026-10-24

law.go.kr 에서 민법 표준판례 917건의 공식 전문을 `tools/fetch_lawgo.py` 로 추출해 `data/fetched/` 에 보존했다. 등록부·목차·표준판례 출처(`standardSource`)·기존 공식 수집 파일은 수정하지 않았다(새 파일만 추가).

## 결과
| 구분 | 건수 |
|---|---:|
| 민법 표준판례 등록 | 917 |
| 공식 전문 수집 | **907** (기존 3 + 이번 904) |
| 미수집 | 10 (모두 `.missing.json` 기록, 아래 표) |

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

## 미수집 10건 (모두 판단 대기)
| id | 사건번호 | 원인 | 처리 |
|---|---|---|---|
| std-civil-62 | 93다2636 | std-civil-61(93다2629·93다2636)과 같은 재판이 별도 등록됨 | 61 에 공식 본문 있음. 병합·삭제는 확인 후 |
| std-civil-70 | 2013다79894 | std-civil-69 와 같은 재판 | 위와 같음 |
| std-civil-95 | 93다31641 | std-civil-94 와 같은 재판 | 위와 같음 |
| std-civil-122 | 2009다50398 | 표준판례 PDF 출처줄이 2009다50398 로 적혀 있으나 공식은 **2009다50308**(precSeq 144851, 선고일·쟁점 일치) | 식별 필드 변경 필요 — 사용자 확인 후 add_cases.py |
| std-civil-827 | 2015드8351 | PDF 출처줄이 '드'. 공식은 **2015므8351 전원합의체 판결**(precSeq 226415, 2020-06-18) | 위와 같음(사건번호·전원합의체 여부 변경) |
| std-civil-141 | 91다32053 | law.go.kr 미게재(검색 8회). 같은 판결이 PDF 에 두 항목(소멸시효의 기산점·중단사유)으로 수록 | 미게재 유지 |
| std-civil-379 | 91다44407 | law.go.kr 미게재(검색 6회) | 미게재 유지 |
| std-civil-398 | 72다1159 | law.go.kr 미게재(검색 7회) | 미게재 유지 |
| std-civil-731 | 75다396 | law.go.kr 미게재(검색 5회), PDF 출처줄 비정형 | 미게재 유지 |
| std-civil-850 | 2000다64502 | law.go.kr 미게재(검색 9회) | 미게재 유지 |

미게재는 나중에 `python -X utf8 tools/fetch_lawgo.py --all-missing --retry-missing` 로 재시도할 수 있다. 다른 사이트의 텍스트는 규칙 1에 따라 `fetched/` 에 넣지 않았다.

## 검증
- `make validate`: 오류 0. `make data build web` 성공(수록 3,236건; 전문 수는 마지막 2건 수집 전 빌드 기준 1,478건). `make webcheck`(HTTP·오프라인·갱신 거부 등) 통과. **`make check`(화면 전수 sweep)는 45분 이상 돌았으나 끝나지 않아 중단했다 — 통과로 보고하지 않는다.** 필요하면 사용자가 직접 `python tools/make.py check` 를 실행한다.
- 공식 인용문 ↔ 등록부 메타 대조(`fetch_unit.py audit`, crosscheck.py 와 같은 4건): 법원·선고일·유형·사건번호 일치 903건, **불일치 4건**은 아래.
- crosscheck(민법): ok 872 · low-similarity 26 · meta-mismatch 4 · missing 10. low-similarity 26건은 모두 사건번호·선고일·법원·유형이 일치한다. 기존 검토 3건과 이번 23건 모두 같은 재판이며 요지의 서술 범위·표현이 다른 것으로 판정했다(다른 재판 오결합 0).
  - 다만 Haiku 1차 판정은 원문 대조가 필요하다고 따로 적은 곳이 있다: 표준판례 판결요지 문장 누락 의심(std-civil-573, "승낙함으로써 당해 근로관계를" 앞뒤), 오기 의심(std-civil-834 "자(자)"). 표준판례 PDF 원쪽 대조는 하지 않았고 `standardSource` 는 그대로다.

### 메타 불일치 4건 (수정하지 않음)
| id | 사건번호 | 등록부 | 공식 |
|---|---|---|---|
| std-civil-399 | 93다951 | 전원합의체 아님 | 전원합의체 판결 |
| std-civil-815 | 82므59 | 전원합의체 아님 | 전원합의체 판결 |
| std-civil-424 | 2013다63257 | 선고일 2013-12-16 | 2013-12-26 |
| std-civil-840 | 2006므751 | 선고일 2006-07-04 | 2006-07-13 |
선고일은 `decisionId` 에 들어가므로 PDF 와 공식 중 어느 쪽이 맞는지 확인한 뒤 `add_cases.py` 로 처리한다.

## 재현
```bash
python -X utf8 tools/fetch_unit.py plan --subject civil --spec <units-spec.json> --out spec/fetch-units-civil.json
python -X utf8 tools/fetch_unit.py run --plan spec/fetch-units-civil.json --unit u01-general --commit     # worktree 마다
python -X utf8 tools/fetch_unit.py resolve --plan spec/fetch-units-civil.json --unit u01-general --commit
python -X utf8 tools/fetch_unit.py audit --plan spec/fetch-units-civil.json
```
