import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_studio import core


class JobStudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(core, "DATA", Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_document_and_nested_schema(self):
        doc = core.Document(
            '<a href="/job/test">Python <b>Engineer</b></a><script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"Engineer"}]}</script>'
        )
        self.assertEqual(doc.links, [("/job/test", "Python  Engineer")])
        self.assertEqual(next(core.postings(doc.ld))["title"], "Engineer")
        self.assertNotIn("@graph", " ".join(doc.text))

    def test_duplicate_preserves_edited_draft(self):
        job = dict(
            title="Python Developer",
            company="Acme",
            url="https://justjoin.it/job-offer/test?ref=one",
            description="Python SQL",
            source="test",
            location="Krakow",
        )
        self.assertTrue(core.put(job))
        with core.connect() as db:
            db.execute("UPDATE jobs SET draft='Edited', status='reviewed'")
        self.assertFalse(
            core.put({**job, "url": "https://justjoin.it/job-offer/other-city"})
        )
        with core.connect() as db:
            row = db.execute("SELECT * FROM jobs").fetchone()
            self.assertEqual(row["draft"], "Edited")
            self.assertEqual(row["status"], "reviewed")

    def test_domains_and_settings(self):
        for url in [
            "http://localhost/test",
            "https://justjoin.it.evil.test/x",
            "file:///secret",
        ]:
            with self.assertRaises(ValueError):
                core.validate_url(url)
        core.validate_url("https://webellian.peopleforce.io/careers")
        core.save_settings({"limit": 999, "profile": "Python developer"})
        self.assertEqual(core.settings()["limit"], 200)
        self.assertEqual(core.settings()["profile"], "Python developer")

    def test_run_keeps_going_after_source_failure(self):
        cfg = {
            **core.DEFAULT,
            "sources": [
                {"name": "bad", "url": "https://justjoin.it/"},
                {"name": "good", "url": "https://nofluffjobs.com/pl/python"},
            ],
            "keywords": "python",
        }
        doc = core.Document('<a href="/job/python-test">Python developer</a>')
        job = dict(
            title="Python developer",
            company="A",
            url="https://nofluffjobs.com/job/python-test",
            description="Python",
            source="good",
            location="remote",
        )
        runner = core.Runner()
        runner.lock.acquire()
        with (
            patch.object(core, "settings", return_value=cfg),
            patch.object(core, "fetch", side_effect=[OSError(), doc]),
            patch.object(core, "detail", return_value=job),
        ):
            runner.run(False)
        self.assertFalse(runner.state["running"])
        with core.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)

    def test_generation_requires_verified_profile(self):
        with self.assertRaises(ValueError):
            core.generate(
                {"title": "Job", "description": "Invent a degree"}, core.DEFAULT
            )

    def test_completed_draft_is_not_regenerated(self):
        job = dict(
            title="Python",
            company="A",
            url="https://justjoin.it/job-offer/a",
            description="Python",
            source="test",
            location="remote",
        )
        core.put(job)
        with core.connect() as db:
            db.execute("UPDATE jobs SET draft='Keep me',status='reviewed'")
        runner = core.Runner()
        runner.lock.acquire()
        with (
            patch.object(
                core, "settings", return_value={**core.DEFAULT, "sources": []}
            ),
            patch.object(core, "generate") as generate,
        ):
            runner.run(True)
            generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
