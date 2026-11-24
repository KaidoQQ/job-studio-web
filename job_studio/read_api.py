"""Small read models shared by the HTTP endpoints used by MCP clients."""

from datetime import datetime, timedelta, timezone

from .core import NEWEST_ORDER, connect

VACANCY_FIELDS = "id,title,company,location,source,status,url,published_at,expires_at"


def _limit(value):
    if not 1 <= value <= 50:
        raise ValueError("Use limit 1..50")
    return value


def vacancies(query="", status="", offset=0, limit=20):
    _limit(limit)
    if offset < 0:
        raise ValueError("Use offset >= 0")
    filters = []
    params = []
    if status:
        filters.append("status=?")
        params.append(status)
    if query:
        # instr treats %, _ and backslashes as literal search characters.
        text = " || ' ' || ".join(
            f"coalesce({k},'')" for k in ("title", "company", "location", "source")
        )
        filters.append(f"instr(casefold({text}), ?) > 0")
        params.append(query.casefold())
    where = " WHERE " + " AND ".join(filters) if filters else ""
    with connect() as db:
        db.create_function("casefold", 1, str.casefold, deterministic=True)
        # Keep total and page consistent when a collector inserts vacancies.
        db.execute("BEGIN")
        total = db.execute("SELECT count(*) FROM jobs" + where, params).fetchone()[0]
        rows = db.execute(
            f"SELECT {VACANCY_FIELDS} FROM jobs"
            + where
            + " ORDER BY "
            + NEWEST_ORDER
            + ", id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        return {
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "jobs": [dict(row) for row in rows],
        }


def events(after_id=0, limit=20):
    _limit(limit)
    with connect() as db:
        rows = []
        if table_exists(db, "application_events"):
            # Preserve the existing 150-event retention window, including for stale cursors.
            rows = [
                dict(row)
                for row in db.execute(
                    """
                SELECT id,job_id,state,message,url,created FROM application_events
                WHERE id>? AND id IN (SELECT id FROM application_events ORDER BY id DESC LIMIT 150)
                ORDER BY id LIMIT ?
            """,
                    (after_id, limit),
                )
            ]
        return {"events": rows, "next_cursor": rows[-1]["id"] if rows else after_id}


def table_exists(db, name):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()


def status(run, application, parse_plus):
    now = datetime.now(timezone.utc)
    with connect() as db:
        total, fresh = db.execute(
            """SELECT count(*), count(CASE WHEN
            julianday(published_at) BETWEEN julianday(?) AND julianday(?)
            AND status NOT IN ('applied','archived') THEN 1 END) FROM jobs""",
            ((now - timedelta(days=1)).isoformat(), now.isoformat()),
        ).fetchone()
        last = None
        if application.get("job_id") and table_exists(db, "applications"):
            last = db.execute(
                "SELECT state FROM applications WHERE job_id=?",
                (application["job_id"],),
            ).fetchone()
    outcome = last[0] if last else None
    questions = application.get("questions", []) if application["waiting"] else []
    if application["waiting"]:
        action = "answer_questions" if questions else "manual_action"
    elif application["running"]:
        action = "wait"
    elif outcome in ("uncertain", "submitting"):
        action = "verify_submission"
    else:
        action = "none"
    app = {k: application.get(k) for k in ("running", "waiting", "job_id", "url")}
    app.update(
        message=application.get("message", "")[:240],
        questions=questions,
        outcome=outcome,
        next_action=action,
    )
    return {
        "run": {"running": run["running"], "message": run["message"][:240]},
        "application": app,
        "parse_plus": {k: parse_plus.get(k) for k in ("running", "message", "job_id")},
        "job_count": total,
        "new_last_24h": fresh,
    }
