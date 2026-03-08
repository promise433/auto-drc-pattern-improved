#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _parse_csv(values: str) -> list[str]:
    return [value.strip() for value in values.split(",") if value.strip()]


def _run_command(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _load_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def run_sweep(
    *,
    repo_root: Path,
    train_jsonl: Path,
    eval_jsonl: Path | None,
    out_root: Path,
    models: list[str],
    learning_rates: list[str],
    lora_rs: list[str],
    epochs: list[str],
    backend: str,
    max_train_samples: int,
    max_eval_samples: int,
) -> dict[str, Any]:
    out_root.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []

    for model, lr, lora_r, epoch in itertools.product(models, learning_rates, lora_rs, epochs):
        exp_name = (
            f"model_{model.split('/')[-1]}"
            f"__lr_{lr}"
            f"__r_{lora_r}"
            f"__ep_{epoch}"
        )
        exp_dir = out_root / exp_name
        cmd = [
            sys.executable,
            "scripts/train_sft.py",
            "--model",
            model,
            "--train-jsonl",
            str(train_jsonl),
            "--output-dir",
            str(exp_dir),
            "--learning-rate",
            lr,
            "--lora-r",
            lora_r,
            "--epochs",
            epoch,
            "--backend",
            backend,
            "--max-train-samples",
            str(max_train_samples),
            "--max-eval-samples",
            str(max_eval_samples),
        ]
        if eval_jsonl is not None:
            cmd.extend(["--eval-jsonl", str(eval_jsonl)])

        returncode, stdout, stderr = _run_command(cmd, repo_root)
        (exp_dir / "stdout.log").write_text(stdout, encoding="utf-8")
        (exp_dir / "stderr.log").write_text(stderr, encoding="utf-8")

        metrics = _load_metrics(exp_dir / "metrics.json")
        manifest = _load_metrics(exp_dir / "run_manifest.json")
        row = {
            "exp_name": exp_name,
            "returncode": returncode,
            "model": model,
            "learning_rate": float(lr),
            "lora_r": int(lora_r),
            "epochs": int(epoch),
            "backend": backend,
            "manifest_status": manifest.get("status"),
            "train_loss": metrics.get("train", {}).get("train_loss"),
            "eval_loss": metrics.get("eval", {}).get("eval_loss"),
            "output_dir": str(exp_dir),
        }
        runs.append(row)

    successful = [run for run in runs if run["returncode"] == 0]
    failed = [run for run in runs if run["returncode"] != 0]

    def _score(run: dict[str, Any]) -> float:
        eval_loss = run.get("eval_loss")
        if eval_loss is None:
            train_loss = run.get("train_loss")
            return float(train_loss) if train_loss is not None else 1e9
        return float(eval_loss)

    best = min(successful, key=_score) if successful else None

    summary = {
        "total_runs": len(runs),
        "successful_runs": len(successful),
        "failed_runs": len(failed),
        "best_run": best,
        "runs": runs,
    }
    (out_root / "sweep_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run batch model/param sweep and auto-report.")
    parser.add_argument("--train-jsonl", required=True)
    parser.add_argument("--eval-jsonl")
    parser.add_argument("--out-root", default="runs/sweeps")
    parser.add_argument("--models", default="TinyLlama/TinyLlama-1.1B-Chat-v1.0")
    parser.add_argument("--learning-rates", default="2e-4,1e-4")
    parser.add_argument("--lora-rs", default="8,16")
    parser.add_argument("--epochs", default="1,2")
    parser.add_argument("--backend", choices=["mock", "hf"], default="mock")
    parser.add_argument("--max-train-samples", type=int, default=64)
    parser.add_argument("--max-eval-samples", type=int, default=64)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    summary = run_sweep(
        repo_root=repo_root,
        train_jsonl=Path(args.train_jsonl),
        eval_jsonl=Path(args.eval_jsonl) if args.eval_jsonl else None,
        out_root=Path(args.out_root),
        models=_parse_csv(args.models),
        learning_rates=_parse_csv(args.learning_rates),
        lora_rs=_parse_csv(args.lora_rs),
        epochs=_parse_csv(args.epochs),
        backend=args.backend,
        max_train_samples=args.max_train_samples,
        max_eval_samples=args.max_eval_samples,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
