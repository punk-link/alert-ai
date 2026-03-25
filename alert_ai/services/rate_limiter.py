import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    """Sliding-window rate limiter for Anthropic API calls.

    Uses a deque of call timestamps. No external dependencies — pure stdlib.
    Safe for use in a single-process async event loop (no locking needed).
    """

    def __init__(self, max_calls: int, window_seconds: int = 60) -> None:
        self._max_calls = max_calls
        self._window = window_seconds
        self._timestamps: deque[float] = deque()

    def acquire(self, *, silent: bool = False) -> bool:
        """Return True and record the call if under the limit, False otherwise.

        Pass ``silent=True`` from polling loops to suppress repeated warnings.
        """
        now = time.monotonic()
        cutoff = now - self._window

        # Evict timestamps outside the sliding window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        if len(self._timestamps) >= self._max_calls:
            if not silent:
                logger.warning(
                    "Anthropic rate limit reached (%d calls / %ds). Alert group enqueued.",
                    self._max_calls,
                    self._window,
                )
            return False

        self._timestamps.append(now)
        return True

    def seconds_until_next_slot(self) -> float:
        """Seconds until the oldest timestamp expires and a new slot opens.

        Returns 0.0 if already under the limit.
        """
        now = time.monotonic()
        cutoff = now - self._window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) < self._max_calls:
            return 0.0
        return max(0.0, self._timestamps[0] + self._window - now)
