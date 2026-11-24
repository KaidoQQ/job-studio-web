import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_studio import core
from job_studio.applications import (
    APPLICANT,
    NEXT,
    ApplicationRunner,
    active_form,
    answer_for,
    applicant,
    create_attempt,
    fill_form,
    is_success,
    prepare_embedded_form,
    record,
    save_applicant,
)
from job_studio.browser.captcha_status import captcha_pending


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(core, "DATA", Path(self.tmp.name))
        self.p.start()
        self.person = {
            **APPLICANT,
            "first_name": "Test",
            "last_name": "Person",
            "email": "test@example.org",
            "cv_path": "test.pdf",
        }

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def job(self):
        core.put(
            dict(
                title="Python",
                company="Example",
                url="https://justjoin.it/job-offer/test",
                source="test",
                description="Test job",
                location="Remote",
            )
        )
        with core.connect() as db:
            db.execute("UPDATE jobs SET draft='My real experience'")
            return db.execute("SELECT id FROM jobs").fetchone()[0]

    def test_mapping_does_not_invent_experience(self):
        self.assertEqual(
            answer_for({"label": "First name *"}, self.person, "Letter"), "Test"
        )
        self.assertEqual(
            answer_for({"label": "Cover letter"}, self.person, "Letter"), "Letter"
        )
        self.assertIsNone(
            answer_for(
                {"label": "How many years of Azure experience?"}, self.person, "Letter"
            )
        )
        self.assertIsNone(
            answer_for({"label": "Accept all terms"}, self.person, "Letter")
        )
        self.assertEqual(
            answer_for({"label": "First and last name*"}, self.person, "Letter"),
            "Test Person",
        )

    def test_modal_scope_is_preferred(self):
        page = MagicMock()
        page.evaluate.return_value = True
        self.assertIs(active_form(page), page.locator.return_value)
        page.locator.assert_called_once_with("[data-job-studio-scope]")

    def test_embedded_form_reveals_message_and_uploads_cv(self):
        page = MagicMock(url="https://justjoin.it/job-offer/test")
        scope = MagicMock()
        textarea = MagicMock()
        textarea.count.return_value = 0
        file = MagicMock()
        file.count.return_value = 1
        file.input_value.return_value = ""
        scope.locator.side_effect = lambda s: (
            file if s == "input[type=file]" else textarea
        )
        toggle = MagicMock()
        toggle.count.return_value = 1
        toggle.is_visible.return_value = True
        upload = MagicMock()
        upload.count.return_value = 1
        upload.is_visible.return_value = True
        filename = MagicMock()
        filename.count.return_value = 0
        scope.get_by_text.side_effect = lambda text, exact: (
            toggle
            if text == "Attach a message for the employer"
            else upload
            if text == "Add document"
            else filename
        )
        with patch("job_studio.applications.active_form", return_value=scope):
            prepare_embedded_form(page, scope, self.person, "Letter", lambda _: None)
        toggle.click.assert_called_once()
        file.set_input_files.assert_called_once_with("test.pdf")

    def test_account_creation_requires_user_confirmation(self):
        page = MagicMock(url="https://justjoin.it/job-offer/test")
        label = (
            "I'm creating an account, I accept the Terms of Service and Privacy Policy."
        )
        page.evaluate.return_value = [
            dict(index=0, label=label, type="checkbox", required=False, checked=False)
        ]
        page.locator.return_value.count.return_value = 0
        self.assertEqual(fill_form(page, self.person, "Letter"), [label])
        page.locator.return_value.check.assert_not_called()

    def test_exact_confirmed_answers(self):
        person = {**self.person, "answers": {"Work authorization?": "Yes"}}
        self.assertEqual(
            answer_for({"label": "Work authorization? *"}, person, ""), "Yes"
        )
        save_applicant(person)
        self.assertEqual(applicant()["email"], "test@example.org")

    def test_uncertain_submission_cannot_be_retried(self):
        jid = self.job()
        create_attempt(jid)
        record(jid, "submitting", "Clicked")
        with self.assertRaises(ValueError):
            create_attempt(jid)
        record(jid, "uncertain", "No confirmation")
        with self.assertRaises(ValueError):
            create_attempt(jid)
        with core.connect() as db:
            self.assertNotEqual(
                db.execute("SELECT status FROM jobs").fetchone()[0], "applied"
            )

    def test_confirmed_submission_marks_applied(self):
        jid = self.job()
        create_attempt(jid)
        record(jid, "submitted", "Application received")
        with core.connect() as db:
            self.assertEqual(
                db.execute("SELECT status FROM jobs").fetchone()[0], "applied"
            )
        with self.assertRaises(ValueError):
            create_attempt(jid)

    def test_unknown_required_field_stops_filling(self):
        page = MagicMock()
        page.evaluate.return_value = [
            dict(
                index=0,
                label="Years of Azure experience",
                type="number",
                value="",
                required=True,
            )
        ]
        page.locator.return_value.count.return_value = 0
        self.assertEqual(
            fill_form(page, self.person, "Letter"), ["Years of Azure experience"]
        )
        page.locator.return_value.fill.assert_not_called()

    def test_cv_and_select(self):
        page = MagicMock()
        page.evaluate.return_value = [
            dict(index=0, label="Resume", type="file", fileCount=0),
            dict(index=1, label="Country", type="select-one", value="", required=True),
        ]
        page.locator.return_value.count.return_value = 0
        self.assertEqual(fill_form(page, self.person, "Letter"), [])
        page.locator.return_value.set_input_files.assert_called_once_with("test.pdf")
        page.locator.return_value.select_option.assert_called_once_with(label="Poland")

    def test_polite_description_is_not_success(self):
        page = MagicMock(url="https://justjoin.it/job-offer/test")
        page.locator.return_value.inner_text.return_value = (
            "Thank you for your interest in our role."
        )
        self.assertFalse(is_success(page))
        page.locator.return_value.inner_text.return_value = "Application received"
        self.assertTrue(is_success(page))

    def test_recaptcha_verified_state(self):
        page = MagicMock()
        frame = MagicMock(url="https://google.com/recaptcha/api2/anchor")
        page.frames = [frame]
        page.evaluate.return_value = False
        frame.locator.return_value.count.return_value = 1
        frame.locator.return_value.is_visible.return_value = True
        frame.locator.return_value.get_attribute.return_value = "false"
        self.assertTrue(captcha_pending(page))
        frame.locator.return_value.get_attribute.return_value = "true"
        self.assertFalse(captcha_pending(page))

    def test_worker_submits_once_and_records_confirmation(self):
        jid = self.job()
        job = create_attempt(jid)
        page = MagicMock(url="https://webellian.peopleforce.io/careers/v/test/a/new")
        body = MagicMock()
        body.inner_text.return_value = "Application form"
        fields = MagicMock()
        fields.count.return_value = 1
        empty = MagicMock()
        empty.count.return_value = 0

        def locator(selector):
            if selector == "body":
                return body
            if "password" in selector:
                return empty
            return fields

        page.locator.side_effect = locator
        final = MagicMock()
        final.count.return_value = 1
        button = final.nth.return_value
        button.is_visible.return_value = True
        button.is_enabled.return_value = True
        button.click.side_effect = lambda: setattr(
            body.inner_text, "return_value", "Application received"
        )
        page.get_by_role.side_effect = lambda role, name: (
            empty if name is NEXT else final
        )
        module = types.ModuleType("job_studio.browser.session")

        class Driver:
            def __init__(self, **kwargs):
                self.page = page

            def _setup_driver(self):
                pass

            def close_driver(self):
                pass

        module.BaseParserPW = Driver
        worker = ApplicationRunner()
        worker.lock.acquire()
        worker.state.update(job_id=jid, url=job["url"], running=True)
        with (
            patch("job_studio.applications.bot_for") as bot_factory,
            patch.dict("sys.modules", {"job_studio.browser.session": module}),
            patch(
                "job_studio.browser.captcha_status.captcha_pending", return_value=False
            ),
            patch("job_studio.applications.fill_form", return_value=[]),
            patch("job_studio.applications.active_form", return_value=page),
        ):
            bot_factory.return_value.ready.return_value = True
            worker.run(job)
        button.click.assert_called_once()
        self.assertFalse(worker.state["running"])
        with core.connect() as db:
            self.assertEqual(
                db.execute("SELECT state FROM applications").fetchone()[0], "submitted"
            )
            self.assertEqual(
                db.execute("SELECT status FROM jobs").fetchone()[0], "applied"
            )


if __name__ == "__main__":
    unittest.main()
