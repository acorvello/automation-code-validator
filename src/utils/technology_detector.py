import os
import re
from typing import Optional, Tuple


FRAMEWORK_PATTERNS = {
    "Cypress": (
        r"\bcypress\b",
        r"\bcy\.(?:get|visit|contains|intercept|find)\s*\(",
        r"CypressError",
    ),
    "Selenium": (
        r"\bselenium\b",
        r"org\.openqa\.selenium",
        r"(?:NoSuchElementException|NoSuchElementError|WebDriverException)",
        r"\bwebdriver\b",
    ),
    "Playwright": (
        r"\bplaywright\b",
        r"strict mode violation",
        r"waiting for locator",
        r"page\.get_by_(?:role|text|test_id)",
    ),
}

LANGUAGE_EXTENSIONS = {
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "JavaScript",
    ".tsx": "JavaScript",
    ".py": "Python",
}

LANGUAGE_NAMES = {
    "java": "Java",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "JavaScript",
    "ts": "JavaScript",
    "python": "Python",
    "py": "Python",
}


def detect_technology(
    raw_logs: str,
    file_path: Optional[str] = None,
    source_code: Optional[str] = None,
) -> Tuple[str, str]:
    """Detect the test framework and source language without guessing."""
    text = "\n".join(part for part in (raw_logs, source_code or "") if part)
    filename = os.path.basename(file_path or "")

    framework = _metadata_value(text, "framework")
    if framework not in FRAMEWORK_PATTERNS:
        framework = _match_framework(filename) or _match_framework(text) or "Unknown"

    language = _metadata_language(text)
    if not language:
        language = _language_from_path(file_path)
    if not language:
        language = _language_from_filename(filename)
    if not language:
        language = _language_from_source(source_code or "")
    if not language:
        language = _language_from_logs(text, framework)
    if not language and framework == "Cypress":
        language = "JavaScript"

    return framework, language or "Unknown"


def _metadata_value(text: str, name: str) -> Optional[str]:
    match = re.search(rf"^\s*{name}\s*:\s*([\w+#.-]+)\s*$", text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip().title() if match else None


def _metadata_language(text: str) -> Optional[str]:
    match = re.search(r"^\s*language\s*:\s*([\w+#.-]+)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return LANGUAGE_NAMES.get(match.group(1).lower())


def _match_framework(text: str) -> Optional[str]:
    for framework, patterns in FRAMEWORK_PATTERNS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            return framework
    return None


def _language_from_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    return LANGUAGE_EXTENSIONS.get(os.path.splitext(file_path)[1].lower())


def _language_from_filename(filename: str) -> Optional[str]:
    tokens = re.split(r"[^a-zA-Z0-9]+", filename.lower())
    for token in tokens:
        language = LANGUAGE_NAMES.get(token)
        if language:
            return language
    return None


def _language_from_source(source_code: str) -> Optional[str]:
    if re.search(r"\b(import|package)\s+org\.openqa\.selenium\b|\bpublic\s+class\b", source_code):
        return "Java"
    if re.search(r"\b(def\s+test_|from\s+playwright|import\s+pytest|webdriver\.Chrome\s*\()", source_code):
        return "Python"
    if re.search(r"\b(cy\.|require\(['\"]cypress|from\s+['\"](?:@playwright/test|playwright))", source_code):
        return "JavaScript"
    return None


def _language_from_logs(logs: str, framework: str) -> Optional[str]:
    if re.search(
        r"org\.openqa\.selenium|com\.microsoft\.playwright|"
        r"\bat\s+[\w.$<>]+\([^\n)]*\.java:\d+\)",
        logs,
    ):
        return "Java"
    if re.search(
        r"Traceback \(most recent call last\)|"
        r"File \"[^\"]+\.py\", line \d+|"
        r"selenium\.common\.exceptions|playwright\._impl",
        logs,
    ):
        return "Python"
    if re.search(
        r"NoSuchElementError|node_modules[/\\](?:@playwright/test|playwright|selenium-webdriver)",
        logs,
    ):
        return "JavaScript"
    if framework == "Cypress":
        return "JavaScript"
    return None