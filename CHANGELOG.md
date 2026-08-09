# Changelog

## 0.13.0rc2

- Makes the release safe to apply over an older checkout. CI removes files that are not present in the sealed release manifest before installation or test collection.
- Retains the old `succession.yml` filename as a manual-only placeholder so the retired workflow cannot run on push.
- Restricts pytest discovery to the maintained successor-benchmark test module, preventing retired tests from being collected in an overlayed checkout.
- Keeps release verification strict after normalization: any remaining unmanifested file still fails closure.

## 0.13.0rc1

- Replaces the metric-based succession path with a direct incumbent-versus-candidate benchmark.
- Requires case registration before either arm is submitted.
- Binds the exact task, constraints, budget, evaluation policy, repository state, incumbent version, candidate version, checker key, case order, and blinding nonce hash.
- Gives the checker one lane at a time; the checker package contains no incumbent/candidate role field and no peer-arm data.
- Requires signed checker reports whose cited evidence is present and hash-verified.
- Promotes a candidate only when it has a determinate passing report, no critical failures, no disallowed regression on required metrics, and at least one declared minimum improvement.
- Emits a recommendation only. It does not execute a model swap or authorize a protected action.
- Moves the pre-0.13 research program out of the maintained product path. Historical artifacts remain in Git history.
