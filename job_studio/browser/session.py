"""Chrome session shared by the vacancy and application workers."""

import logging
import os
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Any, Callable

from job_studio.browser.profiles import ProfileManager
from job_studio.credentials import get_key


# ═════════════════════════════════════════════════════════════
# BaseParserPW — abstract base for Playwright + sb_cdp parsers
# ═════════════════════════════════════════════════════════════
class BaseParserPW(ABC):
    """Abstract base parser using SeleniumBase sb_cdp + Playwright over CDP."""

    def __init__(self, headless: bool = True, profile_name: str | None = None) -> None:
        self.profile_manager = ProfileManager()
        self.profile_lock = None  # Profile lock object
        self.headless = headless
        self.profile_name = profile_name

        # sb_cdp + Playwright objects
        self.sb = None  # seleniumbase sb_cdp.Chrome instance
        self.playwright_instance = None  # playwright sync API
        self.browser = None  # playwright browser (CDP)
        self.page = None  # playwright page

        # Application progress and cancellation
        self.on_step: Callable[[str], None] | None = None
        self.stop_event = None  # threading.Event for stop from GUI

        self.proxy_ext_path = None  # Path to temporary proxy auth extension (if used)

    # ── GUI step notification ────────────────────────────────
    def _step(self, text: str) -> None:
        """Sends a progress update to the GUI callback (if set)."""
        on_step = getattr(self, "on_step", None)
        if on_step:
            try:
                on_step(text)
            except Exception:
                pass

    # ── Stop check ───────────────────────────────────────────
    def _check_stop(self) -> None:
        """Raises RuntimeError if stop_event is set (user cancelled)."""
        stop_event = getattr(self, "stop_event", None)
        if stop_event and stop_event.is_set():
            raise RuntimeError("Parsing stopped by user")

    # ─────────────────────────────────────────────────────────
    # PROFILE MANAGEMENT
    # ─────────────────────────────────────────────────────────
    def _get_profile_path(self) -> str:
        """Returns path to a Chrome profile directory for sb_cdp.

        Uses ProfileManager for locking (same as original BaseParser).
        """
        base_pool = [f"profile_{i}" for i in range(1, 4)]
        random.shuffle(base_pool)

        profile_path, self.profile_lock = self.profile_manager.acquire_lock(
            base_pool=base_pool,
            specific_profile=self.profile_name,
        )

        if not profile_path:
            raise RuntimeError(
                "Could not acquire a Chrome profile lock. All profiles are in use."
            )

        logger.info("Successfully acquired profile: %s", profile_path)
        return profile_path

    def _clean_profile_locks(self, profile_path: str) -> None:
        """Removes Chrome profile stale lock files that remain after a crash."""
        lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"]
        profile = Path(profile_path)
        if not profile.exists():
            return
        for name in lock_files:
            lock = profile / name
            if lock.exists():
                try:
                    lock.unlink(missing_ok=True)
                    logger.info("🔓 Stale lock file deleted: %s", lock)
                except OSError as e:
                    logger.warning("Failed to delete lock file %s: %s", lock, e)

    # ─────────────────────────────────────────────────────────
    # SETUP / TEARDOWN
    # ─────────────────────────────────────────────────────────
    def _setup_driver(self, _max_retries: int = 2) -> None:
        """Launches Chrome via sb_cdp and connects Playwright over CDP.

        Equivalent to BaseParser._setup_driver() but uses the new stack.
        """
        # We allow nest_asyncio to be applied so sb.solve_captcha works alongside Playwright.
        # But to fix the Python 3.11+ "Timeout should be used inside a task" bug,
        # we mock asyncio.current_task temporarily.
        import asyncio

        original_current_task = getattr(asyncio, "current_task", None)

        def _mock_current_task(loop=None):
            task = original_current_task(loop) if original_current_task else None
            if task is None:
                l = loop or asyncio.get_event_loop()
                return asyncio.Task(asyncio.sleep(0), loop=l)
            return task

        if original_current_task:
            asyncio.current_task = _mock_current_task

        from playwright.sync_api import sync_playwright
        from seleniumbase import sb_cdp

        self._step("⚙️ **Step 1 of 5:** Initializing Chrome driver...")
        logger.info("Initializing sb_cdp Chrome (headless=%s)", self.headless)

        profile_path = self._get_profile_path()
        self._clean_profile_locks(profile_path)

        # ── Proxy configuration ──
        # sb_cdp expects proxy as a string: "host:port" or "user:pass@host:port"
        proxy_url = get_key("PROXY_URL")
        proxy_str = None

        if proxy_url:
            from urllib.parse import urlparse

            parsed = urlparse(proxy_url)

            if self.headless and parsed.username:
                logger.warning(
                    "⚠️ Proxy with authorization doesn't work well in headless! "
                    "Switching to visible."
                )
                self.headless = False

            # Build proxy string in format expected by cdp_util.start()
            if parsed.username and parsed.password:
                from job_studio.browser.proxy import _create_proxy_auth_extension

                self.proxy_ext_path = _create_proxy_auth_extension(
                    host=parsed.hostname,
                    port=parsed.port,
                    username=parsed.username,
                    password=parsed.password,
                )
                proxy_str = f"{parsed.hostname}:{parsed.port}"
                logger.info("Proxy with auth configured: %s", proxy_str)
            else:
                proxy_str = f"{parsed.hostname}:{parsed.port}"
                logger.info("Proxy without auth configured: %s", proxy_str)

        # ── Launch sb_cdp Chrome ──
        last_exc = None
        for attempt in range(1, _max_retries + 1):
            try:
                if self.proxy_ext_path:
                    logger.info("Using proxy auth extension: %s", self.proxy_ext_path)
                    self.sb = sb_cdp.Chrome(
                        headless=self.headless,
                        user_data_dir=profile_path,
                        extensions_dir=[self.proxy_ext_path],
                    )
                else:
                    self.sb = sb_cdp.Chrome(
                        headless=self.headless,
                        user_data_dir=profile_path,
                        proxy=proxy_str,
                    )
                logger.info("sb_cdp Chrome launched (attempt %d)", attempt)
                break
            except Exception as e:
                last_exc = e
                logger.warning(
                    "⚠️ sb_cdp Chrome failed (attempt %d/%d): %s",
                    attempt,
                    _max_retries,
                    str(e).split("\n")[0],
                )
                # Keep the profile lease for the next launch attempt.
                if attempt < _max_retries:
                    time.sleep(random.uniform(2, 4))
                continue
        else:
            logger.error("❌ Failed to launch Chrome after %d attempts", _max_retries)
            raise last_exc

        # ── Connect Playwright over CDP ──
        endpoint_url = self.sb.get_endpoint_url()
        logger.info("CDP endpoint: %s", endpoint_url)

        self.playwright_instance = sync_playwright().start()
        self.browser = self.playwright_instance.chromium.connect_over_cdp(endpoint_url)

        context = self.browser.contexts[0]
        self.page = context.pages[0] if context.pages else context.new_page()
        self.page.set_default_timeout(15_000)

        if original_current_task:
            asyncio.current_task = original_current_task
        logger.info("Playwright connected via CDP — driver ready")

    def close_driver(self) -> None:
        """Closes Playwright, sb_cdp Chrome, and releases profile lock.

        Equivalent to BaseParser.close_driver().
        """
        # 1. Disconnect Playwright
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self.playwright_instance:
            try:
                self.playwright_instance.stop()
            except Exception:
                pass
            self.playwright_instance = None

        self.page = None

        # 2. Quit sb_cdp Chrome
        if self.sb:
            try:
                self.sb.quit()
                logger.info("sb_cdp Chrome closed")
            except Exception as e:
                logger.warning("Error closing sb_cdp Chrome: %s", e)
            finally:
                self.sb = None
                if self.proxy_ext_path and os.path.exists(self.proxy_ext_path):
                    try:
                        os.remove(self.proxy_ext_path)
                        logger.info(
                            "Temporary proxy extension deleted: %s", self.proxy_ext_path
                        )
                    except Exception as e:
                        logger.warning("Failed to delete proxy extension: %s", e)

        # 3. Release profile lock
        if hasattr(self, "profile_lock") and self.profile_lock is not None:
            self.profile_lock.release()
            self.profile_lock = None
            logger.info("Profile lock released for profile: %s", self.profile_name)

    def _is_session_alive(self) -> bool:
        """Checks if the browser session is alive."""
        try:
            _ = self.page.title()
            return True
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────
    # CAPTCHA — delegated to sb_cdp
    # ─────────────────────────────────────────────────────────
    def _handle_captcha(self, max_rounds: int = 3) -> bool:
        """Solves captcha using sb.solve_captcha().

        Replaces the entire CaptchaHandlerMixin (234 lines) with a simple call.
        Retries up to max_rounds times.
        """
        from job_studio.browser.captcha_status import captcha_pending

        if not captcha_pending(self.page):
            return True
        for round_num in range(1, max_rounds + 1):
            self._check_stop()
            try:
                self.sb.solve_captcha()
                self.human_delay(1.0, 2.0)
                if not captcha_pending(self.page):
                    logger.info("CAPTCHA verified (round %d/%d)", round_num, max_rounds)
                    self._step("✅ CAPTCHA passed!")
                    return True
            except Exception as e:
                if round_num == 1:
                    logger.debug(
                        "solve_captcha round %d: %s (may be no captcha)", round_num, e
                    )
                else:
                    logger.warning(
                        "solve_captcha round %d/%d failed: %s",
                        round_num,
                        max_rounds,
                        e,
                    )
                self.human_delay(1.0, 2.0)
        self._step("CAPTCHA needs manual completion in the browser.")
        return False

    # ─────────────────────────────────────────────────────────
    # LOGIN
    # ─────────────────────────────────────────────────────────
    def login_from_keyring(self):
        email = get_key("UPWORK_EMAIL")
        password = get_key("UPWORK_PASSWORD")
        if not email or not password:
            raise ValueError("Set UPWORK_EMAIL and UPWORK_PASSWORD to sign in.")
        self._do_login(email, password)

    def _do_login(self, email: str, passwd: str) -> None:
        """Performs UpWork login if the login form is detected.

        Uses Playwright for human-like form interaction.
        """
        self._step("🔐 **Step 3 of 5:** Checking authorization status...")
        self._check_stop()

        # Wait for login form or actual content
        try:
            self.page.wait_for_selector(
                "input[id='login_username'], "
                "div[data-test='job-tile-list'], "
                "#air3-truncation-1",
                timeout=30_000,
            )
        except Exception:
            # Check if captcha appeared again
            self._handle_captcha()
            try:
                self.page.wait_for_selector(
                    "input[id='login_username'], "
                    "div[data-test='job-tile-list'], "
                    "#air3-truncation-1",
                    timeout=30_000,
                )
            except Exception:
                logger.info("No login form or content found — possibly cached session")
                return

        # If no login form — already logged in
        if self.page.locator("input[id='login_username']").count() == 0:
            logger.info("Already logged in (cached session)")
            return

        logger.info("Login form detected — authorization required")

        # ── EMAIL ────────────────────────────────────────────
        self._step("🔑 **Step 3 of 5:** Entering Email to login...")
        email_input = self.page.locator("input[id='login_username']")
        email_input.wait_for(state="visible", timeout=15_000)
        self.human_delay(0.5, 1.0)

        # Check for autofill
        existing_email = email_input.input_value()
        email_success = False

        if existing_email:
            logger.info("Autofill detected for email, pressing Enter...")
            email_input.click()
            self.human_delay(0.3, 0.6)
            url_before = self.page.url
            email_input.press("Enter")
            self.human_delay(2.0, 3.0)

            if (
                self.page.url != url_before
                or self.page.locator("input[id='login_username']").count() == 0
            ):
                logger.info("✅ Email accepted by autofill")
                email_success = True

        if not email_success:
            logger.info("Email autofill failed or empty — entering manually")
            email_input = self.page.locator("input[id='login_username']")
            email_input.click()
            self._human_type(email_input, email)
            self.human_delay(0.3, 0.5)
            email_input.press("Enter")
            self.human_delay(2.0, 3.0)

        # ── PASSWORD ─────────────────────────────────────────
        self._step("🔑 **Step 3 of 5:** Entering Password to login...")
        try:
            pass_input = self.page.locator("input[id='login_password']")
            pass_input.wait_for(state="visible", timeout=15_000)
        except Exception:
            logger.info("Password field not found — may already be logged in")
            return

        self.human_delay(0.5, 1.0)

        # Check for password autofill
        existing_pass = pass_input.input_value()
        pass_success = False

        if existing_pass:
            logger.info("Autofill detected for password, pressing Enter...")
            pass_input.click()
            self.human_delay(0.3, 0.6)
            url_before = self.page.url
            pass_input.press("Enter")
            self.human_delay(2.0, 3.0)

            if (
                self.page.url != url_before
                or self.page.locator("input[id='login_password']").count() == 0
            ):
                logger.info("✅ Password accepted by autofill — authorized")
                pass_success = True

        if not pass_success:
            logger.info("Password autofill failed or empty — entering manually")
            pass_input = self.page.locator("input[id='login_password']")
            pass_input.click()
            self._human_type(pass_input, passwd)
            self.human_delay(0.3, 0.5)
            pass_input.press("Enter")

        self.human_delay(3.0, 5.0)
        logger.info("Login submitted")

    # ─────────────────────────────────────────────────────────
    # HUMAN BEHAVIOR SIMULATION
    # ─────────────────────────────────────────────────────────
    def _human_type(self, locator, text: str) -> None:
        """Character-by-character typing via Playwright with random delays."""
        locator.click()
        locator.press("Control+A")
        locator.press("Backspace")
        self.human_delay(0.05, 0.15)
        for char in text:
            locator.press_sequentially(char, delay=random.uniform(20, 60))
        logger.debug("Typed: %s***", text[:3])

    def human_delay(self, min_sec: float = 0.1, max_sec: float = 0.4) -> None:
        """Random pause, simulating human 'thinking'."""
        time.sleep(random.uniform(min_sec, max_sec))

    # ─────────────────────────────────────────────────────────
    # DOM INTERACTION HELPERS
    # ─────────────────────────────────────────────────────────
    def _safe_click(
        self, selector: str, description: str = "button", timeout: int = 3
    ) -> bool:
        """Tries to click an element via Playwright; returns False if absent.

        Timeout is in SECONDS (matches original BaseParser API).
        """
        try:
            loc = self.page.locator(selector).first
            loc.wait_for(state="visible", timeout=timeout * 1000)
            loc.click()
            logger.debug("Click (safe): %s", description)
            return True
        except Exception:
            logger.debug("Not found (safe skip): %s", description)
            return False

    def _safe_click_sb(self, selector: str, description: str = "") -> bool:
        """Tries to click an element via sb_cdp. Returns True on success."""
        try:
            if self.sb.is_element_visible(selector):
                self.sb.click(selector)
                logger.debug("SB click: %s", description or selector)
                return True
        except Exception:
            pass
        return False

    def random_scroll(self) -> None:
        """A small random scroll of the page."""
        try:
            scroll_amount = random.randint(100, 400)
            direction = random.choice([1, -1])
            self.page.evaluate(f"window.scrollBy(0, {scroll_amount * direction})")
            self.human_delay(0.3, 0.8)
        except Exception as e:
            logger.debug("random_scroll error: %s", e)

    def scroll_to_bottom(self) -> None:
        """Scrolls the page down to load all vacancies."""
        try:
            # Try scrolling to the last job card
            cards = self.page.locator("section.up-card-section, h3.job-tile-title")
            if cards.count() > 0:
                cards.last.scroll_into_view_if_needed()
            else:
                # Fallback — Page Down
                for _ in range(3):
                    self.page.keyboard.press("PageDown")
                    self.human_delay(0.2, 0.4)
        except Exception as e:
            logger.debug("scroll_to_bottom error (using fallback): %s", e)
            try:
                scroll_amount = random.randint(400, 750)
                self.page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            except Exception:
                pass

        self.human_delay(0.5, 1.0)

    # ─────────────────────────────────────────────────────────
    # ABSTRACT
    # ─────────────────────────────────────────────────────────
    @abstractmethod
    def parser(self, **kwargs: Any) -> Any:
        """Main parsing method. Must be implemented by subclasses."""
        pass
