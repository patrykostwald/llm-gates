"""llm-gates: deterministic gates for structured LLM output.

Models propose, code decides.
"""

from llm_gates.citations import (
    CitationProblem,
    CitationReport,
    Norm,
    NormRegistry,
    ProblemKind,
    RegistryError,
    verify_citations,
)
from llm_gates.compare import Agreement, AgreementLevel, compare_outputs
from llm_gates.gate import (
    AgreementRule,
    CitationRule,
    Decision,
    Finding,
    GateContext,
    PiiRule,
    PublicationGate,
    Rule,
    SchemaRule,
    Verdict,
)
from llm_gates.pii import PiiKind, PiiMatch, find_pii
from llm_gates.schema import Field, Schema, SchemaError, ValidationResult

__version__ = "0.1.1"

__all__ = [
    "Agreement",
    "AgreementLevel",
    "AgreementRule",
    "CitationProblem",
    "CitationReport",
    "CitationRule",
    "Decision",
    "Field",
    "Finding",
    "GateContext",
    "Norm",
    "NormRegistry",
    "PiiKind",
    "PiiMatch",
    "PiiRule",
    "ProblemKind",
    "PublicationGate",
    "RegistryError",
    "Rule",
    "Schema",
    "SchemaError",
    "SchemaRule",
    "ValidationResult",
    "Verdict",
    "__version__",
    "compare_outputs",
    "find_pii",
    "verify_citations",
]
