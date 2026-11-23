# The decision gate

An automatic decision publishes a comment or rejects it without a person. The main model call returns a category, a
decision and a reason, and it can be confidently wrong: a polite Bulgarian disagreement ("Не съм съгласен, но статията
е добра.") was labelled *Low Quality* with 93 % probability in an early probe with a category question. The decision
gate puts a **measured probability** next to every automatic decision and sends the comment to a person when that
probability is not high enough.

## The pipeline

```
comment ──► detectors ──► (clear case) ──────────────────────────────────────────► policy
                 │
                 └──► main model call (JSON: category, decision, reason) ──┐
                 └──► gate (same model, in parallel):                      │
                        closed question → one letter (A publish,           │
                        B block, C review) → first-token log-probabilities  ├──► policy ──► APPROVED / REJECTED
                        → keep A/B/C, renormalise → temperature (fitted     │              stands only if the gate
                        on labelled comments) → probability                 │              agrees with p ≥ threshold;
                        → act / confirm / escalate                          ┘              otherwise NEEDS_REVIEW
```

- **Typed answer.** The gate is asked one closed question and must answer with a single letter. The comment is
  wrapped as data (`<<input>> … <</input>>`, the closing tag cannot appear inside); text that claims a decision was
  already made changes nothing.
- **Probabilities.** The first token's alternatives (`top_logprobs`) are read; case and space variants (`a`, ` A`)
  count for `A`, other tokens are dropped, the three answers are renormalised. If the allowed letters carry less than
  half of the probability mass, or the server returns no log-probabilities, the answer is **unknown**.
- **Calibration.** One temperature per model and prompt (`evals/decisions/calibration/moderator.outcome.json`),
  fitted on labelled comments; never below 1, so calibration can make the gate less confident, never more. A file
  fitted for another model or another prompt is ignored, and the thresholds become one band stricter.
- **Policy** (`moderator/decisions.py`):

  | Gate answer | ACT if p ≥ | CONFIRM | ESCALATE if p < |
  |---|---|---|---|
  | publish (a leak is the costly mistake) | 0.95 | 0.70 – 0.95 | 0.70 |
  | block, review | 0.85 | 0.60 – 0.85 | 0.60 |

  An automatic `APPROVED` or `REJECTED` stands only if the gate gives the same outcome **and** ACT. Otherwise the
  comment goes to the review queue with the rule `gate-disagrees`, `gate-unsure` (confirm band), `gate-uncertain`
  (below it) or `gate-unknown`. **Two keys:** the gate can only send a comment to a person; it never publishes or
  rejects anything the policy did not, and it never takes a comment out of review.
- **Records.** The audit log stores the gate's record with every AI decision: question, model, prompt hash, raw and
  calibrated probabilities, chosen answer, action, temperature, latency and a SHA-256 of the input (not the text).

## Measured

Labelled set: `evals/decisions/moderator.outcome.jsonl`, 101 comments: the 69 eval comments the model sees (the
detectors decide the other 7) plus 32 written for the gate (attempts to steer it, mixed messages, quoted insults,
polite spam, a threat "just kidding", veiled hate, Bulgarian). Several answers may be correct for a case (e.g. block
or review).

| Model | Accuracy | ECE | Brier | Fitted T | Auto-acted at p ≥ 0.95 (accuracy) | Latency p50 |
|---|---|---|---|---|---|---|
| Gemma 4 26B | 101/101 | 0.006 | 0.0004 | 1.0 | 97 % (100 %) | 0.77 s |
| Qwen 3.8 27B | 97/101 | 0.105 | 0.070 | 1.0 | 43 % (100 %) | 1.13 s |

- **Gemma** answered the outcome question correctly on every case, with high confidence where it was right and lower
  where a person should look (an arson call at 0.85, a borderline comment at 0.67). There was no over-confidence to
  correct, so T stays 1. With a set that has no errors, an unbounded fit would push T towards 0 and every answer to
  100 %: hence the floor at 1.
- **Qwen** was less confident (ECE 0.105, under-confident) and wrong on 4 hard cases, each with p below 0.8, so none
  of them would have been acted on automatically. Above 0.8 it was right on every case (72 of 101). The thresholds therefore
  cost Qwen automation, not safety. Its calibration is in `evals/decisions/calibration/qwen3.8-27b/`.
- **End to end** (`evals/results/gate-on.md`, Gemma, 76 comments): 0 leaked, 0 over-blocked, 75/76 decisions as
  labelled. The gate sent 3 comments to review where it disagreed with the main call (an indirect arson call the
  main call rejected, an injection it rejected, a hard negative it approved); one of them counts as a miss, because
  that case expects an automatic rejection.
- **Latency:** the gate runs beside the main call. Measured back to back on the same machine: p50 3.06 s without
  the gate, 3.39 s with it (+0.33 s).

Reliability diagrams: [Gemma](../evals/decisions/calibration/moderator.outcome.svg),
[Qwen](../evals/decisions/calibration/qwen3.8-27b/moderator.outcome.svg). Reports:
[Gemma](../evals/decisions/calibration/moderator.outcome.md),
[Qwen](../evals/decisions/calibration/qwen3.8-27b/moderator.outcome.md).

## Reproduce

```bash
python evals/decisions/build_cases.py                                     # the labelled set
python -m moderator.decide.cli collect --question moderator.outcome       # ask the model (LM Studio), save raw answers
python -m moderator.decide.cli calibrate --question moderator.outcome     # fit T, write calibration, report, diagram
python evals/run_evals.py --report gate-on.md                             # the whole pipeline with the gate
```

`DECISION_GATE=0` switches the gate off (the policy then decides from the main verdict alone).

## Limitations

- Needs a server that returns log-probabilities (LM Studio does). Without them every automatic decision goes to
  review: safe, but no automation.
- A calibration belongs to one model and one prompt. Changing either needs a new `collect` + `calibrate`.
- 101 cases is a small calibration set, and the prompts were tuned on the same comments: a held-out set written by
  someone else would be the honest next measurement.
- One more model call per comment (in parallel; +0.33 s measured).
