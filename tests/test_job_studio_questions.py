import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_studio import core
from job_studio.applications import (
    APPLICANT,
    ApplicationRunner,
    answer_for,
    applicant,
    application_events,
    create_attempt,
    record,
)
from job_studio.questions import suggest


class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(core, "DATA", Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_cloudferro_fields(self):
        person = {
            **APPLICANT,
            "phone": "+48 123456789",
            "notice": "1 month",
            "salary_expectation": "6000 PLN brutto / UoP",
            "hybrid_availability": "Warsaw max 2 days/week",
        }
        for label, expected in [
            ("Telefon kontaktowy *", person["phone"]),
            (
                "Czy obowiązuje Cię obecnie okres wypowiedzenia? Jeśli tak, jaki? *",
                person["notice"],
            ),
            (
                "Jakie są Twoje oczekiwania finansowe netto/brutto? *",
                person["salary_expectation"],
            ),
            (
                "Czy jesteś otwarty/a na pracę/współpracę w modelu hybrydowym? Jeśli tak, ile razy w tygodniu/miesiącu? *",
                person["hybrid_availability"],
            ),
        ]:
            self.assertEqual(answer_for({"label": label}, person, ""), expected)

    def test_suggestions_require_evidence(self):
        q = [dict(id="one", kind="text", label="Experience?", options=[])]
        with patch.object(
            core,
            "complete_prompt",
            return_value=json.dumps(
                {
                    "one": {
                        "answer": "Python",
                        "evidence": "Python projects",
                        "needs_user": False,
                    }
                }
            ),
        ):
            self.assertEqual(
                suggest(q, "Python projects", core.DEFAULT)["one"]["suggestion"],
                "Python",
            )
        with patch.object(
            core,
            "complete_prompt",
            return_value=json.dumps(
                {
                    "one": {
                        "answer": "AWS",
                        "evidence": "AWS projects",
                        "needs_user": False,
                    }
                }
            ),
        ):
            self.assertEqual(suggest(q, "Python projects", core.DEFAULT), {})

    def test_unknown_fact_and_invalid_option_not_used(self):
        q = [
            dict(
                id="one", kind="select-one", label="Work permit?", options=["Yes", "No"]
            )
        ]
        for response in (
            {"answer": "Yes", "needs_user": True, "evidence": "Python"},
            {"answer": "Maybe", "needs_user": False, "evidence": "Python"},
        ):
            with patch.object(
                core, "complete_prompt", return_value=json.dumps({"one": response})
            ):
                self.assertEqual(suggest(q, "Python", core.DEFAULT), {})

    def test_consents_are_not_sent_to_ai(self):
        with patch.object(core, "complete_prompt") as complete:
            self.assertEqual(
                suggest(
                    [dict(id="one", kind="checkbox", label="Consent")],
                    "Profile",
                    core.DEFAULT,
                ),
                {},
            )
            complete.assert_not_called()

    def test_user_answers_saved_but_consents_not_reused(self):
        worker = ApplicationRunner()
        worker.state.update(
            waiting=True,
            job_id="job",
            questions=[
                dict(id="a", label="Experience?", kind="text", options=[]),
                dict(id="b", label="Consent", kind="checkbox", options=[]),
            ],
        )
        worker.accept_answers("job", {"a": "Python", "b": True}, True)
        self.assertTrue(worker.resume.is_set())
        self.assertEqual(applicant()["answers"], {"Experience?": "Python"})
        self.assertTrue(worker.session_answers["Consent"])
        with self.assertRaises(ValueError):
            worker.accept_answers("different-job", {"a": "wrong"})

    def test_application_log_is_persistent(self):
        core.put(
            dict(
                title="Python",
                company="A",
                url="https://justjoin.it/job-offer/a",
                source="test",
                description="Python",
                location="Remote",
            )
        )
        with core.connect() as db:
            db.execute("UPDATE jobs SET draft='Letter'")
            jid = db.execute("SELECT id FROM jobs").fetchone()[0]
        create_attempt(jid)
        record(jid, "needs_input", "Question pending")
        self.assertEqual(application_events()[-1]["message"], "Question pending")


if __name__ == "__main__":
    unittest.main()
