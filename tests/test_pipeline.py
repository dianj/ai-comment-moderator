"""Pipeline and policy through the API: which cases skip the LLM, how the policy overrules
inconsistent model answers, what the model is asked, and what the audit log records."""
import json

import pytest

from moderator import policy


def post(client, content, author="Тест"):
    r = client.post("/api/comments", json={"author": author, "content": content})
    assert r.status_code == 200, r.text
    return r.json()


def events(client, admin_headers, comment_id):
    r = client.get(f"/api/admin/comments/{comment_id}/events", headers=admin_headers)
    assert r.status_code == 200
    return r.json()["events"]


# --- detectors decide clear cases without the LLM --------------------------------------------

def test_pii_is_rejected_without_calling_the_llm(client, fake_lm):
    body = post(client, "ЕГН-то на съседа ми е 8503154126")
    assert (body["status"], body["category"]) == ("REJECTED", "PII")
    assert "ЕГН" in body["reason"]                      # the reason follows the comment's language
    assert fake_lm.requests == []


def test_pii_in_the_author_field_is_caught_too(client, fake_lm):
    body = post(client, "Great article", author="Call me 0888 123 456")
    assert body["status"] == "REJECTED"
    assert fake_lm.requests == []


def test_punctuation_only_goes_to_review_without_the_llm(client, fake_lm):
    body = post(client, "...")
    assert (body["status"], body["category"]) == ("NEEDS_REVIEW", "Low Quality")
    assert fake_lm.requests == []


def test_an_invalid_egn_still_goes_to_the_llm(client, fake_lm):
    fake_lm.verdict("APPROVED", "Clean", 0, "Order question.")
    assert post(client, "Номерът на поръчката ми е 4102938475")["status"] == "APPROVED"
    assert len(fake_lm.requests) == 1


# --- what the model is asked ---------------------------------------------------------------

def test_request_uses_json_schema_and_reasoning_setting(client, fake_lm):
    post(client, "Nice post")
    req = fake_lm.requests[-1]
    assert req["response_format"]["type"] == "json_schema"
    enum = req["response_format"]["json_schema"]["schema"]["properties"]["category"]["enum"]
    assert {"Threat", "Harassment", "Low Quality"} <= set(enum)
    assert req["reasoning_effort"] == "none"


# --- the policy overrules inconsistent answers -----------------------------------------------

@pytest.mark.parametrize("model, expected_status", [
    (("APPROVED", "Threat", 90, "x"), "REJECTED"),          # blocked category wins over the model's decision
    (("APPROVED", "Harassment", 60, "x"), "NEEDS_REVIEW"),  # abusive is never auto-published
    (("NEEDS_REVIEW", "Harassment", 40, "x"), "NEEDS_REVIEW"),
    (("REJECTED", "Profanity", 90, "x"), "REJECTED"),
    (("REJECTED", "Clean", 5, "x"), "NEEDS_REVIEW"),         # "rejected but clean" contradicts itself
    (("APPROVED", "Clean", 65, "x"), "NEEDS_REVIEW"),        # clean but scored toxic
    (("APPROVED", "Clean", 10, "x"), "APPROVED"),
    (("REJECTED", "Borderline", 50, "x"), "NEEDS_REVIEW"),
])
def test_policy_rules(client, fake_lm, model, expected_status):
    fake_lm.verdict(*model)
    assert post(client, "some comment")["status"] == expected_status


def test_policy_rule_names_are_recorded(client, fake_lm, admin_headers):
    fake_lm.verdict("APPROVED", "Threat", 90, "threat")
    cid = post(client, "some comment")["id"]
    assert events(client, admin_headers, cid)[0]["details"]["rule"] == "blocked-category"


@pytest.mark.parametrize("raw", [
    "Sure! Looks fine to me.",
    json.dumps({"decision": "APPROVED", "category": "Nice", "toxicity_score": 0, "reason": "x"}),
    json.dumps({"decision": "APPROVED", "category": "Clean", "toxicity_score": 150, "reason": "x"}),
    json.dumps({"decision": "APPROVED", "category": "Clean"}),
])
def test_invalid_model_answers_fail_closed(client, fake_lm, raw):
    fake_lm.raw(raw)
    body = post(client, "some comment")
    assert (body["status"], body["category"]) == ("NEEDS_REVIEW", "System Fallback")
    assert body["reason"] == policy.FALLBACK_REASON


# --- audit log -------------------------------------------------------------------------------

def test_ai_decision_is_audited_with_model_and_prompt_version(client, fake_lm, admin_headers):
    fake_lm.verdict("APPROVED", "Clean", 3, "Fine.")
    cid = post(client, "Nice post")["id"]
    [created] = events(client, admin_headers, cid)
    assert (created["actor"], created["action"], created["to_status"]) == ("ai", "created", "APPROVED")
    d = created["details"]
    assert d["model"] == "gemma-4-26b-a4b-it" and d["prompt_version"] and d["model_decision"] == "APPROVED"
    assert '"category": "Clean"' in d["raw"]
    assert d["llm_latency_ms"] >= 0


def test_rule_decision_is_audited_with_findings(client, admin_headers):
    cid = post(client, "Обадете се на 0888 123 456")["id"]
    [created] = events(client, admin_headers, cid)
    assert created["actor"] == "rule"
    assert created["details"]["findings"] == [{"kind": "phone", "value": "0888 123 456"}]


def test_overrides_and_delete_are_appended_to_the_history(client, fake_lm, admin_headers):
    fake_lm.verdict("NEEDS_REVIEW", "Borderline", 40, "sarcasm")
    cid = post(client, "Sure, another expert")["id"]
    for status in ("APPROVED", "REJECTED"):
        client.post("/api/moderate", json={"comment_id": cid, "new_status": status}, headers=admin_headers)
    client.delete(f"/api/admin/comments/{cid}", headers=admin_headers)

    history = [(e["actor"], e["action"], e["from_status"], e["to_status"]) for e in events(client, admin_headers, cid)]
    assert history == [
        ("ai", "created", None, "NEEDS_REVIEW"),
        ("human", "override", "NEEDS_REVIEW", "APPROVED"),
        ("human", "override", "APPROVED", "REJECTED"),
        ("human", "deleted", "REJECTED", None),
    ]


def test_events_need_the_admin_token(client):
    assert client.get("/api/admin/comments/1/events").status_code == 401


def test_override_of_unknown_comment_is_404(client, admin_headers):
    r = client.post("/api/moderate", json={"comment_id": 9999, "new_status": "APPROVED"}, headers=admin_headers)
    assert r.status_code == 404
