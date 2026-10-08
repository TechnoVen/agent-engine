"""Economics package for Agent Engine (Task R3.10)."""

from core.economics.models import (
    Money,
    TaskOutcome,
    OutcomeSource,
    EvidenceSource,
    OutcomeEvidence,
    HumanCorrectionEvent,
    AttemptEconomicsRecord,
    LogicalTaskEconomicsRecord,
    EconomicsCohortKey,
    EvidenceSufficiencyStatus,
    SufficiencyPolicy,
    ModelEconomicsSummary,
    CostPerSuccessEstimate,
)
from core.economics.service import (
    EconomicsService,
    get_economics_service,
    reset_economics_service,
)
from core.economics.golden_eval import (
    build_golden_eval_service,
    generate_golden_eval_report,
    generate_golden_eval_markdown_report,
)

__all__ = [
    "Money",
    "TaskOutcome",
    "OutcomeSource",
    "EvidenceSource",
    "OutcomeEvidence",
    "HumanCorrectionEvent",
    "AttemptEconomicsRecord",
    "LogicalTaskEconomicsRecord",
    "EconomicsCohortKey",
    "EvidenceSufficiencyStatus",
    "SufficiencyPolicy",
    "ModelEconomicsSummary",
    "CostPerSuccessEstimate",
    "EconomicsService",
    "get_economics_service",
    "reset_economics_service",
    "build_golden_eval_service",
    "generate_golden_eval_report",
    "generate_golden_eval_markdown_report",
]
