# Recovery Intervention Methodology

## Existing substrate

Recovery wraps the existing `world.py` requirement/configuration system and its perturbation generator. It calls the existing `damage.py` implementation only for a secondary diagnostic and adapts cycle observations to the existing `fractography.py` analysis. It does not introduce a second simulator or use damage to generate outcomes.

Each condition receives the same event identity, amplitude, target, truth delta, ambiguity, token cost, and correction draw. The mode changes only what happens at cycle 80. A hidden evaluator retains ground truth; runtime state contains beliefs, derived configuration, known dependency edges, open tasks, policy constraints, required prior decisions/outcome references, and relevant/irrelevant history.

## Handoffs

Full history serializes both relevant and irrelevant history. The compact payload contains six believed requirements, open tasks, policy constraints, recent required decisions/outcomes, and known dependency edges. Irrelevant history is dropped.

The unsigned envelope computes `SHA-256(canonical_json(payload))`. Its payload contains the same `run_id`, `parent_hash`, and `generation_index` fields as OLP, and its verifier compares them with the same session state. It still makes no origin or completeness claim: an attacker may rewrite the fields and recompute the unkeyed checksum.

The v0.9.1 OLP envelope contains eight receipts. Each records `claim`, `action`, `evidence_hashes`, `result`, `tokens_used`, `timestamp`, `witness`, and `next_use_note`; `receipt_parent_hash` chains receipts inside one envelope. `run_id`, packet-level `parent_hash`, and `generation_index` live inside the signed body and every receipt. The verifier independently checks signature, receipt order/hash chain, evidence hashes, required-field coverage, and the verifier session.

## Rejected versus undecidable

A run, parent, or generation mismatch is definitive evidence that the packet is not current, so it is `rejected`. A correctly signed packet can still omit required state; integrity is valid but policy completeness is unsupported, so it is `undecidable`. Neither outcome restores state. Verification returns a proposed session update but never mutates the session; the caller applies it only after `accepted`.

Experiment fixture keys are deterministically derived to make byte-level semantic recomputation possible and are never persisted. They are not an operational key-management recommendation.

## Evidence and recomputation

Cycle observations are deterministic gzip shards with a fixed header and timestamp. Run rows and handoff semantics have independent Merkle roots. Raw timing observations are locally hash-bound but excluded when fresh runs are compared, because CPU and wall time legitimately vary.

The semantic verifier regenerates every shard from the frozen seed partition, compares deterministic gzip bytes, run metrics, and timing-stripped handoff observations, recomputes global roots and the summary, then checks the outer manifest, receipt chain, and release attestation.

## Interpretation

The intervention tests controlled state carriage and refusal behavior. It does not test deployed agents, cognition, coherence recovery, or physical fatigue. Equal clean behavior between checksum and OLP is a design requirement. OLP’s Pass-2 work is isolated by rewriting identical unsigned freshness fields and recomputing their checksum: checksum acceptance and OLP rejection are both required observations.
