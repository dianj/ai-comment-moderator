"""Deterministic detectors: personal data and content-free text.

These run before the LLM. They are exact, instant and unit-tested, so the clear cases
(a valid EGN, an IBAN, a phone number) never depend on a model's judgement.
Checksums keep false positives down: an order number that merely has 10 digits is not an EGN.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Finding:
    kind: str    # "egn" | "iban" | "phone" | "email" | "url"
    value: str
    start: int
    end: int


PII_KINDS = ("egn", "iban", "phone", "email")

# --- EGN (Bulgarian personal number): YYMMDD + 3 digits + checksum ---------------------------

_EGN_WEIGHTS = (2, 4, 8, 5, 10, 9, 7, 3, 6)
_EGN = re.compile(r"(?<!\d)\d{10}(?!\d)")


def egn_is_valid(egn: str) -> bool:
    if len(egn) != 10 or not egn.isdigit():
        return False
    year, month, day = int(egn[0:2]), int(egn[2:4]), int(egn[4:6])
    if 1 <= month <= 12:
        year += 1900
    elif 21 <= month <= 32:
        year, month = year + 1800, month - 20
    elif 41 <= month <= 52:
        year, month = year + 2000, month - 40
    else:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    check = sum(int(d) * w for d, w in zip(egn[:9], _EGN_WEIGHTS, strict=True)) % 11
    return int(egn[9]) == (0 if check == 10 else check)


# --- IBAN: country code + check digits, verified with ISO 7064 mod 97 -------------------------

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", re.IGNORECASE)


def iban_is_valid(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if not 15 <= len(s) <= 34 or not s[:2].isalpha():
        return False
    rearranged = s[4:] + s[:4]
    try:
        number = int("".join(str(int(c, 36)) for c in rearranged))
    except ValueError:
        return False
    return number % 97 == 1


# --- phone numbers: Bulgarian formats and international +CC numbers ---------------------------

_PHONE = re.compile(
    r"(?<![\w+])(?:"
    r"(?:\+|00)359[\s-]?\d(?:[\s-]?\d){7,8}"     # +359 87 654 3210, 00359 2 123 4567
    r"|0[2-9](?:[\s-]?\d){7,8}"                   # 0888 123 456, 02 123 4567
    r"|\+(?!359)[1-9]\d{0,2}(?:[\s-]?\d){6,12}"   # other countries: +44 20 7946 0958
    r")(?![\w])"
)

# --- email and links ----------------------------------------------------------------------------

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b", re.IGNORECASE)
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)


def scan(text: str) -> list[Finding]:
    """All personal data and links in `text`. Overlapping matches keep the most specific kind."""
    found: list[Finding] = []

    def add(kind, m):
        if not any(m.start() < f.end and f.start < m.end() for f in found):
            found.append(Finding(kind, m.group(), m.start(), m.end()))

    for m in _EMAIL.finditer(text):
        add("email", m)
    for m in _URL.finditer(text):
        add("url", m)
    for m in _IBAN.finditer(text):
        if iban_is_valid(m.group()):
            add("iban", m)
    for m in _EGN.finditer(text):
        if egn_is_valid(m.group()):
            add("egn", m)
    for m in _PHONE.finditer(text):
        add("phone", m)
    return sorted(found, key=lambda f: f.start)


def personal_data(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.kind in PII_KINDS]


# --- content-free text --------------------------------------------------------------------------

def is_trivially_empty(text: str) -> bool:
    """Only punctuation/spaces (".", "?!", "---") or one character repeated ("аааааа").

    Emoji are symbols, not punctuation, so a lone 👍 is left to the model as a real reaction.
    """
    stripped = "".join(ch for ch in text if not ch.isspace())
    if not stripped:
        return True
    if all(unicodedata.category(ch).startswith("P") for ch in stripped):
        return True
    return len(stripped) >= 4 and len(set(stripped.lower())) == 1


def looks_bulgarian(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum("Ѐ" <= ch <= "ӿ" for ch in letters) / len(letters) > 0.3
