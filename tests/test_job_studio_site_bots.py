import unittest
from unittest.mock import MagicMock

from job_studio.site_bots import (
    FORM,
    AshbyBot,
    JustJoinBot,
    NoFluffBot,
    PortalBot,
    bot_for,
)


class PortalTests(unittest.TestCase):
    def test_host_boundary(self):
        self.assertIsInstance(bot_for("https://nofluffjobs.com/pl/job/x"), NoFluffBot)
        self.assertIsInstance(bot_for("https://justjoin.it/job-offer/x"), JustJoinBot)
        self.assertIsInstance(bot_for("https://jobs.ashbyhq.com/a/x"), AshbyBot)
        self.assertIs(type(bot_for("https://fakejustjoin.it")), PortalBot)

    def test_no_enabled_apply_does_not_click(self):
        page = MagicMock()
        controls = page.get_by_role.return_value.or_.return_value
        controls.count.return_value = 1
        controls.nth.return_value.is_visible.return_value = True
        controls.nth.return_value.is_enabled.return_value = False
        self.assertFalse(NoFluffBot().open(page, lambda _: None))
        controls.nth.return_value.click.assert_not_called()

    def test_ashby_uses_application_tab(self):
        page = MagicMock()
        tab = page.get_by_role.return_value
        tab.count.return_value = 1
        tab.is_visible.return_value = True
        self.assertTrue(AshbyBot().open(page, lambda _: None))
        tab.click.assert_called_once()

    def test_spa_not_ready_does_not_count_arbitrary_email(self):
        page = MagicMock()
        page.evaluate.return_value = False
        self.assertFalse(NoFluffBot().ready(page))
        page.evaluate.assert_called_once_with(FORM)


if __name__ == "__main__":
    unittest.main()
