from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


class ProjectQualityIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            spec = importlib.util.spec_from_file_location("quality_integrity", scripts / "project_quality.py")
            cls.quality = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.quality)
        finally:
            sys.path.remove(str(scripts))

    def test_manifest_rejects_modified_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "evidence.json"
            path.write_text("original")
            entries = {path.name: dict(size=path.stat().st_size, sha256=self.quality.digest(path))}
            self.assertEqual(self.quality.verify_files(root, entries), 1)
            path.write_text("changed!")
            with self.assertRaisesRegex(RuntimeError, "Manifest mismatch"):
                self.quality.verify_files(root, entries)

    def test_manifest_rejects_missing_file_and_parent_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("missing", "../outside"):
                with self.assertRaisesRegex(RuntimeError, "Invalid manifest path"):
                    self.quality.verify_files(Path(directory), {name: dict(size=0, sha256="")})
