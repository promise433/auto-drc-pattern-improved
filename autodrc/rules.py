from __future__ import annotations

from dataclasses import dataclass
import re


_VALUE_UNIT = r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>nm|um|µm)"
_WIDTH_RE = re.compile(rf"(?i)(?:min(?:imum)?\s+)?width(?:\s+of)?\s*{_VALUE_UNIT}")
_SPACING_RE = re.compile(rf"(?i)(?:min(?:imum)?\s+)?spacing(?:\s+of)?\s*{_VALUE_UNIT}")
_DENSITY_RE = re.compile(
    r"(?i)(?:min(?:imum)?\s+)?density(?:\s+of)?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent)"
)
_AREA_RE = re.compile(
    r"(?i)(?:min(?:imum)?\s+)?area(?:\s+of)?\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>um\^?2|µm\^?2|um2|µm2)"
)
_ENDCAP_RE = re.compile(rf"(?i)(?:poly\s+)?endcap(?:\s+of)?\s*{_VALUE_UNIT}")
_VIA_ENCLOSURE_RE = re.compile(
    rf"(?i)(?:via\s+)?(?:min(?:imum)?\s+)?enclosure(?:\s+of)?\s*{_VALUE_UNIT}"
)
_LAYER_RE = re.compile(r"(?i)\b(?:on|for|in|by)\b\s+(?P<layer>[a-z0-9_]+)")


@dataclass(frozen=True)
class ParsedRule:
    rule_type: str
    layer: str
    threshold_nm: int
    source_text: str


def _to_nm(value_text: str, unit: str) -> int:
    value = float(value_text)
    if unit.lower() in {"um", "µm"}:
        return int(round(value * 1000))
    return int(round(value))


def parse_rule_text(text: str, default_layer: str = "met1") -> ParsedRule:
    lower = text.strip().lower()
    if not lower:
        raise ValueError("rule text is empty")

    width_match = _WIDTH_RE.search(text)
    spacing_match = _SPACING_RE.search(text)
    density_match = _DENSITY_RE.search(text)
    area_match = _AREA_RE.search(text)
    endcap_match = _ENDCAP_RE.search(text)
    via_enclosure_match = _VIA_ENCLOSURE_RE.search(text)

    # Density with explicit window hint is treated as density_window.
    has_window_hint = "window" in lower and density_match is not None

    matches = [
        m
        for m in [
            width_match,
            spacing_match,
            density_match,
            area_match,
            endcap_match,
            via_enclosure_match,
        ]
        if m
    ]

    if len(matches) > 1 and not (density_match and has_window_hint and len(matches) == 1):
        raise ValueError("rule text includes multiple rule kinds; please provide one")
    if not matches:
        raise ValueError(
            "unable to parse threshold from text (supported: width/spacing/density/area/endcap/via enclosure)"
        )

    match = matches[0]
    assert match is not None
    if width_match:
        rule_type = "min_width"
        threshold_nm = _to_nm(match.group("value"), match.group("unit"))
    elif spacing_match:
        rule_type = "min_spacing"
        threshold_nm = _to_nm(match.group("value"), match.group("unit"))
    elif density_match:
        rule_type = "density_window" if has_window_hint else "min_density"
        threshold_nm = int(round(float(match.group("value")) * 100))  # basis points
    elif area_match:
        rule_type = "min_area"
        value = float(match.group("value"))
        # um^2 -> nm^2
        threshold_nm = int(round(value * 1000 * 1000))
    elif endcap_match:
        rule_type = "poly_endcap"
        threshold_nm = _to_nm(match.group("value"), match.group("unit"))
    else:
        rule_type = "via_enclosure"
        threshold_nm = _to_nm(match.group("value"), match.group("unit"))

    layer_match = None
    for candidate in _LAYER_RE.finditer(text):
        layer_match = candidate
    if layer_match:
        layer = layer_match.group("layer").lower()
    elif rule_type == "poly_endcap":
        layer = "poly"
    else:
        layer = default_layer

    return ParsedRule(
        rule_type=rule_type,
        layer=layer,
        threshold_nm=threshold_nm,
        source_text=text.strip(),
    )
