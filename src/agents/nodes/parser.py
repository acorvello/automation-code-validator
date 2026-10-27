from typing import Dict
from src.core.state import GraphState
from src.utils.log_parser import LogParser
from src.utils.technology_detector import detect_technology
from src.core.schemas import EvaluationMetrics

def parse_logs_node(state: GraphState) -> Dict:
    """
    Process browser automation logs and initialize evaluation metrics.
    Extrai anomalias e gera métricas iniciais de avaliação.
    """
    raw_logs = state.get("raw_cypress_logs", "")
    framework, language = detect_technology(
        raw_logs,
        file_path=state.get("current_file_path"),
        source_code=state.get("source_code"),
    )
    
    # Chama o utilitário para processar os logs
    anomalies = LogParser.parse(
        raw_logs,
        file_path=state.get("current_file_path"),
    )
    
    # Define métricas básicas baseadas na quantidade de anomalias
    metrics = EvaluationMetrics(
        robustness_score=max(0.0, 1.0 - (len(anomalies) * 0.1)),
        selector_uniqueness=True, # Valor padrão inicial
        actionable_fix_available=len(anomalies) > 0
    )
    
    # Inicializa a lista de logs de verificação com as anomalias detectadas
    verification_logs = []
    for i, anomaly in enumerate(anomalies):
        verification_logs.append({
            "id": anomaly.id,
            "description": anomaly.description,
            "status": "detected",
            "file_path": anomaly.file_path,
            "corrected": False
        })

    # Retorna apenas as chaves que serão atualizadas no estado
    return {
        "detected_anomalies": anomalies,
        "framework": framework,
        "language": language,
        "evaluation_metrics": metrics.model_dump(),
        "verification_logs": verification_logs,
        "current_node": "parser"
    }
