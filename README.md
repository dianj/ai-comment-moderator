# AI Content Moderation Guardrail Agent

A real-time, multilingual content moderation pipeline powered by **Gemma 4 (26B)**, **FastAPI**, and **SQLite**, featuring structured JSON verdicts, prompt-injection defense, and human-in-the-loop admin overrides.

## Architecture
```text
[User Comment Form] ──► [FastAPI /api/comments] ──► [Gemma 4 Guardrail (LM Studio)]
                                                               │
                        ┌──────────────────────────────────────┼──────────────────────────────────────┐
                        ▼                                      ▼                                      ▼
               [APPROVED (0-30%)]                    [NEEDS_REVIEW (31-70%)]                [REJECTED (71-100%)]
           Published to Public Feed               Queued in Admin Audit Tab              Blocked + User Feedback
```

## Key Features
* **Semantic & Multilingual Detection:** Detects profanity, hate speech, spam, PII leaks (phone numbers, IDs), and borderline sarcasm across Bulgarian, English, and other languages.
* **Prompt Injection Sandboxing:** Isolates untrusted user text inside `<user_comment>` delimiters and flags jailbreak attempts.
* **Human-in-the-Loop Admin Panel:** Full audit trail in SQLite allowing human moderators to inspect AI toxicity scores and override decisions.

## Quick Start
1. Load `gemma-4-26b-a4b-it` in **LM Studio** and start the local server on `http://localhost:1234/v1`.
2. Install dependencies and run the server:
   ```bash
   pip install -r requirements.txt
   uvicorn server:app --host 0.0.0.0 --port 8000
   ```
3. Open `http://localhost:8000` in your browser.
