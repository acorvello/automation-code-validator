from typing import TypedDict, List, Optional, Annotated
from pydantic import BaseModel

class GraphState(TypedDict):
    raw_cypress_logs: str
    detected_anomalies: List[dict]
    evaluation_metrics: dict
    retry_count: int
    current_node: str
    fix_suggestion: Optional[str]
    needs_fix: bool  # Adicionado para o roteamento
    current_file_path: Optional[str]
    source_code: Optional[str]
    verification_logs: List[dict]
    execution_history: List[dict]  # Histórico para a interface Streamlit



