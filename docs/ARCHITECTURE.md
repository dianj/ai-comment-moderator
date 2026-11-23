# Architecture

This document explains how the moderator is built and why. The README has the overview and the results.

## The idea: the model classifies, the code decides

The first version of this project gave the whole decision to the LLM: the model returned `APPROVED`,
`REJECTED` or `NEEDS_REVIEW` and the server stored it. That works in a demo, but it has three problems:

1. **Clear cases depend on a model's mood.** A valid Bulgarian personal number (EGN) is personal data whether
   or not the model notices it, and a checksum can tell an EGN from an order number with certainty.
2. **The model can contradict itself.** It can answer `"decision": "APPROVED"` together with
   `"category": "Threat"`, and nothing catches it.
3. **No one can tell afterwards why a comment was blocked.** Which prompt, which model, which rule?

The current design therefore splits the work into layers, each with one job:

```
POST /api/comments
  │
  ├─ 1. Input guard (api.py)        length limits (422), rate limit per IP (429)
  ├─ 2. Detectors (detectors.py)    EGN, IBAN, phone, email, links, content-free text
  │       └─ clear case? ─────────► decision without an LLM call
  ├─ 3. LLM classifier (llm.py)     JSON-schema verdict: decision, category, toxicity, reason
  ├─ 4. Policy (policy.py)          rules turn findings + verdict into the final decision
  └─ 5. Store (db.py)               comment + append-only audit event
```

![Architecture](../ai-comment-moderator_diagram.svg)

## Modules

| Module | Responsibility |
|---|---|
| `moderator/config.py` | All settings, from environment variables and a git-ignored `.env`. Generates and prints an admin token if none is set. |
| `moderator/detectors.py` | Pure functions, no I/O: EGN (date + checksum), IBAN (ISO 7064 mod 97), phone numbers (Bulgarian and `+CC`), email, links, punctuation-only / repeated-character text. |
| `moderator/prompts.py` | The system prompt, its version (`PROMPT_VERSION`), the JSON schema of the verdict and the safe construction of the user message. |
| `moderator/llm.py` | Async OpenAI-compatible client (one per event loop), `response_format: json_schema`, `reasoning_effort`, timeout, Pydantic validation of the answer. |
| `moderator/policy.py` | The decision rules. Every decision carries the name of the rule that made it and who made it (`rule`, `ai`, `fallback`). |
| `moderator/pipeline.py` | Runs the layers in order and collects the audit details. |
| `moderator/db.py` | SQLite: `comments`, the append-only `moderation_events`, admin queries (filters, sort, paging) and a small schema migration for older databases. |
| `moderator/api.py` | FastAPI routes, admin token check, rate limiter, input models. |
| `server.py` | Entry point for `uvicorn server:app`. |
| `index.html` | The whole UI in one file, vanilla JS, English with a Bulgarian switch. |

## Detectors

Detectors run on the author name and the comment text before the LLM.

- **EGN**: 10 digits whose first six are a real date (the month encodes the century: 1–12 → 1900s,
  21–32 → 1800s, 41–52 → 2000s) and whose last digit matches the weighted checksum
  (weights 2, 4, 8, 5, 10, 9, 7, 3, 6, mod 11). An order number such as `4102938475` is not flagged.
- **IBAN**: country code, check digits, then the mod-97 check.
- **Phone**: `+359`/`00359`/`0` followed by 8–9 digits with optional spaces or dashes, and other `+CC` numbers.
  Version numbers, dates and figures such as "16 GB" are not phones (there are tests for that).
- **Email** and **links**: links are recorded, not blocked. A citation link is fine; spam is the model's call.
- **Content-free text**: only punctuation, or a single character repeated at least 4 times. A lone emoji is
  not content-free; 👍 is a reaction.

Personal data → `REJECTED` / `PII`, with a reason in the comment's language that names what was found.
Content-free text → `NEEDS_REVIEW` / `Low Quality`. In both cases the LLM is not called.

Why not Microsoft Presidio? It is the standard library for PII detection, but its recognisers do not cover
Bulgarian identifiers, and it brings a spaCy model for what are here five exact patterns. Writing them
directly keeps them exact, fast and readable, and each has unit tests.

## LLM classifier

- **Untrusted input stays data.** The author name and the text go inside `<user_comment>` tags. Any
  `<user_comment>` or `</user_comment>` inside the text is escaped first, so a comment cannot close the
  block and append a fake "SYSTEM" message. The prompt says that everything in the block is data and that
  attempts to change the task are the category `Prompt Injection`.
- **Structured output.** The request carries a strict JSON schema with enums for the decision and the
  10 categories, an integer range for the toxicity score and a length limit for the reason. The answer is
  validated again with Pydantic. Anything else (prose, an unknown category, a score of 150, a missing field)
  is treated as no answer.
- **Fail closed.** If the model is unreachable, times out or answers invalidly, the comment goes to
  `NEEDS_REVIEW` with a neutral message. Nothing is published without a verdict, and no error details reach
  the user.
- **Reasoning effort.** Gemma 4 reasons before it answers. Measured on a single threat it used about
  2,400 hidden reasoning tokens and 68 seconds for a 59-token answer. `reasoning_effort: "none"` answered
  the same in 2 seconds. On the whole eval set both settings are correct on every case (reasoning off: 228/228 over
  three runs, p95 2.0 s; default reasoning: 76/76, p95 24 s), after two prompt clarifications that only the faster
  mode needed (see the README). The setting is `LLM_REASONING_EFFORT` in `.env`.
- **Async.** The FastAPI handler awaits the model, so one slow comment no longer blocks the server for other
  visitors.

### Categories

`Clean`, `Profanity`, `Harassment`, `Threat`, `Hate Speech`, `Spam`, `PII`, `Prompt Injection`,
`Borderline`, `Low Quality`.

`Threat` and `Harassment` were added after the first evaluation: without them the model labelled every threat
as "Hate Speech", and it spent its longest reasoning on exactly those comments.

## Policy

| Model category | Final decision | Rule name |
|---|---|---|
| Threat, Hate Speech, Spam, PII, Prompt Injection | `REJECTED`, whatever the model's decision was | `blocked-category` |
| Profanity, Harassment | the model's `REJECTED` or `NEEDS_REVIEW`; never `APPROVED` | `abusive-category` |
| Borderline, Low Quality | `NEEDS_REVIEW` | `review-category` |
| Clean, model said `REJECTED` or `NEEDS_REVIEW` | `NEEDS_REVIEW` (the answer contradicts itself) | `clean-but-not-approved` |
| Clean, toxicity ≥ `REVIEW_TOXICITY_THRESHOLD` (40) | `NEEDS_REVIEW` | `clean-but-high-toxicity` |
| Clean | `APPROVED` | `clean` |
| (detector) personal data | `REJECTED` | `pii-detector` |
| (detector) content-free text | `NEEDS_REVIEW` | `empty-text` |
| (no valid answer) | `NEEDS_REVIEW` | `llm-unavailable` |

Every rule has a test in `tests/test_pipeline.py`, including the contradictory model answers.

## Audit log

`moderation_events` is append-only: rows are inserted, never updated. Each row has the comment id, time,
actor (`rule`, `ai`, `fallback`, `human`), action (`created`, `override`, `deleted`), the status before and
after, and a JSON `details` field. For AI decisions the details hold the model, the prompt version, the
reasoning effort, the rule, the model's own decision, the raw answer, the LLM latency and the reasoning
tokens. For detector decisions they hold the findings.

A deleted comment keeps its history (without its text), so the log can still answer "who removed it, and when".
The moderator panel shows this history per comment.

`comments` keeps the current state, plus `decided_by` and `reviewed_by` / `reviewed_at` for the badges in the
admin list. Older databases get the new columns on start-up.

## Security

| Risk | Defence | Test |
|---|---|---|
| Stored XSS through the name, the text or the model's reason | every value is escaped or set with `textContent`; the status is whitelisted before it is used as a CSS class | Playwright: an `<img onerror>` payload is shown as text in the feed, the result banner and the admin log |
| Moderation actions by anyone | `X-Admin-Token` on every admin route, compared in constant time; a random token if none is configured | API: 401 without or with a wrong token |
| Blocked personal data shown to the public | the public feed returns approved comments only, with selected columns | API: a blocked EGN is not in the public response |
| Prompt injection | delimiters with escaping, a strict schema, the policy layer; the model has no tools, so the worst case is a wrong label | eval set: 8 injection cases; API: the tag cannot be closed |
| Flooding and oversized input | per-IP rate limit, length limits checked before the LLM | API tests |
| Leaking internals | errors are logged on the server only | API: a simulated outage message never reaches the client |

These follow the OWASP Top 10 for LLM Applications, mainly *Prompt Injection* and *Improper Output Handling*.

## Tests and evaluation

- **Tests** (`tests/`, pytest + Playwright) use a scripted fake LM Studio (`tests/fake_lmstudio.py`) that
  records every request and can be slow or fail on purpose. They need no GPU and run in CI.
- **Evals** (`evals/`) run the real pipeline and the real model on 76 hand-labelled comments. Each case lists
  the decisions that count as correct and, for harmful content, the acceptable categories. The report
  separates the two errors that matter most: **leaked** (published although it should not be) and
  **over-blocked** (acceptable content rejected). `--repeat` measures consistency, `--regrade` re-scores
  saved answers when a label was wrong.

Workflow for a reported problem: add an eval case that reproduces it, show it failing, change the prompt or
the code, then re-run the whole set to check for regressions.

## Deliberate limits

- **One process.** The rate limiter is in memory and SQLite is a local file. Several workers would need
  a shared store (for example Redis and PostgreSQL).
- **A single admin token** instead of user accounts. Enough to keep the panel closed in a demo; a real
  deployment would put moderators behind proper login, and the audit log would record who they are.
- **Comment language.** The UI is in English and Bulgarian, and the eval set is too. Other languages work
  through the model but are not measured.
