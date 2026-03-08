from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class TrainingRecipe:
    name: str
    base_model: str
    method: str
    learning_rate: float
    batch_size: int
    grad_accum: int
    epochs: int
    lora_r: int
    lora_alpha: int
    lora_dropout: float
    use_4bit: bool
    notes: str


def default_recipes() -> list[TrainingRecipe]:
    return [
        TrainingRecipe(
            name="lora_tinyllama_rule_to_runset",
            base_model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            method="LoRA",
            learning_rate=2e-4,
            batch_size=4,
            grad_accum=8,
            epochs=3,
            lora_r=16,
            lora_alpha=32,
            lora_dropout=0.05,
            use_4bit=False,
            notes="Baseline small-model instruction tuning for rule-to-runset mapping.",
        ),
        TrainingRecipe(
            name="qlora_qwen2p5_3b_instruction",
            base_model="Qwen/Qwen2.5-3B-Instruct",
            method="Q-LoRA",
            learning_rate=1.5e-4,
            batch_size=2,
            grad_accum=16,
            epochs=3,
            lora_r=32,
            lora_alpha=64,
            lora_dropout=0.05,
            use_4bit=True,
            notes="Higher-capacity but memory-efficient setup for GOOD/BAD/ILLEGAL generation.",
        ),
    ]


def to_command(recipe: TrainingRecipe, train_jsonl: str, out_dir: str) -> str:
    bits = " --load_in_4bit true" if recipe.use_4bit else ""
    return (
        "python -m scripts.train_sft "
        f"--model '{recipe.base_model}' "
        f"--train-jsonl '{train_jsonl}' "
        f"--output-dir '{out_dir}/{recipe.name}' "
        f"--learning-rate {recipe.learning_rate} "
        f"--batch-size {recipe.batch_size} "
        f"--grad-accum {recipe.grad_accum} "
        f"--epochs {recipe.epochs} "
        f"--lora-r {recipe.lora_r} "
        f"--lora-alpha {recipe.lora_alpha} "
        f"--lora-dropout {recipe.lora_dropout}{bits}"
    )


def export_recipes(out_path: Path, train_jsonl: str, out_dir: str) -> dict[str, object]:
    rows = []
    for recipe in default_recipes():
        rows.append(
            {
                "recipe": asdict(recipe),
                "command": to_command(recipe, train_jsonl=train_jsonl, out_dir=out_dir),
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return {"recipes": len(rows), "out_path": str(out_path)}


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Export LoRA/Q-LoRA training recipes for task-3 optimization."
    )
    p.add_argument(
        "--out",
        default="config/training_recipes.json",
        help="Output file path",
    )
    p.add_argument(
        "--train-jsonl",
        default="data/instruction_tuning/instruction.jsonl",
        help="Instruction tuning dataset path",
    )
    p.add_argument(
        "--output-dir",
        default="runs/training",
        help="Directory to store trained adapters",
    )
    args = p.parse_args()

    stats = export_recipes(Path(args.out), train_jsonl=args.train_jsonl, out_dir=args.output_dir)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
