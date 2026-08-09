# Claim boundary

This repository verifies the mechanics of a receiver-defined incumbent-versus-candidate comparison.

A completed case can establish that:

- comparison inputs were hash-bound in the retained registration;
- each submitted arm matched its registered version binding;
- checker packages contained the declared evidence files and hashes;
- checker reports verified under the registered Ed25519 public key;
- the stored recommendation matches the declared metric rules.

It does not establish that the checker was independent or correct, that evidence omitted by every supplied record did not exist, that registration had a particular public timestamp, that the candidate is universally better, or that a replacement may execute.

Synthetic tests in this repository validate protocol behavior only. They are not deployed-agent performance evidence.
