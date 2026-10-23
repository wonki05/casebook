# 판례집 시안 공통 사양 (SPEC)

세 시안(design-a / design-b / design-c)은 **같은 데이터, 같은 기능 집합, 다른 구조·레이아웃**을 가진다.
이 문서의 규칙은 모든 시안에 공통으로 적용된다. 시안별 구조 지시는 맨 아래 §9.

## 0. 산출물
- 템플릿: `src/design-<x>.html` (단일 파일; 외부 JS 없음; 폰트만 Google Fonts `<link>` 허용)
- 템플릿 안에 **정확히 한 번** 다음 줄을 둔다. 빌드 시 데이터가 주입된다.
  `<script id="case-data" type="application/json">__CASE_DATA_JSON__</script>`
- 빌드: `python3 tools/build.py src/design-<x>.html` → `dist/design-<x>.html`
- 확인: `python3 tools/shot.py dist/design-<x>.html shots/<x>` (모바일/데스크톱 × 라이트/다크 스크린샷 + 콘솔 오류 출력)
  판례를 연 상태도 반드시 찍어본다(세 번째 인자로 JS 전달). 스크린샷을 Read 로 열어 직접 눈으로 확인하고 고친다.
- 템플릿에는 데이터를 넣지 말 것(마커만). 개발 중엔 `dist/` 파일을 연다.

## 1. 데이터 (`data/cases.json`) — 빌드 시 주입됨
```
{ meta: {title, built, note, count, stats},
  groups:   [{id:'standard'|'annual'|'enbanc'|'ccourt', label, short, desc}],     // 4개 페이지 = 4개 group
  subjects: [{id:'constitution'|'administrative'|'civil'|'criminal', label}],      // 헌법/행정법/민법/형법
  toc: { <subjectId>: [{id, label, children:[{id,label}]}] },                     // 표준판례 목차(2단계). standard 전용
  cases: [ {
    id, group, subject,
    tocPath: ['hb-1','hb-1-3'] | [],      // standard 만. [편 id, 장 id]
    title,                                // 학습용 짧은 제목(편집)
    caseName,                             // 공식 사건명 (예: "상관모욕", "국회의원과 국회의장 간의 권한쟁의") — 없을 수 있음
    court: '대법원'|'헌법재판소',
    bench: '전원합의체'|'전원재판부'|'지정재판부'|'',
    caseNumber: '2022도5937' | '2023헌바274·351',
    decisionDate: 'YYYY-MM-DD',
    decisionType: '판결'|'결정',
    citation: '대법원 2026. 7. 22. 선고 2022도5937 전원합의체 판결',   // 그대로 표시용. 항상 법원명+선고일+사건번호 포함
    result: '파기환송'|'위헌'|'합헌'|'기각'|'각하'|''  ,                  // 주문 요약(짧게). 비어 있을 수 있음
    summaryType: 'official'|'editorial',   // editorial = 공식 판시사항/요지 미수록(편집 요약). 화면에 작은 표시 필요(§4)
    holdingLabel: '판결요지'|'결정요지',   // 헌법재판소는 결정요지
    issues:   [{n:'[1]'|'1.'|'가.'|'', text}],   // 판시사항 항목. text 안의 \n 은 문단 구분
    holdings: [{n, text}],                       // 판결요지/결정요지 항목 ([다수의견] 등 소제목은 text 안에 그대로 있음)
    subjectStatutes: [string],            // 심판대상조문 (헌법재판소). 비어 있을 수 있음
    statutes: [string],                   // 참조조문 (예: "[1] 헌법 제12조 제1항, 제21조, 군형법 제64조")
    precedents: [string],                 // 참조판례
    fullText: [{heading:'【전문】'|'【주 문】'|'【이 유】'|…, text}] | null,   // 판결문 전문(공식). null 이면 미수록
    source: {label:'국가법령정보센터', url} | null,
    annual: {year:2025, series:'법률신문 2025년 분야별 중요판례분석', part:'(1) 헌법'} | null,
    tags: [string]
  } ] }
```
- 읽기: `JSON.parse(document.getElementById('case-data').textContent)`.
- 전문(fullText) 길이는 사건당 최대 4만 자 이상일 수 있다. 가상 스크롤은 불필요하지만, 전문 탭을 열 때만 렌더한다.

## 2. 페이지 구조 (4 페이지)
1. **표준판례** — 과목(헌법·행정법·민법·형법) → **목차(편/장) 트리** → 판례 목록. 목차는 열고 닫을 수 있고, 각 노드에 수록 건수를 표시한다. 수록 0건인 장도 목차에는 보이되 흐리게.
2. **분야별 주요판례** — 과목별 묶음(헌법 2·행정법 2·민법 2·형법 3). 각 사건에 `annual.part` 표시.
3. **대법원 전원합의체** — 선고일 내림차순, 월별 구분선. 과목 칩으로 필터.
4. **헌법재판소 주요결정** — 선고일 내림차순, 월별 구분선. 과목 칩으로 필터.
- 페이지 전환 UI는 어떤 화면 폭에서도 한 번의 탭/클릭으로 가능해야 한다.
- 라우팅: `location.hash = '#/<group>/<caseId>'` (사건 없이 `#/<group>` 도 가능). 새로고침·뒤로가기 동작.

## 3. 판례 열람 화면 (reader)
헤더: `title` (큰 제목) · `caseName` (있으면 작은 글씨) · **인용표시 줄 = `citation` 그대로** (법원 아이콘 + 글자) · `result` 배지 · 과목 · (표준판례) 목차 경로 · 북마크 버튼 · 인용문 복사 버튼.
탭 3개:
- **판시사항·요지** (기본): 순서대로 ① 판시사항 ② 판결요지/결정요지(`holdingLabel`) ③ 심판대상조문(있을 때) ④ 참조조문 ⑤ 참조판례(있을 때)
- **판결문 전문** (헌법재판소는 "결정문 전문"): `fullText` 블록을 순서대로. 블록 heading(【주 문】【이 유】 등)은 고딕 소제목, 본문은 명조. 본문은 빈 줄 기준 문단(`<p>`), 한 줄 줄바꿈은 줄바꿈 유지. `fullText === null` 이면 안내문 한 줄: "판결문 전문이 아직 수록되지 않았습니다. (데이터 작업 단계에서 추가)" — **외부 링크·iframe 대체 금지**.
- **메모**: 사건별 개인 메모(`<textarea>`, localStorage 자동 저장).
- 이전/다음 판례 이동(현재 목록 기준).
- **없애야 하는 것**: 학습상태(읽는 중/완료) 선택, 요지 가리기/보이기, 복습 주기, 홍보성 문구.

## 4. 타이포그래피 (가장 중요)
```css
:root{
  --serif: "Noto Serif KR","Noto Serif CJK KR","KoPubWorld Batang","KoPub Batang","Nanum Myeongjo","나눔명조","Batang","바탕","AppleMyungjo",Georgia,serif;
  --sans:  "Noto Sans KR","Pretendard Variable","Pretendard",-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic","맑은 고딕","Segoe UI",Roboto,sans-serif;
}
```
`<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>`
`<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=Noto+Serif+KR:wght@400;600&display=swap" rel="stylesheet">`
- **판결문 텍스트(판시사항·요지·참조조문·참조판례·전문 본문)는 명조(--serif)**. 기본 16px(모바일 16px), line-height 1.85, `word-break: keep-all; overflow-wrap: anywhere;` 전문 문단은 `text-align: justify` 권장(가독성 확인 후 결정), `text-indent` 선택.
- **개요 요소(제목, 소제목, 섹션 이름 "판시사항"/"판결요지", 전문의 【주 문】【이 유】, 목차, 탭, 버튼 등 UI)는 고딕(--sans)**.
- **항목 번호 `n` ([1], [2] / 1. 2. / 가. 나.)는 고딕 세미볼드, 들여쓰기(hanging indent)**:
  ```html
  <ol class="items"><li><span class="n">[1]</span><div class="t"><p>…</p><p>…</p></div></li></ol>
  ```
  ```css
  .items{list-style:none;margin:0;padding:0}
  .items li{display:grid;grid-template-columns:max-content 1fr;column-gap:.6em;margin:0 0 .9em}
  .items .n{font-family:var(--sans);font-weight:600;min-width:2.1em;color:var(--accent-ink)}
  .items .t{font-family:var(--serif)} .items .t p{margin:0 0 .55em}
  ```
  `n === ''` 이면 `.n` 을 비우고 들여쓰기 없이 본문만.
- 글자 크기 조절(A− / A+, 14–20px)은 명조 본문에만 적용. 설정 저장.

## 5. 색 — "보라색은 적게, 또렷하게"
- 기본은 종이/잉크: 밝은 모드 배경 `#FFFFFF`(또는 `#FBFAF8`), 글자 `#1B1A20`, 보조 글자 `#5A5866`, 선 `#E6E3EE`.
- 보라는 **강조 1색 + 연한 배경 1색** 정도만: `--accent:#5B3FA6` (기본), `--accent-ink:#3F2B7A` (글자용 짙은 보라), `--accent-soft:#F1EDF9` (선택 배경), 다크 모드 `--accent:#B7A6EC`, `--accent-soft:#2A2344`.
- 보라를 쓰는 곳: 현재 페이지/선택 항목 표시, 탭 밑줄, 항목 번호(선택), 주 버튼, 링크, 아이콘. **넓은 면(헤더 전체, 카드 전체, 배경)을 보라로 칠하지 않는다.**
- 다크 모드: 배경 `#15141A`, 표면 `#1D1C24`, 글자 `#ECEAF2`, 보조 `#A5A2B5`, 선 `#2C2A38`. `prefers-color-scheme` 자동 + 수동 토글(시스템/밝게/어둡게 3단, 설정 저장). 토글은 눈에 띄는 스위치여야 함.
- 블루라이트 차단: 화면 전체 오버레이 `position:fixed; inset:0; pointer-events:none; z-index:9999; background:#ff9a2e; mix-blend-mode:multiply;` 단계 끔/약(Low) .10 /중(Medium) .20 /강(High) .32 (opacity). 라벨은 "끔 · 약(Low) · 중(Medium) · 강(High)". 설정 저장.

## 6. 공통 기능 (모든 시안 필수)
- 검색: 전체 그룹 대상, 입력 즉시(150ms 디바운스), 공백으로 나눈 용어 AND 매치. 대상 필드: title, caseName, caseNumber, citation, issues/holdings text, statutes, tags. 결과에 그룹·과목·citation 표시, 매치어 `<mark>`. `/` 키로 검색창 포커스, Esc 로 닫기.
- 북마크: 별표 토글(목록·헤더 양쪽), "북마크" 보기(모든 그룹의 북마크 모음). 
- 다크 모드 토글, 블루라이트 차단 단계, 글자 크기: "설정" 패널(시트/팝오버)에서. 
- 마지막으로 읽던 판례 복원(해시 또는 저장값).
- 인용문 복사(`citation` 문자열 클립보드 복사, 토스트 "인용 표시를 복사했습니다").
- 키보드: `j/k` 또는 `←/→` 이전·다음 판례, `b` 북마크, `1/2/3` 탭, `/` 검색.
- 인쇄 CSS(판례 1건 인쇄 시 깔끔하게).
- 저장 키(세 시안 공통, 같은 origin 에서 공유되도록): `lawbook:bookmarks`(id 배열) · `lawbook:notes`({id:text}) · `lawbook:settings`({theme:'auto'|'light'|'dark', blue:'off'|'low'|'mid'|'high', font:number}) · `lawbook:last`({group, caseId}).
- 선택 기능(권장, 1~3개): 판시사항·요지 "대응 보기"(같은 번호끼리 가로 나란히; 넓은 화면만), 같은 참조조문을 가진 판례 "관련 판례", 전문 읽기 진행률 바, 북마크 JSON 내보내기, 전문 안에서 문자열 찾기.

## 7. 표기 규칙 (UI 문구)
- "헌재", "전합" 약칭 **금지** → "헌법재판소", "전원합의체". (공식 원문 텍스트 안의 표기는 수정하지 않는다.)
- 사건 표시는 항상 **법원명 + 사건번호**, 가능하면 선고일 병기. 목록에서 좁을 때 최소: `대법원 2022도5937 · 2026. 7. 22.`
- `summaryType==='editorial'` 인 사건의 요지 아래에 작은 회색 한 줄: "※ 공식 판시사항·요지 미수록 — 편집 요약(데이터 작업 시 교체)".
- 홍보성·장식성 문구 금지("천천히 읽을수록…" 류). 라틴어 법격언은 **한 화면에 최대 1개**, 작게, 한국어 번역 병기, 빈 상태(사건 미선택)나 페이지 머리에만. 목록:
  Fiat iustitia, ruat caelum — 하늘이 무너져도 정의를 세우라 / Nullum crimen sine lege — 법률 없으면 범죄 없다 / Ubi ius, ibi remedium — 권리 있는 곳에 구제 있다 / Pacta sunt servanda — 약속은 지켜져야 한다 / Audi alteram partem — 상대방의 말도 들으라 / In dubio pro reo — 의심스러울 때는 피고인의 이익으로 / Lex specialis derogat legi generali — 특별법은 일반법에 우선한다 / Nemo iudex in causa sua — 누구도 자기 사건의 재판관이 될 수 없다.
- 출처 표시: 사건 하단에 작은 글씨 "출처: 국가법령정보센터" (링크는 허용하되 작게; 본문을 대신하는 링크·iframe 은 금지).
- 앱 이름은 "판례집"(가칭). 부제 없음.

## 8. 법원 아이콘 (공통 SVG symbol — 그대로 복사해 넣고 크기·색만 CSS 로)
문서 `<body>` 맨 앞에 한 번 정의. 대법원(전원합의체 포함) = `#ic-scourt`, 헌법재판소 = `#ic-ccourt`. 사용: `<svg class="court-ic"><use href="#ic-scourt"/></svg>`.
배경 없는 선(line) 아이콘, `currentColor`. (공식 휘장이 아니라 자체 제작 도안이다. 나중에 공식 휘장 SVG 로 교체할 수 있도록 symbol 하나에만 들어 있다.)
```html
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <symbol id="ic-scourt" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="4.6" r="2"/>
    <path d="M10.2 8.6h3.6l1.7 12.4H8.5z"/>
    <path d="M5 10.2h14"/>
    <path d="M5 10.2l-2 4.2h4z"/><path d="M19 10.2l-2 4.2h4z"/>
    <path d="M5.5 21h13"/>
  </symbol>
  <symbol id="ic-ccourt" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 3.2v3.6"/><path d="M7.6 4.6h8.8"/>
    <path d="M7.6 4.6l-1.6 3h3.2z"/><path d="M16.4 4.6l-1.6 3h3.2z"/>
    <path d="M3.5 10.5c2.6-.9 5.6-.9 8.5.6 2.9-1.5 5.9-1.5 8.5-.6v9.6c-2.6-.9-5.6-.9-8.5.6-2.9-1.5-5.9-1.5-8.5-.6z"/>
    <path d="M12 11.1v9.6"/>
  </symbol>
</svg>
```
전원합의체/전원재판부 표시는 아이콘 옆 글자로(아이콘을 바꾸지 않는다).

## 9. 시안별 구조 (서로 달라야 하는 부분)
### design-a — "서가(書架)": 세로 분할 열람기
- 데스크톱(≥1024px): 왼쪽 사이드바(폭 300px) = 상단 페이지 전환(4개) + 그 아래 현재 페이지의 탐색 트리(표준판례: 과목 → 편 → 장 → 판례; 다른 페이지: 과목/월 → 판례). 가운데 = reader(최대 폭 760px, 좌측 정렬). 오른쪽(≥1280px) 얇은 정보 레일(220px): 인용표시, 결과, 참조조문 목록, 북마크/복사/메모 바로가기, 전문 읽기 진행률.
- 모바일: 사이드바는 왼쪽 드로어, 하단 고정 바 4개(목차 · 검색 · 북마크 · 설정). reader 는 전체 폭.
- 인상: 종이와 먹, 가는 선. 보라는 트리의 현재 항목 세로 바와 탭 밑줄, 아이콘에만.
### design-b — "판례집(判例集)": 책 같은 단일 열
- 상단 바: 왼쪽 "목차" 버튼, 가운데 4개 페이지 탭, 오른쪽 검색·설정·테마.
- 본문: 가운데 정렬 단일 열(최대 720px), 따뜻한 미색 배경(`#FBFAF7`, 다크는 `#16151B`). 사건을 열면 "책의 한 항목"처럼: 상단 running head(페이지 › 과목 › 편 › 장), 큰 제목, 인용표시, 그 아래 섹션. 섹션 번호는 로마숫자 또는 한자 숫자(一, 二, 三) 작게.
- 목차는 왼쪽에서 슬라이드-인 되는 패널(모든 화면 폭 공통). 사건 하단에 이전/다음 "항목" 넘김 바.
- 빈 상태(사건 미선택)는 해당 페이지의 목차를 본문 열에 바로 보여준다(책의 차례처럼).
- 인상: 인쇄된 판례집. 보라는 상단 얇은 선, 장 번호, 현재 탭 표시에만.
### design-c — "색인(索引)": 카드 격자 + 열람 시트
- 상단: 페이지 전환 세그먼트(4개) + 검색창 상시 노출. 그 아래 필터 바(과목 칩, 표준판례는 편/장 선택, 정렬: 목차순/선고일순).
- 본문: 판례 카드 격자(데스크톱 2~3열, 모바일 1열). 카드 = 법원 아이콘 + citation + title + 요지 첫 항목 2줄 + 참조조문 칩 1~3개 + 북마크 별.
- 카드를 누르면 reader 가 오른쪽에서 열리는 시트(데스크톱 폭 640px, 뒤 격자 흐림; 모바일 전체 화면). 시트 안에 3개 탭과 이전/다음.
- 상단에 "최근 읽은 판례" 가로 스크롤 줄(최대 6개).
- 인상: 앱 같은 밀도, 그러나 카드 안의 텍스트는 명조로 차분하게. 보라는 선택된 칩/카드 테두리/탭 표시에만.

## 10. 품질 기준
- 콘솔 오류 0. 모바일 390px 에서 가로 스크롤 없음, 안전영역(`env(safe-area-inset-bottom)`) 반영.
- 45건 모두 열어서 렌더 오류 없는지 스크립트로 확인(Playwright 에서 모든 case 를 순회하며 `pageerror` 수집).
- 텍스트 대비 WCAG AA. 터치 타깃 44px.
- 파일 크기: 데이터 제외 템플릿 60~120KB 내외 목표(불필요한 코드 금지).
