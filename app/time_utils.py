"""Whole-hour time-window parsing helpers.

Convention (Problem Statement Sec. 05.1): time windows are start-inclusive,
end-exclusive whole-hour intervals. "1 PM to 3 PM" -> hours [13, 14].
"""
from __future__ import annotations

import re

_WORD_HOUR = {
    "midnight": 0,
    "noon": 12,
}

_AMPM_RE = re.compile(
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?", re.IGNORECASE
)


def _to_24h(h: int, m: int, ampm: str | None) -> int:
    h = h % 24
    if ampm:
        ampm = ampm.lower()
        if ampm == "am":
            if h == 12:
                h = 0
        elif ampm == "pm":
            if h != 12:
                h += 12
    return h % 24


def parse_clock_token(token: str) -> int | None:
    token = token.strip().lower()
    if token in _WORD_HOUR:
        return _WORD_HOUR[token]
    m = _AMPM_RE.fullmatch(token)
    if not m:
        return None
    h = int(m.group("h"))
    mm = int(m.group("m") or 0)
    return _to_24h(h, mm, m.group("ampm"))


_RANGE_RE = re.compile(
    r"(?:from|between)?\s*"
    r"(?P<start>\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)"
    r"\s*(?:until|to|-|–|through|and)\s*"
    r"(?P<end>\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)",
    re.IGNORECASE,
)


def extract_hour_window(text: str) -> list[int] | None:
    """Best-effort extraction of a start-inclusive/end-exclusive hour window from free text.

    Returns a list of unique ascending integer hours in [0, 23], or None if no window found.
    Used only by the offline fallback interpreter (see fallback_interpreter.py) when the LLM
    call itself fails, and by tests. The LLM does the primary, paraphrase-robust extraction.
    """
    m = _RANGE_RE.search(text)
    if not m:
        return None
    start_raw, end_raw = m.group("start"), m.group("end")

    # If start has no am/pm and end does, infer start's am/pm won't be attempted here;
    # this is a best-effort fallback, not the primary interpretation path.
    start_h = parse_clock_token(start_raw)
    end_h = parse_clock_token(end_raw)
    if start_h is None or end_h is None:
        return None

    if end_h <= start_h:
        end_h += 24
    hours = [h % 24 for h in range(start_h, end_h)]
    # de-dup while preserving ascending order, clipped to 0..23
    seen = sorted(set(hours))
    return seen if seen else None


_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")

_FRACTION_WORDS = {
    "half": 0.5,
    "one-half": 0.5,
    "a quarter": 0.25,
    "one-quarter": 0.25,
    "one-fourth": 0.25,
    "three-quarters": 0.75,
    "one-fifth": 0.2,
    "two-fifths": 0.4,
    "one-third": 1 / 3,
    "two-thirds": 2 / 3,
    "one-tenth": 0.1,
}


def extract_percentage(text: str) -> float | None:
    m = _PERCENT_RE.search(text)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 100:
            return val / 100.0

    lower = text.lower()
    for phrase, frac in _FRACTION_WORDS.items():
        if phrase in lower:
            return round(frac, 4)
    return None


_KWH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*kwh", re.IGNORECASE)


def extract_kwh(text: str) -> float | None:
    m = _KWH_RE.search(text)
    if not m:
        return None
    return float(m.group(1))
