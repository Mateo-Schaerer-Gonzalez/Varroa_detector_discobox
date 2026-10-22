"""A live run: frames from a live source, analysed by the same core as folder mode
as each recording is captured, with results published after each one.

Threads, and what each may do:

  camera             capture only (classes/live/sources.py)
  analysis           reads the source's stream, scores each recording, saves the
                     mites' ROIs (through the Recorder's own thread), publishes results
  anyone else        reads `results` (a finished dict, replaced whole, never
                     changed in place) and status(), which take no lock the
                     capture needs

Results are published with `publish(session, write_files)`, given by the caller
(pipeline/live/live_capture.py, which builds them exactly as for a folder), under `lock`, the lock
the analysis holds while it changes the core's state. After each recording the
files (workbook, figures) are written too. Once the run is over,
`on_finish(session)`, if given, is called before `finished` is set.
"""

import logging
import threading

from classes.frame_source import Frame, RecordingEnd

_logger = logging.getLogger(__name__)


class LiveSession:
    def __init__(self, source, analysis, recorder=None, publish=None, on_finish=None):
        self.source = source
        self.analysis = analysis
        self.recorder = recorder
        self._publish = publish
        self._on_finish = on_finish
        self.lock = threading.RLock()
        self.results = None
        self.version = 0
        self.error = None
        self.recordings = []  # recordings analysed, and saved when saving
        self.state = "ready"  # ready, running, stopping, finished
        self.finished = threading.Event()
        self._thread = None

    def start(self):
        """Start the source's run and analyse it as it comes."""
        self.source.run()
        self.state = "running"
        self._thread = threading.Thread(target=self._analyse, name="live-analysis", daemon=True)
        self._thread.start()

    def _analyse(self):
        try:
            self.analysis.run(self._events(), lock=self.lock)
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
            if self._on_finish is not None:
                try:
                    self._on_finish(self)
                except Exception:
                    _logger.exception("on_finish failed")
            self.finished.set()

    def _events(self):
        for event in self.source.events():
            yield event
            # The analysis has taken the event in by now: the mites are found
            # on the first frame, placed on the first of each recording, and
            # each recording is scored at its end.
            if self.recorder is not None and isinstance(event, Frame):
                if not self.recorder.started:
                    self.recorder.start(self.analysis.first_frame, [tuple(mite) for mite in self.analysis.mites
                                                                    if mite.start == 0], follow=True)
                if event.index == 0:
                    placed = self.analysis.placed[-1]
                    self.recorder.place([placed.get(mite) for mite in self.analysis.mites])
                self.recorder.save(event)
            if isinstance(event, RecordingEnd):
                # Its frames must be on disk before results pointing at them
                # go out: the page plays them.
                if self.recorder is not None:
                    blobs = self.analysis.blobs[-1] if self.analysis.score and self.analysis.blobs else None
                    self.recorder.end_recording(event.recording, blobs)
                    self.recorder.flush(event.recording.name)
                self.recordings.append(event.recording.name)
                self.publish(write_files=True)

    def publish(self, write_files=False):
        """Describe the results as they are now, if there are any yet."""
        if self._publish is None or not self.analysis.started or not self.analysis.recording_times:
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
            "analysed": len(self.recordings),
            "version": self.version,
            "error": self.error or self.source.error,
            "saving": self.recorder is not None,
            "saved_frames": self.recorder.written if self.recorder is not None else 0,
            "save_error": self.recorder.error if self.recorder is not None else None,
        }
