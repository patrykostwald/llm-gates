# Contributing

Thanks for your interest in `llm-gates`. The project is deliberately small, so the best contributions keep it that way.

## Principles

* **Deterministic.** A rule must give the same answer for the same input. No network, no randomness, no model calls.
* **No runtime dependencies.** The standard library only. Development tools are fine.
* **Small and readable.** Prefer a short function to a new abstraction.
* **Honest limits.** If a check can miss things, say so in its docstring and in the README.

## Setup

```
python -m venv .venv
.venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
```

## Before you open a pull request

```
ruff check .
ruff format --check .
mypy
pytest --cov
```

* `mypy --strict` must pass (it is configured in `pyproject.toml`).
* Add tests for every change, including boundary cases (dates on the first and last day of a validity window, empty lists, wrong types). Coverage should stay at or above 95 percent.
* Code, comments and docstrings are in English.
* Update `CHANGELOG.md` under "Unreleased".

## Proposing a new rule or detector

Open an issue first with: what it catches, an example input, and how it can be wrong. Rules that need a model or a network call do not fit this library; see [ADR 0001](docs/adr/0001-deterministic-gates-over-llm-as-judge.md).

## Conduct

Be kind and assume good faith. Technical disagreement is welcome; personal attacks are not.
