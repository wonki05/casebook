# 판례집 — 데이터 파이프라인과 웹앱 배포 안내

공통 화면과 검증된 원본 데이터에서 두 배포 형식을 생성합니다.
- **웹앱/PWA:** `output/web/index.html` — 버전 정보·판례 목록·전문·법령을 별도 파일에서 읽습니다. GitHub Pages에는 `output/web/` 만 배포합니다.
- **단일 HTML 보관본:** `output/casebook.html` — 판례 JSON과 gzip+base64 법령 데이터를 내장하므로 파일 하나로 해당 시점의 자료를 보관할 수 있습니다.

판례가 추가되면 원문 수집·검증·데이터 생성·배포를 수행합니다. 화면 코드를 변경할 필요는 없습니다. 원본 PDF·수집 후보·개인 기록은 웹 배포물에 포함하지 않습니다. GitHub에 파일을 보관하는 것과 Pages URL에 배포하는 것은 별개이며, 배포가 완료되기 전에는 공개 사이트가 생긴 것으로 보지 않습니다.
**에이전트 작업 안내는 `AGENTS.md`와 `CLAUDE.md`**, 데이터 스키마는 `data/schema.md`, 명령은 `Makefile` 을 보세요.
빠른 시작(처음 복제한 환경에서도 생성 데이터를 다시 만듭니다):

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python tools/make.py validate data laws build check web webcheck
```
`make` 가 없는 Windows에서도 위 명령을 그대로 실행합니다. 단일 HTML 검사는 `output/casebook.html`, 웹앱 검사는 `output/web/` 을 사용합니다. `dist/` 의 기존 HTML 은 백업으로 보존합니다(`clean` 도 백업을 삭제하지 않습니다).

## 구성
```
output/casebook.html      # 최신 단일 HTML 보관본
output/web/              # 웹앱/PWA와 외부 데이터 배포물 (GitHub Pages 게시 대상)
dist/                     # 기존 HTML 백업(일반 빌드·clean 대상에서 제외)
src/design-d.html         # 확정 템플릿 (데이터 자리: __CASE_DATA_JSON__, __LAWS_DATA_B64__)
AGENTS.md / CLAUDE.md     # Claude Code·Codex 작업 레시피 (표준판례 PDF, 법률신문, 전원합의체·헌법재판소, 법령, 과목 추가)
Makefile, requirements.txt   # make 가 없는 PC 에서는 python tools/make.py <타깃…>
tools/subjects.py         # 과목 정의 단일 출처 (헌법·행정법·민법·형법·상법: id·라벨·목차 접두어·PDF 폴더명 → 표준판례 페이지 자동 생성; 지식재산권법 ip 는 표준판례 없음)
                          #   + 법률신문 분야 ANNUAL_FIELDS(8개) · 연도 버튼 범위 ANNUAL_YEARS(2020–2025) · 선고연도 탭 범위 CCOURT_YEARS(헌법재판소 2010–2026) · ENBANC_YEARS/ENBANC_FROM(전원합의체 2020–2026 한 해씩, 그 앞은 1940년대까지 연대)
data/registry.json        # 사건 등록부 (tools/add_cases.py 로 편집)
data/toc.json             # 표준판례 목차 트리 (깊이 1~3; 상법은 PDF 목차 그대로 분야›편›장, 나머지는 시안용 초안)
data/standard-cases/      # 표준판례(2023년 개정판) PDF 5건(헌법·행정법·민법·형법·상법) + 과목별 폴더(PDF→Markdown 중간 산출물 자리)
data/inbox/               # standard_pdf/ (그 밖의 표준판례 PDF), annual/ (법률신문 기사 텍스트)
data/laws_md/             # 법령 Markdown 원본 26건
tools/fetch_lawgo.py      # law.go.kr 공식 텍스트 수집기 (사용자 PC에서 실행)
tools/pdf_standard_cases.py, annual_cases.py, add_cases.py, casenum.py
data/laws.json            # 법령 26건 구조화 데이터 (build_laws.py 산출물; 헌법은 10개 판본)
tools/build_laws.py       # legalize-kr Markdown 법령 → laws.json  (python3 tools/build_laws.py <md 폴더>)
spec/laws-module.html     # 두 시안이 공유하는 법령 렌더 모듈(CSS+JS) + 단독 시험 페이지
spec/emblems.html         # 사용자가 제공한 휘장 PNG 를 data URI 로 담은 스타일 조각
spec/SPEC-v2.md           # v2 사양(8 페이지 · 시트 · 탭 순서 · 전문 조판 · 인용형식 · 법령 페이지)
data/fetched/<id>.json    # 국가법령정보센터(law.go.kr)에서 그대로 추출한 공식 텍스트 (사건별)
data/cases.json           # 정규화된 최종 데이터 (build_data.py 산출물)
tools/FETCH_GUIDE.md      # law.go.kr 원문 추출 절차 + 브라우저용 추출 JS (verbatim)
tools/build_data.py       # registry.json + toc.json + fetched/*.json → cases.json (판시사항/요지 항목 분리, 인용표시 생성, 결과 요약)
tools/build.py            # cases.json 을 템플릿에 주입 → output/casebook.html
tools/build_web.py        # 공통 화면 + 외부 데이터 → output/web/
tools/case_identity.py    # 법원 코드·사건번호·개별 재판 ID
src/data-provider.js      # 버전·해시 확인, 외부 데이터 로딩과 오프라인 캐시
tools/sweep.py            # 수록 사건 전체 × 탭 전체 열어 콘솔 오류·가로 스크롤 검사 (Playwright)
tools/browser_runtime.py  # Chromium 우선, 미설치된 Windows PC에서는 설치된 Edge 사용
tools/test_fulltext.cjs    # 전문 조판·인용 각호·원문 보존 회귀 검사 (Node.js 내장 모듈만 사용)
tools/shot.py, shot_case.py  # 스크린샷 도구
spec/SPEC.md              # 세 시안이 공유하는 사양 (데이터 스키마 · 타이포 · 색 · 기능 · 표기 규칙)
```

## 전문 표시와 동시 작업
전문은 `[이유]` 안의 `1. 사건개요`, `2. 심판대상` 같은 명확한 최상위 개요만 소제목으로 표시합니다. 나머지 본문과 인용 조문·각호에는 들여쓰기나 번호 분리를 추가하지 않으며, `[주문]` 의 기존 조판은 유지합니다. 공식 원문은 변경하지 않습니다.
전문 표시를 수정한 뒤에는 빌드 후 `node tools/test_fulltext.cjs output/casebook.html` 로 실제 사건과 인용·검색·원문 보존 회귀를 검사합니다(Node.js 필요).
Claude Code·Codex 가 동시에 작업할 때는 수정 직전 파일을 다시 읽고 필요한 부분만 패치하여 다른 세션의 변경을 보존합니다.

## 판례 추가 절차 (요약 — 자세한 레시피는 AGENTS.md)
1. `python3 tools/add_cases.py add …`(또는 PDF/기사 후보 파일에서 `--from`)로 `data/registry.json` 에 등록. 표준판례 목차는 `data/toc.json`(`add_cases.py toc …`). 표준판례 과목은 `tools/subjects.py` 의 다섯 개(헌법·행정법·민법·형법·상법)이며 표준판례 PDF 는 `data/standard-cases/` 에 있다.
   법률신문 「분야별 중요판례분석」 사건은 연도(`annual.year`)와 분야(`annual.field`: 헌법 · 행정법 · 민법 총칙·물권법·채권법 · 민법 가족법 · 형법총칙 · 형법각칙 · 상법(회사법·공정거래법 포함) · 지식재산권법)를 가진다. 화면은 연도 버튼(여러 개 선택) · 필터 · 찾기 · 분야별 목록으로 구성된다(AGENTS.md 레시피 B).
2. `python3 tools/fetch_lawgo.py --all-missing` 으로 law.go.kr 공식 텍스트를 `data/fetched/<id>.json` 에 수집(브라우저 창 방식은 `tools/FETCH_GUIDE.md`).
   - 대법원: `https://www.law.go.kr/판례/(사건번호)` → iframe 의 `precSeq` → `LSW/precInfoP.do?precSeq=N`
   - 헌법재판소: `https://www.law.go.kr/헌재결정례/(사건번호)` → `detcSeq` → `LSW/detcInfoP.do?detcSeq=N`
   - 최근 선고분은 미게재(이번 작업에서 2026. 10. 22. 헌법재판소 결정 5건, 2026. 9. 29. 전원합의체 1건)일 수 있음 → 편집 요약 유지, 나중에 재시도.
   - 판시사항·요지가 없는 필드는 검증된 표준판례 자료가 있으면 이를 사용하고, 그것도 없을 때만 편집 요약을 씁니다. 서로 다른 출처가 섞인 경우 필드별 출처를 표시합니다.
3. `make validate data build check web webcheck`. `standardSource` 에 추출·대조한 표준판례 자료가 있으면 동일 재판의 해당 필드는 공식 자료보다 우선합니다. 공식 수집 파일은 그대로 보존합니다.

## 법령 추가·갱신
1. legalize-kr 형식의 Markdown(법제처 국가법령정보 미러)을 한 폴더에 둔다. 파일 머리의 YAML(제목·공포일자·시행일자 등)과 `#/##/###/####/#####` 제목 구조를 그대로 쓴다.
2. `tools/build_laws.py` 의 `LAW_INDEX` 에 (파일명, id, 그룹, 약칭) 을 등록하고 실행 → `data/laws.json`.
3. `make laws build check`. 법령은 압축돼 들어가므로 크기 부담이 작다(26건 5.7MB → 약 1.4MB).

## 휘장 교체
템플릿의 `<style id="emblem-css">` 안 `.court-ic.scourt` / `.court-ic.ccourt` 의 `background-image`(data URI) 만 바꾸면 전체에 반영됩니다(SVG 도 가능: `data:image/svg+xml;base64,…`).
농도는 앱 설정 패널의 "휘장 농도" 슬라이더로 조절됩니다.

## 웹앱 실행·업데이트

`make web` 은 `output/web/` 에 웹앱을 생성합니다. 로컬에서 확인할 때는 다음처럼 HTTP로 열어야 합니다.

```powershell
python tools/serve_web.py --port 8000
```

브라우저에서 `http://localhost:8000/` 을 엽니다. 이 전용 서버와 `webcheck` 검사 서버는 JavaScript 응답 형식을 고정하여 Windows의 MIME 설정과 무관하게 서비스 워커를 등록할 수 있도록 합니다. `index.html` 을 파일로 직접 여는 방식은 외부 데이터·Service Worker를 사용하는 웹앱 검사가 아닙니다. 파일 하나로 실행하려면 `output/casebook.html` 을 사용합니다.

웹앱은 `data-manifest.json` 으로 데이터 버전과 파일 해시를 확인하고 판례 목록을 먼저 읽습니다. 전문은 해당 사건을 열 때 불러옵니다. 법령도 HTML에 내장하지 않고 별도 파일에서 읽습니다. 같은 데이터 형식 안에서는 새 판례를 반영해도 화면 프로그램을 교체할 필요가 없습니다. 데이터 형식이 바뀔 때는 앱과의 호환성을 함께 검사해야 합니다.

새 버전은 온라인에서 실행하거나 업데이트를 확인할 때 반영합니다. 오프라인에서는 이미 저장한 정상 자료를 사용합니다. 처음부터 저장하지 않은 전문까지 오프라인에 있다고 가정하지 않습니다. 홈 화면 설치는 Android/iOS 브라우저의 설치·홈 화면 추가 메뉴를 이용하며, PWA 설치와 앱스토어용 설치 패키지 제작은 별개입니다.

## GitHub 저장소와 Pages 배포

소스 저장소는 [wonki05/casebook](https://github.com/wonki05/casebook) 입니다. Pages 설정과 워크플로 실행이 성공한 뒤 사용할 주소는 [https://wonki05.github.io/casebook/](https://wonki05.github.io/casebook/) 입니다. 저장소 생성·업로드만으로 배포가 완료된 것은 아닙니다.

최초 설정:

1. 저장소의 **Settings → Pages → Build and deployment → Source** 를 **GitHub Actions** 로 설정합니다.
2. **Actions → Validate and deploy Casebook → Run workflow** 로 `main` 브랜치의 첫 배포를 실행하거나, `main` 에 변경을 push합니다.
3. 검사와 `deploy` 작업이 성공하고 배포 URL이 확인되면 웹앱을 엽니다.

이후 `main` 에 반영한 변경은 `.github/workflows/pages.yml` 이 자동으로 검사·빌드·배포합니다. Pull request에서는 검사만 실행하고 공개 배포는 하지 않습니다. 데이터 생성·검사 명령은 `python tools/make.py validate data laws build check web webcheck` 이며, 검증한 `output/web/` 만 Pages에 게시합니다.

단일 HTML은 저장소에 매번 커밋하지 않습니다. 성공한 Actions 실행의 **Artifacts → casebook-offline** 에서 `output/casebook.html` 을 받을 수 있습니다(워크플로 보관 기간 30일). 로컬에서는 같은 빌드 명령으로 언제든 다시 생성할 수 있습니다.

소스 업로드는 필요한 코드·등록부·목차·공식 수집 JSON·법령 Markdown·설정 파일만 포함합니다. `.gitignore` 는 `output/`, `dist/`, 오타 경로 `ouput/`, `tmp/`, `shots/`, `data/inbox/`, `data/standard-cases/`, 생성된 `data/cases.json`·`data/laws.json`, `.env` 계열, 개인 기록 백업을 제외합니다. 원본 표준판례 PDF는 로컬에서 추출·대조에 사용하며 작업 폴더 전체를 저장소나 Pages에 올리지 않습니다. 새 파일을 추가할 때도 이 업로드 범위를 확인합니다.

## 재판 ID와 표준판례 우선순위

기본 사건 ID는 사용자가 정한 `{선고법원ID}-{사건번호ID}` 형식입니다. 예를 들어 `sc-2022do5937` 은 대법원 사건을 나타냅니다. 같은 사건의 날짜나 판결/결정 유형이 다른 재판을 구분하기 위해 `decisionId` 는 `sc-2022do5937-20260722-judgment` 처럼 날짜·유형을 더합니다. 이 ID는 같은 재판을 표준판례·전원합의체·연도별 기사에서 함께 보여줄 때 공통으로 사용합니다.

`sc`, `cc`, `hcseoul`, `dcseoulcentral` 등은 프로젝트 내부 코드이며 공식 법원 기관코드가 아닙니다. 하급심·지원도 정확한 법원명과 별도 코드로 구분합니다. 전체 규칙과 법원 등록 방법은 `data/schema.md` §1-2, `tools/case_identity.py` 를 따릅니다. 기존 등록부 보완은 `python tools/add_cases.py migrate-identities` 로 하며, 기존 배치 `id` 와 `fetched/<id>.json` 파일명은 유지합니다.

표준판례와 공식 판시사항·요지 등에 차이가 있으면 **PDF에서 추출하고 원본과 대조한 표준판례 내용을 필드별로 우선**합니다. `standardSource` 에 책명·판본·파일·PDF 쪽수와 `verified: true` 를 기록합니다. 없는 필드는 공식 자료로, 두 출처 모두 없는 필드만 편집 요약으로 보충합니다. 표준판례 출처에 명시한 빈 배열은 의도적인 공란이고, 필드를 생략한 것과 다릅니다. 화면에서 표준판례와 공식 자료의 출처를 구별하며 공식 원문 파일을 덮어쓰거나 의역하지 않습니다. 법원·사건번호·날짜 자체가 다르면 동일 재판인지부터 확인해야 합니다.

기존 사건의 과목은 `python tools/add_cases.py set <id> --subject civil` 처럼 바꿉니다. 실제 분류를 확인한 뒤 실행하며 재판 ID와 수집 파일·출처는 유지됩니다. 표준판례의 과목을 바꿀 때는 새 과목의 `--toc` 도 지정하고, 법률신문 판례는 `--field` 와 과목을 맞춥니다.

## 개인 메모·북마크와 모바일 확장

개인 기록은 공개 판례 데이터와 따로 저장합니다. 판례 자료를 교체해도 메모·북마크를 지우지 않으며, 같은 재판은 `decisionId` 로 연결합니다. 기존 배치 ID의 기록은 매핑하여 이전하고 충돌하는 메모도 보존합니다.

로컬 HTML과 웹 도메인은 저장 공간이 다르므로 자동으로 기록이 옮겨지는 것으로 가정하지 않습니다. 설정에서 개인 기록을 내보낸 뒤 새 환경에서 가져옵니다. 이 백업 기능은 계정 기반 기기 간 자동 동기화가 아닙니다. 자동 동기화와 Android/iOS 네이티브 설치 패키지는 PWA 사용 검증 후 별도 단계로 구현합니다.
