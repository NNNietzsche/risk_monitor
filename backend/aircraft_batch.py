"""Share one original live-feed response across the aircraft in a collection cycle."""
from copy import deepcopy
import threading
import time
import uuid
from .provider_errors import FetchError


class AircraftLiveFeed:
    def __init__(self, gateway, request, interval=600, clock=time.monotonic, batch_size=50):
        self.gateway, self.request, self.clock = gateway, request, clock
        self.interval, self.batch_size = interval, batch_size
        self.registrations = ()
        self.responses = {}
        self.lock = threading.RLock()

    def configure(self, registrations, interval=None):
        with self.lock:
            registrations = tuple(sorted(set(registrations)))
            if registrations != self.registrations:
                self.responses.clear()
                self.registrations = registrations
            if interval is not None:
                # Manual collection still shares a bounded snapshot when auto-poll is off.
                self.interval = min(interval or 600, 600)

    def fetch(self, registration):
        with self.lock:
            regs = self.registrations
            if registration in regs:
                index = regs.index(registration) // self.batch_size * self.batch_size
                batch = regs[index:index + self.batch_size]
            else:
                batch = (registration,)
            cached = self.responses.get(batch)
            if cached and 0 <= self.clock() - cached[0] < self.interval:
                return deepcopy(cached[1])
            payload = self.gateway.run('flightradar-sdk-v1', ('live_batch', batch),
                lambda: self.request('registration', ','.join(batch)))
            if not isinstance(payload.get('body'), dict):
                raise FetchError('飞机批量位置响应格式异常', payload)
            payload = deepcopy(payload)
            payload['live_batch'] = {'id': str(uuid.uuid4()), 'registrations': list(batch),
                                     'fetched_at': payload.get('fetched_at')}
            self.responses[batch] = (self.clock(), payload)
            return deepcopy(payload)
