"""Best Matches parser v2 — Playwright + SeleniumBase sb_cdp.

Drop-in replacement for parser_best_matches.py.
Uses BaseParserPW instead of BaseParser.

Public interface (same as original):
    parser = BestMatchesParserPW(headless=False, profile_name="profile_auto")
    parser.on_step = my_callback
    jobs = parser.parser()  # -> [{title, url}, ...]
"""

import logging
import random
import time

logger = logging.getLogger(__name__)
from job_studio.browser.session import BaseParserPW

from .timeout import with_timeout

# ── Selectors ────────────────────────────────────────────────
JOB_CARD_SELECTORS = [
    "h3.job-tile-title a",
    "div[data-test='job-tile-list'] h3 a",
    "section.up-card-section h3 a",
]

COOKIE_SELECTORS = [
    "button[id='onetrust-accept-btn-handler']",
    ".cb-lb input[type='checkbox']",
    "button.accept-cookies",
    "[data-testid='cookie-accept']",
]

MODAL_CLOSE_SELECTORS = [
    ".air3-modal-close",
    "[data-test='modal-close']",
    "button.up-modal-close",
    ".up-icon-close",
    ".up-modal-dialog-close",
]


# ═════════════════════════════════════════════════════════════
# BestMatchesParserPW
# ═════════════════════════════════════════════════════════════
class BestMatchesParserPW(BaseParserPW):
    """Parses https://www.upwork.com/nx/find-work/best-matches
    and returns a list of vacancies (title + link) visible on the page.

    Uses SeleniumBase sb_cdp for stealth Chrome + captcha solving,
    and Playwright for DOM parsing via CDP.
    """

    URL = "https://www.upwork.com/nx/find-work/best-matches"
    MAX_RETRIES = 2

    def __init__(
        self,
        headless: bool = False,
        profile_name: str | None = None,
    ) -> None:
        super().__init__(headless=headless, profile_name=profile_name)
        self.jobs: list[dict[str, str]] = []

    # ── Main method with retry ───────────────────────────────
    def parser(self) -> list[dict[str, str]]:
        """Parses Best Matches with retry on session crashes.

        Returns:
            List of dicts: [{"title": "...", "url": "..."}, ...]
        """
        last_error = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            self._check_stop()

            try:
                result = self._do_parse(attempt)
                return result
            except RuntimeError as e:
                self._check_stop()

                last_error = e
                error_msg = str(e)
                # Restart only for crash/session errors
                if "session" in error_msg.lower() or "renderer" in error_msg.lower():
                    logger.warning(
                        "Attempt %d/%d failed (session crash), retrying...",
                        attempt,
                        self.MAX_RETRIES,
                    )
                    self.close_driver()
                    time.sleep(random.uniform(2, 4))
                    continue
                else:
                    raise  # non-crash error — re-raise immediately
        # All attempts exhausted
        raise last_error

    # ── Parsing logic ────────────────────────────────────────
    @with_timeout(600.0)
    def _do_parse(self, attempt: int = 1) -> list[dict[str, str]]:
        t_start = time.perf_counter()
        logger.info("▶ BestMatches parsing started (attempt %d)", attempt)
        self._setup_driver()
        assert self.page is not None, "Playwright page not initialized"
        assert self.sb is not None, "sb_cdp not initialized"

        try:
            # ── 1. Loading the page (via Playwright, NOT sb.get!) ─────
            # Using wait_until="domcontentloaded" instead of "load"
            # because Cloudflare pages may never fire the "load" event
            logger.info("Loading Best Matches page...")
            self._step("🌐 **Step 2 of 5:** Opening Best Matches page on Upwork...")
            self.human_delay(0.5, 1.0)
            self.page.goto(
                self.URL,
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            time.sleep(3)

            # ── 2. Cookie banner ─────────────────────────────
            for sel in COOKIE_SELECTORS:
                if self._safe_click(sel, f"cookie banner ({sel})", timeout=2):
                    self.human_delay(0.5, 1.0)
                    break

            # ── 2.5. Captcha (automatic via sb_cdp) ──────────
            self._handle_captcha()

            # ── 3. Login (if needed) ─────────────────────────
            self._check_stop()
            self.login_from_keyring()

            # ── 3.5. Re-checking captcha after login ─────────
            # UpWork often shows the captcha again after logging in
            self._handle_captcha()

            # ── 4. Waiting for the list of vacancies ─────────
            try:
                self.human_delay(3.0, 5.0)

                logger.info("Waiting for job list to load...")
                self._step("⏳ **Step 4 of 5:** Waiting for job list to load...")
                self.page.wait_for_selector(
                    "div[data-test='job-tile-list']",
                    state="attached",
                    timeout=25_000,
                )

                # Close modals if present
                for sel in MODAL_CLOSE_SELECTORS:
                    if self._safe_click(sel, f"modal window ({sel})", timeout=1):
                        break

                self.human_delay(1.0, 2.0)
                self.random_scroll()

            except Exception:
                # Maybe captcha reappeared
                logger.warning("Job list timeout, re-checking captcha...")
                self._handle_captcha()
                try:
                    self.page.wait_for_selector(
                        "div[data-test='job-tile-list']",
                        state="attached",
                        timeout=25_000,
                    )
                except Exception:
                    logger.error(
                        "Current URL: %s | Title: %s",
                        self.page.url,
                        self.page.title(),
                    )
                    raise RuntimeError("Failed to load job list — timeout 25 sec")

            # ── 4.5. Processing [NEW] popovers ───────────────
            logger.info("Checking for [NEW] popover buttons...")
            try:
                popover = self.page.locator(".ng-side-nav-fte-popover")
                if popover.count() > 0:
                    for _ in range(3):
                        if not self._safe_click(
                            ".ng-side-nav-fte-popover-btn-cta",
                            "popover CTA button",
                            timeout=1,
                        ):
                            break
                        self.human_delay(0.5, 1.0)
            except Exception:
                logger.debug("Popover with buttons not found, continuing...")

            self.human_delay(1.0, 2.0)
            self.scroll_to_bottom()

            # ── 5. Collecting job titles ──────────────────────
            self._step("📄 **Step 5 of 5:** Extracting job titles and links...")
            self._check_stop()

            cards = None
            for sel in JOB_CARD_SELECTORS:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    cards = loc
                    logger.info("Using selector: %s (found %d)", sel, loc.count())
                    break

            if not cards or cards.count() == 0:
                logger.error("No job cards found with any selector!")
                raise RuntimeError("No job cards found on page")

            total = cards.count()
            logger.info("Found %d jobs on page", total)

            self.jobs = []
            for i in range(total):
                try:
                    card = cards.nth(i)
                    title = card.inner_text().strip()
                    # evaluate node.href guarantees an absolute URL (unlike get_attribute)
                    href = card.evaluate("node => node.href") or ""

                    if title:
                        self.jobs.append(
                            {
                                "title": title,
                                "url": href,
                            }
                        )
                except Exception:
                    logger.warning("Element is stale/error at index %d, skipping...", i)
                    continue

            logger.info("✅ Collected %d jobs", len(self.jobs))
            self._step("✅ **Job collection successfully completed!**")
            for i, job in enumerate(self.jobs, 1):
                logger.info("  %d. %s", i, job["title"])

        except RuntimeError:
            raise

        except Exception as e:
            logger.exception("Unexpected parsing error: %s", e)
            raise RuntimeError(f"Parsing error: {e}") from e

        finally:
            elapsed = time.perf_counter() - t_start
            logger.info("BestMatches parsing completed in %.1f sec", elapsed)
            self.close_driver()

        return self.jobs
