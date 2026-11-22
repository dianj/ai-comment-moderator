"""Admin log filtering, sorting and paging. Demo seed: #1 APPROVED Clean 2, #2 APPROVED Clean 0, #3 REJECTED Spam 88."""
import pytest


@pytest.fixture()
def seeded(client, fake_lm):
    """Add a mix of verdicts on top of the 3 demo comments (ids 4-8)."""
    for verdict, text in [
        (("REJECTED", "Profanity", 92, "insult"), "You idiot"),
        (("NEEDS_REVIEW", "Low Quality", 10, "test post"), "Testing testing"),
        (("NEEDS_REVIEW", "Borderline", 45, "sarcasm"), "Sure, another expert"),
        (("REJECTED", "PII", 75, "phone"), "Call Ivan on 0888 123 456"),
        (("APPROVED", "Clean", 5, "fine"), "Great article about Gemma"),
    ]:
        fake_lm.verdict(*verdict)
        assert client.post("/api/comments", json={"author": "Тест", "content": text}).status_code == 200


def get(client, admin_headers, **params):
    r = client.get("/api/admin/comments", params=params, headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()


def ids(body):
    return [c["id"] for c in body["audit_log"]]


def test_no_filters_returns_everything_newest_first(client, admin_headers, seeded):
    body = get(client, admin_headers)
    assert ids(body) == [8, 7, 6, 5, 4, 3, 2, 1]
    assert body["total"] == 8


def test_filter_by_status(client, admin_headers, seeded):
    assert ids(get(client, admin_headers, status="NEEDS_REVIEW")) == [6, 5]
    assert ids(get(client, admin_headers, status="REJECTED")) == [7, 4, 3]


def test_filter_by_category(client, admin_headers, seeded):
    assert ids(get(client, admin_headers, category="Low Quality")) == [5]


def test_filter_by_minimum_toxicity(client, admin_headers, seeded):
    assert ids(get(client, admin_headers, min_toxicity=70)) == [7, 4, 3]


def test_search_in_author_and_text_is_case_insensitive(client, admin_headers, seeded):
    assert ids(get(client, admin_headers, q="gemma")) == [8]
    assert ids(get(client, admin_headers, q="0888")) == [7]


def test_search_treats_wildcards_literally(client, admin_headers, seeded):
    assert ids(get(client, admin_headers, q="%")) == []


def test_filters_combine(client, admin_headers, seeded):
    assert ids(get(client, admin_headers, status="REJECTED", min_toxicity=80)) == [4, 3]


def test_sort_by_toxicity_and_oldest(client, admin_headers, seeded):
    assert ids(get(client, admin_headers, sort="toxic"))[:3] == [4, 3, 7]
    assert ids(get(client, admin_headers, sort="oldest"))[:3] == [1, 2, 3]


def test_paging(client, admin_headers, seeded):
    first = get(client, admin_headers, limit=3, offset=0)
    second = get(client, admin_headers, limit=3, offset=3)
    assert ids(first) == [8, 7, 6] and ids(second) == [5, 4, 3]
    assert first["total"] == second["total"] == 8


def test_counts_for_the_filter_bar(client, admin_headers, seeded):
    """Status counts ignore the status filter (so every chip shows its number); categories list all in use."""
    body = get(client, admin_headers, status="REJECTED")
    assert body["status_counts"] == {"ALL": 8, "APPROVED": 3, "REJECTED": 3, "NEEDS_REVIEW": 2}
    assert set(body["categories"]) == {"Clean", "Spam", "Profanity", "Low Quality", "Borderline", "PII"}


def test_invalid_filter_values_are_refused(client, admin_headers):
    for params in ({"status": "DELETED"}, {"sort": "random"}, {"min_toxicity": 101}, {"limit": 1000}):
        assert client.get("/api/admin/comments", params=params, headers=admin_headers).status_code == 422, params
