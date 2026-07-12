# Methodology

## Question

Do pruning, instance retirement, telemetry-triggered restoration, or ECC-style correction add endurance beyond a verified inheritance capsule?

## Matched modes

Each of 96 declared seeds runs the same 320-event packet with mode excluded from every event-bound random draw. Eight seeds are training, eight validation, and 80 held out.

1. `capsule_baseline` uses the inherited verified capsule every 20 cycles.
2. `scheduled_prune_80` prunes active state every 80 cycles.
3. `fixed_retirement_85` starts a fresh instance every 85 cycles and reconstructs state from verified records.
4. `telemetry_breaker` restores when the synthetic noise or margin trigger crosses its frozen threshold.
5. `ecc_digest` checks state every 10 cycles and attempts one graph-prioritized correction.
6. `restoration_stack` combines adaptive restoration and ECC.
7. `sham_retirement_85` follows the same restart schedule while preserving defects and noise.

The pressure-disabled null repeats baseline and stack with context pressure removed and exogenous noise reduced.

## Frozen design

- horizons: 160 and 320 cycles;
- generation boundary: every 20 cycles;
- scheduled pruning: every 80 cycles;
- fixed retirement: every 85 cycles;
- ECC interval: every 10 cycles;
- adaptive trigger begins after cycle 40;
- epsilon trigger: 0.63;
- margin trigger: 0.16;
- restoration cooldown: 30 cycles;
- held-out seeds: 8117–8196;
- material median-life gain: 4 cycles for pruning/fixed retirement and 2 cycles for adaptive/ECC comparisons;
- significance ceiling: 0.10;
- minimum survival for absolute horizon gates: 0.50.

All mechanisms, thresholds, gates, and seeds were frozen before the held-out block opened. `STATE_RESTORATION_PILOT_LOG.json` preserves the excluded pilot and validation history.

## Failure endpoint

A transient action error is not automatically permanent failure. A run fails when the system crosses the declared invariant, configuration-accuracy, omission, or negative-margin hazard rule. Restoration can quarantine invalid records and reconstruct requirement state from the signed ledger.

## Anti-rigging controls

The sham restart asks whether a fresh process wins while inheriting the same defects. The pressure-disabled null asks whether the stack receives an automatic advantage after the modeled pressure mechanism is removed. Both can fail.

## Gates

The nine preregistered gates test:

- pruning versus capsule baseline;
- fixed retirement versus baseline;
- telemetry breaker versus fixed retirement;
- ECC versus baseline;
- absolute stack survival through 160;
- absolute stack survival through 320;
- checkpoint-accuracy preservation;
- sham-restart specificity;
- pressure-disabled null specificity.

Absolute horizon gates and paired relative-effect gates are separate. Passing 320 does not silently convert a zero paired median into a material relative win.

## Evidence and verification

The release stores 276,480 cycle rows in eight deterministic gzip shards, plus 864 run summaries. Sharding is evidence plumbing only: shards split at fixed 12-seed boundaries, lexical decompression preserves the original seed/mode/cycle order, and their raw canonical Merkle leaves are combined before global reduction.

The semantic verifier can run as eight bounded independent phases. Each phase regenerates its cycle shard byte-for-byte and compares its run metrics. The finalizer combines all fresh leaves, recomputes the global cycle and run roots, all nine gates, the design witness, the public witness, the signed experiment chain, and the pinned v0.6 lineage.

The post-open sharding amendment is recorded in `PREREGISTRATION.json`. `experiment.json` and `state_restoration.py` remained byte-frozen after the held-out seeds opened.
