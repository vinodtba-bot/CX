"""Defense-in-depth redaction applied before anything is written to our
database. Retell's own post-call PII scrubbing (agent `pii_config`) should
also be on; this catches what reaches us regardless."""

import re

SSN_RE = re.compile(r"\b(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b")
CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
DOB_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2})\b"
)
SPOKEN_DOB_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _redact_cards(text: str) -> str:
    def repl(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return "[REDACTED_CARD]"
        return m.group(0)

    return CARD_CANDIDATE_RE.sub(repl, text)


def _redact_line(line: str) -> str:
    line = _redact_cards(line)
    line = SSN_RE.sub("[REDACTED_SSN]", line)
    line = EMAIL_RE.sub("[REDACTED_EMAIL]", line)
    # Dates are only treated as a date of birth when the caller says them;
    # agent lines carry service and decision dates that auditors need.
    if not line.startswith("Agent:"):
        line = DOB_RE.sub("[REDACTED_DOB]", line)
        line = SPOKEN_DOB_RE.sub("[REDACTED_DOB]", line)
    return line


def redact_text(text: str | None) -> str | None:
    if not text:
        return text
    return "\n".join(_redact_line(line) for line in text.split("\n"))


SENSITIVE_ARG_KEYS = {"date_of_birth", "dob", "ssn"}


def redact_args(args: dict | None) -> dict:
    """For audit logs: keep identifiers the auditor needs, mask secrets."""
    if not args:
        return {}
    return {k: ("[REDACTED]" if k in SENSITIVE_ARG_KEYS else v) for k, v in args.items()}
