#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LORA_DEFAULT_TARGETS = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]


def count_jsonl_rows(path: Path) -> int:
    if not path.exists():
        raise FileNotFoundError(path)
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _format_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_prompt(row: dict[str, Any]) -> str:
    instruction = row.get("instruction", "")
    input_payload = _format_payload(row.get("input"))
    output_payload = _format_payload(row.get("output"))
    parts = [
        "### Instruction:\n" + instruction.strip(),
        "### Input:\n" + input_payload,
        "### Response:\n" + output_payload,
    ]
    return "\n\n".join(parts).strip() + "\n"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_mock(args: argparse.Namespace) -> int:
    train_path = Path(args.train_jsonl)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "model": args.model,
        "train_jsonl": str(train_path),
        "train_rows": count_jsonl_rows(train_path),
        "output_dir": str(out_dir),
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "epochs": args.epochs,
        "lora": {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "load_in_4bit": parse_bool(args.load_in_4bit),
            "target_modules": args.lora_target_modules,
        },
        "backend": args.backend,
        "status": "prepared",
        "note": "Mock backend writes manifest only. Use --backend hf to run training.",
    }
    write_json(out_dir / "run_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    return 0


def run_hf(args: argparse.Namespace) -> int:
    import torch
    from datasets import load_dataset
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
        set_seed,
    )

    try:
        from peft import LoraConfig
    except ImportError as exc:  # pragma: no cover - runtime dependency check
        raise SystemExit("peft is required for --backend hf.") from exc

    try:
        from trl import SFTTrainer
    except ImportError as exc:  # pragma: no cover - runtime dependency check
        raise SystemExit("trl is required for --backend hf.") from exc

    train_path = Path(args.train_jsonl)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "args.json", vars(args))

    manifest = {
        "model": args.model,
        "train_jsonl": str(train_path),
        "train_rows": count_jsonl_rows(train_path),
        "output_dir": str(out_dir),
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "epochs": args.epochs,
        "lora": {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
            "load_in_4bit": parse_bool(args.load_in_4bit),
            "target_modules": args.lora_target_modules,
        },
        "backend": args.backend,
        "status": "running",
    }
    write_json(out_dir / "run_manifest.json", manifest)

    data_files = {"train": str(train_path)}
    if args.eval_jsonl:
        data_files["eval"] = str(Path(args.eval_jsonl))
    dataset = load_dataset("json", data_files=data_files)
    train_dataset = dataset["train"]
    eval_dataset = dataset.get("eval")

    if args.max_train_samples:
        train_dataset = train_dataset.select(
            range(min(args.max_train_samples, len(train_dataset)))
        )
    if eval_dataset is not None and args.max_eval_samples:
        eval_dataset = eval_dataset.select(
            range(min(args.max_eval_samples, len(eval_dataset)))
        )

    set_seed(args.seed)

    trust_remote_code = bool(args.trust_remote_code)
    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        use_fast=True,
        trust_remote_code=trust_remote_code,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    load_in_4bit = parse_bool(args.load_in_4bit)
    quantization_config = None
    if load_in_4bit:
        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:  # pragma: no cover - runtime dependency check
            raise SystemExit(
                "bitsandbytes is required for --load_in_4bit true."
            ) from exc
        compute_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=compute_dtype,
        )

    torch_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    device_map = "auto" if torch.cuda.is_available() else None
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch_dtype,
        device_map=device_map,
        trust_remote_code=trust_remote_code,
        quantization_config=quantization_config,
    )

    if args.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.config.use_cache = False

    lora_targets = LORA_DEFAULT_TARGETS
    if args.lora_target_modules:
        lora_targets = [
            item.strip()
            for item in args.lora_target_modules.split(",")
            if item.strip()
        ]
    peft_config = None
    if not args.no_lora and args.lora_r > 0:
        peft_config = LoraConfig(
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=lora_targets,
        )

    use_bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    use_fp16 = torch.cuda.is_available() and not use_bf16
    has_eval = eval_dataset is not None
    eval_strategy = "no"
    if has_eval:
        eval_strategy = "steps" if args.eval_steps > 0 else "epoch"

    save_strategy = "steps" if args.save_steps > 0 else "epoch"
    training_args = TrainingArguments(
        output_dir=str(out_dir),
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        logging_steps=args.logging_steps,
        save_strategy=save_strategy,
        save_steps=max(args.save_steps, 1),
        save_total_limit=args.save_total_limit,
        evaluation_strategy=eval_strategy,
        eval_steps=max(args.eval_steps, 1) if has_eval else None,
        report_to="none",
        bf16=use_bf16,
        fp16=use_fp16,
        gradient_checkpointing=args.gradient_checkpointing,
        seed=args.seed,
    )

    sft_kwargs: dict[str, Any] = {
        "model": model,
        "train_dataset": train_dataset,
        "eval_dataset": eval_dataset,
        "tokenizer": tokenizer,
        "peft_config": peft_config,
        "formatting_func": build_prompt,
    }

    try:
        from trl import SFTConfig  # type: ignore

        sft_config = SFTConfig(
            output_dir=str(out_dir),
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accum,
            num_train_epochs=args.epochs,
            learning_rate=args.learning_rate,
            logging_steps=args.logging_steps,
            save_strategy=save_strategy,
            save_steps=max(args.save_steps, 1),
            save_total_limit=args.save_total_limit,
            evaluation_strategy=eval_strategy,
            eval_steps=max(args.eval_steps, 1) if has_eval else None,
            report_to="none",
            bf16=use_bf16,
            fp16=use_fp16,
            gradient_checkpointing=args.gradient_checkpointing,
            max_seq_length=args.max_seq_len,
            packing=args.packing,
            seed=args.seed,
        )
        trainer = SFTTrainer(args=sft_config, **sft_kwargs)
    except (ImportError, TypeError):
        trainer = SFTTrainer(
            args=training_args,
            max_seq_length=args.max_seq_len,
            packing=args.packing,
            **sft_kwargs,
        )

    train_result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    metrics: dict[str, Any] = {"train": train_result.metrics}
    if has_eval:
        metrics["eval"] = trainer.evaluate()
    metrics["log_history"] = trainer.state.log_history
    write_json(out_dir / "metrics.json", metrics)

    trainer.save_model(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))

    manifest["status"] = "completed"
    write_json(out_dir / "run_manifest.json", manifest)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="SFT training launcher (mock backend by default, HF backend optional)."
    )
    p.add_argument("--model", required=True)
    p.add_argument("--train-jsonl", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--learning-rate", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--lora-dropout", type=float, default=0.05)
    p.add_argument("--lora-target-modules", default=",")
    p.add_argument("--no-lora", action="store_true")
    p.add_argument("--load_in_4bit", default="false")
    p.add_argument("--backend", choices=["mock", "hf"], default="mock")
    p.add_argument("--eval-jsonl")
    p.add_argument("--max-train-samples", type=int, default=0)
    p.add_argument("--max-eval-samples", type=int, default=0)
    p.add_argument("--max-seq-len", type=int, default=1024)
    p.add_argument("--packing", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--logging-steps", type=int, default=10)
    p.add_argument("--save-steps", type=int, default=0)
    p.add_argument("--eval-steps", type=int, default=0)
    p.add_argument("--save-total-limit", type=int, default=2)
    p.add_argument("--gradient-checkpointing", action="store_true")
    p.add_argument("--trust-remote-code", action="store_true")
    p.add_argument("--resume-from-checkpoint")
    args = p.parse_args()

    if args.lora_target_modules == ",":
        args.lora_target_modules = ""

    if args.backend == "mock":
        return run_mock(args)
    return run_hf(args)


if __name__ == "__main__":
    raise SystemExit(main())
