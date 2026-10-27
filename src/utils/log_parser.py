import re
from typing import List, Dict, Optional
from src.core.schemas import AnomalyReport

class LogParser:
    '''
    Utility to process raw Cypress logs and extract anomalies.
    '''

    # Padrões comuns de erro no Cypress
    ERROR_PATTERNS = {
        'TIMEOUT': r'Timed out after (\d+)ms',
        'ELEMENT_NOT_FOUND': r'Could not find element: (.*)',
        'COMMAND_FAILED': r'Command failed: (.*)',
        'RETRY_EXHAUSTED': r'Retrying... (Maximum retries reached)'
    }

    @staticmethod
    def parse(raw_logs: str, file_path: Optional[str] = None) -> List[AnomalyReport]:
        anomalies = []
        lines = raw_logs.split('\n')

        for line_num, line in enumerate(lines, 1):
            for error_type, pattern in LogParser.ERROR_PATTERNS.items():
                match = re.search(pattern, line)
                if match:
                    # Extrai detalhes do erro
                    detail = match.group(1) if len(match.groups()) > 0 else line
                    
                    anomalies.append(AnomalyReport(
                        id=f'ERR_{error_type}_{line_num}',
                        severity='High' if 'TIMEOUT' in error_type else 'Medium',
                        description=f'Line {line_num}: {detail}',
                        selector_affected=detail if 'ELEMENT_NOT_FOUND' in error_type else None,
                        flakiness_score=0.8 if 'TIMEOUT' in error_type or 'ELEMENT_NOT_FOUND' in error_type else 0.5,
                        file_path=file_path,
                        source_code=None
                    ))
                    break
        return anomalies

