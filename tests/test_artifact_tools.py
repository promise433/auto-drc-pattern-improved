from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('artifact_quality', PROJECT / 'scripts/project_quality.py')
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class ArtifactToolsTests(unittest.TestCase):
    def evidence(self, root, info):
        value = quality.Evidence.__new__(quality.Evidence)
        value.entries = {'/removed/response.txt': info}
        value.metadata = {}
        value.verified = set()
        return value

    def test_relocated_response_preserves_hash_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'response.txt').write_bytes(b'failed original response')
            info = dict(storage='file', path='response.txt', kind='file', size=24,
                        sha256=hashlib.sha256(b'failed original response').hexdigest())
            value = self.evidence(root, info)
            with patch.object(quality, 'DEV', root):
                self.assertEqual(value.read_bytes('/removed/response.txt'), b'failed original response')
                (root / 'response.txt').write_bytes(b'edited')
                with self.assertRaisesRegex(RuntimeError, 'Evidence content changed'):
                    value.read_bytes('/removed/response.txt')

    def test_archived_response_is_read_without_old_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b'original failure'
            with tarfile.open(root / 'history.tar.gz', 'w:gz') as archive:
                member = tarfile.TarInfo('run/response.txt')
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            info = dict(storage='archive', archive='history.tar.gz', member='run/response.txt',
                        kind='file', size=len(data), sha256=hashlib.sha256(data).hexdigest())
            with patch.object(quality, 'DEV', root):
                self.assertEqual(self.evidence(root, info).read_bytes('/removed/response.txt'), data)

    def test_external_interpreter_symlink_keeps_link_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'python').symlink_to(sys.executable)
            with patch.object(quality, 'DEV', root):
                value = self.evidence(root, {})
                self.assertTrue(value.local('python').is_symlink())
                with self.assertRaisesRegex(RuntimeError, 'escapes project'):
                    value.local('../outside')

    def test_isolated_entry_rejects_output_outside_runs_before_creating_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'must_not_exist'
            result = subprocess.run([sys.executable, '-B', '-s', str(PROJECT / 'scripts/run_isolated.py'),
                '--entry', 'cli', '--run-dir', str(target)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('below artifacts/runs', result.stderr)
            self.assertFalse(target.exists())
