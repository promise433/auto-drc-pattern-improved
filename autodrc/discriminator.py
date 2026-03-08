from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscriminatorWeights:
    target_hit: float = 2.0
    non_target_penalty: float = 0.3
    invalid_penalty: float = 3.0
    delta_penalty: float = 0.02


@dataclass(frozen=True)
class DiscriminatorScore:
    score: float
    target_hits: int
    non_target_hits: int
    geometry_valid: bool
    delta_nm: int
    explanation: str


def score_case(
    *,
    target_hits: int,
    total_hits: int,
    geometry_valid: bool,
    delta_nm: int,
    weights: DiscriminatorWeights,
) -> DiscriminatorScore:
    non_target_hits = max(0, total_hits - target_hits)
    score = (
        weights.target_hit * target_hits
        - weights.non_target_penalty * non_target_hits
        - weights.delta_penalty * delta_nm
    )
    if not geometry_valid:
        score -= weights.invalid_penalty

    explanation = (
        f"target_hits={target_hits}, non_target_hits={non_target_hits}, "
        f"delta={delta_nm}, geometry_valid={geometry_valid}"
    )
    return DiscriminatorScore(
        score=score,
        target_hits=target_hits,
        non_target_hits=non_target_hits,
        geometry_valid=geometry_valid,
        delta_nm=delta_nm,
        explanation=explanation,
    )
