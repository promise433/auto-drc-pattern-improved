from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleTask:
    name: str
    rule_type: str
    layer: str
    threshold_nm: int
    description: str
    known_rule: bool
    target_categories: tuple[str, ...] = ()


KNOWN_TASKS: tuple[RuleTask, ...] = (
    RuleTask(
        name="met1_min_width",
        rule_type="min_width",
        layer="met1",
        threshold_nm=140,
        description="met1 minimum width 0.14um",
        known_rule=True,
        target_categories=("m1.1",),
    ),
    RuleTask(
        name="met1_min_spacing",
        rule_type="min_spacing",
        layer="met1",
        threshold_nm=140,
        description="met1 minimum spacing 0.14um",
        known_rule=True,
        target_categories=("m1.2",),
    ),
    RuleTask(
        name="li1_min_width",
        rule_type="min_width",
        layer="li1",
        threshold_nm=170,
        description="li1 minimum width 0.17um (periphery-oriented benchmark)",
        known_rule=True,
        target_categories=("li.1",),
    ),
    RuleTask(
        name="li1_min_spacing",
        rule_type="min_spacing",
        layer="li1",
        threshold_nm=170,
        description="li1 minimum spacing 0.17um (periphery-oriented benchmark)",
        known_rule=True,
        target_categories=("li.3",),
    ),
)


UNKNOWN_TASKS: tuple[RuleTask, ...] = (
    RuleTask(
        name="met1_min_density",
        rule_type="min_density",
        layer="met1",
        threshold_nm=3000,  # basis points: 30%
        description="met1 minimum density 30% in analysis window",
        known_rule=False,
    ),
    RuleTask(
        name="met1_density_window",
        rule_type="density_window",
        layer="met1",
        threshold_nm=4000,  # basis points: 40%
        description="met1 density 40% in fixed 2um x 2um window",
        known_rule=False,
    ),
    RuleTask(
        name="poly_endcap",
        rule_type="poly_endcap",
        layer="poly",
        threshold_nm=150,
        description="poly endcap minimum extension 0.15um over active edge",
        known_rule=False,
    ),
    RuleTask(
        name="met1_via_enclosure",
        rule_type="via_enclosure",
        layer="met1",
        threshold_nm=60,
        description="via enclosure by met1 at least 0.06um",
        known_rule=False,
    ),
)
