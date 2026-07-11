from __future__ import annotations

import itertools
import math
from collections import defaultdict
from typing import Any

from .util import clamp, mean, safe_log


def at_risk_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not int(row.get("failed_before_cycle", 0))]


def annotate_failed_before(rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["run_family"], row["mode"], row["schedule"], int(row["seed"]))
        groups[key].append(row)
    for group in groups.values():
        failed = False
        for row in sorted(group, key=lambda item: int(item["cycle"])):
            row["failed_before_cycle"] = int(failed)
            if int(row["first_failure_this_cycle"]):
                failed = True


def compute_damage(rows: list[dict[str, Any]], params: dict[str, float]) -> dict[tuple[str, str, int, int], float]:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["mode"]), str(row["schedule"]), int(row["seed"]))].append(row)
    result: dict[tuple[str, str, int, int], float] = {}
    for key, group in grouped.items():
        damage = 0.0
        for row in sorted(group, key=lambda item: int(item["cycle"])):
            kappa = float(row["kappa"])
            kappa_0 = max(float(row["kappa_star_0"]), 1e-9)
            phi = max(float(row["phi_star"]), 1e-6)
            phi_base = float(row["phi_base"])
            stress = max(0.0, (kappa / kappa_0) * (phi_base / phi))
            retained = math.exp(-1.0 / max(float(params["tau_r"]), 1e-9)) * damage
            cyclic = (stress ** float(params["m"])) * (1.0 + float(params["beta"]) * damage)
            structural = float(params["lambda"]) * float(row["handoff_loss"]) + float(params["mu"]) * abs(float(row["delta_hol"]))
            damage = min(1.0, retained + cyclic + structural)
            result[(key[0], key[1], key[2], int(row["cycle"]))] = damage
    return result


def attach_damage(rows: list[dict[str, Any]], damage_map: dict[tuple[str, str, int, int], float], phi_min: float = 0.70) -> None:
    for row in rows:
        key = (str(row["mode"]), str(row["schedule"]), int(row["seed"]), int(row["cycle"]))
        row["damage_D"] = round(float(damage_map[key]), 10)
        row["kappa_star_eff"] = round(float(row["kappa_star_0"]) * (1.0 - float(row["damage_D"])), 10)
        row["vkd_f"] = round(min(float(row["kappa_star_eff"]) - float(row["kappa"]), float(row["phi_star"]) - float(phi_min)), 10)


def _standardize(
    rows: list[dict[str, Any]], features: list[str], stats: dict[str, tuple[float, float]] | None = None
) -> tuple[list[list[float]], dict[str, tuple[float, float]]]:
    if stats is None:
        stats = {}
        for feature in features:
            values = [float(row[feature]) for row in rows]
            mu = mean(values)
            variance = mean((value - mu) ** 2 for value in values)
            stats[feature] = (mu, math.sqrt(max(variance, 1e-12)))
    matrix = [[1.0] + [(float(row[feature]) - stats[feature][0]) / stats[feature][1] for feature in features] for row in rows]
    return matrix, stats


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    augmented = [list(row) + [float(value)] for row, value in zip(matrix, vector)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            augmented[pivot][col] += 1e-8
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        augmented[col] = [value / divisor for value in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if abs(factor) < 1e-18:
                continue
            augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[col])]
    return [augmented[row][-1] for row in range(n)]


def fit_logistic(
    rows: list[dict[str, Any]],
    features: list[str],
    label: str = "first_failure_this_cycle",
    max_iterations: int = 40,
    l2: float = 0.02,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("cannot fit logistic model without rows")
    x, stats = _standardize(rows, features)
    y = [float(row[label]) for row in rows]
    dimensions = len(features) + 1
    weights = [0.0] * dimensions
    positive_rate = clamp(mean(y), 1e-5, 1 - 1e-5)
    weights[0] = math.log(positive_rate / (1.0 - positive_rate))
    iterations = 0
    for iteration in range(max_iterations):
        gradient = [0.0] * dimensions
        hessian = [[0.0] * dimensions for _ in range(dimensions)]
        for vector, target in zip(x, y):
            prediction = _sigmoid(sum(weight * value for weight, value in zip(weights, vector)))
            residual = target - prediction
            variance = max(prediction * (1.0 - prediction), 1e-8)
            for j in range(dimensions):
                gradient[j] += vector[j] * residual
                for k in range(j, dimensions):
                    hessian[j][k] += variance * vector[j] * vector[k]
        for j in range(dimensions):
            for k in range(j):
                hessian[j][k] = hessian[k][j]
            if j > 0:
                gradient[j] -= l2 * weights[j]
                hessian[j][j] += l2
            else:
                hessian[j][j] += 1e-8
        step = _solve_linear(hessian, gradient)
        for j in range(dimensions):
            weights[j] += step[j]
        iterations = iteration + 1
        if max(abs(value) for value in step) < 1e-7:
            break
    return {"features": features, "weights": weights, "stats": stats, "fit_iterations": iterations, "solver": "ridge_newton_irls"}


def predict_logistic(model: dict[str, Any], rows: list[dict[str, Any]]) -> list[float]:
    features = list(model["features"])
    x, _ = _standardize(rows, features, model["stats"])
    return [_sigmoid(sum(weight * value for weight, value in zip(model["weights"], vector))) for vector in x]


def binary_metrics(labels: list[int], predictions: list[float]) -> dict[str, float]:
    if not labels:
        return {"log_loss": float("nan"), "brier": float("nan"), "auc": float("nan")}
    log_loss = -mean(target * safe_log(prediction) + (1 - target) * safe_log(1 - prediction) for target, prediction in zip(labels, predictions))
    brier = mean((prediction - target) ** 2 for target, prediction in zip(labels, predictions))
    positives = [prediction for target, prediction in zip(labels, predictions) if target == 1]
    negatives = [prediction for target, prediction in zip(labels, predictions) if target == 0]
    if not positives or not negatives:
        auc = float("nan")
    else:
        wins = sum(1.0 if positive > negative else 0.5 if positive == negative else 0.0 for positive in positives for negative in negatives)
        auc = wins / (len(positives) * len(negatives))
    return {"log_loss": log_loss, "brier": brier, "auc": auc}


def _rows_for_seeds(rows: list[dict[str, Any]], seeds: set[int]) -> list[dict[str, Any]]:
    return [row for row in rows if int(row["seed"]) in seeds and not int(row.get("failed_before_cycle", 0))]


def _candidate_scores(rows: list[dict[str, Any]], train: list[dict[str, Any]], validation: list[dict[str, Any]], grid: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for m, beta, lam, mu, tau in itertools.product(grid["m"], grid["beta"], grid["lambda"], grid["mu"], grid["tau_r"]):
        params = {"m": float(m), "beta": float(beta), "lambda": float(lam), "mu": float(mu), "tau_r": float(tau)}
        damage_map = compute_damage(rows, params)
        for row in rows:
            key = (str(row["mode"]), str(row["schedule"]), int(row["seed"]), int(row["cycle"]))
            row["candidate_D"] = damage_map[key]
        model = fit_logistic(train, ["candidate_D"], max_iterations=30, l2=0.02)
        labels = [int(row["first_failure_this_cycle"]) for row in validation]
        metrics = binary_metrics(labels, predict_logistic(model, validation))
        candidates.append({"validation_log_loss": metrics["log_loss"], "validation_brier": metrics["brier"], "parameters": params})
    candidates.sort(key=lambda item: (item["validation_log_loss"], item["validation_brier"], tuple(item["parameters"].values())))
    return candidates


def select_damage_parameters(rows: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    train_seeds = set(map(int, experiment["training_seeds"]))
    validation_seeds = set(map(int, experiment["validation_seeds"]))
    selection_seed_set = train_seeds | validation_seeds
    selection_rows = [row for row in rows if int(row["seed"]) in selection_seed_set]
    train = _rows_for_seeds(selection_rows, train_seeds)
    validation = _rows_for_seeds(selection_rows, validation_seeds)
    candidates = _candidate_scores(selection_rows, train, validation, experiment["damage_parameter_grid"])
    best = candidates[0]
    tolerance = float(experiment.get("damage_identifiability_logloss_tolerance", 0.0005))
    near_best = [candidate for candidate in candidates if candidate["validation_log_loss"] <= best["validation_log_loss"] + tolerance]
    grid = experiment["damage_parameter_grid"]
    boundaries = {
        name: best["parameters"][name] in {float(min(values)), float(max(values))}
        for name, values in grid.items()
    }
    return {
        "parameters": best["parameters"],
        "selection": "grid_search_min_validation_log_loss",
        "training_seeds": sorted(train_seeds),
        "validation_seeds": sorted(validation_seeds),
        "heldout_seeds": list(map(int, experiment["heldout_seeds"])),
        "validation_log_loss": best["validation_log_loss"],
        "validation_brier": best["validation_brier"],
        "candidate_count": len(candidates),
        "near_best_candidate_count": len(near_best),
        "near_best_tolerance": tolerance,
        "selected_parameter_on_grid_boundary": boundaries,
        "top_candidates": candidates[:10],
        "status": "SIM_CALIBRATED_ON_DECLARED_TRAIN_VALIDATION_SPLIT",
    }


def damage_diagnostics(rows: list[dict[str, Any]], fit: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["mode"]), str(row["schedule"]), int(row["seed"]))].append(row)
    saturation_cycles: list[int] = []
    saturated_rows = 0
    for group in grouped.values():
        first = None
        for row in sorted(group, key=lambda item: int(item["cycle"])):
            if float(row["damage_D"]) >= 0.999999:
                saturated_rows += 1
                if first is None:
                    first = int(row["cycle"])
        if first is not None:
            saturation_cycles.append(first)
    return {
        "run_count": len(grouped),
        "row_count": len(rows),
        "saturated_row_fraction": saturated_rows / len(rows) if rows else None,
        "runs_reaching_saturation": len(saturation_cycles),
        "median_first_saturation_cycle": sorted(saturation_cycles)[len(saturation_cycles) // 2] if saturation_cycles else None,
        "near_best_candidate_count": fit["near_best_candidate_count"],
        "selected_parameter_on_grid_boundary": fit["selected_parameter_on_grid_boundary"],
        "identifiability_warning": bool(fit["near_best_candidate_count"] > 1 or any(fit["selected_parameter_on_grid_boundary"].values())),
    }


def compare_models(rows: list[dict[str, Any]], experiment: dict[str, Any]) -> dict[str, Any]:
    fit_seeds = set(map(int, experiment["training_seeds"] + experiment["validation_seeds"]))
    heldout_seeds = set(map(int, experiment["heldout_seeds"]))
    fit_rows = _rows_for_seeds(rows, fit_seeds)
    heldout = _rows_for_seeds(rows, heldout_seeds)
    cd = ["kappa", "phi_star", "vkd", "epsilon", "delta_hol"]
    operational = cd + ["context_pressure", "retry_count", "unresolved_dependency_count", "handoff_loss", "representation_tokens"]
    feature_sets = {
        "cycle_only": ["cycle"],
        "cd_current": cd,
        "cd_plus_cycle": cd + ["cycle"],
        "simple_operational": operational,
        "operational_plus_cycle": operational + ["cycle"],
        "cd_plus_damage": cd + ["damage_D"],
        "operational_plus_damage": operational + ["damage_D"],
        "strong_plus_damage": operational + ["cycle", "damage_D"],
    }
    labels = [int(row["first_failure_this_cycle"]) for row in heldout]
    results: dict[str, Any] = {}
    for name, features in feature_sets.items():
        model = fit_logistic(fit_rows, features)
        metrics = binary_metrics(labels, predict_logistic(model, heldout))
        results[name] = {
            **{key: round(value, 10) if math.isfinite(value) else None for key, value in metrics.items()},
            "features": features,
            "fit_iterations": model["fit_iterations"],
            "solver": model["solver"],
        }
    results["damage_vs_cd_logloss_gain"] = round(results["cd_current"]["log_loss"] - results["cd_plus_damage"]["log_loss"], 10)
    results["damage_vs_operational_logloss_gain"] = round(results["simple_operational"]["log_loss"] - results["operational_plus_damage"]["log_loss"], 10)
    results["damage_vs_strong_baseline_logloss_gain"] = round(results["operational_plus_cycle"]["log_loss"] - results["strong_plus_damage"]["log_loss"], 10)
    results["heldout_row_count"] = len(heldout)
    results["heldout_failure_count"] = sum(labels)
    return results
