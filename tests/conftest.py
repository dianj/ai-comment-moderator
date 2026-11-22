"""Shared fixtures: a fake LM Studio, a fresh database per test and the real app.

Environment variables must be set before `server` is imported, because it reads them at import time.
"""
import os
import socket
import sys
import tempfile
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_lmstudio import FakeLMStudio  # noqa: E402

ADMIN_TOKEN = "test-admin-token"
RATE_LIMIT = 5

_TMP_DIR = tempfile.mkdtemp(prefix="moderator-tests-")
_FAKE = FakeLMStudio().start()
os.environ["MODERATOR_SKIP_DOTENV"] = "1"
os.environ["MODERATION_DB"] = os.path.join(_TMP_DIR, "test_moderation.db")
os.environ["LMSTUDIO_URL"] = _FAKE.base_url
os.environ["ADMIN_TOKEN"] = ADMIN_TOKEN
os.environ["RATE_LIMIT_PER_MINUTE"] = str(RATE_LIMIT)

import server  # noqa: E402  (must come after the environment is prepared)


@pytest.fixture(scope="session")
def fake_lm():
    yield _FAKE
    _FAKE.stop()


@pytest.fixture(autouse=True)
def clean_state(fake_lm):
    """Every test starts from the seeded demo comments, an empty script and a fresh rate limit."""
    fake_lm.reset()
    if os.path.exists(os.environ["MODERATION_DB"]):
        os.remove(os.environ["MODERATION_DB"])
    server.init_db()
    limiter = getattr(server, "rate_limiter", None)
    if limiter is not None:
        limiter.reset()
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(server.app)


@pytest.fixture()
def admin_headers():
    return {"X-Admin-Token": ADMIN_TOKEN}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_url(fake_lm):
    """Run the real FastAPI app (uvicorn) in a background thread."""
    import uvicorn

    port = _free_port()
    uv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not uv.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(timeout=5)
