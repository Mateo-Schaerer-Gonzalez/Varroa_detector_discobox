"""Files written a moment later, off the request that changed them.

A call corrected on the result pages changes the workbook and the figures, and
writing them takes far longer than working out the numbers the page shows. So
the page gets its numbers at once, and the files are written in the background:
once the changes pause, and only as they are then, however many changes came in
between. Whoever needs the files (a download, the end of the program) waits for
them with finish().

Writing them keeps Python busy, and a request that comes meanwhile waits for
its turns (a correction takes a second or two instead of a tenth). So the pause
waited for is a long one: someone checking calls one after the other, looking
at a hard one for a while, is not in it.
"""

import logging
import threading
import time

_logger = logging.getLogger(__name__)


class DeferredFiles:
    """`delay`: seconds without a new job for a key before its job runs."""

    def __init__(self, delay=30.0):
        self.delay = delay
        self._pending = {}    # key -> (job, when it may run)
        self._running = None  # the key whose job is being run
        self._changed = threading.Condition()
        self._thread = None

    def later(self, key, job, delay=None):
        """Run `job()` in the background once no other job for `key` has come
        for `delay` seconds (by default this object's); it replaces a job for
        `key` still waiting."""
        with self._changed:
            self._pending[key] = (job, time.monotonic() + (self.delay if delay is None else delay))
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._work, daemon=True)
                self._thread.start()
            self._changed.notify_all()

    def forget(self, key=None):
        """Drop the job of `key` (by default every job) still waiting; one being
        run is run to its end."""
        with self._changed:
            for waiting in [k for k in self._pending if key in (None, k)]:
                del self._pending[waiting]
            self._changed.notify_all()

    def finish(self, key=None):
        """Return once the files of `key` (by default of every key) are written;
        a job still waiting is run without its delay."""
        with self._changed:
            while True:
                keys = [k for k in (*self._pending, self._running) if k is not None and key in (None, k)]
                if not keys:
                    return
                for k in keys:
                    if k in self._pending:
                        self._pending[k] = (self._pending[k][0], 0)
                self._changed.notify_all()
                self._changed.wait()

    def _work(self):
        while True:
            with self._changed:
                while True:
                    due = min(self._pending.items(), key=lambda item: item[1][1], default=None)
                    wait = None if due is None else due[1][1] - time.monotonic()
                    if wait is not None and wait <= 0:
                        break
                    self._changed.wait(wait)
                key, (job, _when) = due
                del self._pending[key]
                self._running = key
            try:
                job()
            except Exception:  # only files: the page has its numbers already
                _logger.exception("Could not write the files of %s", key)
            with self._changed:
                self._running = None
                self._changed.notify_all()
