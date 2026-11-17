# ADR 0002: Near-miss citations go to review

* Status: accepted
* Date: 2026-11-17

## Context

The citation check proves that an id exists and was in force. It cannot tell that the id is the one the model meant. The 0.1.1 benchmark showed the gap: all six answers that cite a real id in force instead of its twin (`ACT-012` for `ACT-021` and the like) were published.

The obvious fix, "flag ids that are close to another id in the registry", has a trap. Registries are usually numbered consecutively. In the benchmark registry every one of the 24 norms in force has between 5 and 11 neighbours at edit distance one (`ACT-001` has `ACT-002` to `ACT-009`). A rule that fires on distance one alone would send all 30 clean answers to review and be switched off within a day.

## Decision

Add an optional rule, `NearMissRule`, backed by `find_near_misses`. It is on in `PublicationGate.default` (switch it off with `near_miss=False`) and its finding is `review`, never `reject`: the id might be right.

A cited id is a near miss when another norm **in force on the same date** is one slip away and the output does not cite that norm too. Two kinds of slip are judged differently:

* **Swap of two adjacent characters** (`ACT-012` and `ACT-021`): always reported. Consecutive numbering produces ids that differ in one digit; it does not produce ids that differ by a swap, so a swap twin is a real signal even in a dense registry.
* **Edit** (one character replaced, inserted or deleted): reported only if the cited id has at most two such neighbours (`max_edit_neighbours`, default 2). Few neighbours mean a close pair is unusual and more likely a slip; many neighbours mean numbering.

Ids shorter than four characters are skipped (one edit changes a quarter of the string or more), and unknown, malformed and out-of-force citations are left to the citation check.

## Consequences

Measured on the synthetic benchmark (same 206 cases, same labels as 0.1.1):

* All 6 near-miss cases are now held for review.
* 15 clean answers are held for review too: their citation (`ACT-001`, `ACT-002`, `ACT-010`, `ACT-012`, `ACT-020` or `ACT-021`) has a swap twin, and 6 of the 24 ids in force have one. Clean cases blocked went from 4 of 50 to 19 of 50.
* Part of that cost cannot be avoided by any rule that reads only the citations. The dataset contains identical citations twice with opposite labels (c001 and c085, c022 and c089, c026 and c088). The gate has to hold both or neither.
* Slips inside dense numbering (`ACT-012` written for `ACT-013`) are still not detected. That is the price of not flagging every answer.

What this means for users:

* The false alarm rate is roughly the share of your ids that have a swap twin, times how many ids an answer cites. With ids like `ACT-001` to `ACT-040` that share is high; with ids like `HLA-1` to `HLA-5` or `2019/0412` it is close to zero. Count your twins before you rely on the default, and use `near_miss=False` if the rule is too noisy.
* Review is the right verdict: the rule asks a person to compare two ids, which is cheap, and it never blocks a correct answer for good.

## Alternatives considered

### Plain edit distance of one

Rejected: it flags everything in a consecutively numbered registry (see Context).

### Suppress the finding when the second model cites the same id

Tempting, because two models rarely make the same typo. Rejected: it makes agreement a reason to publish, which [ADR 0001](0001-deterministic-gates-over-llm-as-judge.md) rules out, and correlated models do repeat each other's mistakes (the benchmark second opinions do exactly that). The opposite signal is already used: if the second model cites the neighbour instead, the agreement rule can see the low citation overlap and send the answer to review.

### Reject instead of review

Rejected: the cited id is real and in force. Only a person can say which one was meant.

### Similarity by embeddings or phonetics

Rejected: it needs a model, is not deterministic and cannot be tested the way a string comparison can.

### Switch off automatically in crowded registries

A registry-wide measure (the share of ids with a swap twin) could turn the rule off when it would be noisy. Left out for now: the threshold is arbitrary and an automatic switch hides behaviour from the user. The share is easy to compute from the registry, and the rule is a single line to leave out.

## Reproduce

```
python benchmarks/run.py   # the "0.1.1 vs 0.2.0" section lists every case whose decision changed
```
