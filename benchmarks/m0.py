"""Run with python -m benchmarks.m0. Writes only synthetic JSON to stdout."""

import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from .fixtures import ANSWER, EMAIL, LETTER, feed, form


class Client:
    """One real FastMCP subprocess. Count UTF-8 JSON-RPC bodies on its stdio pipe."""

    def __init__(self, metrics):
        self.metrics = metrics
        self.seq = 0
        self.process = subprocess.Popen(
            [sys.executable, "-m", "job_studio.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def send(self, method, params, notification=False):
        self.seq += 1
        request = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            request["id"] = self.seq
        data = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode()
        self.process.stdin.write(data + b"\n")
        self.process.stdin.flush()
        if notification:
            return
        raw = self.process.stdout.readline().rstrip(b"\r\n")
        reply = json.loads(raw)
        if "error" in reply:
            raise RuntimeError(reply["error"])
        if method == "tools/call":
            self.metrics["mcp_bytes"] += len(data) + len(raw)
            self.metrics["tools"][params["name"]] += 1
        return reply["result"]

    def call(self, name, **arguments):
        started = time.perf_counter()
        result = self.send("tools/call", {"name": name, "arguments": arguments})
        self.metrics["latencies"].append((time.perf_counter() - started) * 1000)
        if result.get("isError"):
            raise RuntimeError(result["content"])
        return json.loads(result["content"][0]["text"])

    def __enter__(self):
        self.send(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "m0", "version": "1"},
            },
        )
        self.send("notifications/initialized", {}, notification=True)
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.process.stdin.closed:
            return
        self.process.stdin.close()
        self.process.wait(timeout=15)
        self.process.stdout.close()


def wait_for(test):
    deadline = time.monotonic() + 45
    while not test():
        if time.monotonic() > deadline:
            raise TimeoutError("Fixture worker did not reach the expected checkpoint")
        time.sleep(0.025)


def benchmark(folder):
    # Import the service only after selecting an isolated data directory.
    from http.server import ThreadingHTTPServer
    from playwright.sync_api import sync_playwright
    from pypdf import PdfWriter
    from job_studio import core, applications, server
    from job_studio.browser.session import BaseParserPW

    jobs = feed()
    site = {j["url"]: form(i) for i, j in enumerate(jobs[:10])}
    provider = Counter()
    http = Counter()
    metrics = {"tools": Counter(), "latencies": [], "mcp_bytes": 0}
    outcomes = {}
    cv = folder / "fixture.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(str(cv))
    core.save_settings(
        {
            "sources": [{"name": "M0", "url": jobs[0]["url"], "enabled": True}],
            "profile": "Preferred fixture rotation: Morning",
            "keywords": "python",
            "limit": 120,
        }
    )
    applications.save_applicant(
        dict(first_name="Fixture", last_name="Candidate", email=EMAIL, cv_path=str(cv))
    )

    def respond(prompt, cfg):
        if "\nQUESTIONS:\n" in prompt:
            provider["questions"] += 1
            questions = json.loads(prompt.split("\nQUESTIONS:\n")[1])
            return json.dumps(
                {
                    q["id"]: {"answer": ANSWER, "evidence": ANSWER, "needs_user": False}
                    for q in questions
                }
            )
        provider["letter"] += 1
        return LETTER

    def setup(driver):
        driver.playwright_instance = sync_playwright().start()
        driver.browser = driver.playwright_instance.chromium.launch(
            channel=os.getenv("STUDIO_TEST_BROWSER")
        )
        context = driver.browser.new_context(service_workers="block")

        def route(r):
            body = site.get(r.request.url)
            if r.request.method == "GET" and body:
                r.fulfill(content_type="text/html", body=body)
            else:
                r.abort()

        context.route("**/*", route)
        driver.page = context.new_page()

    class Metered(server.Handler):
        def send_header(self, name, value):
            if name.lower() == "content-length":
                http[self.path.partition("?")[0]] += int(value) + int(
                    self.headers.get("Content-Length", 0)
                )
            super().send_header(name, value)

    with ExitStack() as stack:
        for obj, attr, replacement in [
            (core, "public_feed", lambda _: jobs),
            (core, "complete_prompt", respond),
            (BaseParserPW, "_setup_driver", setup),
        ]:
            stack.enter_context(patch.object(obj, attr, replacement))
        service = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), Metered))
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        stack.callback(service.shutdown)
        (folder / "endpoint.json").write_text(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{service.server_port}",
                    "token": server.TOKEN,
                }
            )
        )
        client = stack.enter_context(Client(metrics))
        started = time.perf_counter()
        client.call("collect_vacancies", generate_letters=False)
        wait_for(lambda: not server.RUNNER.lock.locked())
        page = client.call("list_vacancies", limit=10)
        assert [j["url"] for j in page["jobs"]] == list(site)
        cursor = 0
        for i, j in enumerate(page["jobs"]):
            client.call("parse_vacancy", url=j["url"])
            wait_for(lambda: not server.PARSE_PLUS.lock.locked())
            client.call("start_application", job_id=j["id"])
            app = server.APPLICATIONS
            wait_for(lambda: app.state["waiting"] or not app.lock.locked())
            if i == 0:
                assert app.state["waiting"], app.state
                # Disconnect the client while the browser waits; restore via MCP status.
                client.close()
                client = stack.enter_context(Client(metrics))
                status = client.call("studio_status")["application"]
                (question,) = status["questions"]
                assert question["suggestion"] == ANSWER
                client.call(
                    "answer_questions",
                    job_id=j["id"],
                    answers={question["id"]: ANSWER},
                    remember=True,
                )
            wait_for(lambda: not app.lock.locked())
            client.call("studio_status")
            latest = None
            while True:
                events = client.call("recent_events", after_id=cursor, limit=50)
                cursor = events["next_cursor"]
                if events["events"]:
                    latest = events["events"][-1]
                if len(events["events"]) < 50:
                    break
            assert latest is not None
            last = latest
            outcomes[j["title"]] = last["state"]
            assert last["job_id"] == j["id"] and last["state"] == "submitted", last
        elapsed = time.perf_counter() - started
    timings = sorted(metrics["latencies"])
    print(
        json.dumps(
            dict(
                input_jobs=100,
                input_versions=len(jobs),
                stored=page["total"],
                tools=metrics["tools"],
                ai_calls=provider,
                http_json_bytes=sum(http.values()),
                http_by_route=http,
                mcp_json_bytes=metrics["mcp_bytes"],
                median_ms=round(statistics.median(timings), 2),
                p95_ms=round(timings[math.ceil(0.95 * len(timings)) - 1], 2),
                workflow_seconds=round(elapsed, 2),
                outcomes=outcomes,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        os.environ.update(JOB_STUDIO_DATA=tmp, PYTHON_DOTENV_DISABLED="1")
        benchmark(Path(tmp))
