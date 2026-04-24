from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta

from local_health_assistant.service import HealthService


logger = logging.getLogger(__name__)


class MorningBriefingScheduler:
    def __init__(
        self,
        service: HealthService,
        hour: int,
        minute: int,
        poll_seconds: int = 30,
    ):
        self.service = service
        self.hour = hour
        self.minute = minute
        self.poll_seconds = max(poll_seconds, 5)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_for: date | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="lha-morning-briefing", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now().astimezone()
            target_date = now.date() - timedelta(days=1)
            should_run = (now.hour, now.minute) >= (self.hour, self.minute)
            if should_run and self._last_run_for != target_date:
                try:
                    self.service.run_morning_briefing(target_date)
                    self._last_run_for = target_date
                except Exception:
                    logger.exception("Morning briefing run failed for %s", target_date.isoformat())
            self._stop_event.wait(self.poll_seconds)
