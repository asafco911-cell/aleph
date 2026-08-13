"""Security layer: injection detection and PII redaction.
Runs at the boundary - where external text ENTERS the system."""
import re
from typing import List, Dict

# Patterns that indicate text is trying to address the AI system rather than describe a business
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|prior|the)\s+",
    r"system\s*(note|prompt|message|instruction)",
    r"you\s+(must|should|are\s+required\s+to)\s+(report|say|conclude|rate)",
    r"new\s+instructions?\s*:",
    r"</?(system|instruction|admin)>",
    r"act\s+as\s+(if|though)",
    r"do\s+not\s+(mention|reveal|disclose)\s+(this|these)",
]

PII_PATTERNS = {
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "phone_us": r"\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "api_key": r"\b(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36})\b",
    "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
}


def scan_for_injection(text: str) -> List[Dict]:
    """Deterministic pattern scan. Cheap, instant, catches the blunt cases."""
    findings = []
    for pattern in INJECTION_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            start = max(0, match.start() - 60)
            findings.append({
                "pattern": pattern,
                "matched": match.group()[:80],
                "context": text[start:match.end() + 60].replace("\n", " "),
                "position": match.start(),
            })
    return findings


def redact_pii(text: str) -> tuple:
    """Replace PII with typed placeholders. Returns (clean_text, counts)."""
    counts = {}
    clean = text
    for label, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, clean)
        if matches:
            counts[label] = len(matches)
            clean = re.sub(pattern, f"[REDACTED_{label.upper()}]", clean)
    return clean, counts


def sanitize_document(text: str, doc_name: str = "document") -> Dict:
    """Boundary check: run this ONCE, right after extraction, BEFORE chunking.
    Chunking would split a multi-line injection so no detector could see it whole."""
    injections = scan_for_injection(text)
    clean, pii_counts = redact_pii(text)
    return {
        "document": doc_name,
        "clean_text": clean,
        "injection_findings": injections,
        "pii_redacted": pii_counts,
        "safe": len(injections) == 0,
    }