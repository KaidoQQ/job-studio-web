import logging
import threading
from functools import wraps

logger = logging.getLogger(__name__)


def with_timeout(timeout_sec: float = 60.0):
    """Decorator for interrupting frozen parser methods.
    In case of a timeout, it forces the close_driver() method on the class instance."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            def kill_browser():
                logger.debug(
                    "⏳ Critical timeout (%.1f sec) in %s! Killing driver...",
                    timeout_sec,
                    func.__name__,
                )

                # We check if the first argument (self) has a driver closing method and call it
                if args and hasattr(args[0], "close_driver"):
                    args[0].close_driver()

            # Create and start a timer
            kill_timer = threading.Timer(timeout_sec, kill_browser)
            kill_timer.start()

            try:
                return func(*args, **kwargs)
            finally:
                # Cancel the timer if parsing is completed (successfully or with error)
                # BEFORE timeout_sec expires
                kill_timer.cancel()

        return wrapper

    return decorator
