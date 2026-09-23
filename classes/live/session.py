"""A live run: frames from a live source, analysed by the same core as folder mode
as each pool is captured, with results published after each one.

Threads, and what each may do:

  camera / replay    capture only (classes/live/sources.py)
  analysis           reads the source's stream, saves the frames (through the
                     Recorder's own thread), scores each pool, publishes results
  anyone else        reads `results` (a finished dict, replaced whole, never
                     changed in place) and status(), which take no lock the
                     capture needs

Results are published with `publish(session, write_files)`, given by the caller
(pipeline.py, which builds them exactly as for a folder), under `lock`, the lock
the analysis holds while it changes the core's state. After each recording the
files (workbook, figures) are written too; with a pool size smaller than a
recording, the results in between are published at most every
MIN_PUBLISH_INTERVAL seconds, without files.
"""

import logging
import threading
import time

from classes.frame_source import Frame, RecordingEnd

_logger = logging.getLogger(__name__)

MIN_PUBLISH_INTERVAL = 0.5  # seconds


class LiveSession:
    def __init__(self, source, analysis, pool_size=None, recorder=None, publish=None):
        self.source = source
        self.analysis = analysis
        self.pool_size = pool_size
        self.recorder = recorder
        self._publish = publish
        self.lock = threading.RLock()
        self.results = None
        self.version = 0
        self.error = None
        self.n_pools = 0
        self.recordings = []  # recordings analysed, and saved when saving
        self.state = "ready"  # ready, running, stopping, finished
        self.finished = threading.Event()
        self._last_publish = 0.0
        self._thread = None

    def start(self):
        """Start the source's run and analyse it as it comes."""
        self.source.run()
        self.state = "running"
        self._thread = threading.Thread(target=self._analyse, name="live-analysis", daemon=True)
        self._thread.start()

    def _analyse(self):
        try:
            self.analysis.run(self._events(), self.pool_size, on_pool=self._pool_done, lock=self.lock)
        except Exception as error:
            _logger.exception("The live analysis failed")
            self.error = f"The analysis failed: {error}"
            self.source.stop()
            for _event in self.source.events():  # let the source finish, and its frames go
                pass
        finally:
            if self.recorder is not None:
                self.recorder.close()
            self.publish(write_files=True)
            self.state = "finished"
            self.finished.set()

    def _events(self):
        for event in self.source.events():
            if self.recorder is not None and isinstance(event, Frame):
                self.recorder.save(event)
            yield event
            if isinstance(event, RecordingEnd):
                # The recording's pools are scored by now. Its frames must be on
                # disk before results pointing at them go out: the page plays them.
                if self.recorder is not None:
                    self.recorder.flush(event.recording.name)
                self.recordings.append(event.recording.name)
                self.publish(write_files=True)

    def _pool_done(self, pool):
        self.n_pools += 1
        # A whole-recording pool is published with the recording's files, just after.
        if self.pool_size is not None and time.monotonic() - self._last_publish >= MIN_PUBLISH_INTERVAL:
            self.publish(write_files=False)

    def publish(self, write_files=False):
        """Describe the results as they are now, if there are any yet."""
        if self._publish is None or not self.analysis.started or not self.analysis.pool_times:
            return
        with self.lock:
            try:
                results = self._publish(self, write_files)
            except ValueError as error:  # e.g. no mites were detected
                self.error = str(error)
                return
            except Exception as error:
                _logger.exception("Could not describe the live results")
                self.error = f"Could not describe the results: {error}"
                return
            self.results = results
            self.version += 1
            self._last_publish = time.monotonic()

    def pause(self):
        self.source.pause()

    def resume(self):
        self.source.resume()

    def stop(self, wait=False, timeout=None):
        """Stop capturing; the analysis finishes what was captured and writes the
        final results. With `wait`, returns once that is done."""
        if self.state in ("running", "ready"):
            self.state = "stopping" if self._thread is not None else "finished"
        self.source.stop()
        if self._thread is None:
            self.finished.set()
        if wait:
            self.finished.wait(timeout)
        return self.finished.is_set()

    def status(self):
        source = self.source.status()
        state = self.state
        if state == "running" and source["state"] in ("paused", "stopping"):
            state = source["state"]
        return {
            **source,
            "state": state,
            "pools": self.n_pools,
            "analysed": len(self.recordings),
            "version": self.version,
            "error": self.error or self.source.error,
            "saving": self.recorder is not None,
            "saved_frames": self.recorder.written if self.recorder is not None else 0,
            "save_error": self.recorder.error if self.recorder is not None else None,
        }
