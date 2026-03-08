from __future__ import annotations

import unittest

from autodrc.llm_generator import _extract_json, _polygons_from_payload, build_prompt


class LLMGeneratorTests(unittest.TestCase):
    def test_build_prompt(self) -> None:
        prompt = build_prompt("Minimum width 0.14um on met1", "GOOD")
        self.assertIn("### Instruction", prompt)
        self.assertIn("rule_text", prompt)

    def test_extract_json(self) -> None:
        text = """Some output\n```json\n{\"intent\": \"GOOD\", \"lpl\": []}\n```"""
        payload = _extract_json(text)
        self.assertEqual(payload["intent"], "GOOD")

    def test_polygons_from_payload(self) -> None:
        payload = {
            "intent": "GOOD",
            "lpl": [
                {"layer": "met1", "points": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}
            ],
        }
        polygons = _polygons_from_payload(payload)
        self.assertEqual(len(polygons), 1)
        self.assertEqual(polygons[0].layer, "met1")


if __name__ == "__main__":
    unittest.main()
