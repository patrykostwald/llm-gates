# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
