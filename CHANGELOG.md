# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-11-17

### Added

- `NearMissRule` and `find_near_misses`: a valid, in-force citation that is one swap of two
  adjacent characters (`ACT-012` and `ACT-021`), or one edit in a sparsely numbered
  registry, away from another norm in force goes to `review`. On by default in
  `PublicationGate.default` (`near_miss=False` leaves it out). Trade-off in ADR 0002.
- `NormRegistry` can be iterated.
- Benchmark: `benchmarks/release-0.1.1.json` freezes the 0.1.1 decisions, `RESULTS.md`
  gets a "0.1.1 vs 0.2.0" section (totals, categories and every case whose decision
  changed) and `run.py --snapshot` freezes a release. ADR 0002 records the near-miss
  trade-off.

### Changed

- `pii`: the scanner now reads masked e-mail addresses (`jan [at] example dot com`,
  `jan(at)example.com`, `jan AT example DOT com`), PESEL numbers split with spaces or a
  hyphen between any digits, IBANs in any case with spaces or hyphens between any
  characters, and 26-digit Polish account numbers without the `PL` prefix. IBANs must now
  have the exact length for a known country. Limitations are listed in the module
  docstring.
- Benchmark results, 0.1.1 to 0.2.0 on the same 206 cases: accuracy 87.4% to 89.3%,
  unsafe publishes 22 to 3 of 156, masked personal data published 16 to 3 of 16, near-miss
  typos published 6 to 0 of 6. The price: clean cases blocked 4 to 19 of 50 (publish recall
  92% to 62%), because answers whose citation has a swap twin in the registry go to review
  too. Switch the rule off with `PublicationGate.default(..., near_miss=False)`.

## [0.1.1] - 2026-11-17

### Added

- `benchmarks/`: a deterministic, fully synthetic dataset of 206 labelled cases
  (fictional norm registry with validity dates; nine categories from clean output
  to masked personal data) and `benchmarks/generate.py` to rebuild it.
- `benchmarks/run.py`: scores the default gate against two naive baselines
  (schema validation only; agreement between two models only) and writes
  `benchmarks/RESULTS.md` with precision, recall, confusion matrices, accuracy by
  category and every case the gate gets wrong.
- CI step and test that fail when the benchmark scores drop or `RESULTS.md` is stale.
- README: CI and license badges, a Benchmark section, a pinned-tag install line and a
  roadmap that matches the open GitHub issues.
- CONTRIBUTING: how to work with the benchmark.

### Changed

- Package version is now 0.1.1. The library code is unchanged.

## [0.1.0] - 2026-11-17

### Added

- `schema`: structural validation of model output with path-bearing errors.
- `citations`: `NormRegistry` (JSON and CSV loading) and `verify_citations` with
  `unknown`, `not_in_force` and `malformed` problems.
- `compare`: `compare_outputs` grading two independent outputs as `agree`,
  `partial` or `disagree`.
- `pii`: scanner for e-mail, phone, IBAN, PESEL and `ul.` addresses.
- `gate`: `PublicationGate` with the default rules `SchemaRule`, `CitationRule`,
  `PiiRule`, `AgreementRule` and a `Rule` protocol for custom rules.
- Examples `legal_diagnosis.py` and `news_claims.py`.
- Continuous integration on Python 3.10 to 3.13.
