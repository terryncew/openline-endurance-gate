# Methodology

## Question

Can individually subcritical requirement changes accumulate history-dependent failure across agent handoffs, and does a fitted cumulative damage variable predict failure beyond current-state observables?

The synthetic world is a mechanism test, not evidence that deployed models possess literal material fatigue.

## Hidden ground truth and invariants

The toy repository has six latent requirement variables. A deterministic solver maps them into twelve configuration fields. Twelve immutable tests define the consistency and safety boundary.

The simulated assembly carries an estimated requirement state, a configuration, known causal edges, unresolved notes, and a handoff representation. Only `fresh_ground_truth` receives canonical state directly each cycle.

## Matched load schedules

Each seed generates one multiset of seven low, six medium, and seven high events. Every event has a fixed id, target, sign, ambiguity draw, correction draw, and token cost. The four schedules reorder those exact events.

Requirement deltas are additive, so all schedules reach the same final ground truth.

### Common random numbers

v0.2.0 binds application, correction, compression, reference, and checkpoint random draws to event identity or checkpoint position. The schedule label is excluded from those keys.

For a given event and mode, the latent uniform draw is therefore identical across schedules. Different outcomes can arise only because the preceding state changes the decision threshold or because the event occurs at a different point in the history.

This corrects a confound in v0.1.0, where schedule labels generated independent random draws.

## Matched amplitude sweep

The low, medium, and high amplitude conditions share event ids, targets, signs, and latent random draws at each cycle. Amplitude alone changes delta magnitude, ambiguity transformation, correction threshold, and token cost.

This replaces the earlier sweep, which generated a different random event set for each amplitude.

## Failure and censoring

First failure occurs when either:

- a consequential configuration error produces an unsafe action attempt; or
- a five-cycle checkpoint falls below 11 correct fields out of 12.

Runs continue after first failure so later state remains observable. Hazard models use only at-risk cycles. A run with no failure by cycle 20 is recorded as `N_f = 21` and treated as right-censored at the fixed horizon in survival summaries.

## Coherence observables

For each cycle the harness records `kappa`, `phi_star`, `VKD`, `epsilon`, and `delta_hol`, plus operational state such as context pressure, unresolved dependencies, retry count, handoff loss, token representation size, and cycle index.

The simulator does not read `D`, `m`, `beta`, `lambda`, `mu`, or `tau_r` while generating outcomes.

## Damage fitting

The declared parameter grid lives in `experiment.json` before the run.

- Four seeds fit candidate one-variable hazard models.
- Two validation seeds select the candidate with minimum log loss.
- Twenty held-out seeds evaluate final models.

The fit report includes the ten best candidates, the number of near-ties, grid-boundary hits, saturation behavior, and an identifiability warning. A selected coefficient is called simulation-calibrated, never universal.

## Prediction witnesses

The held-out comparison includes:

```text
cycle only
current Coherence Dynamics observables
CD + cycle
operational state
operational state + cycle
CD + D
operational state + D
operational state + cycle + D
```

The original gate asks whether `D` improves over current CD. The stronger robustness witness asks whether it still improves over cycle plus operational state.

## Sequence test

The primary contrast is paired `N_f(low_to_high) - N_f(high_to_low)` within held-out seed and handoff mode.

Pre-registered requirements:

```text
80 paired differences
absolute median effect >= 2 cycles
exact two-sided sign-flip p <= 0.10
```

The sign-flip distribution is computed exactly by dynamic programming for integer cycle differences. No pair is discarded. Confidence intervals use deterministic percentile bootstrap resampling.

All other schedule contrasts are exploratory and receive Holm adjustment.

## Fractography witness

A cycle's crack load is the observed burden of unresolved dependencies, invariant failures, newly added contradictions, and unsafe attempts. Co-occurring nodes form an undirected diagnostic graph.

The analyzer reports crack origin, peak, burden, unresolved span, repair half-life, and the largest connected cluster. These measurements describe the synthetic trace surface. They do not establish a physical crack mechanism.

## Integrity

`PREREGISTRATION.json` binds the experiment configuration and mechanism files before results are generated. Raw cycle rows are committed by Merkle roots. A signed receipt chain binds run summaries and evidence artifacts. The semantic verifier recomputes all consequential claims from raw cycle files.

The local anchor cannot defend against an attacker replacing the entire repository and generating a new keypair. External publication of the compact witness digest is the next trust boundary.

## Execution tip-capture extension

The graph extension reuses the endurance dependency substrate. Each disturbance creates or attaches to an unresolved dependency node. The attachment conditions are `uniform_null`, `even_spread`, and `diffusive_tip_capture`. The diffusive treatment chooses an active tip and may penetrate inward stochastically; the exposure score reported for analysis is computed separately and is never used by the selector. `even_spread` chooses the least directly captured node inside the smallest branch. Because low-capture nodes in this graph are frequently leaves, that rule has an unintended tip-selection bias and its large frontier lift is treated as a disclosed design artifact rather than a supporting gate.

Every attachment condition and policy receives packet-bound common random numbers. The five policies are no intervention, logging only, random repair, oldest-first repair, and tip-targeted repair. Random and tip-targeted policies receive identical repair opportunities and budgets. Logging records ancestry without changing the graph.

The release design uses 96 fresh seeds: 8 train, 8 validation, and 80 held out. A prior 96-seed pilot is retained in `TIP_CAPTURE_PILOT_LOG.json` and excluded because a proposed burial-depth recovery-cost gate was partly definitional: successful pointer traversal mechanically scales with path depth. The gate was removed before the fresh release seeds ran; mechanisms and remaining thresholds stayed frozen.

The primary graph witnesses are frontier capture concentration, held-out Geometry Lift beyond count/age baselines, null specificity, equal-budget repair yield, and receipt-ancestry root recovery. Burial depth, shielding, branch concentration, and oldest-first behavior remain descriptive unless named in a gate.

Receipts preserve ancestry and visible pointers. They do not directly close defects. Any outcome change requires a gate, rollback, quarantine, or repair policy that actually consults the receipt structure.

## Graph evidence binding

The full verifier regenerates graph cycles, candidate rows, recovery probes, held-out models, gate summaries, and design witnesses. Stored graph CSVs are streamed into canonical row Merkle roots before regeneration, avoiding simultaneous retention of stored and fresh graph objects. The comparison remains exact at the canonical row level.

## v0.3.1 reporting correction

The scientific run is unchanged. Paired repair-yield effects are reported in violations prevented per successful repair, violation contrasts in violation counts, and ancestry recovery effects in recovery-rate points. Reports now separate the majority direction from consistency in the preregistered positive direction. Tied pairs remain explicit and are excluded from both nonzero-direction consistency denominators.
