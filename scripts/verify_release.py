#!/usr/bin/env python3
"""Verify the published file manifest without model or physical calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    for name, entry in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise SystemExit('Unsafe manifest path: ' + name)
        path = root / relative
        if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
            raise SystemExit('Missing or unsafe file: ' + name)
        data = path.read_bytes()
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise SystemExit('File differs from release: ' + name)
    print(json.dumps({'passed': True, 'verified_files': len(manifest['files']),
        'new_model_calls': 0, 'new_drc_calls': 0}))


if __name__ == '__main__':
    main()
