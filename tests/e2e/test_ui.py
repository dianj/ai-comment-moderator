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

