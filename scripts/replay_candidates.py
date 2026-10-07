#!/usr/bin/env python3
"""Replay recorded candidates through five arms, without model or DRC calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from project_quality import Evidence


def materialize(evidence, requests):
    archives = {}
    for original, destination in requests.items():
        info = evidence.entries.get(original)
        if info and info['storage'] == 'archive':
            archives.setdefault(info['archive'], {})[info['member']] = (original, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(evidence.read_bytes(original))
    for name, selected in archives.items():
        seen = set()
        with tarfile.open(evidence.local(name), 'r:gz') as archive:
            for member in archive:
                if member.name not in selected:
                    continue
                original, destination = selected[member.name]
                if not member.isfile():
                    raise RuntimeError('Recorded response is not a file: ' + original)
                data = archive.extractfile(member).read()
                info = evidence.entries[original]
                if len(data) != info['size'] or hashlib.sha256(data).hexdigest() != info['sha256']:
                    raise RuntimeError('Recorded response changed: ' + original)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                seen.add(member.name)
        if seen != selected.keys():
            raise RuntimeError('Missing recorded responses in ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-manifest', required=True)
    parser.add_argument('--model-trace', required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--legacy-parser', action='store_true')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    run = args.run_dir.resolve()
    if not run.is_relative_to(project / 'artifacts/runs') or run == project / 'artifacts/runs' or run.exists():
        parser.error('Use a new directory below artifacts/runs')
    evidence = Evidence()
    tasks_bytes = evidence.read_bytes(args.task_manifest)
    trace_bytes = evidence.read_bytes(args.model_trace)
    trace = json.loads(trace_bytes)
    if not isinstance(trace, list) or not trace:
        parser.error('Trace must be a nonempty list')
    run.mkdir(parents=True)
    inputs = run / 'input'
    inputs.mkdir()
    (inputs / 'task_manifest.json').write_bytes(tasks_bytes)
    (inputs / 'original_trace.json').write_bytes(trace_bytes)
    requests = {}
    relocated = []
    for i, record in enumerate(trace):
        target = inputs / 'calls' / str(i)
        raw = 'llm_raw_' + record['intent'].lower() + '.txt'
        original = str(Path(record['call_dir']) / raw)
        requests[original] = target / raw
        relocated.append(dict(record, call_dir=str(target)))
    materialize(evidence, requests)
    derived_trace = inputs / 'relocated_trace.json'
    derived_trace.write_text(json.dumps(relocated, ensure_ascii=False, indent=2) + '\n')
    source = run / 'source'
    source.mkdir()
    for name in ('autodrc', 'config', 'scripts'):
        shutil.copytree(project / name, source / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    source_hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in source.rglob('*') if p.is_file()}
    metadata = dict(task_original=args.task_manifest, trace_original=args.model_trace,
        task_sha256=hashlib.sha256(tasks_bytes).hexdigest(), trace_sha256=hashlib.sha256(trace_bytes).hexdigest(),
        relocated_trace_sha256=hashlib.sha256(derived_trace.read_bytes()).hexdigest(),
        source_sha256=source_hashes, python=sys.executable, python_hash_seed='0', new_model_calls=0, new_drc_calls=0,
        legacy_parser=args.legacy_parser, transformation='call_dir only; original trace retained')
    (run / 'derivation.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    argv = [sys.executable, '-B', '-s', '-m', 'autodrc.research_compare',
        '--task-manifest', str(inputs / 'task_manifest.json'), '--model-trace', str(derived_trace),
        '--out-dir', str(run / 'output')]
    if args.legacy_parser:
        argv.append('--legacy-parser')
    with (run / 'stdout.log').open('x') as out, (run / 'stderr.log').open('x') as err:
        env = dict(os.environ, PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1',
                   HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        result = subprocess.run(argv, cwd=source, env=env, stdout=out, stderr=err)
    (run / 'result.json').write_text(json.dumps(dict(returncode=result.returncode, argv=argv), indent=2) + '\n')
    print(json.dumps(dict(returncode=result.returncode, run_dir=str(run)), indent=2))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
