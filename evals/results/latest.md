# Moderation eval results

- Date: 2026-11-23 01:41
- Model: `gemma-4-26b-a4b-it` via LM Studio, reasoning effort: `none`
- Target: `moderator.pipeline.moderate (detectors + LLM + policy)`, prompt `2026-11-23.3`
- Cases: 76 × 3 run(s) = 228 verdicts

## Summary

| Metric | Result |
|---|---|
| Correct decision | 228/228 (100%) |
| **Leaked** (published although it should not be) | 0/141 (0%) |
| **Over-blocked** (acceptable content rejected) | 0/108 (0%) |
| Correct category (when not approved) | 138/138 (100%) |
| LLM/parse fallbacks | 0/228 (0%) |
| Decided by detectors (no LLM call) | 21/228 (9%) |
| Policy overruled the model's decision | 0/228 (0%) |
| Latency p50 / p95 | 1.7s / 2.0s |

## By group

| Group | Correct | Leaked | Over-blocked |
|---|---|---|---|
| clean | 30/30 (100%) | 0 | 0 |
| hard_negative | 48/48 (100%) | 0 | 0 |
| profanity | 21/21 (100%) | 0 | 0 |
| threat | 9/9 (100%) | 0 | 0 |
| hate | 12/12 (100%) | 0 | 0 |
| spam | 15/15 (100%) | 0 | 0 |
| pii | 18/18 (100%) | 0 | 0 |
| injection | 24/24 (100%) | 0 | 0 |
| obfuscation | 15/15 (100%) | 0 | 0 |
| borderline | 18/18 (100%) | 0 | 0 |
| low_quality | 18/18 (100%) | 0 | 0 |

## Failures

None.

## Verdict distribution

| Decision | Category | Count |
|---|---|---|
| APPROVED | Clean | 78 |
| REJECTED | Harassment | 33 |
| REJECTED | Prompt Injection | 24 |
| REJECTED | Spam | 18 |
| REJECTED | PII | 18 |
| NEEDS_REVIEW | Low Quality | 18 |
| NEEDS_REVIEW | Borderline | 15 |
| REJECTED | Hate Speech | 12 |
| REJECTED | Threat | 9 |
| REJECTED | Profanity | 3 |
