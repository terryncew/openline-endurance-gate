from __future__ import annotations

from typing import Any

from .sim import AMPLITUDE_RANK, AMPLITUDE_SCALE, _delta_for
from .util import stable_uniform
from .world import REQUIREMENTS, Perturbation


def matched_amplitude_events(seed: int, amplitude: str, cycles: int) -> list[Perturbation]:
    """Build constant-amplitude packets with common random numbers.

    Across low, medium, and high conditions, cycle j has the same target, sign,
    latent ambiguity draw, correction draw, and event id. Only the declared
    amplitude-dependent transformation changes.
    """
    events: list[Perturbation] = []
    rank = AMPLITUDE_RANK[amplitude]
    scale = AMPLITUDE_SCALE[amplitude]
    for index in range(int(cycles)):
        target_index = min(len(REQUIREMENTS) - 1, int(stable_uniform("amp-target", seed, index) * len(REQUIREMENTS)))
        target = REQUIREMENTS[target_index]
        sign = -1 if stable_uniform("amp-sign", seed, index) < 0.5 else 1
        ambiguity_draw = stable_uniform("amp-ambiguity", seed, index)
        correction_draw = stable_uniform("amp-correction", seed, index)
        ambiguity = round(0.02 + 0.04 * rank + 0.08 * ambiguity_draw, 5)
        correction_required = correction_draw < (0.18 + 0.08 * rank)
        token_cost = 18 + 7 * scale + (10 if correction_required else 0)
        events.append(
            Perturbation(
                event_id=f"amp-s{seed}-e{index:02d}",
                amplitude=amplitude,
                target=target,
                delta=_delta_for(target, amplitude, sign),
                ambiguity=ambiguity,
                correction_required=correction_required,
                token_cost=token_cost,
            )
        )
    return events


def matched_packet_witness(seed: int, cycles: int) -> dict[str, Any]:
    packets = {level: matched_amplitude_events(seed, level, cycles) for level in ("low", "medium", "high")}
    aligned = True
    for index in range(cycles):
        rows = [packets[level][index] for level in ("low", "medium", "high")]
        aligned &= len({row.event_id for row in rows}) == 1
        aligned &= len({row.target for row in rows}) == 1
        aligned &= len({1 if row.delta > 0 else -1 for row in rows}) == 1
    return {
        "seed": int(seed),
        "cycles": int(cycles),
        "common_event_ids_targets_and_signs": bool(aligned),
        "levels": ["low", "medium", "high"],
    }
