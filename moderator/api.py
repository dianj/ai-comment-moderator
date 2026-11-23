"""HTTP API and the single-page UI."""
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import config, db, pipeline


class RateLimiter:
    """Sliding one-minute window per client key (IP). In memory: enough for a single-process demo."""

    def __init__(self, limit, window_s=60.0):
        self.limit, self.window_s = limit, window_s
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self):
        with self.lock:
            self.hits.clear()


rate_limiter = RateLimiter(config.RATE_LIMIT_PER_MINUTE)


def require_admin(x_admin_token: str = Header(default="")):
    if not secrets.compare_digest(x_admin_token.encode(), config.ADMIN_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Admin token required.")


class CommentSubmission(BaseModel):
    author: str = Field(default="", max_length=config.MAX_AUTHOR_CHARS)
    content: str = Field(max_length=config.MAX_COMMENT_CHARS)


class ModerationAction(BaseModel):
    comment_id: int
    new_status: Literal["APPROVED", "REJECTED"]


app = FastAPI(title="AI Content Moderation Guardrail Agent")
db.init_db()


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return config.INDEX_HTML.read_text(encoding="utf-8")


@app.get("/api/comments")
async def get_comments():
    """Public feed: approved comments only. Blocked ones may contain PII and stay in the admin log."""
    return JSONResponse({"public": db.public_comments()})


@app.post("/api/comments")
async def post_comment(payload: CommentSubmission, request: Request):
    author = payload.author.strip() or "Anonymous"
    content = payload.content.strip()
    if not content:
        return JSONResponse({"error": "Comment cannot be empty."}, status_code=400)
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(client_ip):
        return JSONResponse({"error": "Too many comments. Please wait a minute."}, status_code=429)

    result = await pipeline.moderate(author, content)
    d = result.decision
    comment_id = db.add_comment(author, content, d, result.details)
    return JSONResponse({"id": comment_id, "status": d.status, "category": d.category,
                         "toxicity_score": d.toxicity_score, "reason": d.reason})


@app.get("/api/admin/comments", dependencies=[Depends(require_admin)])
async def get_audit_log(
    status: Literal["APPROVED", "REJECTED", "NEEDS_REVIEW"] | None = None,
    category: str | None = Query(default=None, max_length=50),
    min_toxicity: int = Query(default=0, ge=0, le=100),
    q: str | None = Query(default=None, max_length=200),
    sort: Literal["newest", "oldest", "toxic"] = "newest",
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Moderator view: every comment, filtered, sorted and paged on the server."""
    return JSONResponse(db.admin_comments(status, category, min_toxicity, q, sort, limit, offset))


@app.get("/api/admin/comments/{comment_id}/events", dependencies=[Depends(require_admin)])
async def get_events(comment_id: int):
    """The audit trail of one comment: who decided what, when, and with which model and prompt."""
    return JSONResponse({"events": db.events(comment_id)})


@app.post("/api/moderate", dependencies=[Depends(require_admin)])
async def manual_override(action: ModerationAction):
    if not db.set_status(action.comment_id, action.new_status):
        raise HTTPException(status_code=404, detail="Comment not found.")
    return JSONResponse({"status": "updated"})


@app.delete("/api/admin/comments/{comment_id}", dependencies=[Depends(require_admin)])
async def delete_comment(comment_id: int):
    """Permanently remove a comment, e.g. one that contains someone's personal data."""
    if not db.delete_comment(comment_id):
        raise HTTPException(status_code=404, detail="Comment not found.")
    return JSONResponse({"status": "deleted"})
