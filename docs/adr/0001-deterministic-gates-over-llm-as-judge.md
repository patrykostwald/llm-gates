# ADR 0001: Deterministic gates over LLM-as-judge

* Status: accepted
* Date: 2026-11-17

## Context

Applications that publish language-model output (legal analysis, news summaries, support answers) need a last line of defence between the model and the reader. The model can return well-formed JSON that cites a repealed statute, invents a source or leaks an e-mail address.

Two common answers to "how do we check the output" are to ask another model to grade it, or to run two models and trust them when they agree. Both are cheap to build and both fail in ways that are hard to see.

## Decision

`llm-gates` checks model output with deterministic code. A gate is a list of rules; each rule is a plain function of the output, the date and optionally a second output. The gate returns `publish`, `review` or `reject` together with the findings that caused it. No rule calls a model or the network.

A second model's output is used only through a deterministic comparison (same conclusion, citation overlap, confidence gap), and only ever to route output to a human, never to approve it on its own.

## Consequences

* The same input gives the same decision on every run. Gates can be unit-tested, replayed against logged outputs and audited line by line.
* Every refusal has a reason with a path or an id in it. Reviewers see why something was held back.
* The checks are narrow. They prove that a citation exists and was in force, not that it supports the claim; they cannot judge tone, nuance or truth beyond what a registry encodes. Humans or domain tooling stay responsible for that.
* The registry of trusted facts (norms, sources) becomes part of the system and must be maintained.
* No runtime cost per check, no API keys, no vendor lock-in; the library has no dependencies.

## Alternatives considered

### LLM-as-judge

A second model grades the first. Rejected as the deciding mechanism because:

* it is non-deterministic, so a decision cannot be reproduced or tested;
* the judge shares failure modes with the author (plausible but false claims look plausible to it too) and can be talked into approval by confident wording;
* it cannot reliably tell that an article id does not exist or expired last month, which a registry lookup answers exactly;
* it adds cost and latency to every check and a second place for prompt injection to land.

A judge model can still be useful to rank or summarise what the gate holds for review. It should not release anything.

### Agreement between models alone

Run two models from different providers and publish when they agree. Rejected as sufficient because agreement measures similarity, not accuracy. Models trained on overlapping data make correlated mistakes, and a shared misleading prompt makes them wrong in the same way. Agreement is kept as one rule that can only escalate to review, and the documentation says plainly what it does and does not mean.

### Prompting for correctness

Instructing the model to "only cite real articles" lowers the error rate but gives no guarantee and no evidence. It complements a gate; it cannot replace one.

## Why code

Code is the part of the system that can be wrong in only one way at a time, and that we can test. When a check can be expressed as code, it should be: the decision stays explainable, reproducible and cheap. What cannot be expressed as code goes to a person, and the gate's job is to make sure it gets there.
