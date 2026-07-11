# OpenLine Endurance Gate

**Digital fractography for AI-agent handoffs, built to lose honestly.**

This repository now runs two synthetic mechanism tests on the same dependency substrate.

The endurance test asks whether individually subcritical changes can consume residual coherence capacity across handoffs, and whether reordering the same event multiset changes cycles-to-first-failure. The proposed damage variable `D` is an observer. It never generates failure. Its parameters begin unfit, are selected on declared training and validation seeds, and are judged on untouched held-out seeds.

The execution tip-capture test asks whether the shape of an unresolved dependency frontier predicts where later disturbances attach, whether that geometry adds information beyond ordinary counts and age, and whether equal-budget tip-targeted repair beats random repair. The diffusive attachment treatment deliberately contains stochastic tip capture; `uniform_null` is a genuine no-geometry specificity control.

## v0.3.1: Reporting-Corrected Powered Endurance + Execution Tip Capture

The endurance design retains the powered v0.2.0 experiment:

```text
12 immutable invariants
4 handoff modes
4 load schedules
26 seeds: 4 train, 2 validation, 20 held out
20 cycles per primary run
= 8,320 primary observations

3 matched constant-amplitude conditions
4 handoff modes
26 seeds
20 cycles
= 6,240 amplitude observations

Primary order contrast
20 held-out seeds × 4 modes
= 80 paired differences
```

The graph extension is frozen before its release run:

```text
3 attachment conditions
5 equal-interface repair/logging policies
96 fresh seeds: 8 train, 8 validation, 80 held out
48 cycles per run
= 1,440 graph runs
= 69,120 graph-cycle observations
```

The first 96-seed graph run is retained in `TIP_CAPTURE_PILOT_LOG.json` and excluded from the release analysis because it exposed a partly tautological burial-depth gate. That gate was retired before the fresh seed set ran. Simulator constants, attachment mechanics, repair mechanics, model features, thresholds, and the remaining gates stayed frozen.

## Current bound result

The release result is **mixed: 7 of 10 pre-registered gates passed**.

The endurance test passed fresh subcritical calibration, the matched amplitude gradient, held-out prediction from fitted `D`, and receipt-handoff advantage. Load-order noncommutativity did not pass.

The tip-capture test passed geometry lift over count/age baselines, null specificity, and receipt-ancestry root recovery. Frontier concentration missed its material threshold, and tip-targeted repair did not beat equal-budget random repair. Across the 80 held-out repair pairs, 30 favored random repair, 14 favored tip-targeted repair, and 36 tied. v0.3.1 reports the majority direction explicitly and labels repair-yield and recovery-rate effects in their actual units.

That is the intended behavior of the instrument. A failed gate remains a failed gate.

## Four handoff mechanisms

All endurance modes receive the same perturbation packets and a 256-token representation ceiling.

- `fresh_ground_truth` reconstructs canonical state each cycle and acts as the one-shot control.
- `persistent_history` preserves raw history until the budget clips older causal events.
- `prose_summary` compresses broad state and can omit dependencies or distort a value.
- `receipt_ancestry` preserves referenced dependency structure, while stale or missing references remain real failure paths.

Receipt ancestry can lose. A valid signature can preserve a wrong action perfectly.

## Attachment and repair boundary

The attachment selector and the reported exposure metric are separate code paths.

- `uniform_null` selects uniformly among active unresolved nodes.
- `even_spread` chooses the least directly captured node inside the smallest active branch. In this synthetic graph, that creates an unintended leaf/tip bias; its unusually high frontier lift is a design artifact, not evidence for the diffusive hypothesis.
- `diffusive_tip_capture` selects an active tip and may stochastically penetrate inward.

Every policy receives the same packet stream and repair opportunities. `random_repair` and `tip_targeted` spend the same repair budget. Logging-only is mechanically checked to leave graph dynamics unchanged.

Receipts do not repair anything by themselves. In this harness they preserve ancestry and visible pointers. A gate or repair policy must consult that structure to change outcomes.

## Ten pre-registered gates

Endurance:

1. Fresh isolated perturbations clear the 95% subcritical floor.
2. Matched low-amplitude packets outlast high-amplitude packets.
3. Low→high and high→low schedules differ materially under common random numbers.
4. Fitted `D` adds held-out prediction over current Coherence Dynamics observables.
5. Receipt ancestry extends median fatigue life over equal-token prose summaries without exceeding the checkpoint-accuracy tolerance.

Execution tip capture:

1. Diffusive attachment materially concentrates capture at exposed frontier nodes beyond the null.
2. Geometry adds held-out prediction over event count, context length, unresolved count, retries, node age, and branch age.
3. The uniform null shows no material geometry lift.
4. Equal-budget tip-targeted repair beats random repair.
5. Receipt ancestry improves recovery of buried initiating causes.

## Statistical boundary

The endurance sequence test uses all 80 pairs. The graph repair contrast uses 80 untouched held-out seeds. Exact sign-flip tests, deterministic bootstrap intervals, effect sizes, and declared material thresholds are reported.

A failed gate can mean either a materially excluded effect or an unresolved interval. The report preserves that distinction. Synthetic passage does not establish that deployed agents obey material fatigue, fracture mechanics, or DLA.

## Evidence integrity

The full verifier checks:

```text
pre-registration and mechanism hashes
Ed25519 signatures and parent continuity
anchored receipt count, tail, and chain digest
manifest and evidence-bundle hashes
run metrics recomputed from raw cycles
fresh calibration and damage-parameter reselection
D-series and held-out model-comparison recomputation
bootstrap and sign-flip summaries
fractography and tip-capture recomputation
canonical cycle/candidate/probe Merkle roots
public witness digest
retired pilot disclosure binding
```

Large graph CSVs are streamed into canonical Merkle roots before regeneration, keeping verifier memory bounded without replacing semantic recomputation with trust in stored summaries.

The mandatory tamper suite tests tail deletion, a resealed summary forgery, a resealed raw `damage_D` forgery, and source drift. Each hostile semantic attack runs in a fresh process so verifier memory is released between witnesses. Metric forgeries remain detectable even when an attacker updates artifact hashes, replaces the local keypair, and resigns the chain.

The local public key and witness are self-declared. A full-write attacker can replace the entire repository and create a new internally consistent history. Publish `results/public_witness.json` or its digest outside the repository to make that replacement detectable.

## Run

```bash
python -m pip install -e .
python -m pytest -q
openline-endurance run --root .
openline-endurance verify --root . --source-root .
python scripts/tamper_check.py
python scripts/release_check.py
openline-endurance witness --root .
openline-endurance fracture --root .
openline-endurance tip-capture --root .
```

## Main artifacts

```text
PREREGISTRATION.json
TIP_CAPTURE_PILOT_LOG.json
experiment.json
results/cycles.csv
results/amplitude_cycles.csv
results/tip_capture_cycles.csv
results/tip_capture_candidates.csv
results/tip_capture_probes.csv
results/damage_fit.json
results/model_comparison.json
results/fractography_summary.json
results/tip_capture_summary.json
results/heldout_witness.json
results/cycle_roots.json
results/public_witness.json
results/summary.json
receipts/experiment.jsonl
receipts/experiment.anchor.json
MANIFEST.json
TAMPER_REPORT.json
RUN_REPORT.json
```

The signing private key is generated in memory and never written into the repository.

**Unrepaired errors grow at the edge while their causes disappear into the interior. A receipt preserves the path back.**
