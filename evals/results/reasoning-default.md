# Moderation eval results

- Date: 2026-11-23 01:47
- Model: `gemma-4-26b-a4b-it` via LM Studio, reasoning effort: `model default`
- Target: `moderator.pipeline.moderate (detectors + LLM + policy)`, prompt `2026-11-23.3`
- Cases: 76 × 1 run(s) = 76 verdicts

## Summary

| Metric | Result |
|---|---|
| Correct decision | 76/76 (100%) |
| **Leaked** (published although it should not be) | 0/47 (0%) |
| **Over-blocked** (acceptable content rejected) | 0/36 (0%) |
| Correct category (when not approved) | 46/46 (100%) |
| LLM/parse fallbacks | 0/76 (0%) |
| Decided by detectors (no LLM call) | 7/76 (9%) |
| Policy overruled the model's decision | 0/76 (0%) |
| Latency p50 / p95 | 12.4s / 24.0s |

## By group

| Group | Correct | Leaked | Over-blocked |
|---|---|---|---|
| clean | 10/10 (100%) | 0 | 0 |
| hard_negative | 16/16 (100%) | 0 | 0 |
| profanity | 7/7 (100%) | 0 | 0 |
| threat | 3/3 (100%) | 0 | 0 |
| hate | 4/4 (100%) | 0 | 0 |
| spam | 5/5 (100%) | 0 | 0 |
| pii | 6/6 (100%) | 0 | 0 |
| injection | 8/8 (100%) | 0 | 0 |
| obfuscation | 5/5 (100%) | 0 | 0 |
| borderline | 6/6 (100%) | 0 | 0 |
| low_quality | 6/6 (100%) | 0 | 0 |

## Failures

None.

## Verdict distribution

| Decision | Category | Count |
|---|---|---|
| APPROVED | Clean | 26 |
| REJECTED | Harassment | 10 |
| REJECTED | Prompt Injection | 8 |
| REJECTED | Spam | 6 |
| REJECTED | PII | 6 |
| NEEDS_REVIEW | Borderline | 6 |
| NEEDS_REVIEW | Low Quality | 6 |
| REJECTED | Hate Speech | 4 |
| REJECTED | Threat | 3 |
| REJECTED | Profanity | 1 |
