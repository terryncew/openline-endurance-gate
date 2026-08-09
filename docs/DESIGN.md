# Design

The benchmark answers one question: **does the candidate improve on the current agent without violating the receiver's declared floor?**

The receiver defines integer-valued metrics before execution. Each metric declares whether higher or lower is better, how much regression is allowed, and how much improvement is large enough to count.

For a candidate to be recommended:

- both reports must be determinate;
- the candidate report must pass;
- the candidate must have no critical failure;
- every required metric must stay within its allowed regression;
- at least one metric must meet its minimum improvement.

This prevents “newer” from being treated as “better.” The benchmark also keeps the recommendation separate from execution so stale comparison evidence cannot by itself replace a newer incumbent.
