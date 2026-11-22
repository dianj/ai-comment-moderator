"""Browser tests (Playwright): comment text is shown as text, never run as HTML/JS."""
import httpx
import pytest

from conftest import ADMIN_TOKEN

pytestmark = pytest.mark.e2e

XSS = '<img src=x onerror="window.__xss = (window.__xss || 0) + 1">'


def test_approved_comment_with_html_is_shown_as_text(page, app_url, fake_lm):
    fake_lm.verdict("APPROVED", "Clean", 0, "OK")
    httpx.post(f"{app_url}/api/comments", json={"author": XSS, "content": XSS})

    page.goto(app_url)
    page.wait_for_selector("#publicCommentsList .comment-item")
    assert page.evaluate("window.__xss") is None
    assert page.locator("#publicCommentsList").get_by_text(XSS).count() >= 1


def test_feedback_banner_does_not_run_model_text(page, app_url, fake_lm):
    """The model's `reason` is untrusted too: it can echo the comment back."""
    fake_lm.verdict("REJECTED", "Spam", 90, f"Коментарът съдържа {XSS}")
    page.goto(app_url)
    page.fill("#contentInput", "нещо")
    page.click("#submitBtn")
    page.wait_for_selector("#feedbackBanner", state="visible")
    assert page.evaluate("window.__xss") is None
    assert XSS in page.inner_text("#feedbackBanner")


def test_admin_log_shows_html_as_text_after_login(page, app_url, fake_lm):
    fake_lm.verdict("REJECTED", "Spam", 90, XSS)
    httpx.post(f"{app_url}/api/comments", json={"author": XSS, "content": XSS})

    page.goto(app_url)
    page.click("#tabAdmin")
    page.fill("#adminTokenInput", ADMIN_TOKEN)
    page.click("#adminLoginBtn")
    page.wait_for_selector("#auditLogList .comment-item")
    assert page.evaluate("window.__xss") is None
    assert page.locator("#auditLogList").get_by_text(XSS).count() >= 1


def test_admin_log_is_hidden_without_login(page, app_url):
    page.goto(app_url)
    page.click("#tabAdmin")
    assert page.locator("#auditLogList .comment-item").count() == 0


def test_english_is_the_default_and_bulgarian_is_remembered(page, app_url):
    page.goto(app_url)
    assert page.get_attribute("html", "lang") == "en"
    assert page.inner_text("#submitBtn") == "Post comment"

    page.click(".lang-btn[data-lang='bg']")
    assert page.inner_text("#submitBtn") == "Публикувай коментар"
    page.reload()
    assert page.get_attribute("html", "lang") == "bg"
    assert page.inner_text("#submitBtn") == "Публикувай коментар"


def test_processing_indicator_while_the_model_works(page, app_url, fake_lm):
    fake_lm.delay_s = 1.5
    fake_lm.verdict("APPROVED", "Clean", 0, "OK")
    page.goto(app_url)
    page.fill("#contentInput", "Great article")
    page.click("#submitBtn")

    page.wait_for_selector("#processing.visible")
    assert page.is_disabled("#submitBtn")
    assert page.locator("#submitBtn .spinner").count() == 0  # one spinner only: in the status box
    assert page.locator("#processing .spinner").count() == 1
    assert page.get_attribute("#contentInput", "readonly") is not None

    page.wait_for_selector("#feedbackBanner.APPROVED", state="visible")
    assert not page.is_visible("#processing")
    assert page.is_enabled("#submitBtn")
    assert page.inner_text("#submitBtn") == "Post comment"
    assert page.get_attribute("#contentInput", "readonly") is None


def test_admin_can_delete_a_comment_after_confirming(page, app_url):
    page.goto(app_url)
    page.click("#tabAdmin")
    page.fill("#adminTokenInput", ADMIN_TOKEN)
    page.click("#adminLoginBtn")
    page.wait_for_selector("#auditLogList .comment-item")
    before = page.locator("#auditLogList .comment-item").count()

    page.once("dialog", lambda d: d.dismiss())          # "Cancel" keeps the comment
    page.locator("#auditLogList .btn-delete").first.click()
    page.wait_for_timeout(300)
    assert page.locator("#auditLogList .comment-item").count() == before

    page.once("dialog", lambda d: d.accept())
    page.locator("#auditLogList .btn-delete").first.click()
    page.wait_for_function(f"document.querySelectorAll('#auditLogList .comment-item').length === {before - 1}")


def test_waiting_messages_change_as_time_passes(page, app_url, fake_lm):
    """Real stages are 10/20/30 s; the test compresses them to keep the run short."""
    page.add_init_script("window.__slowHints = [[0.4, 'processingSlow'], [0.8, 'processingSlower'], [1.2, 'processingSlowest']]")
    fake_lm.delay_s = 2.0
    page.goto(app_url)
    page.fill("#contentInput", "Great article")
    page.click("#submitBtn")

    hint = page.locator("#processingHint")
    for text in ("This can take up to a minute.", "Still checking. Some comments need a closer look.",
                 "Almost there. Thanks for your patience."):
        page.wait_for_function("t => document.getElementById('processingHint').textContent === t", arg=text)
        assert hint.is_visible()
    page.wait_for_selector("#feedbackBanner", state="visible")
    assert not page.is_visible("#processing")


def _login(page, app_url):
    page.goto(app_url)
    page.click("#tabAdmin")
    page.fill("#adminTokenInput", ADMIN_TOKEN)
    page.click("#adminLoginBtn")
    page.wait_for_selector("#adminFilters", state="visible")


def test_admin_filters_status_search_and_reset(page, app_url, fake_lm):
    fake_lm.verdict("NEEDS_REVIEW", "Low Quality", 10, "test post")
    httpx.post(f"{app_url}/api/comments", json={"author": "Tester", "content": "Testing testing"})
    _login(page, app_url)
    items = page.locator("#auditLogList .comment-item")
    assert items.count() == 4

    page.click(".chip[data-status='NEEDS_REVIEW']")
    page.wait_for_function("document.querySelectorAll('#auditLogList .comment-item').length === 1")
    assert "Testing testing" in items.first.inner_text()
    assert page.locator(".chip[data-status='NEEDS_REVIEW'] .chip-count").inner_text() == "1"

    page.click(".chip[data-status='']")
    page.wait_for_function("document.querySelectorAll('#auditLogList .comment-item').length === 4")
    page.fill("#filterSearch", "crypto")
    page.wait_for_function("document.querySelectorAll('#auditLogList .comment-item').length === 1")
    assert "CRYPTO" in items.first.inner_text()

    page.select_option("#filterCategory", "Clean")
    page.wait_for_selector("#auditLogList .empty")

    page.click("#filterReset")
    page.wait_for_function("document.querySelectorAll('#auditLogList .comment-item').length === 4")
    assert page.input_value("#filterSearch") == ""


def test_admin_load_more_pages_through_the_log(page, app_url, fake_lm):
    import server
    server.rate_limiter.reset()
    for i in range(20):  # 3 demo comments + 20 = 23, page size is 20
        fake_lm.verdict("APPROVED", "Clean", 0, "ok")
        server.rate_limiter.reset()
        httpx.post(f"{app_url}/api/comments", json={"author": "Bulk", "content": f"Comment {i}"})
    _login(page, app_url)
    assert page.locator("#auditLogList .comment-item").count() == 20
    assert page.inner_text("#resultInfo") == "Showing 20 of 23"
    page.click("#loadMoreBtn")
    page.wait_for_function("document.querySelectorAll('#auditLogList .comment-item').length === 23")
    assert not page.is_visible("#loadMoreBtn")
