"""The policy: turns detector findings and the model's verdict into the final decision.

The model classifies; this code decides. Every decision names the rule that produced it,
and the rules can overrule a model answer that contradicts itself (for example
"APPROVED" with category "Threat").
"""
from dataclasses import dataclass

from . import config
from .detectors import Finding, looks_bulgarian

BLOCKED_CATEGORIES = {"Threat", "Hate Speech", "Spam", "PII", "Prompt Injection"}
ABUSIVE_CATEGORIES = {"Profanity", "Harassment"}   # rejected, or reviewed if the model calls it mild
REVIEW_CATEGORIES = {"Borderline", "Low Quality"}

_PII_NAMES = {
    "en": {"egn": "a national ID number (EGN)", "iban": "a bank account (IBAN)",
           "phone": "a phone number", "email": "an email address"},
    "bg": {"egn": "ЕГН", "iban": "банкова сметка (IBAN)", "phone": "телефонен номер", "email": "имейл адрес"},
}


@dataclass
class Decision:
    status: str            # APPROVED | REJECTED | NEEDS_REVIEW
    category: str
    toxicity_score: int
    reason: str
    rule: str              # which policy rule decided
    decided_by: str        # "rule" (no LLM) | "ai" | "fallback"


def decide_without_llm(text: str, pii: list[Finding], trivially_empty: bool):
    """Clear-cut cases that need no model. Returns None when the LLM should decide."""
    lang = "bg" if looks_bulgarian(text) else "en"
    if pii:
        kinds = list(dict.fromkeys(f.kind for f in pii))
        names = ", ".join(_PII_NAMES[lang][k] for k in kinds)
        reason = (f"Коментарът съдържа лични данни: {names}. Премахнете ги и публикувайте отново."
                  if lang == "bg" else
                  f"The comment contains personal data: {names}. Remove it and post again.")
        return Decision("REJECTED", "PII", 80, reason, "pii-detector", "rule")
    if trivially_empty:
        reason = ("Коментарът няма смислено съдържание." if lang == "bg"
                  else "The comment has no readable content.")
        return Decision("NEEDS_REVIEW", "Low Quality", 0, reason, "empty-text", "rule")
    return None


def decide_from_verdict(decision: str, category: str, toxicity_score: int, reason: str) -> Decision:
    def make(status, rule):
        return Decision(status, category, toxicity_score, reason, rule, "ai")

    if category in BLOCKED_CATEGORIES:
        return make("REJECTED", "blocked-category")
    if category in ABUSIVE_CATEGORIES:
        # Never auto-publish a comment the model itself labels abusive.
        return make(decision if decision in ("REJECTED", "NEEDS_REVIEW") else "NEEDS_REVIEW", "abusive-category")
    if category in REVIEW_CATEGORIES:
        return make("NEEDS_REVIEW", "review-category")
    # Clean
    if decision != "APPROVED":
        return make("NEEDS_REVIEW", "clean-but-not-approved")
    if toxicity_score >= config.REVIEW_TOXICITY_THRESHOLD:
        return make("NEEDS_REVIEW", "clean-but-high-toxicity")
    return make("APPROVED", "clean")


FALLBACK_REASON = "Automatic moderation is unavailable right now. The comment is waiting for a human moderator."


def fallback() -> Decision:
    """Fail closed: without a verdict nothing is published; a human decides."""
    return Decision("NEEDS_REVIEW", "System Fallback", 50, FALLBACK_REASON, "llm-unavailable", "fallback")
