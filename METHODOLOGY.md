# Method

Each case has four stages.

**Register.** Before either arm is submitted, record hashes for the task, constraints, budget, evaluation policy, repository state, both version identities, checker key, case order, and blinding nonce.

**Prepare.** After both arms finish, verify those fixed inputs and version bindings. Copy only indexed evidence into two separate checker packages and commit both package hashes before checker reports exist.

**Check.** The checker receives one opaque lane package at a time. It returns a signed status, the exact registered integer metrics, cited evidence IDs, and reason codes.

**Compare.** Verify both reports and independently recompute the result. A candidate is recommended only when it passes, has no critical failure, remains within every required metric floor, and shows at least one pre-declared material improvement.

The final artifact includes a complete file manifest and an independent verification report. The recommendation never authorizes execution.
