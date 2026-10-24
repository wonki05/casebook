const test = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto, createHash} = require('node:crypto');
const {createProvider, createUpdateMonitor} = require('../src/data-provider.js');
const personal = require('../src/personal-data.js');
const digest = text => createHash('sha256').update(text).digest('hex');
const BASE = 'https://example.test/casebook/';
function fixture() {
  const files = new Map(), cached = new Map(), calls = [];
  const cache = {async match(url) { const v = cached.get(String(url)); return v && v.clone(); }, async put(url,r) { cached.set(String(url),r.clone()); }, async delete(url) { return cached.delete(String(url)); }};
  let online = true;
  function add(path,obj) { const text = JSON.stringify(obj); files.set(BASE+path,text); return {url:path,sha256:digest(text)}; }
  const full = add('data/full.one.json',[{heading:'[이유]',text:'공식 원문\n가. 원문 보존'}]);
  const laws = add('data/laws.one.json',{groups:[],laws:[]});
  const data = {pages:[{id:'enbanc'}],subjects:[],cases:[{id:'old-1',page:'enbanc',fullTextRef:full}]};
  const cases = add('data/cases.one.json',data);
  const manifest = {schemaVersion:1,version:'v1',generatedAt:'2026-10-24',cases,laws};
  add('data-manifest.json',manifest);
  const env = {baseURL:BASE+'index.html',crypto:webcrypto,caches:{async open(){return cache;}},async fetch(url) {calls.push(String(url)); if(!online)throw Error('offline'); const s=files.get(String(url));return new Response(s||'not found',{status:s?200:404});}};
  return {files,cached,calls,cache,env,data,full,laws,cases,manifest,add,setOnline:v=>online=v,provider:()=>createProvider(env)};
}
test('placement migration preserves distinct notes, aliases and unknown records',()=>{
  const cases=[{id:'std-old',decisionId:'sc-1-20260101-judgment'},{id:'enbanc-old',decisionId:'sc-1-20260101-judgment'}];
  const result=personal.normalize({bookmarks:['std-old','enbanc-old','unknown'],notes:{'std-old':'메모 A','enbanc-old':'메모 B',unknown:'미등록 메모'}},cases);
  assert.deepEqual(result.bookmarks,['sc-1-20260101-judgment','unknown']);
  assert.ok(result.notes['sc-1-20260101-judgment'].includes('메모 A'));
  assert.ok(result.notes['sc-1-20260101-judgment'].includes('메모 B'));
  assert.equal(result.notes.unknown,'미등록 메모');
  assert.equal(result.conflicts.length,1);
});
test('backup import merges without replacing existing notes or enabling prototype pollution',()=>{
  const incoming={format:'lawbook-personal',version:1,bookmarks:['new'],notes:{same:'가져온 메모',new:'새 메모'}};
  const r=personal.merge({bookmarks:['old'],notes:{same:'기존 메모'}},incoming,[]);
  assert.ok(r.notes.same.includes('기존 메모')&&r.notes.same.includes('가져온 메모'));
  assert.deepEqual(r.bookmarks,['old','new']);
  assert.throws(()=>personal.merge({},JSON.parse('{"format":"lawbook-personal","version":1,"bookmarks":[],"notes":{"__proto__":"bad"}}'),[]));
  assert.throws(()=>personal.merge({}, {...incoming,version:99}, []));
});
test('metadata boot does not download full text or laws and respects project subpath',async()=>{
  const f=fixture(),p=f.provider(); await p.loadCases();
  assert.deepEqual(f.calls,[BASE+'data-manifest.json',BASE+f.cases.url]);
  const c=(await p.loadCases()).cases[0];await p.loadFullText(c);
  assert.equal(c.fullText[0].text,'공식 원문\n가. 원문 보존');
  await p.loadLaws(); assert.equal(f.calls.length,4);
});
test('SHA mismatch cannot populate official full text',async()=>{
  const f=fixture(),p=f.provider(),c=(await p.loadCases()).cases[0];
  f.files.set(BASE+f.full.url,JSON.stringify([{text:'altered'}]));
  await assert.rejects(p.loadFullText(c),/무결성/);assert.equal(c.fullText,undefined);
  assert.equal(await f.cache.match(BASE+f.full.url),undefined);
});
test('corrupted cached resources are rejected and replaced from verified network bytes',async()=>{
  const f=fixture(),p=f.provider();await p.loadCases();
  await f.cache.put(BASE+f.full.url,new Response('[{"text":"bad"}]'));
  const c=(await p.loadCases()).cases[0];await p.loadFullText(c);
  assert.equal(c.fullText[0].text,'공식 원문\n가. 원문 보존');
});
test('complete offline pack reloads all data with network unavailable',async()=>{
  const f=fixture(),p=f.provider();await p.loadCases(); const result=await p.downloadOffline();assert.equal(result.files,3);
  f.setOnline(false);const offline=f.provider(),data=await offline.loadCases();
  assert.equal(offline.status().offline,true);await offline.loadFullText(data.cases[0]);await offline.loadLaws();
  assert.equal(data.cases[0].fullText.length,1);
});
test('incompatible new schema falls back to saved verified release',async()=>{
  const f=fixture();await f.provider().loadCases();f.add('data-manifest.json',{...f.manifest,schemaVersion:88});
  const p=f.provider();await p.loadCases();assert.equal(p.status().version,'v1');assert.equal(p.status().offline,true);
});
test('update check validates candidates without changing active session',async()=>{
  const f=fixture(),p=f.provider();await p.loadCases();f.add('data-manifest.json',{...f.manifest,version:'v2'});
  const result=await p.checkForUpdate();assert.equal(result.available,true);assert.equal(p.status().version,'v1');
});
test('external or parent-path resource URLs are refused',async()=>{
  const f=fixture();f.add('data-manifest.json',{...f.manifest,cases:{...f.cases,url:'https://elsewhere.test/data.json'}});
  await assert.rejects(f.provider().loadCases(),/허용되지/);
  f.add('data-manifest.json',{...f.manifest,cases:{...f.cases,url:'../private.json'}});
  await assert.rejects(f.provider().loadCases(),/허용되지/);
});
test('failed offline pack never advertises completion',async()=>{
  const f=fixture(),p=f.provider();await p.loadCases();f.files.delete(BASE+f.full.url);
  await assert.rejects(p.downloadOffline());
  assert.equal(await f.cache.match(BASE+'__lawbook_offline_manifest__'),undefined);
});
test('removed release assets require one coherent refresh without mixing newer text',async()=>{
  const f=fixture(),p=f.provider(),old=(await p.loadCases()).cases[0];
  const nextFull=f.add('data/full.two.json',[{heading:'[이유]',text:'새 버전 원문'}]);
  const nextLaws=f.add('data/laws.two.json',{groups:[],laws:[{id:'v2'}]});
  const nextCases=f.add('data/cases.two.json',{...f.data,cases:[{id:old.id,page:'enbanc',title:'새 버전 제목',fullTextRef:nextFull}]});
  f.add('data-manifest.json',{...f.manifest,version:'v2',cases:nextCases,laws:nextLaws});
  f.files.delete(BASE+f.full.url);f.files.delete(BASE+f.laws.url);
  await assert.rejects(p.loadFullText(old),e=>e.code==='DATA_VERSION_CHANGED'&&e.version==='v2');
  assert.equal(old.fullText,undefined);assert.equal(p.status().version,'v1');
  await assert.rejects(p.loadFullText(old),e=>e.code==='DATA_VERSION_CHANGED');
  await assert.rejects(p.loadLaws(),e=>e.code==='DATA_VERSION_CHANGED');
  assert.equal(f.calls.filter(u=>u===BASE+'data-manifest.json').length,2);
  assert.equal(f.calls.filter(u=>u===BASE+f.full.url).length,1);
  assert.equal(f.calls.includes(BASE+nextFull.url),false);
  const refreshed=f.provider(),fresh=(await refreshed.loadCases()).cases[0];
  assert.equal(fresh.title,'새 버전 제목');await refreshed.loadFullText(fresh);
  assert.equal(fresh.fullText[0].text,'새 버전 원문');assert.equal(refreshed.status().version,'v2');
});
test('missing asset without a changed manifest remains retryable and does not claim a new version',async()=>{
  const f=fixture(),p=f.provider(),c=(await p.loadCases()).cases[0],saved=f.files.get(BASE+f.full.url);
  f.files.delete(BASE+f.full.url);
  await assert.rejects(p.loadFullText(c),e=>e.status===404&&!e.code);
  f.files.set(BASE+f.full.url,saved);await p.loadFullText(c);
  assert.equal(c.fullText[0].text,'공식 원문\n가. 원문 보존');
});

test('release monitor coalesces focus probes and throttles completed checks', async()=>{
  let now=100, calls=0, finish;
  const monitor=createUpdateMonitor({checkForUpdate(){calls++; return new Promise(resolve=>{finish=resolve;});}}, {now:()=>now,intervalMs:50});
  const first=monitor.check(), second=monitor.check();
  assert.equal(first,second);
  await Promise.resolve();assert.equal(calls,1);
  finish({available:false});await first;
  now=149;assert.equal(await monitor.check(),null);assert.equal(calls,1);
  now=150;const next=monitor.check();await Promise.resolve();assert.equal(calls,2);
  finish({available:true});assert.equal((await next).available,true);
});
test('release monitor avoids a redundant boot probe but probes on network recovery', async()=>{
  let calls=0;
  const monitor=createUpdateMonitor({async checkForUpdate(){calls++;return {available:false};}}, {now:()=>100,initialCheckedAt:100});
  assert.equal(await monitor.check(),null);assert.equal(calls,0);
  await monitor.check({force:true});assert.equal(calls,1);
});
test('automatic release notice leaves active data intact and a refreshed provider loads new full text',async()=>{
  const f=fixture(),p=f.provider(),old=(await p.loadCases()).cases[0];
  const nextFull=f.add('data/full.notice.json',[{heading:'[이유]',text:'갱신된 전문'}]);
  const nextCases=f.add('data/cases.notice.json',{...f.data,cases:[{...old,title:'새 제목',fullTextRef:nextFull}]});
  f.add('data-manifest.json',{...f.manifest,version:'v2',cases:nextCases});
  const results=[],monitor=createUpdateMonitor(p,{onResult:value=>results.push(value)});
  await monitor.check();assert.equal(results[0].available,true);
  assert.equal(p.status().version,'v1');assert.equal((await p.loadCases()).cases[0],old);
  await p.loadFullText(old);assert.equal(old.fullText[0].text,'공식 원문\n가. 원문 보존');
  const fresh=f.provider(),updated=(await fresh.loadCases()).cases[0];await fresh.loadFullText(updated);
  assert.equal(fresh.status().version,'v2');assert.equal(updated.fullText[0].text,'갱신된 전문');
});
test('failed automatic release probe retains the verified active release',async()=>{
  const f=fixture(),p=f.provider(),data=await p.loadCases(),errors=[];
  f.setOnline(false);
  const monitor=createUpdateMonitor(p,{onError:error=>errors.push(error)});
  assert.equal(await monitor.check(),null);assert.equal(errors.length,1);
  assert.equal(await p.loadCases(),data);assert.equal(p.status().version,'v1');
});
