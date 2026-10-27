from pydantic import BaseModel, Field
from typing import List, Optional

class AnomalyReport(BaseModel):
    id: str
    severity: str = Field(description="Low, Medium, High, Critical")
    description: str
    selector_affected: Optional[str]
    flakiness_score: float = Field(ge=0, le=1)
    file_path: Optional[str] = None
    source_code: Optional[str] = None

class EvaluationMetrics(BaseModel):
    robustness_score: float
    selector_uniqueness: bool
    actionable_fix_available: bool
