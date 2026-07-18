# Succession Calibrator

## The question it answers

The calibrator asks a narrow, operational question:

> For this agent, task family, signal schema, and handoff method, do repeated COLE checkpoint patterns predict that a fresh successor will outperform continued execution?

It does not estimate a universal lifespan. It does not turn Coherence Dynamics into a physical law. It does not prove that a successor will be better. It produces a receiver-owned advisory whose usefulness can be measured on held-out paired runs.

## Architecture

The layers stay separate:

1. **Wire Canon input** — a signed provisional checkpoint plus disclosed semantic graph and normalized signal.
2. **COLE measurement** — deterministic kappa, epsilon, delta-hol, phi-star, VKD, and UCR recomputation.
3. **Succession calibration** — agent/task-specific thresholds and persistence learned from labeled paired outcomes.
4. **Succession assessment** — a local unsigned recomputation report ending in a bounded advisory.
5. **Verified handoff** — required before a receiver may retire the source runtime.

The calibrator imports the official `cole-portable-core` implementation at a pinned commit. It does not carry a second copy of the equations.

## What to measure

Choose one normalized signal schema before collecting data. The schema must specify what every integer point means, its direction, its sampling cadence, its missing-data behavior, and the evaluator that produced it. Values must be integer micros in `[0, 1000000]`.

Do not call a proxy “quality” unless the evaluator supports that interpretation. Useful signals may include bounded task-check accuracy, invariant satisfaction, or receiver-scored completion. Token count, latency, and cost should remain separate operational measurements.

COLE’s metrics also remain separate:

- `kappa_micros`: curvature of the declared normalized signal;
- `epsilon_micros`: rolling variability of that signal;
- `delta_hol_micros`: structural graph drift;
- `phi_star_micros`: the declared fixed-point composite in the pinned COLE profile;
- `ucr_micros`: unsupported material-claim ratio.

UCR is not used as agent health. A checkpoint with no material claim or nonzero UCR is inadmissible for calibration and insufficient for a succession candidate.

## Collect matched labels

At a sampled checkpoint, fork two arms while the source state is still available:

- **continue arm:** let the current runtime continue;
- **successor arm:** start a fresh runtime from the same verified, bounded handoff.

Hold the task, evaluator, tool permissions, evidence availability, token budget, and time budget constant. Declare a benefit margin before scoring either arm. The CLI derives the label:

```text
succession_beneficial if successor_quality - continued_quality >= benefit_margin
continue otherwise
```

This paired arm is the strongest label source. Human-review labels are accepted only when they include the SHA-256 hash of a durable review artifact; that hash binds the label to the review but does not prove the reviewer was correct.

Avoid sampling every adjacent checkpoint from one long run. Many checkpoints from one run are correlated. The calibrator assigns entire `run_id` groups to train or holdout, preventing direct run leakage, but broader diversity is still the operator’s responsibility.

## Activation gates

A policy remains `observe_only` unless all of these are true:

- at least 500 labeled observations are admitted, matching COLE’s calibrated-profile floor;
- each split contains at least 20 observations and five independent run IDs for each label class under this v1 safety profile;
- every submitted observation passes validation, signature checking, and full COLE recomputation;
- material claims are present and fully supported;
- every admitted measurement signer is pinned by the receiver;
- one COLE metric-affecting contract is used throughout;
- train and holdout splits both contain `continue` and `succession_beneficial` labels;
- whole `run_id` groups remain disjoint across the split;
- thresholds and a persistence rule can be fitted.
- the untouched holdout meets the receiver-declared acceptance floors (defaults: 0.60 balanced accuracy, 0.95 specificity, and 0.50 sensitivity).

The 500-sample floor is necessary for this profile, not sufficient evidence of usefulness. Read the held-out confusion matrix, sensitivity, specificity, precision, accuracy, and balanced accuracy separately. The three acceptance floors are signed policy inputs, not universal constants; set them before calibration. A poor held-out result keeps the policy observation-only even if its signatures are valid.

The signed policy carries two corpus commitments. `submitted_corpus_hash` binds every supplied row, including hostile or rejected rows, so inconvenient failures cannot be silently deleted. `admitted_corpus_hash` binds only the rows actually used for fitting and becomes the exact COLE calibrated-profile corpus hash.

## Deterministic fitting

The implementation searches observed integer thresholds for each metric independently. Amber thresholds maximize training balanced accuracy, then specificity, then choose the more conservative tied threshold. Critical kappa and phi thresholds maximize training sensitivity subject to the declared specificity floor, which defaults to `950000` micros and is stored in the policy.

It then searches:

- minimum metric breaches per checkpoint;
- persistence window;
- required signaled checkpoints in that window.

The rule maximizes training balanced accuracy, specificity, and sensitivity in that order, then prefers stronger metric consensus and the shortest equally performing window. The untouched run-grouped holdout is reported afterward.

These selection rules are implementation policy, not natural constants. Change them only as a new version and compare the result on untouched data.

## Advisory meanings

- `observe_only` — calibration is not activated; values are visible but cannot drive succession.
- `continue_observation` — the calibrated persistence rule is not met.
- `prepare_handoff` — the current checkpoint is signaled, but persistence is not yet met.
- `insufficient_evidence` — signatures may be valid, but support or measurement completeness is inadequate.
- `succession_candidate` — the calibrated persistence rule is met; receiver review and a verified handoff are required.

No output authorizes automatic retirement. The assessment deliberately says `automatic_retirement_authorized: false` and `receiver_approval_required: true`.

Assessment also requires the receiver's pinned policy public key. A self-consistent signature without a trusted key does not authenticate who issued the policy.

## Handoff boundary

Before source retirement, the fresh runtime should verify a handoff bound to at least:

- `run_id`;
- `parent_hash`;
- `generation_index`;
- objective and constraints;
- unresolved work;
- evidence hashes;
- the calibration policy hash.

The existing Endurance Gate recovery experiment tests those continuity and freshness concepts in a synthetic world. The succession assessment names the required bindings but does not claim to be a universal production orchestrator or to undo side effects already executed.

## Hostile controls

Run:

```bash
PYTHONPATH=/path/to/cole-portable-core python scripts/succession_selftest.py
```

The self-test checks:

- full COLE recomputation;
- run-binding tamper rejection;
- hostile JSON nesting rejection before artifact evaluation;
- the 500-sample activation floor;
- grouped held-out recovery of a constructed persistence mechanism;
- single-spike refusal;
- repeated-signal candidate behavior;
- automatic-retirement prohibition;
- handoff-before-retirement ordering;
- signed-but-unsupported evidence refusal;
- separate UCR reporting;
- cross-run history refusal;
- signed-policy tamper rejection.

Its labels are deliberately constructed, so its perfect held-out result is a mechanism test, not evidence that the policy works on a deployed agent.

## Falsifier

The practical falsifier is simple:

> On untouched, receiver-scored paired runs, the calibrated policy does not identify checkpoints where a verified successor improves outcomes at an acceptable false-positive cost.

If that happens, keep the policy observation-only, revise the signal or label process under a new version, and collect a new untouched corpus. Do not solve a failed result by lowering the evidence gate after seeing the holdout.
