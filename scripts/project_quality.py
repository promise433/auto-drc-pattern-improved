#!/usr/bin/env python3
"""Verify relocated research evidence without the former recovery directory."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import stat
from pathlib import Path
import tarfile

DEV = Path(__file__).resolve().parents[1]
if DEV.name == 'provenance':
    DEV = Path(__file__).resolve().parents[3]
RECORD = DEV / 'artifacts/provenance/cleanup_20261006'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def verify_files(root, entries):
    root = Path(root).resolve()
    for name, value in entries.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError('Invalid manifest path: ' + name)
        if path.stat().st_size != value['size'] or digest(path) != value['sha256']:
            raise RuntimeError('Manifest mismatch: ' + str(path))
    return len(entries)


class Evidence:
    def __init__(self):
        self.entries = read(RECORD / 'PATH_INDEX.json')['entries']
        self.metadata = {}
        self.verified = set()

    def local(self, relative):
        path = DEV / relative
        if not path.parent.resolve().is_relative_to(DEV) or '..' in Path(relative).parts:
            raise RuntimeError('Evidence path escapes project: ' + relative)
        return path

    def read_bytes(self, original):
        original = str(original)
        value = self.entries.get(original)
        if value is None:
            path = Path(original)
            if not path.is_absolute():
                path = DEV / path
            if not path.resolve().is_relative_to(DEV):
                raise RuntimeError('Unmapped historical path: ' + original)
            return path.read_bytes()
        if value['kind'] != 'file':
            raise RuntimeError('Not a regular evidence file: ' + original)
        if original in self.metadata:
            data = self.metadata[original]
        elif value['storage'] != 'archive':
            data = self.local(value['path']).read_bytes()
        else:
            with tarfile.open(self.local(value['archive']), 'r:gz') as archive:
                member = archive.getmember(value['member'])
                if not member.isfile():
                    raise RuntimeError('Invalid archive evidence member: ' + member.name)
                data = archive.extractfile(member).read()
        if len(data) != value['size'] or hashlib.sha256(data).hexdigest() != value['sha256']:
            raise RuntimeError('Evidence content changed: ' + original)
        return data

    def json(self, original):
        return json.loads(self.read_bytes(original))

    def verify_migration(self):
        grouped = {}
        for original, value in self.entries.items():
            if value['storage'] == 'archive':
                grouped.setdefault(value['archive'], {})[value['member']] = (original, value)
                continue
            path = self.local(value['path'])
            if value['kind'] == 'file':
                if path.stat().st_size != value['size'] or digest(path) != value['sha256']:
                    raise RuntimeError('Migration mismatch: ' + original)
                self.verified.add(original)
            elif value['kind'] == 'directory':
                if not path.is_dir():
                    raise RuntimeError('Missing directory: ' + original)
            elif not path.is_symlink() or str(path.readlink()) != value['target']:
                link = DEV / value['path']
                if not link.is_symlink() or str(link.readlink()) != value['target']:
                    raise RuntimeError('Changed symbolic link: ' + original)
        for name, expected in grouped.items():
            seen = set()
            with tarfile.open(self.local(name), 'r:gz') as archive:
                for member in archive:
                    if member.name not in expected or member.name in seen:
                        raise RuntimeError('Unexpected archive member: ' + member.name)
                    seen.add(member.name)
                    original, value = expected[member.name]
                    if value['kind'] == 'file':
                        if not member.isfile() or member.size != value['size']:
                            raise RuntimeError('Invalid evidence member: ' + member.name)
                        h = hashlib.sha256()
                        collect = Path(member.name).name in {'SEAL_RESULT.json', 'source_manifest.json', 'evidence_manifest.json'}
                        data = []
                        with archive.extractfile(member) as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                                h.update(chunk)
                                if collect:
                                    data.append(chunk)
                        if h.hexdigest() != value['sha256']:
                            raise RuntimeError('Archived evidence changed: ' + member.name)
                        self.verified.add(original)
                        if collect:
                            self.metadata[original] = b''.join(data)
                    elif value['kind'] == 'symlink':
                        if not member.issym() or member.linkname != value['target']:
                            raise RuntimeError('Changed archived link: ' + member.name)
                    elif not member.isdir():
                        raise RuntimeError('Changed archived directory: ' + member.name)
            if seen != expected.keys():
                raise RuntimeError('Missing archive members: ' + name)
            print('verified archive', name, len(seen), flush=True)
        for relative, identity in read(RECORD / 'ARCHIVES.json').items():
            if digest(self.local(relative)) != identity['sha256']:
                raise RuntimeError('Archive hash mismatch: ' + relative)
        for relative, identity in read(RECORD / 'PROTECTED.json').items():
            path = self.local(relative)
            if identity['kind'] == 'file':
                if path.stat().st_size != identity['size'] or digest(path) != identity['sha256']:
                    raise RuntimeError('Protected asset changed: ' + relative)
            elif identity['kind'] == 'symlink':
                if not path.is_symlink() or str(path.readlink()) != identity['target']:
                    raise RuntimeError('Protected link changed: ' + relative)
            elif not path.is_dir():
                raise RuntimeError('Protected directory missing: ' + relative)
            if stat.S_IMODE(path.lstat().st_mode) != identity['mode']:
                raise RuntimeError('Protected mode changed: ' + relative)
        return len(self.verified)

    def check_identity(self, original, expected):
        original = str(original)
        info = self.entries.get(original)
        if not info or original not in self.verified:
            raise RuntimeError('Seal dependency not verified: ' + original)
        sha = expected if isinstance(expected, str) else expected['sha256']
        if info.get('sha256') != sha or (isinstance(expected, dict) and info['size'] != expected['size']):
            raise RuntimeError('Historical seal mismatch: ' + original)

    def verify_seals(self):
        result = []
        for original in sorted(self.entries):
            if not original.endswith('/SEAL_RESULT.json'):
                continue
            seal = self.json(original)
            if not seal.get('passed'):
                raise RuntimeError('Unaccepted seal: ' + original)
            folder = Path(original).parent
            source = self.json(folder / 'source_manifest.json')
            evidence = self.json(folder / 'evidence_manifest.json')
            for name in ('source', 'evidence'):
                expected = seal.get(name + '_manifest_sha256')
                if expected:
                    self.check_identity(folder / (name + '_manifest.json'), expected)
            for relative, identity in source.items():
                self.check_identity(folder / 'source' / relative, identity)
            if 'files' in evidence:
                pairs = [(Path(evidence['root']) / relative, identity) for relative, identity in evidence['files'].items()]
            elif all(isinstance(v, str) for v in evidence.values()):
                pairs = [(Path(name), sha) for name, sha in evidence.items()]
            else:
                prefix = folder / 'evidence'
                if str(prefix) not in self.entries:
                    prefix = folder.parent
                pairs = [(prefix / relative, identity) for relative, identity in evidence.items()]
            for path, expected in pairs:
                self.check_identity(path, expected)
            acceptance = seal.get('acceptance_sha256')
            if acceptance and not any(
                    (expected if isinstance(expected, str) else expected['sha256']) == acceptance
                    for _, expected in pairs):
                raise RuntimeError('Acceptance absent from seal evidence: ' + original)
            result.append(dict(original=str(folder), source_files=len(source), evidence_files=len(pairs), passed=True))
        return result


def review():
    evidence = Evidence()
    files = evidence.verify_migration()
    seals = evidence.verify_seals()
    latest = DEV / 'artifacts/validation/cold_full_validation_20261005_01'
    accepted = read(latest / 'FINAL_REVIEW.json')
    if not accepted['passed'] or accepted['unresolved']:
        raise RuntimeError('Latest run was not accepted')
    before = read(RECORD / 'PROJECT_BEFORE.json')
    for name, info in before.items():
        if info['kind'] == 'file' and '__pycache__' not in Path(name).parts and (name.startswith(('autodrc/', 'config/', 'tests/')) or name == 'scripts/lpl_to_gds.rb'):
            if digest(DEV / name) != info['sha256']:
                raise RuntimeError('Tested business changed: ' + name)
    readonly = read(RECORD / 'READONLY_IDENTITY.json')
    if digest(Path(readonly['path'])) != readonly['sha256']:
        raise RuntimeError('Readonly original ZIP changed')
    return dict(passed=True, evidence_files=files, historical_seals=seals,
        business_config_tests_unchanged=True, new_model_calls=0, new_drc_graphs=0,
        legacy_cache_resume_claim=False, scope='relocation integrity and historical seals; not new model or physical evidence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('review', 'read'), default='review')
    parser.add_argument('--path', help='Original absolute evidence path or current project path')
    parser.add_argument('--out', type=Path, help='Explicit new output file for review JSON or original bytes')
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error('Output already exists')
    if args.phase == 'read':
        if not args.path:
            parser.error('--path is required')
        data = Evidence().read_bytes(args.path)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(data)
        else:
            print(data.decode('utf-8'))
        return
    value = review()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
