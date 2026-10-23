# 판례집 (lawbook) — 에이전트 작업 안내

이 저장소는 **화면과 데이터를 분리한 웹앱/PWA(`output/web/`)와 단일 HTML 보관본(`output/casebook.html`)을 만드는 법학 판례·법령 학습 앱**의 데이터와 빌드 도구다.
에이전트(Claude Code / Codex)의 임무는 **출처를 보존하여 데이터를 채우고 검증한 뒤 배포물을 생성하는 것**이다. 화면 템플릿(`src/design-d.html`)은 사용자가 확정한 디자인이므로 데이터 작업 중에는 건드리지 않는다. 사용자가 요청한 웹앱/PWA 전환에 필요한 데이터 로딩·개인 기록 이관·출처 표시 수정은 디자인을 유지하는 범위에서 수행한다.

## 한눈에 보는 흐름
```
data/standard-cases/표준판례(2023년 개정판)_<과목>.pdf ── pdf_standard_cases.py ─► candidates-<subject>.json ─ 검토 ─ add_cases.py ─┐
registry.json(사건 등록부) + toc.json(표준판례 목차)  ◄────────────────────────────────────────────────────────────────────────────┘
fetched/<id>.json (law.go.kr 공식 텍스트, fetch_lawgo.py)  ├─ build_data.py ─► cases.json ─┐
laws_md/*.md (법령 Markdown) ── build_laws.py ─► laws.json ─────────────────────────────┴─ build.py ─► output/casebook.html ─ sweep.py(검사)
cases.json + laws.json + 공통 화면 ── build_web.py ─► output/web/ ─ webcheck(HTTP·오프라인 검사)
```
표준판례 과목(subject)은 **헌법 · 행정법 · 민법 · 형법 · 상법** 다섯 개이고, 법률신문 주요판례용으로 **지식재산권법**(`ip`, 표준판례 페이지·목차 없음 — `standard: False`)이 더 있다. 과목 목록·순서·목차 접두어·PDF 폴더명과 법률신문 분야(`ANNUAL_FIELDS`)·연도 범위(`ANNUAL_YEARS`)는 `tools/subjects.py` 한 곳에 있고, 표준판례 페이지(`std-<subject>`)는 거기서 자동으로 만들어진다.
명령: `make data` · `make laws` · `make build` · `make check` · `make web` · `make webcheck` · `make fetch`(사용자 PC) · `make validate`. `make` 가 없는 PC(Windows)에서는 같은 타깃을 `python tools/make.py validate data build check web webcheck` 처럼 실행한다. 스키마는 `data/schema.md`.

## 절대 규칙
1. **원출처별 텍스트를 그대로 보존하고, 내용이 다르면 검증된 표준판례를 우선한다.** 공식 판시사항·요지·참조조문·전문은 국가법령정보센터(law.go.kr) 페이지에서 `tools/fetch_lawgo.py` 로 추출한 것만 `fetched/` 에 보존한다. 표준판례 PDF에서 추출·대조한 판시사항·요지·참조조문 등은 별도 `standardSource` 에 책명·판본·파일·쪽수와 함께 보존하고, 동일 재판의 화면에서는 해당 필드별로 공식 자료보다 우선한다(전원합의체 등 다른 페이지에도 적용). 요약·의역·오탈자 교정·원문 직접 작성 금지. 표준판례 선택을 이유로 공식 수집 파일을 수정하지 않는다. 법원·사건번호·선고일이 다르면 내용 우선순위 문제가 아니라 동일 재판 여부의 충돌이므로 자동 병합하지 않고 확인한다.
2. **표기**: "헌재"·"전합" 약칭 금지(헌법재판소·전원합의체). 괄호는 `[ ]`(【 】 금지). 인용형식은 `data/schema.md` §6.
3. **필드별 표시 우선순위는 검증된 표준판례 → 공식 자료 → 편집 요약(`editorial`)이다.** 표준판례에 없는 필드만 공식 자료로 보충하고, 둘 다 없을 때만 편집 요약을 쓴다. 표준판례는 "표준판례"와 책명·판본·쪽수, 편집 요약은 "편집 요약"으로 표시한다. 서로 다른 출처를 섞어 표시할 때는 필드별 출처를 기록하며 전체를 공식 원문이라고 표시하지 않는다. 전문은 공식 수집본을 유지한다.
4. 등록·목차 수정은 `tools/add_cases.py` 로만 한다(id 관례·검증 포함). `cases.json`, `laws.json`, `fetched/*.json` 은 손으로 편집하지 않는다.
5. 끝낼 때는 항상 `make validate && make data && make build && make check` 를 통과시키고, 웹앱을 변경했으면 `make web && make webcheck` 도 통과시킨다. 바뀐 사건 수·수집 실패(.missing) 목록·실제 배포 여부를 보고한다. 검사 오류를 출력했으나 종료코드가 0이라는 이유만으로 통과라고 판단하지 않는다.
6. **웹앱 배포물은 `output/web/`, 최신 단일 HTML 보관본은 `output/casebook.html`이다.** 빌드·검사·화면 확인은 `output/` 을 사용한다. `dist/` 는 기존 결과의 백업 보관용이며, 일반 빌드·`clean` 으로 덮어쓰거나 삭제하지 않는다. GitHub Pages에는 검증한 `output/web/` 만 배포하고 원본 PDF·inbox·개인 기록은 배포물에 넣지 않는다.
7. **전문 조판은 최소한으로.** `[이유]` 안의 `1. 사건개요`, `2. 심판대상` 같은 명확한 최상위 개요만 소제목으로 처리한다. 그 밖의 본문은 왼쪽 정렬하고 들여쓰기를 추가하지 않는다. `가.`, `(1)`, `①`, 인용 법령의 조·항·호, 참조조문의 각호는 소제목이나 번호 분리 대상으로 추정하지 않는다. `[주문]` 의 기존 전용 조판만 예외로 유지한다. 공식 원문 문자열은 바꾸지 않는다.
8. **다른 세션의 변경을 보존한다.** Claude Code·Codex 세션이 동시에 작업 중이면 수정 직전에 대상 파일을 다시 읽고 담당 범위만 최소한으로 패치한다. 최신 파일을 이전 사본으로 덮어쓰거나 다른 세션의 프로세스를 중단하지 않는다. 데이터 작업과 화면 작업을 나누고, 빌드 직전 최신 데이터를 확인한 뒤 검사를 수행한다.

## 재판 ID와 법원 구분

- `caseId = {courtId}-{caseNumberId}` 가 법원별 사건의 기본 ID이고 `decisionId = {caseId}-{YYYYMMDD}-{judgment|decision}` 가 개별 판결·결정의 ID다. 같은 법원·사건번호라도 날짜나 판결/결정 유형이 다르면 별도 재판이다. 같은 날 같은 유형의 별도 재판이 확인되면 자동 병합하지 말고 추가 식별 규칙을 먼저 정한다.
- 법원 ID는 프로젝트 내부에서 관리하는 영문 소문자·숫자 조합이며 법원 공식 기관코드가 아니다. `tools/case_identity.py` 의 명시적 법원 목록을 단일 기준으로 삼는다. 법원명만 보고 대법원으로 대체하거나 지역 없는 "지방법원"을 자동으로 특정하지 않는다.
- 기본 코드: `sc`=대법원, `cc`=헌법재판소, `hcseoul`=서울고등법원, `dcseoulcentral`=서울중앙지방법원, `fcseoul`=서울가정법원, `acseoul`=서울행정법원, `pc`=특허법원. 지원도 본원과 별도 코드로 등록한다(예: `dcsuwonbseongnam`=수원지방법원 성남지원). 새 법원은 정확한 명칭·코드를 목록에 추가한 뒤 사용하고 기존 코드는 바꾸거나 재사용하지 않는다.
- 사건번호 ID는 사건번호의 연도·사건부호·일련번호를 보존한다. 예: `2022도5937` → `2022do5937`, `2002다1178` → `2002da1178`. 연도가 두 자리이면 세기를 추측해 네 자리로 늘리지 않는다. 정해진 영문 대응이 없는 사건부호는 가역적인 ASCII 인코딩을 쓰며 한글을 삭제하거나 임의 약칭으로 충돌시키지 않는다.
- 예: 기본 사건 ID `sc-2022do5937`, 개별 재판 ID `sc-2022do5937-20260722-judgment`. `group`, 과목, 연도별 기사 분야는 페이지 배치 속성이며 재판의 정체성을 결정하지 않는다.
- 병합사건은 표시용 전체 사건번호를 보존하고 검증된 대표 사건번호를 기본 ID에 쓴다. 표기 순서만 바뀐 병합사건·중복 배치는 공식 일련번호 및 날짜·법원·유형을 함께 대조한다. 자동 재번호 부여나 공식 ID만을 근거로 하는 무조건 병합은 금지한다.
- 기존 등록부의 식별 필드 보완은 `python tools/add_cases.py migrate-identities` 로 수행한다. 신규·수정 등록은 `--court` 와 `--decision-type` 을 명시하고 후보의 `lawgo`·`standardSource` 를 보존한다.
- 기존 사건의 과목은 `python tools/add_cases.py set <id> --subject <subject>` 로 바꾼다. `id`·`caseId`·`decisionId`·공식 수집 파일과 출처는 유지한다. 표준판례를 다른 과목으로 옮길 때는 대상 과목의 유효한 `--toc` 경로도 함께 지정한다. 법률신문 판례는 `--field` 와 과목이 일치해야 하며, 분야만 바꾸면 과목도 해당 분야에 맞춰진다.
- 표준판례 출처 필드를 생략하면 다음 출처로 보충하지만, 검증된 빈 배열 `[]` 을 명시하면 그 필드는 비워 둔다. 쪽수는 PDF 기준 1부터 시작하는 정수다. 서로 다른 검증 출처의 동일 필드가 충돌하면 임의로 하나를 고르지 않는다.
- 기존 `id` 는 페이지 배치·이전 링크·수집 파일명의 호환 키다. 기존 `id`, `fetched/<id>.json`, 링크를 일괄 이름 변경하지 않는다. 개인 메모·북마크는 `decisionId` 로 연결하며 기존 ID 매핑과 내보내기·가져오기로 이전한다. 충돌하는 메모나 알 수 없는 ID의 기록도 버리지 않는다.

## 웹앱·PWA 배포와 개인 기록

- 공식 원문·등록부 → 검증·정규화 데이터 → 웹 데이터 묶음과 단일 HTML 보관본을 생성한다. 데이터가 바뀌면 검증과 데이터 생성·배포를 수행하되 화면 코드를 함께 수정할 필요는 없다.
- 웹앱은 `data-manifest.json` 의 형식 버전·데이터 버전·파일 해시를 확인하고 목록·법령·전문을 외부 파일에서 읽는다. 목록을 먼저 읽고 전문은 필요할 때 불러온다. 최신 버전 확인과 기존 정상 캐시의 복구를 구분하여 갱신 실패 시 기존 자료를 유지한다.
- PWA는 HTTPS 또는 로컬 개발 서버에서 검사한다(`output/web/index.html` 을 `file://` 로 여는 방식은 웹앱 검사가 아니다). 앱 실행·업데이트 확인 시 온라인 최신 자료를 확인하고, 오프라인에서는 저장한 자료만 보장한다. GitHub 반영과 모든 단말의 즉시 갱신을 같은 의미로 보고하지 않는다.
- 개인 메모·북마크·설정은 공개 판례 데이터와 별도 보관한다. 로컬 파일·웹 도메인·모바일 앱 사이에 자동으로 옮겨진다고 가정하지 않고 내보내기·가져오기를 제공한다. 계정 기반 기기 간 동기화와 Android/iOS 설치 패키지는 별도 구현·검증 단계이며 PWA 완성만으로 완료했다고 보고하지 않는다.

## 작업 레시피
### A. 표준판례를 PDF 에서 채우기 (헌법·행정법·민법·형법·상법 각 과목 페이지)
- 다섯 PDF 전체를 일괄 전사·검증·등록하는 분업 절차(스크립트 뼈대 → 하위 모델 전사 → 스크립트 대조 → 상위 모델 판정 → `add_cases.py`)는 `spec/TASK-pdf2md.md`(작업 지시서) 와 `spec/PIPELINE-pdf2md.md`(설계) 를 따른다. Claude Code·Codex 어느 쪽이든 같은 문서로 진행하며, 아래 1~7 은 소량·수동 작업 절차다.
1. PDF 원본은 `data/standard-cases/표준판례(2023년 개정판)_<과목>.pdf` 다(법학전문대학원협의회 발행본 5건이 이미 있다. 다른 판본은 `data/inbox/standard_pdf/` 에 둔다). 과목별 폴더 `data/standard-cases/<과목>/` 는 PDF 를 Markdown 으로 옮긴 중간 산출물 자리다(비어 있어도 된다).
2. `python3 tools/pdf_standard_cases.py "data/standard-cases/표준판례(2023년 개정판)_상법.pdf" [--subject commercial]`
   → 같은 폴더에 `candidates-<subject>.json` (사건번호·선고일·법원·전원합의체 여부·주변 목차 문맥·표 행). `--subject` 를 생략하면 파일명의 한글 과목명으로 추정한다(id 또는 한글명 모두 허용).
3. 후보 파일을 **읽고 검토**: PDF 원문과 대조해 사건번호/선고일을 확인하고, 각 항목에 `title`(학습용 짧은 제목, 12자 안팎), `tocPath`(toc.json 의 id 배열), 필요하면 `selectionReason`·`keywords` 를 채운 뒤 `status` 를 `"ok"` 로 바꾼다. 목차가 없으면 먼저 `python3 tools/add_cases.py toc add --subject civil --parent mb-3 --id mb-3-4 --label "사무관리"` 로 만든다(협의회 목차의 대·중·소주제를 그대로 옮기는 것을 권장).
   - 상법 목차는 PDF 목차를 그대로 옮긴 **분야 › 편 › 장** 3단계(`sb-1`…`sb-5` = 총칙·상행위 / 회사 / 어음·수표 / 보험 / 해상)가 이미 들어 있다. 장 아래 로마숫자 절(Ⅰ. Ⅱ. …)은 목차에 넣지 않고 `keywords`/`memo` 로 남긴다. 장이 없는 편(예: 회사 제1편 통칙 `sb-2-1`, 보험 제1편 `sb-4-1`)에는 tocPath 를 2단계로 둔다.
   - 헌법·행정법·민법·형법의 toc.json 은 아직 시안용 초안이므로 PDF 목차로 교체해도 된다 — 바꾸면 기존 시안 사건(과목당 3건)의 tocPath 도 `set --toc` 으로 옮길 것.
4. 표준판례의 판시사항·요지 등을 화면에 적용하려면 후보에 `standardSource` 를 함께 기록한다. PDF 추출 문자열을 원본 쪽과 대조한 뒤에만 `verified: true` 로 표시하고 책명(`book`)·판본(`edition`)·파일(`file`)·쪽수(`pages`, PDF 기준 1부터 시작)를 필수로 남긴다. 단순 사건목록 후보나 모델의 요약을 표준판례 원문이라고 표시하지 않는다. 상세 구조는 `data/schema.md` §1-3.
5. `python3 tools/add_cases.py add --from data/standard-cases/candidates-<subject>.json`
6. `make fetch` (사용자 PC에서; 샌드박스에서는 law.go.kr 이 막혀 있다) → `make data build check web webcheck`.
7. 보고: 등록 n건, 수집 성공/실패, 실패 사유(미게재는 나중에 `python3 tools/fetch_lawgo.py --all-missing --retry-missing`).

### B. 법률신문 「분야별 중요판례분석」 채우기 (법률신문 주요판례 페이지)
화면 구성(템플릿에 구현됨): 라틴어 격언 아래 **연도 버튼**(최신 → 과거, 현재 2025 → 2020; 여러 개를 누르면 함께 표시되고, 좁은 화면에서는 버튼 줄을 가로로 밀어 과거 연도를 드러낸다) — 그 오른쪽에 **필터**(분야·법원·전원합의체 판결만)와 **찾기**(제목·사건번호·조문·요지). 목록은 아래 8개 **분야**로 나뉘고, 연도를 여럿 고르면 분야 안에서 연도별로 묶인다.

| 분야 id (`--field`) | 화면 표시 (작은 보라색 = 뒤 부분) | 과목 | 해당 기사 |
|---|---|---|---|
| `constitution` | 헌법 | constitution | 헌법 |
| `administrative` | 행정법 | administrative | 행정법 |
| `civil` | 민법 **총칙·물권법·채권법** | civil | 민법(총칙·물권법), 민법(채권법) |
| `family` | 민법 **가족법** | civil | 가족법, 민법(가족법), 친족·상속법 |
| `criminal-general` | 형법 **형법총칙** | criminal | 형법 총칙 |
| `criminal-special` | 형법 **형법각칙** | criminal | 형법 각칙 |
| `commercial` | 상법 | commercial | 상법·회사법·보험·해상·어음수표, **공정거래법도 상법** |
| `ip` | 지식재산권법 | ip | 지식재산권법(특허·저작권·상표) |

- 법률신문 기사 제목의 연재 순번(`(3)` 등)은 화면에 쓰지 않는다(분야 이름만 표시). 분야 목록·순서·표시는 `tools/subjects.py` 의 `ANNUAL_FIELDS` 가 단일 출처다.
- 위 분야가 아닌 기사(민사소송법·형사소송법·노동법·조세법 등)는 대상이 아니다.
1. 기사 본문을 브라우저에서 복사해 `data/inbox/annual/<year>-<field>[-n].txt` 로 저장(1행 제목, 2행 URL, 3행부터 본문). 한 분야에 기사가 여럿이면(민법 총칙·물권법 / 채권법 등) `-1`, `-2` 를 붙인다. 웹 도구로 가져왔다면 같은 형식으로 저장.
2. `python3 tools/annual_cases.py data/inbox/annual/2025-civil-1.txt [--year 2025] [--field civil]` → `.candidates.json`. 연도·분야를 생략하면 기사 제목(`[2025년 분야별 중요판례분석] (3) 민법(총칙·물권법)`, `8. 형법(총칙)` 등)에서 추정한다. 형법 기사 제목에 총칙/각칙 표시가 없으면 `--field criminal-general|criminal-special` 를 준다. `--field` 는 id 대신 화면 이름(`가족법`, `민법 총칙·물권법·채권법`)이나 `회사법`·`공정거래법`(→ 상법)도 받는다.
3. 검토 후 `title` 채우고 `status: "ok"` → `python3 tools/add_cases.py add --from <candidates>` (그룹 annual; 연도·분야·기사 제목·URL 자동 기록, 과목은 분야에서 정해진다). 후보 항목마다 `field` 가 파일 분야로 미리 채워져 있으니, 한 기사에 형법 총칙·각칙(또는 여러 분야) 사건이 섞여 있으면 항목의 `field` 를 고친다(우선순위: 명령줄 `--field` > 항목 `field` > 파일 `field`; 연도도 명령줄 `--year` 가 우선). 사건 하나는 `add --group annual --field family --year 2024 --case … --date … --title … [--article … --url …]`.
4. `make fetch` → `make data build check`.
- 분야를 고칠 때는 `python3 tools/add_cases.py set <id> --field <field>`(과목도 함께 맞춰진다; `--year/--article/--url` 도 가능). `make validate` 는 `annual.field` 가 없거나 과목과 맞지 않으면 알린다.
- 같은 판례가 두 분야 기사에 실리면 분야마다 따로 등록된다(같은 연도·같은 분야의 중복만 막는다).
- 연도 버튼 범위는 `tools/subjects.py` 의 `ANNUAL_YEARS`(현재 2020–2025). 등록부에 더 최근·과거 연도가 들어오면 build_data.py 가 자동으로 넓힌다.

### C. 대법원 전원합의체·헌법재판소 주요결정 추가
- `python3 tools/add_cases.py add --group enbanc --subject <과목> --case 2023다275578 --date 2026-09-29 --title "채권가압류 후 원인계약의 합의해제"`
- `python3 tools/add_cases.py add --group ccourt --subject constitution --case 2026헌라3 --date 2026-07-23 --title "국정조사계획서 가결선포와 심의·표결권"`
- 표준판례로 등록하는 전원합의체 판결은 `--enbanc` 를 붙인다(`set <id> --enbanc yes|no` 로 고칠 수 있다).
- 병합사건은 `--case "2023헌바274·351"` 처럼 표시용 번호를 주면 조회는 첫 번호로 한다.
- 출처: 대법원 판례속보(https://www.scourt.go.kr → 판례속보), 헌법재판소 최근 주요결정(https://www.ccourt.go.kr → 최근 주요결정). 선고 직후에는 law.go.kr 미게재일 수 있다 → 등록해 두고 나중에 재시도.
- 헌법재판소 주요결정·대법원 전원합의체 페이지는 과목 칩(**전체분야**·헌법·행정법·민법·형법·상법) 아래 **선고연도 탭**(**전체연도** + 최신 → 과거; 여러 개를 함께 고를 수 있고, 넓은 화면은 줄바꿈·좁은 화면은 가로로 민다)으로 고른다. 칩 필터는 결정·판결의 과목(`--subject`)을 쓴다.
  - 헌법재판소: 2026 → 2010 한 해씩(`tools/subjects.py` 의 `CCOURT_YEARS`, 현재 2010–2026).
  - 전원합의체(건국 후 전부 수록 예정): 2026 → 2020 은 한 해씩(`ENBANC_YEARS`, 현재 2020–2026), 그 앞은 2010년대 · 2000년대 · … · 1940년대 10년 단위(`ENBANC_FROM` = 1948 이 든 연대까지).
  - 탭은 build_data.py 가 `cases.json` 의 `yearTabs` 로 만들며, 등록부 선고일이 범위 밖이면 그쪽으로 넓힌다(전원합의체의 과거 쪽은 연대 탭으로).

### D. 법령 추가·갱신 (주요법령 페이지)
- legalize-kr 형식 Markdown(법제처 국가법령정보 미러)을 `data/laws_md/` 에 넣고 `tools/build_laws.py` 의 `LAW_INDEX` 에 (파일명, id, 그룹, 약칭) 추가 → `make laws build check`.
- 그룹 순서는 `GROUPS`(헌법 → 민사법 → 형사법 → 행정법 → 법원과 국회에 관한 법 → 경제법·지식재산법). 상법·어음법·수표법·보험업법 등 상사법령을 넣을 때는 민사법 그룹에 두거나 새 그룹 "상사법"을 `GROUPS` 에 추가한다.

### E. 공식 텍스트 수집기 사용법 (`tools/fetch_lawgo.py`)
- `--all-missing`(기본 작업), `--id <id>`(재시도·강제는 `--force`), `--retry-missing`, `--engine requests`(Playwright 가 없을 때).
- 조회 경로: `https://www.law.go.kr/판례/(사건번호)` 또는 `/헌재결정례/(사건번호)` → iframe 의 `precSeq`/`detcSeq` → `LSW/precInfoP.do?precSeq=N` / `LSW/detcInfoP.do?detcSeq=N` → `#conScroll` 섹션 추출.
- 결과 검증: 페이지의 사건번호가 lookupKey 와 일치하지 않으면 저장하지 않고 `.missing.json` 을 남긴다.
- 브라우저 없이 Claude.ai 에서 작업할 때는 `tools/FETCH_GUIDE.md`(브라우저 창 안에서 추출 JS 실행) 절차를 쓴다.

### F. 과목을 추가·변경할 때 (예: 상법을 추가한 방법)
1. `tools/subjects.py` 의 `SUBJECTS` 에 `{"id", "label", "tocPrefix", "folder", "standard"}` 한 줄 추가 — add_cases·pdf_standard_cases·annual_cases·build_data 의 과목 목록과 `std-<id>` 페이지가 여기서 나온다. 표준판례 페이지 없이 법률신문 분야로만 쓰는 과목은 `"standard": False`(지식재산권법처럼; 아래 2·3단계 불필요). 법률신문 분야를 늘리거나 나눌 때는 `ANNUAL_FIELDS` 에 `{"id", "subject", "label", "sub", "keys"}` 를 추가한다(화면·페이지 설명은 자동). 새 분야는 기사 제목 추정에서 기존 분야보다 먼저 검사되므로, 넓은 분야의 `keys` 와 겹치면 그쪽 `keys` 를 정리하고 필요하면 `_MATCH_ORDER`(좁은 분야 → 넓은 분야 순서)에 자리를 정해 준다.
2. `data/toc.json` 에 같은 id 의 목차 트리(깊이 1~3)를 만든다(`add_cases.py toc add`, 또는 PDF 목차를 옮긴 스크립트).
3. `src/design-d.html` 의 `MAXIMS` 와 `PAGE_DESC` 에 `'std-<id>'` 항목(라틴어 격언 1개, 페이지 설명 1줄)을 더한다. 이 경우와 사용자가 명시적으로 요청한 화면 수정에 한해 템플릿을 수정한다.
4. 시안용으로 과목당 3건 정도 등록·수집해 페이지가 비지 않게 한 뒤 `make validate data build check`.

## 검사 기준
- `make check` 결과의 `errors`(Google Fonts 차단 외) 0, `overflow` 0, `empty` 0, laws 항목 정상.
- 새 표준판례는 해당 과목 페이지의 목차 아래 보여야 하고(목차 미지정 사건은 "목차 미지정"으로 모임), 인용표시가 `대법원 … 선고 … 판결` 형식으로 나와야 한다.
- 새 법률신문 판례는 그 연도 버튼을 눌렀을 때 해당 분야 아래 보여야 한다(분야를 정하지 못한 사건은 "분야 미지정"으로 모이고 build_data.py 가 WARN 을 낸다). `make check` 결과의 `annual` 항목(연도·필터·찾기 동작, 오류 없음)도 확인한다.
- 새 헌법재판소 결정·전원합의체 판례는 그 선고연도 탭(또는 전체연도)을 눌렀을 때 보여야 한다. `make check` 결과의 `ccourt`·`enbanc` 항목(전체연도·연도 탭·과목 칩 동작, 오류 없음)도 확인한다.
- 화면 확인이 필요하면 `python3 tools/shot_case.py output/casebook.html <page> <caseId> shots/x` 로 스크린샷을 찍어 본다(page: std-constitution | std-administrative | std-civil | std-criminal | std-commercial | annual | enbanc | ccourt).

## 파일 안내
- `output/web/` 웹앱/PWA 배포물, `output/casebook.html` 최신 단일 HTML 보관본. `dist/` 는 백업 보관용(일반 빌드·검사·정리 대상에서 제외).
- `src/design-d.html` 확정 템플릿(데이터 자리 `__CASE_DATA_JSON__`, `__LAWS_DATA_B64__`). `spec/` 는 설계 사양(참고용; 과목이 4개이던 때의 문서라 페이지 수 등은 현재와 다를 수 있다).
- `tools/`: subjects.py(과목·법률신문 분야·연도 범위 정의) · build_data.py · build_laws.py · build.py · make.py(make 대체) · sweep.py · shot.py · shot_case.py · fetch_lawgo.py · pdf_standard_cases.py · annual_cases.py · add_cases.py · casenum.py · FETCH_GUIDE.md
- `data/`: registry.json · toc.json · fetched/ · laws_md/ · standard-cases/(표준판례 PDF 5건 + 과목별 폴더) · inbox/ · cases.json(생성) · laws.json(생성) · schema.md
