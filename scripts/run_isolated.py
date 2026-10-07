#!/usr/bin/env python3
"""Run existing entrypoints from independent source/config with explicit output."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MODULES = {'coverage': ('autodrc.runset_coverage', '--out-dir'),
           'pipeline': ('autodrc.pipeline', '--out-root'),
           'cli': ('autodrc.cli', '--out-dir'),
           'closed-loop': ('autodrc.closed_loop', '--out-dir')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', choices=MODULES, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--model-path', type=Path, help='Existing local model for llm generation')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    run = args.run_dir.resolve()
    if not run.is_relative_to(project / 'artifacts/runs') or run == project / 'artifacts/runs':
        parser.error('Use a new directory below artifacts/runs')
    if run.exists():
        parser.error('Run directory already exists; use a new name')
    rest = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    rest = list(rest)
    module, output_flag = MODULES[args.entry]
    if any(a.split('=', 1)[0] in {'--out-dir', '--out-root', '--llm-model'} for a in rest):
        parser.error('Output is managed here; use --model-path for a local model')
    for i, token in enumerate(rest):
        if token == '--runset':
            if i + 1 == len(rest):
                parser.error('--runset needs a path')
            rest[i + 1] = str(Path(rest[i + 1]).resolve())
        elif token.startswith('--runset='):
            rest[i] = '--runset=' + str(Path(token.split('=', 1)[1]).resolve())
    generator = 'template'
    for i, token in enumerate(rest):
        if token == '--generator':
            if i + 1 == len(rest):
                parser.error('--generator needs a value')
            generator = rest[i + 1]
        elif token.startswith('--generator='):
            generator = token.split('=', 1)[1]
    model = args.model_path or Path(os.environ.get('AUTO_DRC_LLM_MODEL', str(project / 'models/TinyLlama-1.1B-Chat-v1.0')))
    model = model.resolve()
    if generator == 'llm' and not model.is_dir():
        parser.error('Model must be an existing local directory')
    if args.model_path and generator != 'llm':
        parser.error('--model-path requires --generator llm')
    run.mkdir(parents=True)
    source = run / 'source'
    source.mkdir()
    for name in ('autodrc', 'config', 'scripts'):
        shutil.copytree(project / name, source / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in source.rglob('*') if p.is_file()}
    env = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
        env.pop(name, None)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    env.setdefault('AUTO_DRC_KLAYOUT_BIN', 'klayout')
    argv = [sys.executable, '-B', '-s', '-m', module, output_flag, str(run / 'output'), *rest]
    if generator == 'llm':
        argv.extend(['--llm-model', str(model)])
    metadata = dict(argv=argv, cwd=str(source), python=sys.executable, python_prefix=sys.prefix,
                    source_sha256=hashes, explicit_output=str(run / 'output'), model_training=False,
                    environment={name: env.get(name, '') for name in (
                        'PYTHONHASHSEED', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE',
                        'AUTO_DRC_KLAYOUT_BIN', 'AUTO_DRC_KLAYOUT_LD_LIBRARY_PATH', 'KLAYOUT_PATH')})
    (run / 'parameters.json').write_text(json.dumps(metadata, indent=2) + '\n')
    with (run / 'stdout.log').open('x') as out, (run / 'stderr.log').open('x') as err:
        result = subprocess.run(argv, cwd=source, env=env, stdout=out, stderr=err)
    metadata['returncode'] = result.returncode
    metadata['source_after_sha256'] = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in source.rglob('*') if p.is_file()}
    (run / 'result.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(dict(returncode=result.returncode, run_dir=str(run)), indent=2))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
