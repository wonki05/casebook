import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from check_web_package import check_package


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class PackageCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in (".nojekyll", "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png", "manifest.webmanifest"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fixture")
        (self.root / "index.html").write_text('<link href="manifest.webmanifest"><script src="sw.js"></script>', encoding="utf-8")
        (self.root / "sw.js").write_text("const SHELL = 'lawbook-shell-0123456789abcdef0123';", encoding="utf-8")
        self.full = self.asset("fulltext", [{"heading": "이유", "text": "검증 원문"}])
        self.cases = self.asset("cases", {"cases": [{"id": "case-1", "page": "std-constitution", "fullText": None, "fullTextRef": self.full}, {"id": "case-2", "page": "std-constitution", "fullText": None}]})
        self.laws = self.asset("laws", {"laws": [{"id": "constitution"}]})
        version = hashlib.sha256(encode({"cases": self.cases["sha256"], "laws": self.laws["sha256"]})).hexdigest()[:20]
        self.manifest = {"schemaVersion": 1, "caseCount": 2, "version": version, "cases": self.cases, "laws": self.laws}
        self.save_manifest()
        self.registry = self.root.parent / (self.root.name + "-registry.json")
        self.registry.write_bytes(encode({"cases": [{"id": "case-1"}, {"id": "case-2"}]}))
        self.addCleanup(self.registry.unlink)

    def asset(self, kind, value):
        raw = encode(value)
        sha = hashlib.sha256(raw).hexdigest()
        relative = f"data/{kind}.{sha}.json"
        path = self.root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(raw)
        return {"url": relative, "sha256": sha, "bytes": len(raw)}

    def save_manifest(self):
        (self.root / "data-manifest.json").write_bytes(encode(self.manifest))

    def test_valid_package_allows_case_without_full_text(self):
        result = check_package(self.root, self.registry)
        self.assertEqual(result["caseCount"], 2)
        self.assertEqual(result["fullTextReferences"], 1)
        self.assertTrue(result["registryIdsChecked"])

    def test_corrupted_asset_is_rejected(self):
        (self.root / self.full["url"]).write_bytes(b"[]")
        with self.assertRaisesRegex(ValueError, "filename hash mismatch"):
            check_package(self.root, self.registry)

    def test_missing_full_text_asset_is_rejected(self):
        (self.root / self.full["url"]).unlink()
        with self.assertRaisesRegex(ValueError, "Referenced asset is missing"):
            check_package(self.root, self.registry)

    def test_wrong_byte_length_is_rejected(self):
        self.manifest["cases"]["bytes"] += 1
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "byte length mismatch"):
            check_package(self.root, self.registry)

    def test_count_mismatch_is_rejected(self):
        self.manifest["caseCount"] = 3
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "case count mismatch"):
            check_package(self.root, self.registry)

    def test_reference_path_traversal_is_rejected(self):
        self.manifest["cases"]["url"] = "../outside.json"
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "Unsafe asset URL"):
            check_package(self.root, self.registry)

    def test_private_file_is_rejected(self):
        (self.root / "personal-notes.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source/private files are forbidden"):
            check_package(self.root, self.registry)

    def test_registry_id_mismatch_is_rejected(self):
        self.registry.write_bytes(encode({"cases": [{"id": "other"}]}))
        with self.assertRaisesRegex(ValueError, "Registry/list IDs differ"):
            check_package(self.root, self.registry)

    def test_unresolved_placeholder_is_rejected(self):
        (self.root / "sw.js").write_text("const SHELL = 'lawbook-shell-__SHELL_VERSION__';", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unresolved build placeholder"):
            check_package(self.root, self.registry)


if __name__ == "__main__":
    unittest.main()
