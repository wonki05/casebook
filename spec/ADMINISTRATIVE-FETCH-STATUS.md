# 행정법 표준판례 공식 전문 수집 상태 — 2026-10-28

law.go.kr 에서 행정법 표준판례의 공식 전문을 `tools/fetch_lawgo.py` 로 추출해 `data/fetched/` 에 보존했다. 이 작업은 **커밋하지 않았다**(요청: 수집까지). 수집 단계에서 등록부·목차·`standardSource` 는 수정하지 않았다.

## 결과
| 구분 | 건수 |
|---|---:|
| 행정법 표준판례 등록 | **486** |
| 전문 있음 — law.go.kr 공식 수집 | **481** (이번 수집 477 + 이전 수집 4) |
| 전문 없음 | **5** — std-administrative-36·40·107·291·417 |

단원 8개를 각각 별도 worktree(`.worktrees/fetch-adm-uNN-*`, 브랜치 `fetch-adm-uNN-*`)에서 병렬 수집했고 결과 파일만 통합 worktree(`casebook-administrative-integration-20261028-173625`, 브랜치 `administrative/integrate-20261028-173625`)로 복사했다. 단원 구성은 `spec/fetch-units-administrative.json`, 단원별 결과는 `spec/fetch-reports/administrative-*.json`.

| 단원 | 범위 | 전체 | 수집 | 전문 없음 |
|---|---|---:|---:|---:|
| u01-gen-intro-infodisclosure | 총론 서론(행정과 행정법·법원·행정법관계) + 정보공개 | 62 | 61 | 36 |
| u02-gen-administrative-act | 총론 행정행위 | 64 | 63 | 40 (95 는 아래) |
| u03-gen-other-forms-procedure | 행정행위 이외의 작용형식 + 행정절차 | 72 | 71 | 107 |
| u04-remedy-state-compensation | 행정상 손해전보 | 61 | 61 | – |
| u05-remedy-suit-requirements | 항고소송의 소송요건 | 67 | 67 | – |
| u06-remedy-appeal-trial-judgment | 이의신청·행정심판·가구제·심리·판결·당사자소송 | 54 | 53 | 291 |
| u07-enforcement-organization | 실효성 확보수단 + 행정조직·지방자치·공무원 | 65 | 65 | – |
| u08-special-administrative-law | 개별행정법 | 41 | 40 | 417 |

## 수집 방식과 모델 사용
- 수집은 모델 없이 `tools/fetch_unit.py run`(청크 수집→실패 재시도→검사) 뒤 `resolve`(사건번호·선고일이 모두 일치할 때만 검색으로 수집)로 했다. 8개 worktree 동시 실행, 단원당 7~12분.
- 판단이 필요한 단계에만 저가 모델을 읽기 전용으로 썼다(저장소 쓰기 없음, 결과는 JSON 파일로만).
  - Haiku(xhigh) ×2 — crosscheck low-similarity 31건 중 스크립트(책 판결요지 10글자 조각이 공식 전문에 든 비율 0.95 이상)가 걸러내지 못한 10건의 1차 판정. 결과 10건 모두 "같은 재판의 발췌·표기 차이(법리 모순 없음)". 입력·결과: 스크래치패드 `review/` (보존 안 함).
  - Sonnet(high) ×1 — 미게재 6건의 원인 조사(law.go.kr + 종합법률정보 포털). 6건 중 1건(95)은 병합 표기로 조회가 안 된 것이었고 직접 확인해 수집했다.
  - 모델 판정 중 영향이 큰 것(95 수집, 36·40 후보)은 직접 페이지를 열어 선고일·판시사항을 다시 확인했다.
- 종합법률정보의 주소는 glaw.scourt.go.kr 이 이 환경에서 해석되지 않아 `portal.scourt.go.kr`(종합법률정보 포털)로 검색했다.

## 전문이 없는 5건
| id | 사건번호 | 선고일 | 제목 | 쪽 | 확인 결과 |
|---|---|---|---|---|---|
| std-administrative-36 | 2017두74302 | 2019-10-31 | 중대한 공익상 필요로 인한 수리거부 | 30~31 | 두 사이트 모두 없음. 같은 날 대법원 **2017두74320**(건축신고반려처분취소, precSeq 210441)이 제목과 맞음 — 끝 두 자리 오기 의심 |
| std-administrative-40 | 2020두39356 | 2022-01-27 | 대물적 행정행위 | 33 | 두 사이트 모두 없음. 같은 날 **2020두39365**(업무정지처분취소, precSeq 219319)가 제목과 맞음 — 끝 두 자리 오기 의심 |
| std-administrative-107 | 90누6613 | 1991-08-27 | 조례와 법률유보, 포괄위임 | 81 | law.go.kr 없음, **종합법률정보 포털에는 있음**(유지점용료부과처분취소, 번호·날짜 일치) |
| std-administrative-291 | 97누15432 | 1998-05-08 | 재결의 효력 | 246~247 | 두 사이트 모두 없음. 인접 번호·선고일 검색에도 후보 없음. 제3자 자료가 같은 번호를 인용해 책의 오기 가능성은 낮음 |
| std-administrative-417 | 85감도356 | 1986-01-28 | 경찰권 발동의 근거규정 | – | std-administrative-416(85도2448·85감도356, 같은 날·같은 제목·같은 목차, **수집됨** precSeq 101381)의 중복 배치로 보임 |

## 사용자 확인이 필요한 식별 정보 불일치
수집 파일은 공식 그대로이며, 등록부(책 출처줄)와 다른 곳이다. 자동으로 고치지 않았다.

| id | 사건번호 | 등록부 | 공식 | 비고 |
|---|---|---|---|---|
| std-administrative-31 | 2015두295 | 전원합의체 아니오 | 전원합의체 | 같은 재판의 std-administrative-472 는 "예". 책 출처줄: 31 은 표기 없음(c002), 472 는 "전원합의체 판결"(c017) |
| std-administrative-44 | 2013두987 | 2015-02-15(일요일) | 2015-02-12 | 같은 재판 std-administrative-311 은 2015-02-12(c018). 별도 재판 ID 로 등록돼 있다 |
| std-administrative-79 | 2017도7321 | 2017-08-21 | 2017-09-21 | 책 출처줄 "2017. 8 21." |
| std-administrative-195 | 91누13564 | 1992-04-12(일요일) | 1992-06-12 | |
| std-administrative-207 | 84누250 | 1985-11-23(토요일) | 1985-11-12 | |

## 표준판례 판결요지·쟁점과 공식 본문이 다른 곳 (1차 판정, 표준판례 PDF 원쪽 대조는 하지 않음)
crosscheck 행정법: ok 412 · low-similarity 31 · meta-mismatch 7 · missing 4. low-similarity 31건은 모두 같은 재판이며 책이 공식 판결요지의 일부만 발췌했거나 항을 달리 묶은 것이다. 책 판결요지의 숫자는 125 번을 빼고 모두 공식 본문에 있다.

| id | 사건번호 | 책 문장이 공식과 다른 곳 |
|---|---|---|
| std-administrative-125 | 2014두42742 | 판결요지에 "핀결" 오탈자, 공식에 없는 인용 "(대법원 2004. 4. 28. 선고 2003두1806 판결)" |
| std-administrative-03 | 93헌마186 | "아울러 … 과잉금지원칙을 준수하는 것이 된다" 문장과 쟁점이 공식 판결요지에 없음(헌법 과목에도 같은 결정 있음) |
| std-administrative-389 | 2016두45240 | "자연인이든 법인이든 … 개별적으로 판단할 수밖에 없다" 문장이 공식과 표현이 다름 |
| std-administrative-345 | 2004두7023 | 책 [2]가 사례 적용 문장으로 공식 판결요지에 없음 |
| std-administrative-137, 391 | 2002헌마337 등, 2015추528 | 쟁점 문장을 책이 달리 서술(결론은 같음) |

그 밖에 공식 판결요지가 없어 비교할 수 없는 19건(12·14·41·50·119·144·154·158·162·168·174·231·243·263·308·338·367·409·441), 표준판례 출처(`standardSource`)가 없어 비교하지 않은 32건(416·417·457~486: 같은 재판의 중복 배치)이 있다.

## 검증
- `make validate`: 오류 0 (3,388건 점검, 경고 627건 — 아직 수집하지 않은 다른 과목과 위의 전문 없음 5건).
- `make data`: 3,388건, 전문 2,755건. `make laws build web` 성공.
- `make webcheck`: 13개 항목 모두 통과(첫 시도에 통과, 전문 해시 2,755).
- `fetch_unit.py audit`: 전체 486, 정상 481, 미게재 5, 표시 27(헌법재판소 형식 차이 21 · 위 날짜·전원합의체 5 · 법원명 약칭 1).
- **`make check`(화면 전수 sweep)와 사건별 웹 열람은 실행하지 않았다.** 형법 때 3,400건 규모에서 끝나지 않았다 — 통과로 보고하지 않는다.

## 재현
```bash
python -X utf8 tools/fetch_unit.py plan --subject administrative --spec <units-spec.json> --out spec/fetch-units-administrative.json
python -X utf8 tools/fetch_unit.py run --plan spec/fetch-units-administrative.json --unit u01-gen-intro-infodisclosure     # worktree 마다
python -X utf8 tools/fetch_unit.py resolve --plan spec/fetch-units-administrative.json --unit u01-gen-intro-infodisclosure
python -X utf8 tools/fetch_unit.py audit --plan spec/fetch-units-administrative.json --write-reports
python -X utf8 tools/crosscheck.py --subject administrative --out data/standard-cases/_reports/crosscheck-administrative-fetch.json
```
