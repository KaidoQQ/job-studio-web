"""UpWork single-job parser v2 — Playwright + SeleniumBase sb_cdp.

Drop-in replacement for parser_UpWork.py.
Uses BaseParserPW instead of BaseParser.

Public interface (same as original):
    parser = UpWorkPW(headless=False, url="https://www.upwork.com/jobs/~01...")
    parser.on_step = my_callback
    parser.stop_event = threading.Event()
    text = parser.parser()  # -> str
    details = parser.job_details
"""

import logging
import random
import time

logger = logging.getLogger(__name__)
from job_studio.browser.session import BaseParserPW

from .timeout import with_timeout

# ── Selectors ────────────────────────────────────────────────
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
# UpWorkPW — single job page parser (Playwright + sb_cdp)
# ═════════════════════════════════════════════════════════════
class UpWorkPW(BaseParserPW):
    """Parses a single UpWork job page and extracts the job description.

    Uses SeleniumBase sb_cdp for stealth Chrome + captcha solving,
    and Playwright for DOM parsing via CDP.
    """

    MAX_RETRIES = 2  # number of attempts when browser crashes

    def __init__(
        self,
        headless: bool = True,
        url: str | None = None,
        profile_name: str | None = None,
    ) -> None:
        super().__init__(headless=headless, profile_name=profile_name)
        self.url = url
        self.job_details = ""

    # ── Main method with retry ───────────────────────────────
    def parser(self) -> str:
        """Parses a single job page with retry on session crashes.

        Returns:
            str: Job description text.
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
                    raise  # if it doesn't crash, we throw it away immediately
        # All attempts are exhausted
        raise last_error

    # ── Parsing logic ────────────────────────────────────────
    @with_timeout(600.0)
    def _do_parse(self, attempt: int = 1) -> str:
        t_start = time.perf_counter()
        logger.info("▶ Parsing started for URL: %s (attempt %d)", self.url, attempt)
        self._setup_driver()
        assert self.page is not None, "Playwright page not initialized"
        assert self.sb is not None, "sb_cdp not initialized"

        parsed_info = ""
        try:
            # ── 1. Loading the page (via Playwright) ─────────
            # Using wait_until="domcontentloaded" instead of "load"
            # because Cloudflare pages may never fire the "load" event
            logger.info("Loading page...")
            self._step("🌐 **Step 2 of 5:** Opening job page on Upwork...")
            self.human_delay(0.5, 1.0)
            self.page.goto(
                self.url,
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            time.sleep(3)

            # Checking that the session is alive after loading
            if not self._is_session_alive():
                raise RuntimeError("Browser session crashed after page load")

            # Human pause - "look at the page"
            self.human_delay(1.5, 3.0)

            # ── 2. Cookie banner / CAPTCHA ───────────────────
            for sel in COOKIE_SELECTORS:
                if self._safe_click(sel, f"cookie banner ({sel})", timeout=2):
                    self.human_delay(1.0, 2.0)
                    break

            # We process the captcha (automatically via sb_cdp)
            self._handle_captcha()

            # ── 3. Authorization check and login (if needed) ─
            self._check_stop()
            self.login_from_keyring()

            # ── 3.5. Re-checking captcha after login ─────────
            # UpWork often shows the captcha again after authorization
            self._handle_captcha()

            # ── 4. Waiting for the vacancy to load ───────────
            try:
                # After login - human pause
                self.human_delay(2.0, 4.0)

                # ── 4.1. Processing [NEW] popovers ───────────
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

                logger.info("Waiting for job content to load...")
                self._step("⏳ **Step 4 of 5:** Waiting for job content to load...")
                self.page.wait_for_selector(
                    "#air3-truncation-1, .air3-modal-content",
                    state="attached",
                    timeout=25_000,
                )

                # Close modals if present
                for sel in MODAL_CLOSE_SELECTORS:
                    if self._safe_click(sel, f"modal window ({sel})", timeout=1):
                        break

                # A small scroll - a person is "looking at the page"
                self.human_delay(0.5, 1.0)
                self.random_scroll()

                # We are waiting for an element with a description
                self.page.wait_for_selector(
                    "span[id='air3-truncation-1']",
                    state="attached",
                    timeout=15_000,
                )

                # Expanding the full text
                self._safe_click(
                    ".air3-truncation-btn",
                    "button 'Read more'",
                    timeout=2,
                )

                self._step("📄 **Step 5 of 5:** Extracting job description...")
                desc_el = self.page.locator("#air3-truncation-1")
                parsed_info = desc_el.inner_text().strip()

                self.job_details = parsed_info

                if parsed_info:
                    logger.info(
                        "✅ Parsing successful! Received %d characters",
                        len(parsed_info),
                    )
                    logger.debug("First 200 characters: %s", parsed_info[:200])
                    self._step("✅ **Parsing successfully completed!**")
                else:
                    logger.warning("Element found, but text is empty!")

            except Exception:
                # Maybe captcha reappeared
                logger.warning("Job content timeout, re-checking captcha...")
                self._handle_captcha()
                try:
                    self.page.wait_for_selector(
                        "span[id='air3-truncation-1']",
                        state="attached",
                        timeout=25_000,
                    )
                    # Expanding the full text (retry)
                    self._safe_click(
                        ".air3-truncation-btn",
                        "button 'Read more'",
                        timeout=2,
                    )
                    desc_el = self.page.locator("#air3-truncation-1")
                    parsed_info = desc_el.inner_text().strip()
                    self.job_details = parsed_info

                    if parsed_info:
                        logger.info(
                            "✅ Parsing successful (after captcha retry)! %d chars",
                            len(parsed_info),
                        )
                        self._step("✅ **Parsing successfully completed!**")
                    else:
                        logger.warning("Element found after retry, but text is empty!")
                except Exception:
                    logger.error(
                        "Current URL: %s | Title: %s",
                        self.page.url,
                        self.page.title(),
                    )
                    raise RuntimeError("Failed to load job content — timeout 25 sec")

        except RuntimeError:
            raise

        except Exception as e:
            logger.exception("Unexpected parsing error: %s", e)
            raise RuntimeError(f"Parsing error: {e}") from e

        finally:
            elapsed = time.perf_counter() - t_start
            logger.info("Parsing completed in %.1f sec", elapsed)
            self.close_driver()

        return parsed_info
