import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_studio import core, read_api
from job_studio.applications import record


class CompactReads(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = patch.object(core, "DATA", Path(directory.name))
        override.start()
        self.addCleanup(override.stop)

    def test_sql_page_and_unicode_literal_search(self):
        with core.connect() as db:
            for i in range(4):
                db.execute(
                    "INSERT INTO jobs(id,title,status,published_at,description,draft) VALUES(?,?,?,?,?,?)",
                    (
                        str(i),
                        "Straße_100%",
                        "draft",
                        "" if i == 3 else "2025-01-01",
                        "private",
                        "letter",
                    ),
                )
        page = read_api.vacancies("STRASSE_100%", "draft", 1, 2)
        self.assertEqual((page["total"], page["next_offset"]), (4, 3))
        self.assertEqual([j["id"] for j in page["jobs"]], ["1", "2"])
        self.assertNotIn("description", page["jobs"][0])
        self.assertEqual(read_api.vacancies("strasseZ100")["total"], 0)
        self.assertEqual(read_api.vacancies(offset=4)["jobs"], [])
        with self.assertRaises(ValueError):
            read_api.vacancies(offset=-1)

    def test_status_does_not_scale_with_documents_or_controls(self):
        args = (
            {"running": False, "message": "Ready"},
            {"running": False, "waiting": False},
            {"running": False},
        )
        with core.connect() as db:
            db.execute("INSERT INTO jobs(id) VALUES('example')")
        before = read_api.status(*args)
        with core.connect() as db:
            db.execute(
                "UPDATE jobs SET description=?, draft=?", ("x" * 100000, "y" * 100000)
            )
        args[1]["diagnostics"] = {"controls": ["secret"] * 500}
        self.assertEqual(before, read_api.status(*args))
        self.assertNotIn("secret", json.dumps(before))

    def test_bounded_cursor_window_and_empty_db(self):
        self.assertEqual(
            read_api.events(), {"events": [], "next_cursor": 0, "gap": False}
        )
        # record normally has an application row; only the event stream is relevant here.
        from job_studio.applications import create_attempt

        with core.connect() as db:
            db.execute("INSERT INTO jobs(id,status,draft) VALUES('foo','draft','text')")
        create_attempt("foo")
        record("foo", "starting", "event")
        with core.connect() as db:
            db.executemany(
                "INSERT INTO application_events(job_id,state,message,created) VALUES('foo','filling','event',?)",
                [(n,) for n in range(155)],
            )
        lost = read_api.events(4, 2, 30)
        self.assertTrue(lost["gap"])
        self.assertEqual(
            lost["recovery"],
            {
                "reason": "history_gap",
                "oldest_id": 7,
                "latest_id": 156,
                "latest_job_id": "foo",
                "latest_state": "filling",
            },
        )
        self.assertEqual([e["id"] for e in lost["events"]], [7, 8])
        self.assertFalse(read_api.events(6, 2)["gap"])
        self.assertEqual(read_api.events(lost["next_cursor"], 2)["next_cursor"], 10)
        self.assertEqual(
            read_api.events(156), {"events": [], "next_cursor": 156, "gap": False}
        )
