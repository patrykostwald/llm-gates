"""Shared fixtures."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

BENCHMARKS = Path(__file__).resolve().parent.parent / "benchmarks"


def _load(name: str) -> ModuleType:
    """Import ``benchmarks/<name>.py`` as a module (``benchmarks`` is not a package)."""
    qualified = f"benchmarks_{name}"
    if qualified in sys.modules:
        return sys.modules[qualified]
    spec = importlib.util.spec_from_file_location(qualified, BENCHMARKS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module  # dataclasses look the module up while it executes
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def bench() -> Callable[[str], ModuleType]:
    """Load a script from the ``benchmarks`` directory by name."""
    return _load
