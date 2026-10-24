/* Versioned public data. Official text is fetched and verified, never rewritten here. */
(function (root) {
  'use strict';
  function createProvider(env) {
    const base = new URL('./', env.baseURL);
    const manifestURL = new URL('data-manifest.json', base).href;
    const cacheName = 'lawbook-data-v1';
    const activeKey = new URL('__lawbook_active_manifest__', base).href;
    const offlineKey = new URL('__lawbook_offline_manifest__', base).href;
    let current = null, cases = null, loading = null, offline = false;
    let staleError = null, staleProbe = null;
    const pending = new Map();
    const jsonResponse = obj => new Response(JSON.stringify(obj), {headers: {'Content-Type': 'application/json; charset=utf-8'}});
    async function cache() { try { return env.caches ? await env.caches.open(cacheName) : null; } catch (_) { return null; } }
    function descriptor(ref) {
      if (!ref || typeof ref.url !== 'string' || !/^[a-f0-9]{64}$/i.test(ref.sha256 || '')) throw new Error('데이터 파일 정보가 올바르지 않습니다.');
      const url = new URL(ref.url, base);
      if (url.origin !== base.origin || !url.pathname.startsWith(base.pathname)) throw new Error('허용되지 않은 데이터 파일 위치입니다.');
      return {url: url.href, sha256: ref.sha256.toLowerCase()};
    }
    function manifest(value) {
      if (!value || value.schemaVersion !== 1 || typeof value.version !== 'string' || !value.version) throw new Error('앱 업데이트가 필요한 데이터 형식입니다.');
      descriptor(value.cases); descriptor(value.laws);
      return value;
    }
    async function request(url, mode) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const r = await env.fetch(url, {cache: mode || 'no-store', signal: controller.signal});
        if (!r.ok) { const error = new Error('자료를 불러오지 못했습니다 (' + r.status + ').'); error.status = r.status; throw error; }
        return r;
      } finally { clearTimeout(timer); }
    }
    async function checked(response, ref) {
      if (!env.crypto || !env.crypto.subtle) throw new Error('안전한 HTTPS 주소에서 실행해 주세요.');
      const bytes = await response.arrayBuffer();
      const digest = await env.crypto.subtle.digest('SHA-256', bytes);
      const hex = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
      if (hex !== ref.sha256) throw new Error('자료의 무결성 검사에 실패했습니다. 다시 시도해 주세요.');
      return JSON.parse(new TextDecoder().decode(bytes));
    }
    async function missingVersion(error) {
      if (staleError) return staleError;
      if (!current || ![404, 410].includes(error.status)) return error;
      if (!staleProbe) {
        staleProbe = (async () => {
          try {
            const next = await (await request(manifestURL, 'no-store')).json();
            if (next && typeof next.version === 'string' && next.version && next.version !== current.version) {
              staleError = new Error('자료가 새 버전으로 갱신되었습니다. 새로고침하여 같은 버전의 자료로 다시 열어 주세요.');
              staleError.code = 'DATA_VERSION_CHANGED';
              staleError.version = next.version;
            }
          } catch (_) { /* Network failure is not evidence that the release changed. */ }
        })().finally(() => { staleProbe = null; });
      }
      await staleProbe;
      return staleError || error;
    }
    async function resource(input) {
      const ref = descriptor(input), key = ref.url + '#' + ref.sha256;
      if (pending.has(key)) return pending.get(key);
      const task = (async () => {
        const store = await cache();
        if (store) {
          const saved = await store.match(ref.url);
          if (saved) {
            try { return await checked(saved, ref); }
            catch (_) { await store.delete(ref.url); }
          }
        }
        // Keep this session pinned. Missing old assets must never be replaced by new-release text.
        if (staleError) throw staleError;
        let response;
        try { response = await request(ref.url); }
        catch (error) { throw await missingVersion(error); }
        const value = await checked(response.clone(), ref);
        if (store) { try { await store.put(ref.url, response); } catch (_) { /* Online use remains available when storage is full. */ } }
        return value;
      })();
      pending.set(key, task);
      try { return await task; } finally { pending.delete(key); }
    }
    function validateCases(data) {
      if (!data || !Array.isArray(data.cases) || !Array.isArray(data.pages) || !Array.isArray(data.subjects)) throw new Error('판례 목록의 형식이 올바르지 않습니다.');
      for (const c of data.cases) {
        if (!c.id || !c.page) throw new Error('판례 식별 정보가 빠져 있습니다.');
        if (c.fullTextRef) descriptor(c.fullTextRef);
      }
      return data;
    }
    async function remember(key, value) {
      const store = await cache();
      if (store) { try { await store.put(key, jsonResponse(value)); return true; } catch (_) {} }
      return false;
    }
    async function savedManifest(key) {
      const store = await cache(), saved = store && await store.match(key);
      return saved ? manifest(await saved.json()) : null;
    }
    async function fetchManifest() { return manifest(await (await request(manifestURL, 'no-store')).json()); }
    async function loadCases() {
      if (cases) return cases;
      if (loading) return loading;
      loading = (async () => {
        let lastError;
        try {
          const next = await fetchManifest();
          const data = validateCases(await resource(next.cases));
          current = next; cases = data; offline = false;
          await remember(activeKey, next);
          return cases;
        } catch (e) { lastError = e; }
        // A fully downloaded release is preferred to a newer partially cached one offline.
        for (const key of [offlineKey, activeKey]) {
          try {
            const previous = await savedManifest(key);
            if (!previous) continue;
            const data = validateCases(await resource(previous.cases));
            current = previous; cases = data; offline = true;
            return cases;
          } catch (_) {}
        }
        throw lastError;
      })();
      try { return await loading; } finally { loading = null; }
    }
    async function loadLaws() {
      await loadCases();
      const value = await resource(current.laws);
      if (!value || !Array.isArray(value.laws) || !Array.isArray(value.groups)) throw new Error('법령 자료의 형식이 올바르지 않습니다.');
      return value;
    }
    async function loadFullText(c) {
      if (c.fullText) return c.fullText;
      if (!c.fullTextRef) return null;
      const value = await resource(c.fullTextRef), full = Array.isArray(value) ? value : value && value.fullText;
      if (!Array.isArray(full) || full.some(b => !b || typeof b.text !== 'string')) throw new Error('전문 자료의 형식이 올바르지 않습니다.');
      c.fullText = full;
      return full;
    }
    async function checkForUpdate() {
      await loadCases();
      const next = await fetchManifest();
      validateCases(await resource(next.cases));
      return {available: next.version !== current.version, currentVersion: current.version, version: next.version};
    }
    async function downloadOffline(onProgress) {
      await loadCases();
      const store = await cache();
      if (!store) throw new Error('이 브라우저에서는 오프라인 저장을 사용할 수 없습니다.');
      const refs = [current.cases, current.laws, ...cases.cases.filter(c => c.fullTextRef).map(c => c.fullTextRef)];
      const unique = [...new Map(refs.map(r => [descriptor(r).url, r])).values()];
      let done = 0;
      for (const ref of unique) {
        await resource(ref);
        const saved = await store.match(descriptor(ref).url);
        if (!saved) throw new Error('저장 공간이 부족해 일부 자료를 저장하지 못했습니다.');
        await checked(saved, descriptor(ref));
        if (onProgress) onProgress(++done, unique.length);
      }
      if (!await remember(offlineKey, current)) throw new Error('오프라인 버전을 저장하지 못했습니다.');
      return {version: current.version, files: unique.length};
    }
    return {loadCases, loadLaws, loadFullText, checkForUpdate, downloadOffline,
      status: () => ({version: current && current.version, generatedAt: current && current.generatedAt, offline})};
  }
  // Probe for new releases without changing the active, version-pinned session.
  function createUpdateMonitor(provider, options) {
    options = options || {};
    const now = options.now || Date.now;
    const interval = options.intervalMs == null ? 60000 : options.intervalMs;
    let checkedAt = options.initialCheckedAt == null ? null : options.initialCheckedAt;
    let pending = null;
    function check(input) {
      if (pending) return pending;
      const force = !!(input && input.force), time = now();
      if (!force && checkedAt !== null && time - checkedAt < interval) return Promise.resolve(null);
      checkedAt = time;
      pending = Promise.resolve().then(() => provider.checkForUpdate()).then(result => {
        if (options.onResult) options.onResult(result);
        return result;
      }).catch(error => {
        if (options.onError) options.onError(error);
        return null;
      }).finally(() => { pending = null; });
      return pending;
    }
    return {check};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {createProvider, createUpdateMonitor};
  if (root && root.document) {
    root.CasebookData = createProvider({baseURL: root.document.baseURI, fetch: root.fetch.bind(root), caches: root.caches, crypto: root.crypto});
    root.CasebookUpdateMonitor = createUpdateMonitor;
  }
})(typeof window !== 'undefined' ? window : null);
