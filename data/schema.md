# 데이터 스키마

## 1. `data/registry.json` — 사건 등록부 (`tools/add_cases.py` 로만 수정)
```json
{ "cases": [ {
  "id": "std-civil-02",                 // 페이지 배치·기존 링크·fetched 파일명의 호환 ID (유지)
  "courtId": "sc",                      // 프로젝트 내부 법원 ID (공식 기관코드 아님)
  "caseNumberId": "2002da1178",          // 대표 사건번호의 손실 없는 영문·숫자 ID
  "caseId": "sc-2002da1178",             // {courtId}-{caseNumberId}
  "decisionType": "판결",               // 판결 | 결정
  "decisionId": "sc-2002da1178-20050721-judgment", // 개별 재판 ID
  "group": "standard",                  // standard | annual | enbanc | ccourt (페이지 배치; 재판 정체성과 별도)
  "subject": "civil",                   // constitution | administrative | civil | criminal | commercial | ip   (목록·순서 = tools/subjects.py; ip=지식재산권법은 표준판례 과목이 아니라 annual 등에서만)
  "title": "여성의 종중 구성원 자격",     // 학습용 짧은 제목(편집). 공식 사건명은 수집 시 자동(pageTitle)
  "court": "대법원",                    // 하급심·지원까지 정확한 법원명; case_identity.py COURTS 에 등록
  "caseNumber": "2002다1178",           // 표시용(병합사건은 "2023헌바274·351" 처럼)
  "lookupKey": "2002다1178",            // law.go.kr 조회용 대표 사건번호
  "decisionDate": "2005-07-21",         // YYYY-MM-DD
  "enBanc": true,                       // 대법원 전원합의체 여부
  "tocPath": ["mb-1", "mb-1-2"],        // 표준판례만. toc.json 의 id 경로(깊이 1~3)
  "tags": ["민법총칙", "관습법"],
  "result": "",                         // 비우면 주문에서 자동 추정(파기환송/상고기각/위헌/합헌/각하…)
  "editorial": { "issues": [...], "holding": [...], "statutes": [...] },   // 해당 필드에 표준판례·공식 자료가 모두 없을 때만 쓰는 대체문(선택)
  "standardSource": { "verified": true, "book": "표준판례", "edition": "2023년 개정판", "file": "data/standard-cases/표준판례(2023년 개정판)_민법.pdf", "pages": [...], "holdings": [...] }, // 검증된 PDF 추출문, §1-3
  "annual": { "year": 2025, "field": "civil", "article": "[2025년 분야별 중요판례분석] (3) 민법(총칙·물권법)", "url": "https://..." },   // annual 만. field = 법률신문 분야(아래)
  "lawgo": { "kind": "prec", "seq": "193822" },   // law.go.kr 일련번호를 알면(선택) — fetch 가 바로 조회
  "selectionReason": "", "keywords": [], "difficulty": "", "memo": ""     // 선택(표준판례 PDF·노션 필드)
} ] }
```

### 1-1. 법률신문 분야 `annual.field` (tools/subjects.py 의 `ANNUAL_FIELDS` — 화면 순서·표시의 단일 출처)
| field | 화면(분야 이름 + 작은 보라색 부제) | subject |
|---|---|---|
| constitution | 헌법 | constitution |
| administrative | 행정법 | administrative |
| civil | 민법 · 총칙·물권법·채권법 | civil |
| family | 민법 · 가족법 | civil |
| criminal-general | 형법 · 형법총칙 | criminal |
| criminal-special | 형법 · 형법각칙 | criminal |
| commercial | 상법 (회사법·보험·해상·어음수표·공정거래법 포함) | commercial |
| ip | 지식재산권법 | ip |
- `subject` 는 field 에서 정해진다(add_cases.py 가 맞추고 validate 가 검사). 기사 제목의 연재 순번 `(3)` 은 화면에 쓰지 않는다.
- field 가 비어 있으면 build_data.py 가 기사 제목·과목으로 추정하고, 그래도 모르면 WARN 과 함께 "분야 미지정"으로 둔다.

### 1-2. 법원·사건·재판 ID

| 필드 | 규칙 | 예 |
|---|---|---|
| `courtId` | 정확한 법원·지원별 고정 코드, 소문자 영문·숫자 | `sc`, `hcseoul`, `dcseoulcentral` |
| `caseNumberId` | 대표 사건번호의 연도 + 사건부호 ID + 일련번호 | `2002da1178`, `2022do5937` |
| `caseId` | `{courtId}-{caseNumberId}` | `sc-2002da1178` |
| `decisionId` | `{caseId}-{YYYYMMDD}-{유형}` (`judgment` 또는 `decision`) | `sc-2002da1178-20050721-judgment` |
| 기존 `id` | 그룹·분야·목차상의 배치를 위한 호환 ID | `std-civil-02` |

- 기본 법원 대응은 `sc`=대법원, `cc`=헌법재판소, `hcseoul`=서울고등법원, `dcseoulcentral`=서울중앙지방법원, `fcseoul`=서울가정법원, `acseoul`=서울행정법원, `pc`=특허법원이다. 지원은 별도 코드(예: `dcsuwonbseongnam`=수원지방법원 성남지원)를 쓴다. 전체 허용 목록은 `tools/case_identity.py` 의 `COURTS` 이며 새 법원은 정확한 명칭을 확인하여 여기에 등록한다. 공식 기관코드로 오인하지 않는다.
- 사건부호 대응표의 `다`→`da`, `도`→`do` 등을 사용한다. 미등록 한글 부호는 `x` 뒤에 글자별 6자리 Unicode 16진수를 이어 붙이고 `z` 로 닫아 손실 없이 인코딩한다. 원래 두 자리 연도를 유지하고 세기를 추정하지 않는다. 원래 사건번호는 별도 `caseNumber` 로 항상 보존한다.
- 사건번호가 같아도 법원이 다르면 다른 `caseId` 다. 같은 사건의 중간 결정·종국판결, 날짜가 다른 재판은 별도 `decisionId` 다. 동일 날짜·유형에도 별도 재판이 있다면 현재 키로 자동 병합하지 않고 식별 규칙을 보완한다.
- 같은 재판의 표준판례·전원합의체·연도별 기사 배치는 `id` 가 달라도 `decisionId` 를 공유한다. 개인 메모·북마크의 연결 키는 `decisionId` 이다. 기존 `id`·fetched 파일명·링크는 변경하지 않고 기존 개인 기록을 매핑해 이전한다.
- 병합사건의 전체 번호는 `caseNumber` 에 남기고 검증된 대표번호를 `lookupKey` 및 ID 산정에 쓴다. 표기 순서가 달라 대표번호가 바뀌는 경우 공식 일련번호·법원·날짜·유형을 함께 확인한 뒤 연결한다.
- 등록: `add --court "서울중앙지방법원" --decision-type 판결 ...`; 수정: `set <id> --court ... --decision-type ...`. 후보 `--from` 에서도 정확한 `court`, `decisionType`, `lawgo` 를 전달한다. 기존 등록부 보완: `python tools/add_cases.py migrate-identities`.

### 1-3. 표준판례 출처 `standardSource`

표준판례와 공식 자료가 다르면 **검증된 표준판례의 해당 필드를 우선**한다. 이는 학습 화면의 표시 기준이며 공식 원문 파일의 내용을 고치는 작업이 아니다. 같은 `decisionId` 의 다른 페이지 배치에도 이 기준을 적용한다.

| 필드 | 형식·요건 |
|---|---|
| `verified` | PDF에서 추출한 문자열을 해당 쪽과 대조한 뒤에만 `true` |
| `book` | 책명, 비어 있지 않은 문자열 |
| `edition` | 판본·발행연도, 비어 있지 않은 문자열 |
| `file` | 출처 PDF 파일 경로, 비어 있지 않은 문자열 |
| `pages` | **PDF 기준 1부터 시작하는 양의 정수 쪽번호 배열**; 인쇄된 본문 쪽번호와 혼동하지 않음 |
| `issues`, `holdings` | 선택, `[{"n": "[1]", "text": "PDF에서 추출·대조한 문자열"}]` |
| `statutes`, `precedents`, `subjectStatutes` | 선택, 원문 문자열 배열 |

- 우선순위는 **필드별** `standardSource` → 공식 추출본 → `editorial` 이다. 표준판례 필드를 **생략**하면 다음 출처로 넘어가지만, 검증된 빈 배열 `[]` 을 명시하면 그 필드는 비워 두며 낮은 우선순위의 내용을 넣지 않는다.
- 최소 하나의 검토된 텍스트 필드가 필요하다. 빈 배열은 해당 필드를 의도적으로 비워 두는 경우에만 지정한다.
- 모델이 작성한 요약·추측한 문구·사건목록만 있는 후보를 `verified: true` 인 표준판례 원문으로 등록하지 않는다. 자동 PDF 텍스트 추출만으로 검토 완료 처리하지 않는다.
- 공식 전문은 `fetched/` 수집본을 사용한다. 원문별 저장 문자열을 의역·교정하거나 표준판례와 공식 문구를 합성하지 않는다.
- 여러 검증된 표준판례 출처가 동일 필드에서 서로 다르면 임의 선택하지 않고 충돌로 보고하여 판본·쪽수·대상 재판을 확인한다. 법원·사건번호·날짜 자체가 다른 경우도 자동 병합하지 않는다.

## 2. `data/toc.json` — 표준판례 목차 (과목별 트리, 깊이 1~3)
```json
{ "civil": [ { "id": "mb-1", "label": "제1편 민법총칙", "children": [ { "id": "mb-1-1", "label": "민법의 법원", "children": [] } ] } ], ... }
```
- id 는 과목 접두어 + 번호(헌법 hb-, 행정법 hj-, 민법 mb-, 형법 hb2-, 상법 sb-; 접두어는 tools/subjects.py 의 tocPrefix) 관례. 라벨은 자유(협의회 목차의 대·중·소주제 그대로 권장).
- 깊이 3단계(대주제 › 중주제 › 소주제)까지 화면이 재귀로 처리한다. 사건은 `tocPath` 가 노드 경로와 정확히 일치하는 노드에 붙으므로 깊이 1·2 노드에도 사건을 둘 수 있다.
- 상법은 PDF 구성대로 **분야(총칙·상행위 / 회사 / 어음·수표 / 보험 / 해상) › 편 › 장** 의 3단계이고(편 번호가 분야마다 다시 시작하므로 분야 층이 필요), 장 아래의 로마숫자 절(Ⅰ. Ⅱ. …)은 목차에 넣지 않고 사건의 `keywords`/`memo` 로 남긴다. 다른 네 과목의 toc.json 은 아직 시안용 초안(편 › 장 2단계)이다.

## 3. `data/fetched/<id>.json` — law.go.kr 공식 텍스트 (tools/fetch_lawgo.py 산출; 손대지 않음)
```json
{ "id", "caseNumber", "lookupKey", "kind": "prec|detc", "seq", "sourceUrl", "pageTitle", "citation",
  "sections": [ {"heading": "【판시사항】", "text": "..."}, {"heading": "【판결요지】", ...}, {"heading": "【참조조문】", ...}, {"heading": "【전문】", ...}, {"heading": "【주 문】", ...}, {"heading": "【이 유】", ...} ] }
```
- 실패 시 `<id>.missing.json` {id, reason, triedUrls}. 미게재(최근 선고)면 나중에 `--retry-missing`.

## 4. `data/cases.json` — 화면용 정규화 데이터 (tools/build_data.py 산출; 손대지 않음)
registry + toc + fetched 를 합쳐 만든다. `pages`(표준판례는 standard 과목마다 `std-<subject>` 한 페이지 — tools/subjects.py 순서) · `subjects`([{id, label, standard}]) · `annual`({years: [2025, …, 2020] 최신순, fields: [{id, label, sub, subject}]}) · `toc` · `cases`. 사건 주요 필드: page, citation("대법원 2026. 7. 22. 선고 2022도5937 전원합의체 판결"), citeShort("대판 2022도5937"),
issues/holdings([{n:"[1]", text}]), statutes, precedents, subjectStatutes, fullText([{heading:"[주 문]", text}]), summaryType(standard|mixed|official|editorial), fieldSources, standardSource, courtId, caseNumberId, caseId, decisionId, result, annual({year, field, series, article, url} — annual 만).
괄호는 화면용 조판에서 `[ ]` 로 통일된다(【 】 금지). 원출처 파일은 보존한다.

`fieldSources` 는 `issues`, `holdings`, `statutes`, `precedents`, `subjectStatutes` 등 각 표시 필드의 출처를 기록한다.
- 표준판례: `{"type":"standard","sources":[{"book":...,"edition":...,"file":...,"pages":[...]}]}`
- 공식 자료: `{"type":"official","label":...,"url":...}`
- 편집 요약: `{"type":"editorial","label":...}`
- 자료 없음: `{"type":"missing"}`

`summaryType` 은 판시사항·요지의 표시 출처에 따라 둘 다 표준판례면 `standard`, 둘 다 공식 자료면 `official`, 편집 요약 또는 부재만 있으면 `editorial`, 그 밖의 조합이면 `mixed` 다. `mixed` 를 일괄 공식 원문으로 표시하지 않고 개별 출처를 표시한다. `standardSource` 는 화면 출처 표시에 필요한 책명·판본·파일·쪽수 정보를 보존한다.

## 5. `data/laws.json` — 법령 (tools/build_laws.py 가 생성; 단일 HTML에는 gzip 내장, 웹에는 외부 JSON)
groups(순서: 헌법 → 민사법 → 형사법 → 행정법 → 법원과 국회에 관한 법 → 경제법·지식재산법), laws[{id, group, name, short, meta, toc[{id,l,t,a}], articles[{no,t,h,b:[[mark,text]]}], supp, versions(헌법만)}]

## 6. 표기 규칙(모든 데이터·UI 공통)
- "헌재", "전합" 약칭 금지 → 헌법재판소, 전원합의체. (공식 원문 텍스트 안의 표기는 그대로 둔다.)
- 인용: `법원명 YYYY. M. D. 선고 사건번호 [전원합의체 ]판결` / 법원 결정 `법원명 YYYY. M. D.자 사건번호 결정` / `헌법재판소 YYYY. M. D. 선고 사건번호 전원재판부 결정`. 하급심의 정확한 법원·지원 명칭을 유지한다. `대판/대결` 은 대법원, `헌결` 은 헌법재판소에만 쓴다.
- 공식 원문과 검증된 표준판례 추출문은 원출처별로 보존하고 내용 문자열을 교정·의역하지 않는다. 화면은 §1-3 우선순위와 필드별 출처를 따른다. 편집 요약은 `editorial` 에만 두고 해당 필드에 "편집 요약" 표시를 붙인다.

## 7. 웹 배포 데이터와 개인 기록

- `tools/build_web.py` 가 `data/cases.json`·`data/laws.json` 과 공통 화면을 사용하여 `output/web/` 을 생성한다. 단일 HTML은 기존 `tools/build.py` 가 `output/casebook.html` 로 생성한다.
- `data-manifest.json`: `{schemaVersion: 1, version, generatedAt, cases: {url, sha256}, laws: {url, sha256}}`. 형식 호환성과 파일 해시를 확인하여 읽는다. 앱 설치용 Web App Manifest와는 별도 파일이다.
- 웹용 판례 목록은 전문을 제외하고 각 사건의 `fullTextRef: {url, sha256}` 로 해당 전문 파일을 참조할 수 있다. URL은 웹앱 기준 상대경로다. 판례별 전문과 데이터 파일은 내용에 따라 구분된 경로를 사용한다.
- 온라인 버전 확인에 성공한 자료와 마지막 정상 캐시를 구분한다. 형식·해시가 맞지 않는 새 자료를 활성화하지 않는다. 오프라인에서 아직 내려받지 않은 전문이 있다고 표시하지 않는다.
- 개인 메모·북마크·설정은 배포 JSON에 포함하지 않는다. 기존 배치 `id` 기반 개인 기록은 `decisionId` 에 연결하고 충돌·알 수 없는 ID를 보존한다. 내보내기·가져오기는 출처 주소가 달라지는 로컬 HTML → 웹앱 또는 기기 이전에 사용한다. 계정 동기화를 의미하지 않는다.
