from pydantic import BaseModel, Field
from typing import List, Literal, Optional

class AnomalyReport(BaseModel):
    id: str
    severity: str = Field(description="Low, Medium, High, Critical")
    description: str
    error_type: Optional[str] = None
    selector_affected: Optional[str]
    flakiness_score: float = Field(ge=0, le=1)
    file_path: Optional[str] = None
    source_code: Optional[str] = None

class EvaluationMetrics(BaseModel):
    robustness_score: float
    selector_uniqueness: bool
    actionable_fix_available: bool


class EvaluatorResponse(BaseModel):
    anomaly_id: str
    classification: Literal[
        "INFRA_FAILURE",
        "ERR_AMBIGUOUS_SELECTOR",
        "LOGIC_OR_STATE_ERROR",
        "FLAKY_SELECTOR",
        "UNCLASSIFIED",
    ]
    reasoning: str
    needs_fix: bool
    recommendation: str
