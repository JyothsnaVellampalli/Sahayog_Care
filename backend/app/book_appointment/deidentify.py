"""De-identification of patient free text.

PRD section 6/7: identifiers must be removed before any external model call, and
the scope/identity must never come from the prompt. This module scrubs direct
identifiers (name, phone, email, addresses, government / health IDs) from the
patient's natural-language input and returns the cleaned text plus a summary of
what was removed (types and counts only — never the raw values, per PRD section
9: "Never log raw free text, identifiers ...").

A built-in regex scrubber is always available. If Microsoft Presidio is
installed (see backend/requirements-deid.txt), it is used additionally for
ML-backed entity detection. The regex layer runs regardless, so the node never
silently does nothing when the optional dependency is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Regex patterns for common Indian + generic direct identifiers ------------

# Email addresses.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# URLs.
_URL = re.compile(r"\bhttps?://\S+\b", re.IGNORECASE)

# Indian mobile numbers: optional +91 / 0, then a 10-digit number starting 6-9.
# Also catches generic 10+ digit runs with separators.
_PHONE = re.compile(
    r"(?:(?:\+?91[\-\s]?)|0)?[6-9]\d{9}\b"
    r"|\b\d{3}[\-\s]\d{3}[\-\s]\d{4}\b"
)

# Aadhaar: 12 digits, often grouped 4-4-4.
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")

# ABHA number: 14 digits, often grouped 2-4-4-4.
_ABHA = re.compile(r"\b\d{2}[\-\s]?\d{4}[\-\s]?\d{4}[\-\s]?\d{4}\b")

# PAN: 5 letters, 4 digits, 1 letter.
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

# Names introduced by a keyword ("my name is X", "I am X", "this is X ...").
# Optionally consumes a title (Dr./Mr./Mrs./Ms./Shri/Smt/Miss) before the name
# so "Dr. Anjali Mehta" is captured in full. The introducing phrase matches
# case-insensitively; the captured name requires capitalised words.
_NAME_INTRO = re.compile(
    r"(?i:\b(?:my name is|i am|i'm|this is|name|myself)\b[:\-]?\s+)"
    r"(?i:(?:dr|mr|mrs|ms|miss|shri|smt)\.?\s+)?"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
)

# Title directly in front of a capitalised name, anywhere ("Dr Anjali Mehta").
_TITLED_NAME = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Miss|Shri|Smt)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)

# Address hints ("address ...", pin codes).
_PINCODE = re.compile(r"\b\d{6}\b")
_ADDRESS_INTRO = re.compile(
    r"\b(?:address|live at|residing at|flat|plot|house no\.?)\s*[:\-]?\s*"
    r"([^.,\n]{3,60})",
    re.IGNORECASE,
)

# Order matters: more specific IDs before generic phone/number patterns.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", _EMAIL),
    ("URL", _URL),
    ("ABHA", _ABHA),
    ("AADHAAR", _AADHAAR),
    ("PAN", _PAN),
    ("PHONE", _PHONE),
    ("PINCODE", _PINCODE),
]


@dataclass
class DeidResult:
    """The result of de-identifying one piece of text.

    Attributes:
        text: the cleaned text, with identifiers replaced by placeholders like
            "[NAME]" or "[PHONE]".
        removed: a summary of what was taken out, as {type: count}, for example
            {"NAME": 1, "PHONE": 2}. It stores only the counts, never the real
            values, so logging it can never leak a patient's details.
    """

    text: str
    removed: dict[str, int] = field(default_factory=dict)

    @property
    def removed_count(self) -> int:
        """Total number of identifiers removed across all types."""
        return sum(self.removed.values())


def _placeholder(label: str) -> str:
    """Turn a label like "NAME" into the placeholder text "[NAME]"."""
    return f"[{label}]"


def _scrub_regex(text: str, removed: dict[str, int]) -> str:
    """Remove identifiers using regular expressions.

    This always runs, so there is a reliable baseline even when the optional
    ML scrubber (Presidio) is not installed. It handles two kinds of patterns:

    1. Patterns with a "cue" phrase (name, address). Here we keep the cue and
       redact only the sensitive part, e.g. "my name is Rahul" -> "my name is
       [NAME]". This is done by `_sub_group` below.
    2. Patterns that are themselves the identifier (email, phone, Aadhaar, ...).
       The whole match is replaced with a placeholder.

    Each removal is counted in `removed` (by type), never stored by value.

    Args:
        text: the input text to clean.
        removed: a dict that is updated in place with type -> count.

    Returns:
        The text with all regex-detected identifiers replaced.
    """

    def _sub_group(pattern: re.Pattern[str], label: str, s: str) -> str:
        """Redact only the captured group, keeping its surrounding cue phrase."""

        def repl(match: re.Match[str]) -> str:
            removed[label] = removed.get(label, 0) + 1
            # Keep the introducing phrase, redact the captured value.
            full = match.group(0)
            value = match.group(1)
            return full.replace(value, _placeholder(label))

        return pattern.sub(repl, s)

    text = _sub_group(_NAME_INTRO, "NAME", text)
    text = _sub_group(_TITLED_NAME, "NAME", text)
    text = _sub_group(_ADDRESS_INTRO, "ADDRESS", text)

    for label, pattern in _PATTERNS:
        def repl(_match: re.Match[str], _label: str = label) -> str:
            removed[_label] = removed.get(_label, 0) + 1
            return _placeholder(_label)

        text = pattern.sub(repl, text)

    return text


def _scrub_presidio(text: str, removed: dict[str, int]) -> str:
    """Optional second pass using Microsoft Presidio (ML-based detection).

    Presidio can spot identifiers the regex layer misses (for example a plain
    name with no "my name is" cue). It is optional: if Presidio or its language
    model is not installed, this function returns the text unchanged instead of
    raising, so the flow keeps working.

    Args:
        text: the already regex-cleaned text.
        removed: a dict updated in place with any extra removals (by type).

    Returns:
        The text with additional entities redacted, or unchanged if Presidio is
        unavailable.
    """
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
    except Exception:
        return text

    try:
        analyzer = _get_analyzer()
        results = analyzer.analyze(text=text, language="en")
        if not results:
            return text
        for r in results:
            removed[r.entity_type] = removed.get(r.entity_type, 0) + 1
        anonymizer = AnonymizerEngine()
        return anonymizer.anonymize(text=text, analyzer_results=results).text
    except Exception:
        # Presidio present but model missing/misconfigured: fall back silently.
        return text


_ANALYZER = None


def _get_analyzer():
    """Build the Presidio analyzer once and reuse it (it is expensive to create)."""
    global _ANALYZER
    if _ANALYZER is None:
        from presidio_analyzer import AnalyzerEngine

        _ANALYZER = AnalyzerEngine()
    return _ANALYZER


def deidentify(text: str | None) -> DeidResult:
    """Remove personal details from patient free text before it is sent anywhere.

    This is the public entry point used by the booking graph. It runs the regex
    scrubber first (always), then the optional Presidio pass, then tidies up any
    extra spaces left behind.

    Example:
        >>> r = deidentify("My name is Rahul, call 9876543210. I have a cough.")
        >>> r.text
        'My name is [NAME], call [PHONE]. I have a cough.'
        >>> r.removed
        {'NAME': 1, 'PHONE': 1}

    Args:
        text: the raw text the patient typed (may be None or empty).

    Returns:
        A DeidResult with the cleaned text and a {type: count} summary. Medical
        wording is preserved; only identifiers are replaced with placeholders.
    """
    if not text or not text.strip():
        return DeidResult(text="", removed={})

    removed: dict[str, int] = {}
    cleaned = _scrub_regex(text, removed)
    cleaned = _scrub_presidio(cleaned, removed)
    # Collapse any whitespace introduced by substitutions.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return DeidResult(text=cleaned, removed=removed)
