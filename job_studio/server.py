"""Run with python -m job_studio.server; serves only the loopback interface."""

import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .applications import (
    ApplicationRunner,
    applicant,
    application_events,
    application_history,
    record,
    save_applicant,
)
from .core import (
    DATA,
    NEWEST_ORDER,
    Runner,
    connect,
    detail,
    put,
    save_settings,
    settings,
)
from .parse_plus import ParsePlus

STATIC = Path(__file__).with_name("static")
TOKEN = secrets.token_urlsafe(32)
RUNNER = Runner()
APPLICATIONS = ApplicationRunner()
PARSE_PLUS = ParsePlus(APPLICATIONS)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            return self.reply({"error": "Invalid host"}, 403)
        if self.path == "/":
            body = (
                (STATIC / "index.html")
                .read_text("utf-8")
                .replace("__TOKEN__", TOKEN)
                .encode()
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/studio.css", "/studio.js"):
            body = (STATIC / self.path[1:]).read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                ("text/css" if self.path.endswith(".css") else "text/javascript")
                + "; charset=utf-8",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/health":
            self.reply({"service": "job-studio", "version": 1})
        elif self.path == "/api/state":
            with connect() as db:
                jobs = [
                    dict(row)
                    for row in db.execute("SELECT * FROM jobs ORDER BY " + NEWEST_ORDER)
                ]
            self.reply(
                {
                    "jobs": jobs,
                    "settings": settings(),
                    "run": RUNNER.state,
                    "applicant": applicant(),
                    "application": APPLICATIONS.state,
                    "applications": application_history(),
                    "application_events": application_events(),
                    "parse_plus": PARSE_PLUS.state,
                }
            )
        else:
            self.reply({"error": "Not found"}, 404)

    def do_POST(self):
        if (
            self.headers.get("X-Studio-Token") != TOKEN
            or self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
        ):
            return self.reply({"error": "Forbidden"}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 200000:
                return self.reply({"error": "Request too large"}, 413)
            value = json.loads(self.rfile.read(length) or "{}")
            if self.path == "/api/settings":
                save_settings(value)
            elif self.path == "/api/applicant":
                save_applicant(value)
            elif self.path == "/api/apply":
                APPLICATIONS.start(value["id"])
            elif self.path == "/api/apply/resume":
                if not APPLICATIONS.state["waiting"]:
                    raise ValueError("No application is waiting for input")
                APPLICATIONS.resume.set()
            elif self.path == "/api/apply/answers":
                APPLICATIONS.accept_answers(
                    value["id"], value.get("answers", {}), value.get("remember", False)
                )
            elif self.path == "/api/apply/cancel":
                APPLICATIONS.cancel.set()
            elif self.path == "/api/apply/finish":
                APPLICATIONS.finish_manual(value["id"])
            elif self.path == "/api/parse-plus":
                PARSE_PLUS.start(
                    value["url"].strip(),
                    value.get("title", ""),
                    value.get("apply", False),
                )
            elif self.path == "/api/apply/resolve":
                if APPLICATIONS.state["running"]:
                    raise ValueError(
                        "Stop the active browser workflow before resolving its status"
                    )
                if value.get("result") not in ("submitted", "not_sent"):
                    raise ValueError(
                        "Confirm submitted or not_sent after checking the employer site"
                    )
                record(
                    value["id"],
                    "submitted" if value["result"] == "submitted" else "failed",
                    "Manually verified by user: " + value["result"],
                )
            elif self.path == "/api/key":
                import keyring

                key = value.get("key", "").strip()
                if not key:
                    raise ValueError("Enter a key")
                keyring.set_password("UpWorkAITool", "INFERCOM_API_KEY", key)
            elif self.path == "/api/run":
                if value.get("drafts", True) and not settings()["profile"].strip():
                    raise ValueError(
                        "Save your verified profile before generating letters"
                    )
                if not RUNNER.start(value.get("drafts", True)):
                    return self.reply({"error": "A run is already active"}, 409)
            elif self.path == "/api/stop":
                RUNNER.stop.set()
            elif self.path == "/api/job":
                if value.get("status") not in (
                    "new",
                    "draft",
                    "reviewed",
                    "applied",
                    "archived",
                ):
                    raise ValueError("Invalid status")
                with connect() as db:
                    db.execute(
                        "UPDATE jobs SET draft=?,status=? WHERE id=?",
                        (value["draft"], value["status"], value["id"]),
                    )
            elif self.path == "/api/import":
                put(
                    detail(
                        value["url"],
                        value.get("title", "Imported vacancy"),
                        "Manual import",
                    )
                )
            else:
                return self.reply({"error": "Not found"}, 404)
            self.reply({"ok": True})
        except ValueError as exc:
            self.reply({"error": str(exc)}, 400)
        except Exception as exc:
            self.reply({"error": type(exc).__name__ + ": operation failed"}, 500)


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    DATA.mkdir(exist_ok=True)
    endpoint = DATA / "endpoint.json"
    endpoint.write_text(json.dumps({"url": url, "token": TOKEN}), encoding="utf-8")
    print(url, flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        RUNNER.stop.set()
        APPLICATIONS.cancel.set()
    finally:
        server.server_close()
        if (
            endpoint.exists()
            and json.loads(endpoint.read_text("utf-8")).get("token") == TOKEN
        ):
            endpoint.unlink()


def main():
    from filelock import FileLock, Timeout

    DATA.mkdir(exist_ok=True)
    try:
        with FileLock(str(DATA / "server.lock"), timeout=0):
            serve()
    except Timeout:
        endpoint = DATA / "endpoint.json"
        if endpoint.exists():
            url = json.loads(endpoint.read_text("utf-8"))["url"]
            print(url, flush=True)
            if "--no-browser" not in sys.argv:
                webbrowser.open(url)
        else:
            print("Job Studio is starting; try again shortly.", file=sys.stderr)


if __name__ == "__main__":
    main()
