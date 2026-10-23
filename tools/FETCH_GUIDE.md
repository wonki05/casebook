# 국가법령정보센터(law.go.kr) 판례·헌재결정례 원문 추출 가이드

목표: 지정된 사건 각각에 대해 law.go.kr 의 공식 페이지에서 **판시사항 / 판결요지(결정요지) / 심판대상조문 / 참조조문 / 참조판례 / 전문(주문·이유 등)** 을
**한 글자도 바꾸지 않고(verbatim)** 추출하여 JSON 파일로 저장한다. 요약·의역·생략 절대 금지. 텍스트를 직접 타이핑하지 말고
반드시 아래 JS 추출기 결과를 그대로 파일에 쓴다.

## 0. 도구 준비
- 브라우저 도구가 deferred 상태이면 ToolSearch 한 번으로 모두 로드:
  `ToolSearch { query: "mcp__remote-devices__Claude_Browser__", max_results: 64 }`
- 탭 열기: `preview_start { url: "<첫 번째 URL>" }` → 반환된 `tabId` 를 **모든** 후속 호출(navigate / javascript_tool)에 반드시 넘긴다
  (다른 에이전트가 같은 브라우저의 다른 탭을 동시에 쓰고 있으므로 tabId 없는 호출 금지).
- 사이트 접근이 "허용되지 않음"이라고 나오면 `request_access { url: "https://www.law.go.kr", scope: "site" }` 호출 후 재시도.
- 작업 끝나면 `tabs_close { tabId }` 로 자기 탭만 닫는다.

## 1. 페이지 URL 규칙
- 대법원 판례(kind=prec): seq 를 알면 `https://www.law.go.kr/LSW/precInfoP.do?precSeq=<seq>`
  모르면 `https://www.law.go.kr/판례/(<lookupKey>)` 로 navigate → 약 3초 대기 후
  `Array.from(document.querySelectorAll('iframe')).map(f=>f.src)` 로 iframe src 에서 `precSeq=NNN` 을 읽고, 그 `precInfoP.do?precSeq=NNN` URL로 다시 navigate.
- 헌법재판소 결정(kind=detc): seq 를 알면 `https://www.law.go.kr/LSW/detcInfoP.do?detcSeq=<seq>`
  모르면 `https://www.law.go.kr/헌재결정례/(<lookupKey>)` → iframe src 에서 `detcSeq=NNN` → `detcInfoP.do?detcSeq=NNN`.
- navigate 직후에는 `await new Promise(r=>setTimeout(r,2500))` 정도 기다린 뒤 추출한다. `#conScroll` 이 없으면 1~2번 더 기다려 본다.
- 페이지 제목(h2)과 사건번호가 목표 사건과 일치하는지 확인한다(병합사건은 대표 사건번호만 일치하면 됨).

## 2. 추출기 (javascript_tool, action=javascript_exec, tabId 필수)
### 2-1. 1단계: 섹션 목록만 받기(본문은 window.__law 에 저장)
```js
(() => {
  const root = document.querySelector('#conScroll') || document.querySelector('#contentBody');
  if (!root) return {error:'no root', title: document.title, url: location.href};
  const toText = (el) => { const c = el.cloneNode(true);
    c.querySelectorAll('br').forEach(b=>b.replaceWith('\n'));
    c.querySelectorAll('p,div,li,tr,h5,h6').forEach(b=>b.appendChild(document.createTextNode('\n')));
    return c.textContent.replace(/\u00a0/g,' ').replace(/[ \t]+\n/g,'\n').replace(/\n{3,}/g,'\n\n').trim(); };
  const sections=[]; let cur=null;
  Array.from(root.children).forEach(ch=>{
    if(/^H[1-6]$/.test(ch.tagName)){ cur={heading:ch.textContent.trim(), text:''}; sections.push(cur); }
    else if(ch.tagName==='INPUT'||ch.tagName==='SCRIPT'||ch.tagName==='STYLE'){ }
    else { const t=toText(ch); if(!t) return; if(cur) cur.text+=(cur.text?'\n':'')+t; else sections.push({heading:'', text:t}); }
  });
  const h2=document.querySelector('#contentBody h2'); const sub=document.querySelector('#contentBody .subtit1');
  window.__law={pageTitle:h2?h2.textContent.trim():document.title, citation:sub?sub.textContent.trim():'', url:location.href, sections};
  return {pageTitle:window.__law.pageTitle, citation:window.__law.citation, url:location.href,
          sections:sections.map((s,i)=>({i, heading:s.heading, len:s.text.length}))};
})()
```
### 2-2. 2단계: 섹션 본문 받기
- 길이 합계가 작으면(총 40,000자 이하) 한 번에: `window.__law.sections.map(s=>({heading:s.heading,text:s.text}))`
- 길면 섹션별/구간별로 나누어 받는다: `window.__law.sections[i].text.slice(0,40000)`, `.slice(40000,80000)` …
  한 번의 호출 결과가 40,000자를 넘지 않게 한다.

## 3. 저장 형식 (파일: `/home/claude/lawbook/data/fetched/<id>.json`)
```json
{
  "id": "<id>",
  "caseNumber": "<fetch_targets 의 caseNumber>",
  "lookupKey": "<lookupKey>",
  "kind": "prec | detc",
  "seq": "<precSeq 또는 detcSeq 숫자>",
  "sourceUrl": "https://www.law.go.kr/LSW/precInfoP.do?precSeq=NNN  (또는 detcInfoP.do?detcSeq=NNN)",
  "pageTitle": "<h2 사건명 그대로>",
  "citation": "<subtit1 그대로, 예: [대법원 2026. 7. 22. 선고 2022도5937 전원합의체 판결] 또는 [전원재판부 2026헌라3, 2026. 7. 23.]>",
  "sections": [ {"heading": "【판시사항】", "text": "..."}, {"heading": "【판결요지】", "text": "..."}, ... , {"heading": "【이 유】", "text": "..."} ]
}
```
- sections 는 페이지 순서 그대로, heading 과 text 를 **그대로** 넣는다(빈 heading 섹션도 유지). 긴 섹션을 여러 번에 나눠 받았으면 이어 붙여서 하나의 text 로 저장.
- JSON 문자열 이스케이프(따옴표, 줄바꿈 \n)에 주의. Write 도구로 저장하며, 저장 후 `python3 -c "import json;json.load(open('<path>'))"` 로 유효성 검사.
- 파일이 너무 커서 한 번의 Write 가 부담되면 섹션을 `<id>.part1.json`, `<id>.part2.json` 처럼 나누어 저장해도 된다(각 파일은 같은 스키마에 sections 일부만 포함). 나중에 병합한다.

## 4. 실패 처리
- 페이지를 못 찾으면(검색 결과 없음, iframe 없음 등) `/home/claude/lawbook/data/fetched/<id>.missing.json` 에
  `{"id":"...","reason":"...","triedUrls":[...]}` 를 저장하고 다음 사건으로 넘어간다. 같은 사건에 3번 이상 재시도하지 않는다.
- 어떤 경우에도 텍스트를 요약·재작성하지 않는다. 추출기가 돌려준 문자열만 저장한다.

## 5. 완료 보고
마지막에 사건별로 `성공(길이) / 실패(이유)` 한 줄씩 요약하여 보고한다. 본문 내용은 보고에 넣지 않는다.
