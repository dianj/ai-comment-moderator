"""SQLite storage: the comments and an append-only audit log of every moderation event."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

STATUSES = ("APPROVED", "REJECTED", "NEEDS_REVIEW")
SORT_ORDERS = {
    "newest": "id DESC",
    "oldest": "id ASC",
    "toxic": "toxicity_score DESC, id DESC",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _unicode_lower(value):
    # SQLite's LOWER() and LIKE only fold ASCII; this also handles Cyrillic.
    return value.lower() if isinstance(value, str) else value


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("ulower", 1, _unicode_lower, deterministic=True)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author TEXT,
                content TEXT,
                status TEXT,          -- APPROVED, REJECTED, NEEDS_REVIEW
                category TEXT,
                toxicity_score INTEGER,
                ai_reason TEXT,
                created_at TEXT
            )""")
        # Columns added after the first version; older databases get them on start-up.
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(comments)")}
        for column in ("decided_by", "reviewed_by", "reviewed_at"):
            if column not in existing:
                conn.execute(f"ALTER TABLE comments ADD COLUMN {column} TEXT")
        # Append-only: rows are only ever inserted. A deleted comment keeps its history.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS moderation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                comment_id INTEGER NOT NULL,
                at TEXT NOT NULL,
                actor TEXT NOT NULL,      -- rule | ai | fallback | human
                action TEXT NOT NULL,     -- created | override | deleted
                from_status TEXT,
                to_status TEXT,
                details TEXT              -- JSON: model, prompt version, latency, raw answer, findings
            )""")
        if conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0] == 0:
            now = _now()
            conn.executemany(
                "INSERT INTO comments (author, content, status, category, toxicity_score, ai_reason,"
                " created_at, decided_by) VALUES (?, ?, ?, ?, ?, ?, ?, 'seed')",
                [
                    ("Мария Иванова", "Страхотна статия! Много полезно обяснение за локалните AI модели.",
                     "APPROVED", "Clean", 2, "Constructive and polite feedback.", now),
                    ("Alex Petrov", "Great breakdown of the architecture, looking forward to part 2!",
                     "APPROVED", "Clean", 0, "Positive community comment.", now),
                    ("SpamBot99", "BUY CHEAP CRYPTO NOW!!! Visit http://scam-link.example",
                     "REJECTED", "Spam", 88, "Unsolicited promotional spam and suspicious link.", now),
                ])


def _event(conn, comment_id, actor, action, from_status, to_status, details=None):
    conn.execute(
        "INSERT INTO moderation_events (comment_id, at, actor, action, from_status, to_status, details)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (comment_id, _now(), actor, action, from_status, to_status,
         json.dumps(details, ensure_ascii=False) if details else None))


def add_comment(author, content, decision, details) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO comments (author, content, status, category, toxicity_score, ai_reason,"
            " created_at, decided_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (author, content, decision.status, decision.category, decision.toxicity_score, decision.reason,
             datetime.now().strftime("%Y-%m-%d %H:%M"), decision.decided_by))
        _event(conn, cur.lastrowid, decision.decided_by, "created", None, decision.status, details)
        return cur.lastrowid


def set_status(comment_id: int, status: str) -> bool:
    """A moderator's decision. Returns False if the comment does not exist."""
    with connect() as conn:
        row = conn.execute("SELECT status FROM comments WHERE id = ?", (comment_id,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE comments SET status = ?, reviewed_by = 'human', reviewed_at = ? WHERE id = ?",
                     (status, _now(), comment_id))
        _event(conn, comment_id, "human", "override", row["status"], status)
        return True


def delete_comment(comment_id: int) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT status FROM comments WHERE id = ?", (comment_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        _event(conn, comment_id, "human", "deleted", row["status"], None)
        return True


def public_comments():
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, author, content, toxicity_score, created_at FROM comments"
            " WHERE status = 'APPROVED' ORDER BY id DESC")]


def admin_comments(status: str | None, category: str | None, min_toxicity: int, q: str | None,
                   sort: str, limit: int, offset: int) -> dict:
    # Filters other than status; status counts are computed under these, so each status chip
    # in the UI can show how many comments it would list.
    where, params = ["toxicity_score >= ?"], [min_toxicity]
    if category:
        where.append("category = ?")
        params.append(category)
    if q and q.strip():
        where.append("instr(ulower(author || ' ' || content), ?) > 0")  # literal match, no LIKE wildcards
        params.append(q.strip().lower())

    with connect() as conn:
        base = " AND ".join(where)
        counts = {r["status"]: r["n"] for r in conn.execute(
            f"SELECT status, COUNT(*) AS n FROM comments WHERE {base} GROUP BY status", params)}
        status_counts = {"ALL": sum(counts.values()), **{s: counts.get(s, 0) for s in STATUSES}}
        if status:
            base += " AND status = ?"
            params = params + [status]
        total = conn.execute(f"SELECT COUNT(*) FROM comments WHERE {base}", params).fetchone()[0]
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM comments WHERE {base} ORDER BY {SORT_ORDERS[sort]} LIMIT ? OFFSET ?",
            params + [limit, offset])]
        categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM comments ORDER BY category")]
    return {"audit_log": rows, "total": total, "status_counts": status_counts, "categories": categories}


def events(comment_id: int) -> list[dict]:
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM moderation_events WHERE comment_id = ? ORDER BY id", (comment_id,))]
    for r in rows:
        r["details"] = json.loads(r["details"]) if r["details"] else None
    return rows
