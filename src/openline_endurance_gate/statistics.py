from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from typing import Any, Callable, Iterable

from .util import mean, median


def _deterministic_seed(*parts: object) -> int:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def exact_sign_flip_p(differences: Iterable[float]) -> float:
    """Exact two-sided paired randomization p-value.

    Integer-valued cycle differences use dynamic programming, so all declared
    pairs are retained. Non-integer inputs fall back to a deterministic Monte
    Carlo sign-flip test rather than silently truncating the sample.
    """
    values = [float(value) for value in differences if abs(float(value)) > 1e-12]
    if not values:
        return 1.0
    rounded = [int(round(value)) for value in values]
    if all(abs(value - integer) <= 1e-9 for value, integer in zip(values, rounded)):
        observed = abs(sum(rounded))
        distribution: Counter[int] = Counter({0: 1})
        for value in rounded:
            next_distribution: Counter[int] = Counter()
            for current, count in distribution.items():
                next_distribution[current + value] += count
                next_distribution[current - value] += count
            distribution = next_distribution
        extreme = sum(count for signed_sum, count in distribution.items() if abs(signed_sum) >= observed)
        return extreme / (2 ** len(rounded))

    rng = random.Random(_deterministic_seed("sign-flip", *[f"{v:.12g}" for v in values]))
    observed = abs(mean(values))
    draws = 200_000
    extreme = 0
    for _ in range(draws):
        statistic = abs(mean(value if rng.random() < 0.5 else -value for value in values))
        extreme += int(statistic + 1e-12 >= observed)
    return (extreme + 1) / (draws + 1)


def bootstrap_interval(
    values: Iterable[float],
    statistic: Callable[[Iterable[float]], float] = median,
    confidence: float = 0.95,
    resamples: int = 5_000,
    seed_tag: str = "bootstrap",
) -> list[float | None]:
    data = [float(value) for value in values]
    if not data:
        return [None, None]
    if len(data) == 1:
        value = float(statistic(data))
        return [value, value]
    rng = random.Random(_deterministic_seed(seed_tag, *[f"{v:.12g}" for v in data]))
    estimates: list[float] = []
    n = len(data)
    for _ in range(int(resamples)):
        sample = [data[rng.randrange(n)] for _ in range(n)]
        estimates.append(float(statistic(sample)))
    estimates.sort()
    alpha = max(0.0, min(1.0, 1.0 - float(confidence)))
    lo_index = max(0, min(len(estimates) - 1, int((alpha / 2.0) * len(estimates))))
    hi_index = max(0, min(len(estimates) - 1, int((1.0 - alpha / 2.0) * len(estimates)) - 1))
    return [estimates[lo_index], estimates[hi_index]]


def paired_effect(
    differences: Iterable[float],
    confidence: float = 0.95,
    resamples: int = 5_000,
    seed_tag: str = "paired-effect",
) -> dict[str, Any]:
    values = [float(value) for value in differences]
    nonzero = [value for value in values if abs(value) > 1e-12]
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    zero = len(values) - positive - negative
    return {
        "paired_difference_count": len(values),
        "nonzero_pair_count": len(nonzero),
        "differences": values,
        "median_difference_cycles": median(values),
        "mean_difference_cycles": mean(values),
        "median_confidence_interval": bootstrap_interval(values, median, confidence, resamples, seed_tag + "-median"),
        "mean_confidence_interval": bootstrap_interval(values, mean, confidence, resamples, seed_tag + "-mean"),
        "exact_sign_flip_p": exact_sign_flip_p(values),
        "positive_count": positive,
        "negative_count": negative,
        "zero_count": zero,
        "directional_consistency": max(positive, negative) / len(nonzero) if nonzero else 0.0,
    }


def holm_adjust(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    indexed = sorted(enumerate(float(value) for value in p_values), key=lambda item: item[1])
    adjusted = [1.0] * len(indexed)
    running = 0.0
    m = len(indexed)
    for rank, (original_index, p_value) in enumerate(indexed):
        candidate = min(1.0, (m - rank) * p_value)
        running = max(running, candidate)
        adjusted[original_index] = running
    return adjusted


def approximate_paired_mde(values: Iterable[float], alpha: float = 0.10, power: float = 0.80) -> float | None:
    """Normal-approximation minimum detectable paired mean difference.

    The constants cover the pre-registered alpha=.10, power=.80 case used by
    the default experiment. Other values use a compact inverse-normal
    approximation.
    """
    data = [float(value) for value in values]
    if len(data) < 2:
        return None
    mu = mean(data)
    sd = math.sqrt(sum((value - mu) ** 2 for value in data) / (len(data) - 1))
    z_alpha = _inverse_normal_cdf(1.0 - alpha / 2.0)
    z_power = _inverse_normal_cdf(power)
    return (z_alpha + z_power) * sd / math.sqrt(len(data))


def _inverse_normal_cdf(p: float) -> float:
    # Peter J. Acklam's rational approximation.
    if not 0.0 < p < 1.0:
        raise ValueError("p must be between zero and one")
    a = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
    b = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00)
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


def effect_classification(effect: dict[str, Any], material_threshold: float) -> str:
    ci = effect.get("median_confidence_interval") or [None, None]
    lo, hi = ci
    median_value = float(effect.get("median_difference_cycles", 0.0))
    if lo is None or hi is None:
        return "INSUFFICIENT_PAIRS"
    if abs(median_value) >= material_threshold and effect.get("exact_sign_flip_p", 1.0) <= 0.10:
        return "DETECTED_MATERIAL_EFFECT"
    if float(lo) > -material_threshold and float(hi) < material_threshold:
        return "MATERIAL_EFFECT_EXCLUDED_AT_DECLARED_SCALE"
    return "INCONCLUSIVE_EFFECT_INTERVAL"


def survival_summary(n_f_values: Iterable[float], horizon: int) -> dict[str, Any]:
    values = [int(round(float(value))) for value in n_f_values]
    if not values:
        return {"run_count": 0, "rmst_cycles": None, "survival": {}}
    at_risk = len(values)
    survival = 1.0
    curve: dict[str, float] = {"0": 1.0}
    rmst = 0.0
    for cycle in range(1, horizon + 1):
        rmst += survival
        events = sum(value == cycle for value in values)
        censored = sum(value == horizon + 1 and cycle == horizon for value in values)
        if at_risk > 0 and events:
            survival *= 1.0 - events / at_risk
        curve[str(cycle)] = survival
        at_risk -= events + censored
    return {
        "run_count": len(values),
        "failure_count": sum(value <= horizon for value in values),
        "censored_count": sum(value > horizon for value in values),
        "rmst_cycles": rmst,
        "survival": curve,
    }
