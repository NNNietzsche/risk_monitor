"""Spread collection across a cycle and respect upstream rate-limit responses."""
import math
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from .provider_errors import FetchError


class CollectionDeferred(FetchError):
    """No request was sent; this is not an upstream response or new evidence."""


class RequestBudget:
    def __init__(self, spacing=3.0, clock=time.monotonic, sleep=time.sleep,
                 wall_clock=lambda: datetime.now(timezone.utc), backoff_statuses=('429',),
                 pause_message='数据源限流'):
        self.spacing, self.clock, self.sleep, self.wall_clock = spacing, clock, sleep, wall_clock
        self.lock = threading.RLock()
        self.next_request = self.blocked_until = 0.0
        self.failures = 0
        self.backoff_statuses = set(map(str, backoff_statuses))
        self.pause_message = pause_message

    def retry_in(self):
        with self.lock:
            return max(0.0, self.blocked_until - self.clock())

    def _retry_after(self, value):
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                seconds = (parsedate_to_datetime(value) - self.wall_clock()).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return 0.0
        return seconds if math.isfinite(seconds) and seconds > 0 else 0.0

    def run(self, callback):
        # One shared budget for live feed, history, details, category and enrollment.
        # Hold only for a short spacing delay or one bounded HTTP request, never
        # sleep through a rate-limit cooldown while holding the store's lock.
        with self.lock:
            remaining = self.retry_in()
            if remaining:
                raise CollectionDeferred(f'{self.pause_message}，约 {math.ceil(remaining)} 秒后自动继续',
                    {'request_sent': False, 'retry_in_seconds': math.ceil(remaining)})
            self.sleep(max(0.0, self.next_request - self.clock()))
            self.next_request = self.clock() + self.spacing
            try:
                result = callback()
            except Exception as exc:
                payload = getattr(exc, 'payload', {})
                code = getattr(exc, 'status_code', None) or payload.get('http_status')
                if str(code) in self.backoff_statuses:
                    self.failures += 1
                    # Observed Retry-After: 0 is not permission to retry in a loop.
                    fallback = min(900, 60 * 2 ** min(self.failures - 1, 4))
                    retry_after = payload.get('retry_after', getattr(exc, 'retry_after', None))
                    self.blocked_until = self.clock() + max(fallback, self._retry_after(retry_after))
                raise
            self.failures = 0
            return result


class CollectionSchedule:
    """Oldest due target first, with independent slots for each data source."""
    def __init__(self, interval):
        self.interval = interval
        self.next_slot = {}
        self.attempts = {}
        self.selection = None

    def pick(self, targets, now, blocked=None):
        blocked = blocked or {}
        counts = {}
        active = {m['id'] for m in targets}
        self.attempts = {k:v for k,v in self.attempts.items() if k in active}
        for m in targets:
            counts[m['provider']] = counts.get(m['provider'], 0) + 1
        def last(m):
            persisted = datetime.fromisoformat(m['last_poll_at']).timestamp() if m['last_poll_at'] else 0
            return max(persisted, self.attempts.get(m['id'], 0))
        for m in sorted(targets, key=lambda m: (last(m), m['created_at'], m['id'])):
            provider = m['provider']
            if blocked.get(provider, 0) > 0 or now < max(last(m) + self.interval, self.next_slot.get(provider, 0)):
                continue
            # Schedule relative to actual start: slow requests never cause catch-up bursts.
            self.next_slot[provider] = now + self.interval / counts[provider]
            self.attempts[m['id']] = now
            self.selection = (m['id'], provider)
            return m['id']
        return None

    def defer(self, monitor_id):
        # An enrollment request may trigger a 429 after pick but before poll.
        # No upstream request was made, so do not consume this target's cycle.
        if self.selection and self.selection[0] == monitor_id:
            self.attempts.pop(monitor_id, None)
            self.next_slot.pop(self.selection[1], None)
            self.selection = None
