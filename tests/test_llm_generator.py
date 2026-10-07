from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autodrc.llm_generator import (
    _allowed_layers_for_tech,
    _effective_sampling_params,
    _extract_json,
    _polygons_from_payload,
    build_prompt,
    generate_case_with_llm,
    LLMCase,
    LLMResponseError,
    main,
)


class LLMGeneratorTests(unittest.TestCase):
    def test_generation_parses_only_continuation_and_preserves_debug(self) -> None:
        completion = json.dumps({"lpl": [{"layer": "met1", "points":
            [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]}]})
        empty = json.dumps({"intent": "GOOD", "lpl": []})
        for response in (completion, "unfinished response {\"intent\": \"GOOD\",",
                         empty, json.dumps({"intent": "BAD", "lpl": json.loads(completion)["lpl"]})):
            valid = response in (completion, empty)
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as tmp:
                tokenizer = Mock(return_value={"input_ids": SimpleNamespace(shape=(1, 1))})
                tokenizer.decode.side_effect = lambda tokens, **kwargs: "".join(tokens)
                rule_text = "Use of met1 layer is prohibited" if response == empty else "Minimum width 0.14um on met1"
                prompt = build_prompt(rule_text, "GOOD")
                model = SimpleNamespace(config=SimpleNamespace(model_type="llama"),
                                        generate=Mock(return_value=[[prompt, response]]))
                with patch("autodrc.llm_generator._load_model_and_tokenizer", return_value=(tokenizer, model)), patch.dict(
                    "sys.modules", {"torch": SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))}
                ):
                    if valid:
                        case = generate_case_with_llm(model_name="fixture", rule_text=rule_text,
                                                      intent="GOOD", debug_dir=Path(tmp))
                        self.assertEqual(case.raw_response, response)
                        if response == empty:
                            self.assertEqual(case.polygons, ())
                        else:
                            self.assertEqual(case.polygons[0].points[1], (200, 0))
                    else:
                        with self.assertRaises(LLMResponseError):
                            generate_case_with_llm(model_name="fixture", rule_text=rule_text,
                                                   intent="GOOD", debug_dir=Path(tmp))
                self.assertEqual((Path(tmp)/"llm_raw_good.txt").read_text(), response)
                self.assertEqual((Path(tmp)/"llm_prompt_good.txt").read_text(), prompt)

    def test_model_cli_writes_case_without_loading_a_model(self) -> None:
        polygons = _polygons_from_payload({"lpl": [{"layer": "met1", "points":
            [[0, 0], [400, 0], [400, 160], [0, 160], [0, 0]]}]})
        candidate = LLMCase(intent="GOOD", polygons=polygons, raw_response="fixture")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "candidate.json"
            argv = ["llm_generator", "--model", "local-fixture", "--rule-text",
                    "Minimum width 0.14um on met1", "--intent", "GOOD", "--out", str(output)]
            with patch("sys.argv", argv), patch("builtins.print"), patch(
                "autodrc.llm_generator.generate_case_with_llm", return_value=candidate
            ) as generate:
                self.assertEqual(main(), 0)
            self.assertEqual(generate.call_count, 1)
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(payload["geometry_valid"])
        self.assertEqual(payload["intent"], "GOOD")
        self.assertEqual(payload["lpl"][0]["layer"], "met1")

    def test_build_prompt(self) -> None:
        prompt = build_prompt("Minimum width 0.14um on met1", "GOOD")
        self.assertIn("### Instruction", prompt)
        self.assertIn("rule_text", prompt)
        self.assertIn('"intent": "GOOD"', prompt)
        self.assertNotIn('GOOD|BAD|ILLEGAL', prompt)

    def test_build_prompt_uses_tech_specific_allowed_layers(self) -> None:
        sky_prompt = build_prompt("Minimum width 0.14um on met1", "GOOD", tech_name="sky130")
        ihp_prompt = build_prompt("Min. Activ width", "GOOD", tech_name="ihp_sg13g2")
        self.assertIn('"met1"', sky_prompt)
        self.assertNotIn('"activ"', sky_prompt)
        self.assertIn('"activ"', ihp_prompt)
        self.assertNotIn('"li1"', ihp_prompt)
        self.assertNotIn('"layer": "met1"', ihp_prompt)
        self.assertIn('"layer": "activ"', ihp_prompt)

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

    def test_polygons_from_payload_respects_tech_specific_layers(self) -> None:
        payload = {
            "intent": "GOOD",
            "lpl": [
                {"layer": "activ", "points": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}
            ],
        }
        polygons = _polygons_from_payload(payload, expected_layer="met1", tech_name="sky130")
        self.assertEqual(polygons[0].layer, "met1")
        polygons = _polygons_from_payload(payload, expected_layer="activ", tech_name="ihp_sg13g2")
        self.assertEqual(polygons[0].layer, "activ")

    def test_polygons_from_payload_falls_back_to_tech_default_layer(self) -> None:
        payload = {
            "intent": "GOOD",
            "lpl": [
                {"layer": "bogus", "points": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]}
            ],
        }
        polygons = _polygons_from_payload(payload, tech_name="ihp_sg13g2")
        self.assertEqual(polygons[0].layer, "activ")

    def test_allowed_layers_do_not_cross_fallback_to_sky130(self) -> None:
        with patch("autodrc.llm_generator.load_known_layers_for_tech", side_effect=RuntimeError("boom")):
            self.assertEqual(_allowed_layers_for_tech("ihp_sg13g2"), set())

    def test_qwen3_default_sampling_params_are_overridden(self) -> None:
        temperature, top_p = _effective_sampling_params(
            is_qwen3=True,
            temperature=0.2,
            top_p=0.9,
        )
        self.assertEqual(temperature, 0.7)
        self.assertEqual(top_p, 0.8)

    def test_qwen3_explicit_sampling_params_are_preserved(self) -> None:
        temperature, top_p = _effective_sampling_params(
            is_qwen3=True,
            temperature=0.4,
            top_p=0.85,
        )
        self.assertEqual(temperature, 0.4)
        self.assertEqual(top_p, 0.85)

    def test_non_qwen3_sampling_params_are_unchanged(self) -> None:
        temperature, top_p = _effective_sampling_params(
            is_qwen3=False,
            temperature=0.2,
            top_p=0.9,
        )
        self.assertEqual(temperature, 0.2)
        self.assertEqual(top_p, 0.9)


if __name__ == "__main__":
    unittest.main()
