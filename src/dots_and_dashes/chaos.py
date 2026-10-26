"""The chaos switch: fails or slows Entry saves on purpose, to stage an incident.

Off unless configured (docs/runbooks/README.md). It sits outside the Journal:
it decides nothing about bullet journaling, only whether a save is let through.
"""

import math
import threading
import time

from dots_and_dashes.settings import Settings


class InjectedSaveFailure(Exception):
    """An Entry save failed on purpose by the chaos switch."""


class SaveChaos:
    """Slows every Entry save by a set time, and fails a set share of them.

    The failures are spread evenly rather than drawn at random, so a rate of
    0.25 fails exactly every fourth save: a staged incident crosses the
    alert's threshold every time it is staged.
    """

    def __init__(self, *, error_rate: float = 0.0, latency_ms: int = 0) -> None:
        self.error_rate = error_rate
        self.latency_ms = latency_ms
        self._saves = 0
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> "SaveChaos":
        return cls(
            error_rate=settings.chaos_save_error_rate,
            latency_ms=settings.chaos_save_latency_ms,
        )

    @property
    def on(self) -> bool:
        return self.error_rate > 0 or self.latency_ms > 0

    def save(self) -> None:
        """Let one Entry save through after the latency, or raise InjectedSaveFailure."""
        time.sleep(self.latency_ms / 1000)
        with self._lock:
            before, self._saves = self._saves, self._saves + 1
        # Fail this save when it brings the count due to fail to a new whole number.
        if math.floor((before + 1) * self.error_rate) > math.floor(before * self.error_rate):
            raise InjectedSaveFailure
