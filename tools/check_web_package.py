#!/usr/bin/env python3
"""Check a built public web package without opening browsers or modifying files."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit

PLACEHOLDERS = ("__CASE_DATA_JSON__", "__LAWS_DATA_B64__", "__SHELL_VERSION__")
HASHED_DATA = re.compile(r"data/(cases|laws|fulltext)\.([0-9a-f]{64})\.json\Z")
STATIC_FILES = {"index.html", "sw.js", ".nojekyll", "data-manifest.json", "manifest.webmanifest",
                "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def check_package(directory, registry=None):
    """Return a JSON-serializable summary; raise ValueError/OSError on invalid input.

    registry, when supplied, is the registry.json path whose case IDs must match the
    package exactly. Data files and source files are only read by this function.
    """
    directory = Path(directory).resolve()
    require(directory.is_dir(), f"Web package directory is missing: {directory}")
    files = {}
    for path in directory.rglob("*"):
        require(not path.is_symlink(), f"Symlink is not a public package asset: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        require(relative in STATIC_FILES or HASHED_DATA.fullmatch(relative),
                f"Unexpected public package file (source/private files are forbidden): {relative}")
        files[relative] = path
    require(STATIC_FILES <= files.keys(), "Required web files are missing: " + ", ".join(sorted(STATIC_FILES - files.keys())))

    def read_json(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid UTF-8 JSON: {path.name}: {error}") from error

    manifest = read_json(files["data-manifest.json"])
    require(isinstance(manifest, dict) and manifest.get("schemaVersion") == 1,
            "Unsupported data manifest schema")
    require(isinstance(manifest.get("version"), str) and re.fullmatch(r"[0-9a-f]{20}", manifest["version"]),
            "Invalid data version")
    checked = {}
    parsed = {}

    def check_ref(ref, label):
        require(isinstance(ref, dict) and isinstance(ref.get("url"), str), f"Invalid asset reference: {label}")
        url = urlsplit(ref["url"])
        relative = unquote(url.path)
        parts = PurePosixPath(relative).parts
        require(not url.scheme and not url.netloc and not url.query and not url.fragment
                and not relative.startswith("/") and ".." not in parts and "\\" not in relative,
                f"Unsafe asset URL: {ref['url']}")
        require(relative in files, f"Referenced asset is missing: {relative}")
        match = HASHED_DATA.fullmatch(relative)
        require(match, f"Data reference must use a content-hashed public file: {relative}")
        if relative not in checked:
            raw = files[relative].read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            require(actual == match.group(2), f"Content filename hash mismatch: {relative}")
            checked[relative] = (actual, len(raw))
        actual, length = checked[relative]
        if "sha256" in ref:
            require(ref["sha256"] == actual, f"Reference SHA256 mismatch: {relative}")
        if "bytes" in ref:
            require(type(ref["bytes"]) is int and ref["bytes"] == length,
                    f"Reference byte length mismatch: {relative}")
        if relative not in parsed:
            parsed[relative] = read_json(files[relative])
        return parsed[relative]

    def manifest_refs(value):
        if isinstance(value, dict):
            if "url" in value and ("sha256" in value or "bytes" in value):
                yield value
            for item in value.values():
                yield from manifest_refs(item)
        elif isinstance(value, list):
            for item in value:
                yield from manifest_refs(item)

    for ref in manifest_refs(manifest):
        check_ref(ref, "manifest")
    cases_ref, laws_ref = manifest.get("cases"), manifest.get("laws")
    data = check_ref(cases_ref, "cases")
    laws = check_ref(laws_ref, "laws")
    require(isinstance(data, dict) and isinstance(data.get("cases"), list), "Invalid case list")
    require(isinstance(laws, dict) and isinstance(laws.get("laws"), list) and laws["laws"], "Empty or invalid law list")
    cases = data["cases"]
    require(manifest.get("caseCount") == len(cases), "Manifest/list case count mismatch")
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    require(len(ids) == len(cases) and all(isinstance(key, str) and key for key in ids), "Invalid case ID")
    require(len(set(ids)) == len(ids), "Duplicate case IDs in list")
    if registry is not None:
        registered = read_json(Path(registry))
        registered = registered.get("cases") if isinstance(registered, dict) else registered
        require(isinstance(registered, list), "Invalid registry case list")
        registered_ids = [case.get("id") for case in registered if isinstance(case, dict)]
        require(len(registered_ids) == len(registered) and len(set(registered_ids)) == len(registered_ids),
                "Invalid or duplicate registry IDs")
        require(set(ids) == set(registered_ids), "Registry/list IDs differ")
    references = 0
    for case in cases:
        require(not case.get("fullText"), f"List payload embeds full text: {case['id']}")
        if case.get("fullTextRef") is not None:
            full = check_ref(case["fullTextRef"], case["id"])
            require(isinstance(full, list) and full, f"Empty or invalid full text asset: {case['id']}")
            references += 1
    # Check stale immutable versions too: build_web deliberately keeps older assets.
    for relative in files:
        match = HASHED_DATA.fullmatch(relative)
        if match and relative not in checked:
            raw = files[relative].read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            require(actual == match.group(2), f"Content filename hash mismatch: {relative}")
            checked[relative] = (actual, len(raw))
    expected_version = hashlib.sha256(encoded({"cases": checked[cases_ref["url"]][0],
                                               "laws": checked[laws_ref["url"]][0]})).hexdigest()[:20]
    require(manifest["version"] == expected_version, "Data manifest version does not match case/law hashes")
    html = files["index.html"].read_text(encoding="utf-8")
    worker = files["sw.js"].read_text(encoding="utf-8")
    for name, source in (("index.html", html), ("sw.js", worker)):
        require(not any(marker in source for marker in PLACEHOLDERS), f"Unresolved build placeholder in {name}")
        # Corpus versions are normally fetched at runtime. Compare them only when
        # a future shell explicitly embeds a DATA_VERSION/CORPUS_VERSION value.
        embedded = re.findall(r"\b(?:DATA_VERSION|CORPUS_VERSION)\s*[:=]\s*['\"]([0-9a-f]{20})['\"]", source)
        require(all(value == manifest["version"] for value in embedded), f"Embedded data version mismatch in {name}")
    shell = re.search(r"\bSHELL\s*=\s*['\"]lawbook-shell-([0-9a-f]{20})['\"]", worker)
    require(shell is not None, "Missing generated service worker shell version")
    require("manifest.webmanifest" in html and "sw.js" in html, "HTML does not reference the manifest and service worker")
    return {"caseCount": len(cases), "pages": dict(sorted(Counter(case.get("page", "") for case in cases).items())),
            "laws": len(laws["laws"]), "fullTextReferences": references,
            "hashedFilesChecked": len(checked), "dataVersion": manifest["version"],
            "shellVersion": shell.group(1), "registryIdsChecked": registry is not None,
            "privateFiles": 0, "browserCheck": "not run"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("output/web"))
    parser.add_argument("--registry", type=Path, default=Path("data/registry.json"))
    args = parser.parse_args()
    try:
        print(json.dumps(check_package(args.directory, args.registry), ensure_ascii=False, indent=2))
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(f"Package check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
