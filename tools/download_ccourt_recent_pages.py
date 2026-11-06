#!/usr/bin/env python3
"""Download the Constitutional Court's saved-search list pages and exports."""

import argparse
import datetime as dt
import hashlib
import html.parser
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO


BASE = "https://www.ccourt.go.kr"
LIST_URL = BASE + "/site/kor/ex/bbs/List.do"
EXCEL_URL = BASE + "/site/kor/event/newRecentListExcel.do"
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "inbox" / "ccourt-recent-2009-2026"
FORM = {
    "cbIdx": "1195",
    "bcIdx": "4268005",
    "mode": "",
    "ext1": "",
    "searchDateType": "ADJUDGE_DATE",
    "tgtTypeCd": "EVENT_NAME",
    "searchDateFrom": "2009-01-01",
    "searchDateTo": "2026-10-22",
    "searchKey": "",
}


class ListParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = []
        self.cases = []
        self._active_text = None
        self._case_text = None
        self._event = None
        self._total_depth = 0
        self._total_text = []
        self.total = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set(a.get("class", "").split())
        if tag == "input" and a.get("name"):
            self.fields[a["name"]] = a.get("value", "")
        if self._total_depth:
            self._total_depth += 1
        elif tag == "div" and "bbsTotal" in classes:
            self._total_depth = 1
        if tag == "a" and {"num", "active"} <= classes:
            self._active_text = []
        if tag == "a":
            m = re.search(r"viewPop\s*\(\s*['\"]1195['\"]\s*,\s*['\"](\d+)['\"]", a.get("onclick", ""))
            if m:
                self._event = m.group(1)
        if tag == "b" and "caseNum" in classes and self._event:
            self._case_text = []

    def handle_data(self, data):
        if self._active_text is not None:
            self._active_text.append(data)
        if self._case_text is not None:
            self._case_text.append(data)
        if self._total_depth:
            self._total_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._active_text is not None:
            value = "".join(self._active_text).strip()
            if value.isdigit():
                self.active.append(int(value))
            self._active_text = None
        if tag == "b" and self._case_text is not None:
            self.cases.append((self._event, "".join(self._case_text).strip()))
            self._case_text = None
        if tag == "a":
            self._event = None
        if self._total_depth:
            self._total_depth -= 1
            if not self._total_depth:
                m = re.search(r"총\s*([\d,]+)\s*건", " ".join(self._total_text))
                if m:
                    self.total = int(m.group(1).replace(",", ""))


def parse_list(raw, charset, expected_page):
    text = raw.decode(charset, errors="strict")
    p = ListParser()
    p.feed(text)
    if p.active != [expected_page]:
        raise ValueError(f"active page mismatch: expected {expected_page}, got {p.active}")
    if p.fields.get("cbIdx") != "1195" or p.fields.get("pageIndex") != str(expected_page):
        raise ValueError("board or page form field mismatch")
    for name in ("searchDateFrom", "searchDateTo"):
        actual = re.sub(r"\D", "", p.fields.get(name, ""))
        expected = FORM[name].replace("-", "")
        # The visible form may omit zero padding in month/day.
        if actual != expected:
            parts = re.findall(r"\d+", p.fields.get(name, ""))
            if len(parts) != 3 or f"{int(parts[0]):04d}{int(parts[1]):02d}{int(parts[2]):02d}" != expected:
                raise ValueError(f"unexpected {name}: {p.fields.get(name)!r}")
    # A few list rows publish an empty case number; the row is kept (event id intact) and the planner
    # resolves it from an explicit, verified override instead of dropping the whole page.
    if p.total is None or not p.cases or any(not event for event, _ in p.cases):
        raise ValueError("list total or case links missing")
    if len({x[0] for x in p.cases}) != len(p.cases):
        raise ValueError("duplicate case identifiers on page")
    return p


def excel_type(raw):
    if raw.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return ".xls"
    if raw.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                if "[Content_Types].xml" in archive.namelist() and "xl/workbook.xml" in archive.namelist():
                    return ".xlsx"
        except zipfile.BadZipFile:
            pass
    raise ValueError("download is not an XLS or XLSX file; server may have returned an error page")


def request(opener, url, data, delay, retries):
    payload = urllib.parse.urlencode(data).encode("utf-8")
    error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=payload, headers={
                "User-Agent": "Mozilla/5.0 (compatible; casebook-research/1.0)",
                "Referer": LIST_URL + "?cbIdx=1195",
            })
            with opener.open(req, timeout=45) as response:
                raw = response.read()
                if not raw:
                    raise ValueError("empty response")
                return raw, response.headers.get_content_charset() or "utf-8"
        except (OSError, ValueError, urllib.error.URLError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(min(15, delay * (2 ** attempt) + 1))
    raise RuntimeError(str(error))


def write_new(path, data):
    # Exclusive creation prevents replacing user files or previous downloads.
    with path.open("xb") as stream:
        stream.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=252)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default: 1)")
    ap.add_argument("--retries", type=int, default=2)
    args = ap.parse_args()
    if not (1 <= args.start <= args.end <= 252) or args.delay < 0 or args.retries < 0:
        ap.error("require 1 <= start <= end <= 252, nonnegative delay and retries")
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log = args.output / f"run-{stamp}.jsonl"
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    seen_lists = {}
    seen_exports = {}
    expected_total = None
    failed = 0
    consecutive_list_failures = 0
    attempted = 0

    def record(kind, page, message):
        item = {"time": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind,
                "page": page, "message": message}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"[{page:03d}] {kind}: {message}", flush=True)

    for page in range(args.start, args.end + 1):
        attempted += 1
        fields = dict(FORM, pageIndex=str(page))
        list_path = args.output / f"page-{page:03d}.html"
        try:
            if list_path.exists():
                raw, charset = list_path.read_bytes(), "utf-8"
            else:
                raw, charset = request(opener, LIST_URL, fields, args.delay, args.retries)
                time.sleep(args.delay)
            parsed = parse_list(raw, charset, page)
            if expected_total is None:
                expected_total = parsed.total
            if parsed.total != expected_total:
                raise ValueError(f"result total changed: {expected_total} -> {parsed.total}")
            signature = tuple(event for event, _ in parsed.cases)
            if signature in seen_lists:
                raise ValueError(f"case links identical to page {seen_lists[signature]}")
            seen_lists[signature] = page
            if not list_path.exists():
                write_new(list_path, raw)
            record("list", page, f"{len(parsed.cases)} cases; first={parsed.cases[0][1]}; total={parsed.total}")
            consecutive_list_failures = 0
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            failed += 1
            consecutive_list_failures += 1
            record("list-failed", page, str(exc))
            if consecutive_list_failures >= 3:
                record("aborted", page, "three consecutive list requests or validations failed; fix the cause and rerun")
                break
            continue

        try:
            existing = [p for p in (args.output / f"page-{page:03d}.xls", args.output / f"page-{page:03d}.xlsx") if p.exists()]
            if len(existing) > 1:
                raise ValueError("both xls and xlsx exist for this page")
            if existing:
                raw = existing[0].read_bytes()
                suffix = excel_type(raw)
                if existing[0].suffix.lower() != suffix:
                    raise ValueError("existing file extension does not match content")
            else:
                raw, _ = request(opener, EXCEL_URL, fields, args.delay, args.retries)
                time.sleep(args.delay)
                suffix = excel_type(raw)
                write_new(args.output / f"page-{page:03d}{suffix}", raw)
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen_exports:
                record("warning", page, f"export is byte-identical to page {seen_exports[digest]}; server may export all matching records")
            else:
                seen_exports[digest] = page
            record("excel", page, f"{len(raw)} bytes, sha256={digest}")
        except (OSError, RuntimeError, ValueError) as exc:
            failed += 1
            record("excel-failed", page, str(exc))

    print(f"Finished: {attempted} of {args.end - args.start + 1} pages attempted, {failed} failures; log: {log}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
