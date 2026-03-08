from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autodrc.training_recipes import export_recipes


class TrainingRecipesTests(unittest.TestCase):
    def test_export_recipes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recipes.json"
            stats = export_recipes(
                out_path=out,
                train_jsonl="data/instruction_tuning/instruction.jsonl",
                out_dir="runs/training",
            )
            self.assertEqual(stats["recipes"], 2)
            rows = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 2)
            self.assertIn("command", rows[0])


if __name__ == "__main__":
    unittest.main()
