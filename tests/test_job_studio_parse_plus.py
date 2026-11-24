import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_studio import core
from job_studio.applications import ApplicationRunner, create_attempt
from job_studio.parse_plus import ParsePlus


class ParsePlusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(core, "DATA", Path(self.tmp.name))
        self.p.start()
        self.job = dict(
            title="Python",
            company="Example",
            url="https://justjoin.it/job-offer/test",
            source="Parse plus",
            description="Python job",
            location="Remote",
        )

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_one_link_generates_and_starts_application(self):
        apps = MagicMock()
        runner = ParsePlus(apps)
        runner.lock.acquire()
        with (
            patch.object(core, "detail", return_value=self.job),
            patch.object(core, "generate", return_value="Letter"),
        ):
            runner.run(self.job["url"], "Python", True)
        apps.start.assert_called_once_with(runner.state["job_id"])
        with core.connect() as db:
            self.assertEqual(
                db.execute("SELECT draft FROM jobs").fetchone()[0], "Letter"
            )
        self.assertFalse(runner.state["running"])
        self.assertFalse(runner.lock.locked())

    def test_existing_draft_is_kept(self):
        core.put(self.job)
        with core.connect() as db:
            db.execute("UPDATE jobs SET draft='Edited by user'")
        runner = ParsePlus(MagicMock())
        runner.lock.acquire()
        with (
            patch.object(core, "detail") as detail,
            patch.object(core, "generate") as generate,
        ):
            runner.run(self.job["url"], "Python", False)
            detail.assert_not_called()
            generate.assert_not_called()

    def test_sent_job_is_not_applied_again(self):
        core.put(self.job)
        with core.connect() as db:
            db.execute("UPDATE jobs SET status='applied'")
        apps = MagicMock()
        runner = ParsePlus(apps)
        runner.lock.acquire()
        runner.run(self.job["url"], "Python", True)
        apps.start.assert_not_called()

    def test_manual_finish_marks_completed_without_browser_clicks(self):
        core.put(self.job)
        with core.connect() as db:
            db.execute("UPDATE jobs SET draft='Letter'")
            jid = db.execute("SELECT id FROM jobs").fetchone()[0]
        create_attempt(jid)
        runner = ApplicationRunner()
        runner.state.update(job_id=jid)
        runner.finish_manual(jid)
        with core.connect() as db:
            self.assertEqual(
                db.execute("SELECT status FROM jobs").fetchone()[0], "applied"
            )

    def test_finish_wakes_paused_worker_and_rejects_busy_worker(self):
        runner = ApplicationRunner()
        runner.state.update(job_id="one", running=True, waiting=False)
        with self.assertRaises(ValueError):
            runner.finish_manual("one")
        runner.state["waiting"] = True
        runner.finish_manual("one")
        self.assertTrue(runner.manual_done.is_set())
        self.assertTrue(runner.resume.is_set())


if __name__ == "__main__":
    unittest.main()
