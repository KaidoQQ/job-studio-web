import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_studio import core


class FreshnessTests(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(
            core.normalize_date("2026-11-23T13:00:00+01:00"),
            "2026-11-23T12:00:00+00:00",
        )
        self.assertEqual(core.normalize_date("yesterday"), "")
        self.assertEqual(core.normalize_date(None), "")

    def test_refresh_preserves_draft_and_first_seen(self):
        with tempfile.TemporaryDirectory() as d, patch.object(core, "DATA", Path(d)):
            j = dict(
                title="Engineer",
                company="Company",
                url="https://justjoin.it/job-offer/a",
                source="test",
                location="remote",
                description="text",
                published_at="2026-11-20",
            )
            core.put(j)
            with core.connect() as db:
                created = db.execute("SELECT created FROM jobs").fetchone()[0]
                db.execute("UPDATE jobs SET draft='edited',status='applied'")
            self.assertFalse(core.put({**j, "published_at": "2026-11-21"}))
            with core.connect() as db:
                row = db.execute("SELECT * FROM jobs").fetchone()
                self.assertEqual(row["draft"], "edited")
                self.assertEqual(row["status"], "applied")
                self.assertEqual(row["created"], created)
                self.assertTrue(row["published_at"].startswith("2026-11-21"))

    def test_source_keeps_filters(self):
        url = core.newest_source_url(
            "https://justjoin.it/job-offers/remote/python?experience-levels=junior"
        )
        self.assertIn("experience-levels=junior", url)
        self.assertIn("sortBy=published", url)

    def test_unknown_dates_last(self):
        with tempfile.TemporaryDirectory() as d, patch.object(core, "DATA", Path(d)):
            for slug, date in [
                ("old", "2026-10-01"),
                ("new", "2026-11-23"),
                ("unknown", ""),
            ]:
                core.put(
                    dict(
                        title=slug,
                        company="",
                        url="https://justjoin.it/job-offer/" + slug,
                        source="test",
                        location="",
                        description="",
                        published_at=date,
                    )
                )
            with core.connect() as db:
                titles = [
                    r["title"]
                    for r in db.execute(
                        "SELECT * FROM jobs ORDER BY " + core.NEWEST_ORDER
                    )
                ]
            self.assertEqual(titles, ["new", "old", "unknown"])


if __name__ == "__main__":
    unittest.main()
