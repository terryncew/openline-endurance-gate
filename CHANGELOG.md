# Changelog

## 0.9.1

- Preserves the complete v0.9.0 Pass-1 release byte-for-byte in `lineage/v0.9.0`.
- Gives both compact tracks identical `run_id`, `parent_hash`, and `generation_index` fields while signing them only in OLP.
- Adds pure verifier-session checks for expected run, accepted parent, and advancing generation; callers apply proposed state only after acceptance.
- Adds stale replay, cross-run copy, isolated generation rollback, and same-packet replay controls, plus a supporting correctly signed omission check.
- Uses fresh training seeds 9201–9208, validation seeds 9217–9224, and 80 held-out seeds 9225–9304; no v0.9.0 recovery seed is reused.
- Expands the recovery gate set from seven to eight and the isolated top-level hostile suite from 15 to 19 attacks.

## 0.9.0

- Adds the preregistered Recovery Intervention Pass 1 at cycle 80 over a 320-cycle horizon.
- Adds five conditions, including a fair unsigned-minimal SHA-256 comparator and an eight-receipt Ed25519 OLP handoff.
- Adds sharded generation, timing-aware semantic recomputation, five fail-closed hostile controls, recovery documentation, a module release gate, and v0.8.1 lineage pinning.
- Explicitly defers stateful replay/freshness binding and its three controls to v0.9.1 with fresh seeds.

## 0.8.1

- Preserved the original v0.8.0 mixed 3/4 result byte-for-byte in `lineage/v0.8.0`.
- Fixed the discovered schedule-phase confound: ordinary-work scratch context is now released after each completed task while token work and repair opportunities remain intact.
- Kept all four gates and thresholds unchanged.
- Used fresh pilot seeds 8201-8208, validation seeds 8217-8224, and 80 untouched held-out seeds 8225-8304.
- Added mode-specific null reporting so pooled results cannot hide architecture-specific timing effects.
- Held-out result: 4/4 gates passed. Slow delivery gained 4.5792 disturbances; recovery windows gained 4.0583; the rate-disabled null was +0.0417 overall.
- Added pinned v0.8.0 lineage verification and a second signed load-rate replication receipt.
- Bumped the package and CLI version to 0.8.1.

## 0.8.0

- Added the separately preregistered **Same Disturbance, Different Speed** experiment.
- Matched disturbance identity, order, total load, ordinary work, horizon, common random draws, and active-context budget across four schedules.
- Required recovery windows to contain ordinary task execution rather than empty turns.
- Made disturbances survived before critical failure the primary endpoint; failure tick and synthetic damage remain secondary.
- Added a rate-disabled null world and four explicit falsification gates.
- Held-out result: 3/4 gates passed. Slow delivery survived 3.2583 more disturbances on average and recovery windows gained 2.45, but the rate-disabled null failed at -0.2583 and continuous history moved in the opposite direction.
- Preserved the null failure; no parameter, threshold, seed, or gate was tuned after opening held-out data.
- Compared continuous history, ordinary summary reset, and verified inheritance capsule without adding an intervention arm.
- Preserved v0.7 evidence through `V070_LINEAGE.json`.
- Added deterministic compressed cycle evidence, independent semantic recomputation, and a resealed load-rate-cycle forgery attack.
- Bumped the package and CLI version to 0.8.0.

## 0.7.0

Adds an exploratory state-restoration extension without changing inherited v0.6 scientific evidence.

- Separates pruning, fixed retirement, adaptive telemetry-triggered restoration, ECC-style correction, a combined stack, and a sham restart.
- Runs 160/320 horizons over 80 untouched held-out seeds with event-bound common random draws.
- Declares epsilon, coherence margin, and stability values as synthetic trigger proxies rather than measured physical variables.
- Adds a pressure-disabled null and a same-defect sham restart.
- Records a post-open execution-plumbing amendment after the hosted runner exposed a per-process CPU ceiling; no mechanism, threshold, gate, seed, or analysis changed.
- Stores all 276,480 cycle observations in eight deterministic gzip shards and verifies them through phased semantic recomputation.
- Fixes the documented release-order deadlock: standalone hostile tests now write an unattested report, and release preflight can rebuild a stale detached attestation.
- Adds a resealed compressed state-restoration forgery attack.

Scientific result: 5/9 gates passed. The stack cleared the absolute 160- and 320-cycle gates and preserved accuracy. Every individual material median-life intervention gate failed. Sham restart and the one-sided pressure-disabled null passed.

## 0.6.0

Adds the exploratory generational-endurance experiment without changing inherited v0.5 scientific artifacts.

- Compares continuous history, equal-budget prose summary reset, verified inheritance capsule, and capsule plus conflict-aware scheduling.
- Uses 20-cycle generations and a preregistered 40/80/160 doubling ladder.
- Adds an external raw-record and hash-reference capsule mechanism with quarantine on invalid inheritance.
- Adds a pressure-disabled null world to detect a simulator that grants capsules an automatic advantage.
- Uses 8 training, 8 validation, and 80 untouched held-out seeds.
- Discloses all retired pilot blocks in `GENERATIONAL_PILOT_LOG.json`.
- Adds independent semantic recomputation of 92,160 cycle rows and 576 run rows.
- Adds a resealed generational-cycle forgery attack.
- Adds a detached signed release receipt for `RUN_REPORT.json` and `TAMPER_REPORT.json`, plus a hostile report-mutation test.
- Clarifies that the pressure-disabled control forbids a positive automatic capsule advantage; it is not a two-sided equivalence gate. No scientific metric, threshold, seed, or pass/fail result changed.

Scientific result: 5/7 exploratory generational gates passed. The capsule cleared 40 and 80 cycles, failed 160, beat ordinary summary reset, and received no measurable endurance gain from conflict-aware scheduling.

## 0.5.0

Added matched clustered, random-sparse, Ulam-spaced, and conflict-aware scheduling. Ulam failed; graph-informed spacing passed. Result preserved through `V050_LINEAGE.json`.

## 0.4.0

Powered load-order and first-contact tip-capture study. Result preserved inside the v0.5 lineage snapshot.
