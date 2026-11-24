"""Check the MCP adapter and loopback HTTP service together, on a fresh database."""

import asyncio
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from job_studio import applications, core, mcp_server, server


class EventWaitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name)
        for module in (core, mcp_server):
            override = patch.object(module, "DATA", data)
            override.start()
            self.addCleanup(override.stop)
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(http.shutdown)
        (data / "endpoint.json").write_text(
            json.dumps(
                {"url": f"http://127.0.0.1:{http.server_port}", "token": server.TOKEN}
            )
        )
        with core.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,status,draft) VALUES('fixture','draft','text')"
            )
        applications.create_attempt("fixture")

    def test_wake_all_clients_once_after_commit_and_resume(self):
        both_waiting = threading.Event()
        waits = 0
        original = applications.EVENTS_COMMITTED.wait

        def wait(timeout):
            nonlocal waits
            waits += 1
            if waits == 2:
                both_waiting.set()
            return original(timeout)

        async def scenario():
            pending = [
                asyncio.create_task(mcp_server.recent_events(wait_seconds=5))
                for _ in range(2)
            ]
            self.assertTrue(await asyncio.to_thread(both_waiting.wait, 3))
            applications.record("fixture", "filling", "Answer received")
            replies = await asyncio.wait_for(asyncio.gather(*pending), 3)
            self.assertEqual(replies[0], replies[1])
            first = replies[0]
            self.assertFalse(first["gap"])
            self.assertEqual(
                [e["message"] for e in first["events"]], ["Answer received"]
            )
            applications.record("fixture", "submitted", "Done")
            resumed = await mcp_server.recent_events(
                first["next_cursor"], wait_seconds=30
            )
            self.assertEqual([e["state"] for e in resumed["events"]], ["submitted"])

        with patch.object(applications.EVENTS_COMMITTED, "wait", wait):
            asyncio.run(scenario())

    def test_quiet_timeout_and_lost_database(self):
        start = time.monotonic()
        page = asyncio.run(mcp_server.recent_events(wait_seconds=1))
        self.assertGreaterEqual(time.monotonic() - start, 0.9)
        self.assertEqual(page, {"events": [], "next_cursor": 0, "gap": False})
        reset = asyncio.run(mcp_server.recent_events(100, wait_seconds=30))
        self.assertTrue(reset["gap"])
        self.assertEqual(reset["next_cursor"], 0)
        self.assertEqual(reset["recovery"]["reason"], "cursor_ahead")

    def test_maximum_wait_is_enforced_by_both_interfaces(self):
        for value in (-1, 31):
            with self.assertRaises(ValueError):
                asyncio.run(mcp_server.recent_events(wait_seconds=value))
            with self.assertRaises(ValueError):
                mcp_server.request(f"/api/mcp/events?wait_seconds={value}")
