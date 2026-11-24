import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_studio import mcp_server as api


class MCPTests(unittest.TestCase):
    def state(self):
        return {
            "jobs": [
                {
                    "id": str(i),
                    "title": "Python Engineer",
                    "company": "Example",
                    "status": "new",
                    "description": "large private text",
                    "draft": "letter",
                }
                for i in range(65)
            ],
            "run": {"running": False, "events": ["large"]},
            "parse_plus": {"running": False, "events": ["large"]},
            "application": {"running": False, "job_id": "0"},
            "applications": [],
            "application_events": [{"id": i, "message": "event"} for i in range(1, 10)],
        }

    def test_compact_pagination(self):
        with patch.object(api, "request", return_value=self.state()):
            result = api.list_vacancies("python", offset=20, limit=20)
        self.assertEqual(result["next_offset"], 40)
        self.assertEqual(result["total"], 65)
        self.assertNotIn("description", result["jobs"][0])
        self.assertNotIn("draft", result["jobs"][0])

    def test_status_omits_lists_and_event_bulk(self):
        with patch.object(api, "request", return_value=self.state()):
            result = api.studio_status()
        self.assertNotIn("jobs", result)
        self.assertNotIn("events", result["run"])

    def test_parse_does_not_apply(self):
        with patch.object(api, "request", return_value={"ok": True}) as req:
            api.parse_vacancy("https://justjoin.it/test")
        self.assertFalse(req.call_args.args[1]["apply"])

    def test_wrong_job_cannot_resume(self):
        with patch.object(api, "request", return_value=self.state()) as req:
            with self.assertRaises(ValueError):
                api.application_action("resume", "wrong")
        self.assertEqual(req.call_count, 1)

    def test_applied_letter_not_changed(self):
        state = self.state()
        state["jobs"][0]["status"] = "applied"
        with patch.object(api, "request", return_value=state) as req:
            with self.assertRaises(ValueError):
                api.save_letter("0", "changed")
        self.assertEqual(req.call_count, 1)

    def test_cursor(self):
        with patch.object(api, "request", return_value=self.state()):
            result = api.recent_events(3, 2)
        self.assertEqual(result["next_cursor"], 5)

    def test_reject_remote_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "endpoint.json").write_text(
                json.dumps({"url": "https://example.com", "token": "secret"})
            )
            with patch.object(api, "DATA", Path(folder)):
                with self.assertRaises(ValueError):
                    api.request("/api/state")

    def test_missing_service(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(api, "DATA", Path(folder)),
        ):
            with self.assertRaisesRegex(ValueError, "Start or restart"):
                api.studio_status()


if __name__ == "__main__":
    unittest.main()
