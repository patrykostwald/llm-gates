# Security Policy

## Supported versions

Only the latest released minor version receives security fixes.

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private vulnerability reporting ("Report a vulnerability" under the repository's Security tab) and include:

* what you found and its impact,
* a minimal input that reproduces it,
* the version of `llm-gates` and Python.

You can expect an acknowledgement within a week and a fix or a clear answer within 30 days.

## Scope

In scope: bugs that make a gate return `publish` for input it should block (for example a validity-window off-by-one, a PII pattern that can be bypassed by trivial input, a regular expression with catastrophic backtracking), and anything that leaks the matched personal data into logs or reasons.

Out of scope: the documented limitations, such as the PII scanner not finding names or the citation check not judging relevance.
