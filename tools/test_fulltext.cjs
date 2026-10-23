#!/usr/bin/env node
/* Regression checks for judgment/decision typography using the built HTML's actual functions.
 * Run after building: node tools/test_fulltext.cjs [output/casebook.html]
 * Uses only Node built-ins; does not modify HTML or official case data.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const htmlPath = process.argv[2] || path.join(__dirname, '..', 'output', 'casebook.html');
const html = fs.readFileSync(htmlPath, 'utf8');
function between(start, end) {
  const a = html.indexOf(start), b = html.indexOf(end, a + start.length);
  assert(a >= 0 && b > a, `Missing source section: ${start}`);
  return html.slice(a, b);
}
const helpers = ['sq', 'esc'].map(name => {
  const matches = html.match(new RegExp(`^const ${name} = .+;$`, 'gm')) || [];
  assert.equal(matches.length, 1, `Expected one actual ${name} definition`);
  return matches[0];
}).join('\n');
const context = vm.createContext(Object.create(null));
vm.runInContext([
  helpers,
  'const S = {findQ: ""};',
  between('/* ---------- 전문 조판 ---------- */', '/* ---------- statute refs'),
  between('function srcHTML(c) {', 'function memoHTML(c) {'),
  'globalThis.api = {ftLines, fullHTML, sq, esc, setQuery(q) { S.findQ = q; }};'
].join('\n'), context, {filename: htmlPath, timeout: 1000});
const api = context.api;
const dataMatch = html.match(/<script\b[^>]*\bid=["']case-data["'][^>]*>([\s\S]*?)<\/script\s*>/i);
assert(dataMatch, 'Missing embedded case data');
const cases = JSON.parse(dataMatch[1]).cases;
const headings = rendered => [...rendered.matchAll(/<p class="hd h1"[^>]*>(.*?)<\/p>/g)].map(m => m[1]);
const normalized = text => String(text || '').split('\n').map(l => api.sq(l).trim()).filter(Boolean);
const isHeading = (rendered, title) => headings(rendered).includes(api.esc(title));
const reason = id => {
  const c = cases.find(item => item.id === id);
  assert(c, `Missing regression case ${id}`);
  const b = c.fullText.find(block => api.sq(block.heading).replace(/[\s\[\]]/g, '') === '이유');
  assert(b, `Missing reason block ${id}`);
  return {c, rendered: api.ftLines(b.text, true)};
};
let passed = 0;
function check(name, test) {
  try { test(); passed++; }
  catch (error) { error.message = `${name}: ${error.message}`; throw error; }
}
check('Only top-level outlines', () => {
  const text = '1. 사건개요\n가. 하위 개요\n(1) 내용\n1) 내용\n① 내용\n[반대의견]\n재판관 홍길동 김철수 이영희\n2. 심판대상';
  const rendered = api.ftLines(text, true);
  assert.deepEqual(headings(rendered), ['1. 사건개요', '2. 심판대상']);
  assert(!/class="(?:np|judges)"|<h4>/.test(rendered));
});
check('Non-reason blocks stay plain', () => {
  assert.equal(api.ftLines('1. 사건개요\n2. 판단\n① 내용', false), '<p>1. 사건개요</p><p>2. 판단</p><p>① 내용</p>');
});
check('Order keeps dedicated numbering', () => {
  const rendered = api.ftLines('1. 심판청구를 기각한다.\n2. 나머지 청구를 각하한다.', false, true);
  assert.equal((rendered.match(/class="np"/g) || []).length, 2);
  assert.equal(headings(rendered).length, 0);
});
check('2025헌라1 quoted ministry item', () => {
  const {rendered} = reason('annual-2025-02');
  assert(rendered.includes('<p>1. 기획재정부</p>'));
  assert(isHeading(rendered, '2. 심판대상'));
  assert(isHeading(rendered, '3. 청구인의 주장 및 피청구인의 답변'));
});
check('2026헌가1 returns from statutory quotation', () => {
  const {rendered} = reason('cc-2026heolga1');
  for (const title of ['3. 제청법원의 위헌제청이유', '4. 이 사건 정의 조항에 대한 판단', '5. 이 사건 과세 조항에 대한 판단', '6. 결론']) assert(isHeading(rendered, title), title);
});
check('2026헌바70 quoted table is not a final annex', () => {
  const {rendered} = reason('cc-2026heolba70');
  for (const title of ['3. 청구인들의 주장', '4. 판단', '5. 결론']) assert(isHeading(rendered, title), title);
});
check('Quoted item ending in 여부 is not an outline', () => {
  const rendered = api.ftLines('1. 사건개요\n2. 심판대상\n[관련조항]\n제1조(목적)\n3. 심사 여부\n3. 청구인의 주장\n4. 판단', true);
  assert(rendered.includes('<p>3. 심사 여부</p>'));
  assert(isHeading(rendered, '3. 청구인의 주장'));
  assert(isHeading(rendered, '4. 판단'));
});
check('Final annex stays plain', () => {
  const rendered = api.ftLines('1. 사건개요\n2. 판단\n[별지]\n1. 사건개요\n2. 판단\n3. 결론', true);
  assert.deepEqual(headings(rendered), ['1. 사건개요', '2. 판단']);
});
check('Narrative sentence is not an outline', () => {
  assert.equal(api.ftLines('3. 이를 앞서 본 법리에 비추어 살펴본다.', true), '<p>3. 이를 앞서 본 법리에 비추어 살펴본다.</p>');
});
let checkedBlocks = 0;
check('Corpus preserves text and removes lower-level layout', () => {
  for (const c of cases) for (const block of c.fullText || []) {
    const name = api.sq(block.heading).replace(/[\s\[\]]/g, '');
    if (name === '주문') continue;
    const rendered = api.ftLines(block.text, /^(?:이유|전문)$/.test(name));
    assert.equal(rendered.replace(/<[^>]*>/g, ''), normalized(block.text).map(api.esc).join(''), `${c.id} ${block.heading}`);
    assert(!/class="(?:np|judges)"|<h4>/.test(rendered), `${c.id} ${block.heading}`);
    checkedBlocks++;
  }
});
check('Search highlights escaped text without changing outlines', () => {
  const c = {court: '헌법재판소', fullText: [{heading: '[이유]', text: '1. 사건개요\n가. 검색 & <표> "인용"\n2. 심판대상'}]};
  const before = api.fullHTML(c);
  api.setQuery('검색 & <표>');
  const highlighted = api.fullHTML(c);
  api.setQuery('');
  assert(highlighted.includes('<mark class="hit">검색 &amp; &lt;표&gt;</mark>'));
  assert(highlighted.includes('id="findCnt">1건</span>'));
  assert.deepEqual(headings(highlighted), headings(before));
  assert(!highlighted.includes('<표>'));
});
console.log(`PASS: ${passed} full-text regression checks; ${cases.length} cases, ${checkedBlocks} non-order blocks checked (${path.resolve(htmlPath)}).`);