import re
from typing import List, Dict, Optional
from src.core.schemas import AnomalyReport

class LogParser:
    '''
    Utility to process browser automation logs and extract anomalies.
    '''

    ERROR_PATTERNS = {
        'INFRA_FAILURE': (
            r'\bHTTP(?:/\d(?:\.\d)?)?\s+(?:401|403|404|5\d{2})\b|'
            r'\b(?:401|403|404|5\d{2})\s+(?:Unauthorized|Forbidden|Not Found|Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout)\b|'
            r'\b(?:ECONNRESET|ECONNREFUSED|ETIMEDOUT|ENOTFOUND|ERR_NETWORK)\b|'
            r'connection (?:refused|reset|timed out)|request timed out|socket timed out|network error'
        ),
        'AMBIGUOUS_SELECTOR': r'strict mode violation|resolved to \d+ elements',
        'ELEMENT_NOT_INTERACTABLE': r'element (?:is )?not interactable|ElementNotInteractableException',
        'ELEMENT_NOT_FOUND': (
            r'Could not find element:\s*(.*)|'
            r'NoSuchElement(?:Exception|Error)|'
            r'resolved to 0 elements'
        ),
        'TIMEOUT': (
            r'Timed out (?:after|retrying after) \d+ms|'
            r'Timeout \d+ms exceeded|timeout of \d+ms exceeded'
        ),
        'COMMAND_FAILED': r'Command failed: (.*)',
        'RETRY_EXHAUSTED': r'Retrying... (Maximum retries reached)'
    }

    ELEMENT_TIMEOUT_PATTERN = (
        r'element|locator|selector|cy\.get|expected to find|'
        r'not interactable|waiting for (?:a )?(?:selector|locator|element|button|text|role)'
    )

    SELECTOR_PATTERNS = (
        r'Could not find element:\s*(.+)',
        r'["\']selector["\']\s*[:=]\s*["\']([^"\']+)',
        r'Unable to locate element:\s*["\']?([^"\'\s,}]+)',
        r'(?:locator|getBy\w+|get_by_\w+|cy\.get)\(["\']([^"\']+)',
        r'\((?:"|\')([^"\']+)(?:"|\')\).*?resolved to \d+ elements',
    )

    @staticmethod
    def parse(raw_logs: str, file_path: Optional[str] = None) -> List[AnomalyReport]:
        anomalies = []
        lines = raw_logs.split('\n')

        for line_num, line in enumerate(lines, 1):
            for error_type, pattern in LogParser.ERROR_PATTERNS.items():
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    classified_type = error_type
                    if error_type == 'TIMEOUT':
                        classified_type = (
                            'ELEMENT_TIMEOUT'
                            if re.search(
                                LogParser.ELEMENT_TIMEOUT_PATTERN,
                                line,
                                re.IGNORECASE,
                            )
                            else 'UNKNOWN_TIMEOUT'
                        )
                    selector = LogParser._extract_selector(line)
                    is_selector_error = error_type in {
                        'ELEMENT_NOT_FOUND', 'ELEMENT_NOT_INTERACTABLE',
                        'AMBIGUOUS_SELECTOR'
                    } or classified_type == 'ELEMENT_TIMEOUT'
                    if classified_type == 'INFRA_FAILURE':
                        selector = None

                    flakiness_score = {
                        'ELEMENT_NOT_FOUND': 0.8,
                        'ELEMENT_NOT_INTERACTABLE': 0.8,
                        'ELEMENT_TIMEOUT': 0.8,
                        'AMBIGUOUS_SELECTOR': 0.7,
                        'COMMAND_FAILED': 0.5,
                        'RETRY_EXHAUSTED': 0.5,
                        'INFRA_FAILURE': 0.0,
                        'UNKNOWN_TIMEOUT': 0.0,
                    }.get(classified_type, 0.0)
                    
                    anomalies.append(AnomalyReport(
                        id=f'ERR_{classified_type}_{line_num}',
                        severity='High' if classified_type in {
                            'INFRA_FAILURE', 'ELEMENT_TIMEOUT', 'UNKNOWN_TIMEOUT'
                        } else 'Medium',
                        description=f'Line {line_num}: {line.strip()}',
                        error_type=classified_type,
                        selector_affected=selector if is_selector_error else None,
                        flakiness_score=flakiness_score,
                        file_path=file_path,
                        source_code=None
                    ))
                    break
        return anomalies

    @staticmethod
    def _extract_selector(line: str) -> Optional[str]:
        for pattern in LogParser.SELECTOR_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

