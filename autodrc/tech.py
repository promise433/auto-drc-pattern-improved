from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_TECH_LAYER_MAPS = {
    "sky130": "layers_sky130.json",
    "ihp_sg13g2": "layers_ihp_sg13g2.json",
}
_TECH_NAME_ALIASES = {
    "sky130": "sky130",
    "ihp": "ihp_sg13g2",
    "ihp_sg13g2": "ihp_sg13g2",
    "ihp-sg13g2": "ihp_sg13g2",
    "sg13g2": "ihp_sg13g2",
}


def normalize_tech_name(tech_name: str | None) -> str:
    if tech_name is None:
        return "sky130"
    low = str(tech_name).strip().lower()
    if not low:
        return "sky130"
    if low not in _TECH_NAME_ALIASES:
        raise ValueError(f"Unknown technology: {tech_name!r}")
    return _TECH_NAME_ALIASES[low]


def detect_tech_name(runset_path: Path | None = None) -> str:
    if runset_path is None:
        return "sky130"

    path_text = str(runset_path).lower()
    text = runset_path.read_text(encoding="utf-8", errors="replace").lower() if runset_path.is_file() else ""
    ihp = "sg13g2" in text or bool(re.search(r'topmetal1\s*=\s*source\.polygons\(["\']126/0', text))
    sky = "sky130" in text or bool(re.search(r'm1\s*=\s*(?:input|polygons)\(m1_?drawing', text))
    path_ihp = "sg13g2" in path_text
    path_sky = "sky130" in path_text
    if (ihp and sky) or (ihp and path_sky) or (sky and path_ihp):
        raise ValueError(f"Conflicting technology identities in runset: {runset_path}")
    if ihp or path_ihp:
        return "ihp_sg13g2"
    # Preserve the original SKY default for small, unlabelled legacy rule decks.
    return "sky130"


def require_sky_research(tech_name: str) -> None:
    if normalize_tech_name(tech_name) != "sky130":
        raise NotImplementedError("IHP research task presets are not connected; use runset_coverage or closed_loop with explicit IHP targets.")


def layer_map_path_for_tech(tech_name: str) -> Path:
    tech_name = normalize_tech_name(tech_name)
    filename = _TECH_LAYER_MAPS.get(tech_name, _TECH_LAYER_MAPS["sky130"])
    return _CONFIG_DIR / filename


def layer_map_path_for_runset(runset_path: Path | None) -> Path:
    return layer_map_path_for_tech(detect_tech_name(runset_path))


@lru_cache(maxsize=None)
def load_layer_pairs_for_tech(tech_name: str) -> dict[str, tuple[int, int]]:
    tech_name = normalize_tech_name(tech_name)
    path = layer_map_path_for_tech(tech_name)
    rows = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, tuple[int, int]] = {}
    for key, pair in rows.items():
        if not isinstance(key, str):
            continue
        if not isinstance(pair, list | tuple) or len(pair) != 2:
            continue
        try:
            out[key.strip().lower()] = (int(pair[0]), int(pair[1]))
        except Exception:
            continue
    return out


@lru_cache(maxsize=None)
def load_known_layers_for_tech(tech_name: str) -> set[str]:
    return set(load_layer_pairs_for_tech(normalize_tech_name(tech_name)).keys())
