/* Personal records use stable decision IDs; unknown records and conflicting notes are preserved. */
(function (root) {
  'use strict';
  const safeKey = k => typeof k === 'string' && k.length > 0 && k.length < 500 && !['__proto__', 'constructor', 'prototype'].includes(k);
  function aliases(cases) {
    const map = new Map();
    for (const c of cases) {
      const key = c.decisionId || c.id;
      map.set(c.id, key); map.set(key, key);
      for (const old of (c.legacyIds || c.aliases || [])) if (typeof old === 'string') map.set(old, key);
    }
    return map;
  }
  function normalize(input, cases) {
    const map = aliases(cases), out = {bookmarks: [], notes: Object.create(null), conflicts: []};
    for (const id of Array.isArray(input.bookmarks) ? input.bookmarks : []) if (safeKey(id)) out.bookmarks.push(map.get(id) || id);
    out.bookmarks = [...new Set(out.bookmarks)];
    for (const [id, text] of Object.entries(input.notes || {})) {
      if (!safeKey(id) || typeof text !== 'string' || !text) continue;
      const key = map.get(id) || id;
      if (!Object.prototype.hasOwnProperty.call(out.notes, key)) out.notes[key] = text;
      else if (out.notes[key] !== text) {
        out.notes[key] += '\n\n──────── 가져온 메모 (' + id + ') ────────\n' + text;
        out.conflicts.push({id, decisionId: key});
      }
    }
    return out;
  }
  function merge(existing, incoming, cases) {
    if (!incoming || incoming.format !== 'lawbook-personal' || incoming.version !== 1 || !Array.isArray(incoming.bookmarks) || !incoming.notes || typeof incoming.notes !== 'object' || Array.isArray(incoming.notes)) throw new Error('판례집 메모 백업 파일이 아닙니다.');
    if (incoming.bookmarks.some(id => !safeKey(id)) || Object.entries(incoming.notes).some(([k, v]) => !safeKey(k) || typeof v !== 'string')) throw new Error('백업 파일에 올바르지 않은 메모가 있습니다.');
    const a = normalize(existing, cases), b = normalize(incoming, cases);
    const out = {bookmarks: [...new Set([...a.bookmarks, ...b.bookmarks])], notes: {...a.notes}, conflicts: [...a.conflicts, ...b.conflicts]};
    for (const [id, text] of Object.entries(b.notes)) {
      if (!out.notes[id]) out.notes[id] = text;
      else if (out.notes[id] !== text && !out.notes[id].endsWith('\n' + text)) {
        out.notes[id] += '\n\n──────── 가져온 메모 ────────\n' + text;
        out.conflicts.push({id});
      }
    }
    return out;
  }
  function backup(state, now) {
    return {format: 'lawbook-personal', version: 1, exportedAt: (now || new Date()).toISOString(), bookmarks: [...state.bookmarks], notes: {...state.notes}, settings: {...state.settings}};
  }
  const api = {aliases, normalize, merge, backup};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.CasebookPersonal = api;
})(typeof window !== 'undefined' ? window : null);
