# Methodology

## Question

Does disturbance delivery rate change critical-failure life when total disturbance, ordinary work, and retained context at the same disturbance index are held fixed?

## Matched design

Every schedule receives the same 20 disturbances in the same order, with identical amplitudes, targets, truth changes, event-bound random draws, 160-tick horizon, 140 ordinary-work ticks, and 1,200-token active-context ceiling.

Only disturbance positions differ: slow drip, steady load, sudden burst, and burst with ordinary-work recovery windows.

Ordinary work consumes tokens and can repair unresolved state in the rate-sensitive world. Its task-local scratch context is released after completion. Receipt-worthy disturbances remain persistent. Therefore the kth disturbance encounters the same retained-context growth profile across schedules.

## Primary endpoint

The primary endpoint is disturbances survived before first critical failure. Failure tick, checkpoint accuracy, critical omissions, active-context use, peak rate, and synthetic damage remain separate receipts.

Synthetic damage is descriptive and does not decide the main gate.

## Null world

The rate-disabled null removes rolling-rate difficulty and ordinary repair. With ordinary task scratch context also released, the schedules share the same persistent state at each disturbance index. Any material slow-versus-burst difference rejects specificity.

## Gates

1. Slow delivery survives at least one additional disturbance on average relative to sudden burst, with a positive bootstrap lower bound and sign-flip `p <= 0.10`.
2. The positive direction appears in at least two of three state modes.
3. Burst schedules separated by ordinary work survive at least 0.5 additional disturbances relative to one continuous burst.
4. The rate-disabled null remains within 0.25 mean disturbance and its confidence interval includes zero.

The correction, thresholds, schedules, and fresh held-out seeds 8225-8304 were sealed after pilot 8201-8208 and validation 8217-8224.

## Outputs

- `results/load_rate_cycles.part-000.csv.gz` through `part-011` — every tick in deterministic eight-seed shards;
- `results/load_rate_runs.csv` — one record per seed, world, mode, and schedule;
- `results/load_rate_summary.json` and `.md` — held-out effects and gates;
- `results/load_rate_design_witness.json` — matching declarations;
- `LOAD_RATE_PILOT_LOG.json` — confound diagnosis, pilot, and validation disclosure;
- `V080_LINEAGE.json` and `lineage/v0.8.0/` — pinned original mixed result.

## Semantic verification

The verifier independently regenerates every v0.8.1 cycle and run, reproduces deterministic gzip bytes, recomputes canonical Merkle roots and all gates, and reconstructs the integrated witness. Patching hashes and replacing the local signing key cannot make altered rows pass semantic recomputation.
