"""A stand-in for the Discobox camera in tests: the recordings of a folder, handed
to the live pipeline as if the camera had just captured them, so a live run can
be tested with no camera and compared with folder mode on the same frames."""

import shutil
import threading
from pathlib import Path

import pipeline
from pipeline.live import live_setup
from classes.results.call_corrections import CallCorrections
from classes.storage.frame_source import Frame, FolderSource, RecordingEnd
from classes.live.lights import NoLights
from classes.live.sources import LiveSource
from classes.plate.zone_layout import ZoneLayout


DEAD_AFTER = 10000  # minutes


class FolderCamera(LiveSource):
    """What pipeline asks of CameraSource, fed from `data_dir`: its recordings
    one after the other, `gap` seconds apart, under their own names."""

    kind = "camera"

    def __init__(self, data_dir, settings, lights, gap=0.0):
        super().__init__()
        self.folder = FolderSource(data_dir)
        self.settings = settings
        self.lights = lights
        self.gap = gap
        self.movement = None
        self.recording = None  # the recording being handed over
        self._stop = threading.Event()
        self._unpaused = threading.Event()
        self._unpaused.set()
        self._thread = None

    @property
    def settings_text(self):
        return str(self.settings)

    def open(self):
        first = next(event for event in self.folder.events(decode=FolderSource.FIRST) if isinstance(event, Frame))
        self.latest.put(first.image)

    def run(self):
        self.state = "running"
        self._thread = threading.Thread(target=self._play, name="folder-camera", daemon=True)
        self._thread.start()

    def _play(self):
        try:
            for event in self.folder.events():
                if self._stop.is_set():
                    break
                if isinstance(event, RecordingEnd):
                    self._events.put(event)
                    self.completed += 1
                    self.recording = None
                    if self._stop.wait(self.gap):
                        break
                    continue
                if event.index == 0:
                    self._unpaused.wait()  # as in a test run, a pause takes effect before the next recording
                    if self._stop.is_set():
                        break
                self.recording = event.recording
                self.latest.put(event.image)
                self._events.put(event)
            if self.recording is not None:
                # Stopped in the middle of a recording: it ends with the frames it has.
                self._events.put(RecordingEnd(self.recording))
                self.completed += 1
        finally:
            self.recording = None
            self.state = "finished"
            self._end_stream()
            self._stopped.set()

    def pause(self):
        if self.state == "running":
            self._unpaused.clear()
            self.state = "paused"

    def resume(self):
        if self.state == "paused":
            self._unpaused.set()
            self.state = "running"

    def stop(self):
        self._stop.set()
        self._unpaused.set()
        if self._thread is None:
            self.state = "finished"
            self._end_stream()
            self._stopped.set()
        else:
            self.state = "stopping"

    def wait_closed(self, timeout=None):
        return self._stopped.wait(timeout)

    def status(self):
        recordings = len(self.folder.recordings())
        return {
            "source": self.kind,
            "camera": f"Folder camera ({self.folder.data_dir.name})",
            "state": self.state,
            "feed": self.latest.count,
            "fps": 0.0,
            "fps_set": self.settings.fps,
            "dropped": 0,
            "incomplete": 0,
            "recording": min(self.completed + bool(self.recording), recordings),
            "recordings": recordings,
            "recording_name": self.recording.name if self.recording else None,
            "frame": 0,
            "frames": None,
            "completed": self.completed,
            "next_recording": None,
            "lights": self.lights.state(),
            "timeline": None,
        }


def open_live(monkeypatch, live_id, out_dir, run_name, data_dir, gap=0.0, **kwargs):
    """pipeline.open_live() with the recordings of `data_dir` for a camera and no
    fan or LEDs. The run takes the folder's settings (its zones per plate among
    them), plate labels, "not a mite" marks and corrected calls, so it gives the
    folder's results."""
    data_dir = Path(data_dir)
    # A live run needs a time to count a mite as dead; one longer than any run
    # here follows every mite to the end, as folder mode scores them.
    kwargs["settings"] = {"death_minutes": DEAD_AFTER, **(kwargs.get("settings") or {})}
    monkeypatch.setattr(live_setup.live_camera, "choose_camera", lambda camera_id: "FOLDER")
    monkeypatch.setattr(live_setup, "open_lights", lambda port: NoLights())
    monkeypatch.setattr(live_setup, "CameraSource", lambda _id, settings, lights: FolderCamera(data_dir, settings, lights, gap))
    status = pipeline.open_live(live_id, out_dir, run_name, settings_path=data_dir / pipeline.SETTINGS_FILENAME, **kwargs)
    for name in (*ZoneLayout.filenames(pipeline.LABELS_FILENAME), *ZoneLayout.filenames(pipeline.CONTROLS_FILENAME),
                 pipeline.GROUND_TRUTH_FILENAME, CallCorrections.FILENAME):
        if (data_dir / name).is_file():
            shutil.copy2(data_dir / name, Path(status["run_dir"]) / name)
    return status
