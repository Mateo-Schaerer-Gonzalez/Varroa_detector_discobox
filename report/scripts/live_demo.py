"""The app with a simulated Discobox, for the user manual's screenshots of a live
run (report/scripts/manual_screenshots.mjs): the camera plays the recordings of a
folder instead (unit_tests/folder_camera.py), the fan and LEDs are switched on a
serial port that goes nowhere, and everything else is the app as it runs on the
Discobox.

    set DISCOBOX_CONFIG=<the copy>\\config.yaml
    python report/scripts/live_demo.py <recordings folder> [--port 8765] [--gap 75]

Run it in a copy of the app holding only the 2025 test sessions (see
scripts/readme_screenshots.mjs): a live run is saved to the copy's recordings/.

Unlike FolderCamera, the camera here goes on streaming between recordings, as
the real one does (the first frame of the recording to come, so Add mites sees
mites put on before it), shows its frame rate, plays each recording at its frame
rate with the fan and LEDs on, and counts down `gap` seconds to the next one.
"""
import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "unit_tests"))

import uvicorn  # noqa: E402

from classes.live import camera as live_camera  # noqa: E402
from classes.live.lights import DEVICES, Lights  # noqa: E402
from classes.storage.data_loader import DataLoader  # noqa: E402
from classes.storage.frame_source import RecordingEnd  # noqa: E402
from folder_camera import FolderCamera  # noqa: E402
from pipeline.live import live_settings, live_setup  # noqa: E402


class Nowhere:
    """A serial port that takes every command and sends it nowhere."""

    def write(self, data):
        pass

    def flush(self):
        pass


class DemoCamera(FolderCamera):
    """FolderCamera as the Discobox's camera looks on the live page."""

    def __init__(self, data_dir, settings, lights, gap):
        super().__init__(data_dir, settings, lights, gap)
        self.t0 = None
        self.starts = []         # seconds after the run's start at which each recording began
        self.next_start = None   # when the next one will
        self.frame = 0
        self.frames = 0
        self.firsts = []         # each recording's first frame, streamed while waiting for it
        self.counts = {}         # each recording's frames

    def open(self):
        loader = self.folder.loader
        for recording in self.folder.recordings():
            paths = loader.frame_paths(recording.name)
            self.firsts.append(DataLoader.read_image(paths[0]))
            self.counts[recording.name] = len(paths)
        self.latest.put(self.firsts[0])
        threading.Thread(target=self._stream, name="demo-stream", daemon=True).start()

    def _stream(self):
        """Between recordings: the newest frame again and again, at the frame rate."""
        while not self._stopped.is_set():
            if self.recording is None:
                image = self.firsts[min(self.completed, len(self.firsts) - 1)]
                self.latest.put(image)
                self.rate.tick(time.monotonic())
            time.sleep(1 / self.settings.fps)

    def run(self):
        self.t0 = time.monotonic()
        super().run()

    def _lights(self, on):
        for device in DEVICES:
            if on:
                self.lights.switch(device, True, getattr(self.settings, device))
            else:
                self.lights.switch_off(device)

    def _play(self):
        try:
            for event in self.folder.events():
                if self._stop.is_set():
                    break
                if isinstance(event, RecordingEnd):
                    self._events.put(event)
                    self.completed += 1
                    self.recording = None
                    self._lights(False)
                    self.next_start = time.monotonic() + self.gap
                    if self._stop.wait(self.gap):
                        break
                    continue
                if event.index == 0:
                    self._unpaused.wait()
                    if self._stop.is_set():
                        break
                    self._lights(True)
                    self.starts.append(time.monotonic() - self.t0)
                    self.next_start = None
                    self.frames = self.counts.get(event.recording.name, 0)
                self.recording = event.recording
                self.frame = event.index + 1
                self.latest.put(event.image)
                self.rate.tick(time.monotonic())
                self._events.put(event)
                time.sleep(1 / event.recording.fps)
            if self.recording is not None:
                self._events.put(RecordingEnd(self.recording))
                self.completed += 1
        finally:
            self.recording = None
            self._lights(False)
            self.state = "finished"
            self._end_stream()
            self._stopped.set()

    def status(self):
        status = super().status()
        now = time.monotonic()
        timeline = None
        if self.t0 is not None:
            starts = list(self.starts) + ([self.next_start - self.t0] if self.next_start else [])
            timeline = {"elapsed": now - self.t0, "length": 0, "starts": starts, "minutes": 0}
        return {**status, "camera": "Demo camera (recordings of " + self.folder.data_dir.name + ")",
                "fps": round(self.rate.rate(), 1), "frame": self.frame if self.recording else 0,
                "frames": self.frames or None, "timeline": timeline}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="the recordings the camera plays")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--gap", type=float, default=75, help="seconds between two recordings")
    args = parser.parse_args()
    folder = args.folder.resolve()

    live_camera.list_cameras = lambda: [{"id": "DEMO", "model": "Demo camera", "name": f"recordings of {folder.name}", "serial": "-"}]
    live_camera.choose_camera = lambda camera_id: "DEMO"
    live_setup.open_lights = lambda port="auto": Lights(port="demo", connection=Nowhere())
    live_setup.CameraSource = lambda _id, settings, lights: DemoCamera(folder, settings, lights, args.gap)
    live_settings.serial_ports = lambda: [{"device": "demo", "description": "Demo Arduino", "arduino": True}]
    uvicorn.run("web.server:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
