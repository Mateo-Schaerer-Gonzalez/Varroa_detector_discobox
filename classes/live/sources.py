"""The live frame sources: the camera during a Discobox test run, and a recorded
folder replayed as if it were the camera.

Both give what FolderSource gives (classes/frame_source.py), a stream of Frames
and RecordingEnds, so the analysis reads them all the same way. They also keep the
newest frame for the live feed, whether or not it belongs to a recording, and say
how acquisition is going (status()).

CameraSource
    The camera streams all the time, for the live feed. Only the frames of the
    bursts the test run starts (classes/live/schedule.py) go to the analysis:
    each burst is `frame_count` frames, collected as they arrive and handed over
    once complete, in the order of their file names -- the order folder mode will
    read them back in, even where the camera's frame counter wraps or gains a
    digit in the middle of a burst. Frames the camera delivers incomplete are
    skipped, and so are frames dropped because the reader fell behind; either way
    the burst goes on until it has `frame_count` frames, as in the Discobox app.

ReplaySource
    The recordings of a folder, played at `fps` frames per second with `gap`
    seconds between them. They keep their names, so their times and scores are
    those of the folder: the live pipeline, its pages and its feed can be
    developed and tested with no camera.

Both stop cleanly: no more bursts are started, the camera stops streaming, every
frame it had already captured is taken in, the recording being captured ends with
those frames, and the stream ends.
"""

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from classes.frame_source import Frame, FolderSource, Recording, RecordingEnd, as_analysis_image
from classes.live.camera import QUEUE_SIZE, Camera
from classes.live.schedule import TestRun

_logger = logging.getLogger(__name__)

_END = object()  # the end of a source's stream
DROP_LOG_INTERVAL = 5.0  # seconds between two warnings about dropped frames
# A burst is held in memory until complete. Longer bursts are refused rather than
# risking the memory of the computer.
MAX_BURST_BYTES = 2 * 1024**3


class LatestFrame:
    """The newest frame, for the live feed, with a count that changes with it."""

    def __init__(self):
        self._lock = threading.Lock()
        self.count = 0
        self.image = None

    def put(self, image):
        with self._lock:
            self.image = image
            self.count += 1

    def get(self):
        with self._lock:
            return self.count, self.image


class RateMeter:
    """Frames per second over the last few seconds."""

    def __init__(self, window=3.0):
        self.window = window
        self._times = deque()
        self._lock = threading.Lock()

    def tick(self, when=None):
        when = time.monotonic() if when is None else when
        with self._lock:
            self._times.append(when)
            while self._times and when - self._times[0] > self.window:
                self._times.popleft()

    def rate(self):
        with self._lock:
            if len(self._times) < 2 or time.monotonic() - self._times[-1] > self.window:
                return 0.0
            return (len(self._times) - 1) / (self._times[-1] - self._times[0])


def rounded(timeline):
    """A timeline as the status sends it, twice a second: seconds to a tenth."""
    if timeline is None:
        return None
    return {"elapsed": round(timeline["elapsed"], 1), "length": round(timeline["length"], 1),
            "starts": [round(start, 1) for start in timeline["starts"]], "minutes": round(timeline["minutes"], 3)}


class LiveSource:
    """What the live sources share: the stream, the live feed, the state."""

    kind = ""

    def __init__(self):
        self.latest = LatestFrame()
        self.rate = RateMeter()
        self._events = queue.Queue()
        self.state = "ready"  # ready (feed only), running, paused, stopping, finished
        self.completed = 0  # recordings handed over complete
        self.error = None
        self._stopped = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._shut_down = False

    def events(self):
        """The stream of Frames and RecordingEnds, until the source is done.
        Blocks while waiting for the next burst."""
        while True:
            event = self._events.get()
            if event is _END:
                return
            if isinstance(event, tuple):  # a camera frame, made a Frame here, off the camera's threads
                recording, index, filename, gray = event
                event = Frame(recording, index, filename, as_analysis_image(gray), gray=gray)
            yield event

    def _end_stream(self):
        self._events.put(_END)

    @property
    def settings_text(self):
        """The .settings.txt written next to the recordings of the run."""
        return None


@dataclass
class _Burst:
    recording: Recording
    size: int
    frames: list = field(default_factory=list)
    done: threading.Event = field(default_factory=threading.Event)


class CameraSource(LiveSource):
    """The camera, with the fan and LEDs, during a Discobox test run."""

    kind = "camera"

    def __init__(self, camera_id, settings, lights, queue_size=QUEUE_SIZE, camera=None, clock=None):
        """`camera` and `clock` (keyword arguments of TestRun: now, wait,
        wall_clock) replace the real ones in tests."""
        super().__init__()
        self.clock = clock or {}
        self.settings = settings
        self.lights = lights
        self.frames = queue.Queue(maxsize=queue_size)
        self.camera = camera or Camera(camera_id, settings.fps, self.frames)
        self.test_run = None
        self._burst = None
        self._burst_lock = threading.Lock()
        self._router = None
        self._router_stop = threading.Event()
        self._dropped_logged = 0
        self._last_drop_log = 0.0

    @property
    def handler(self):
        return self.camera.handler

    @property
    def settings_text(self):
        return str(self.settings)

    def open(self):
        """Start the camera and the live feed; nothing is recorded yet."""
        self.lights.all_off()
        self.camera.open()
        self._router = threading.Thread(target=self._route, name="frame-router", daemon=True)
        self._router.start()

    def _route(self):
        """Take each frame off the handler's queue: into the live feed, and into
        the burst when one is being collected. Once the camera has stopped, the
        queue is emptied before this returns."""
        while True:
            try:
                frame_id, arrived, image = self.frames.get(timeout=0.1)
            except queue.Empty:
                if self._router_stop.is_set():
                    return
                continue
            self.rate.tick(arrived)
            self.latest.put(image)
            with self._burst_lock:
                burst = self._burst
                if burst is not None:
                    burst.frames.append((frame_id, image))
                    if len(burst.frames) >= burst.size:
                        self._hand_over()
            self._log_drops()

    def _log_drops(self):
        dropped = self.handler.dropped if self.handler else 0
        now = time.monotonic()
        if dropped > self._dropped_logged and now - self._last_drop_log > DROP_LOG_INTERVAL:
            _logger.warning("%d frame(s) dropped: frames came faster than they were taken in (%d in all).",
                            dropped - self._dropped_logged, dropped)
            self._dropped_logged = dropped
            self._last_drop_log = now

    def check_burst_memory(self):
        _count, image = self.latest.get()
        if image is not None and self.settings.frame_count * image.nbytes > MAX_BURST_BYTES:
            most = MAX_BURST_BYTES // image.nbytes
            raise ValueError(f"{self.settings.frame_count} frames per recording do not fit in memory; at most {most}.")

    def run(self):
        """Start the test run."""
        self.settings.check_cycle()
        self.check_burst_memory()
        self.test_run = TestRun(self.settings, self.lights, self.start_burst, self.end_burst, **self.clock)
        self.state = "running"
        self.test_run.start()
        threading.Thread(target=self._when_run_ends, name="test-run-end", daemon=True).start()

    def _when_run_ends(self):
        self.test_run.finished.wait()
        self._shutdown()

    def start_burst(self, name):
        """Start collecting the frames of the recording `name`."""
        with self._burst_lock:
            if self._burst is not None:
                self._hand_over()
            self._burst = _Burst(Recording.from_name(name, self.settings.fps), self.settings.frame_count)
            return self._burst.done

    def end_burst(self):
        """End the burst being collected with the frames it has."""
        with self._burst_lock:
            if self._burst is not None:
                self._hand_over()

    def _hand_over(self):
        """Hand the burst's frames to the analysis, in file name order. Holds the burst lock."""
        burst, self._burst = self._burst, None
        name = burst.recording.name
        frames = sorted(((f"{name}_{frame_id:06}.bmp", image) for frame_id, image in burst.frames), key=lambda item: item[0])
        for index, (filename, image) in enumerate(frames):
            self._events.put((burst.recording, index, filename, image))
        if frames:
            self._events.put(RecordingEnd(burst.recording))
            self.completed += 1
        burst.done.set()

    def pause(self):
        if self.test_run is not None and self.state == "running":
            self.test_run.pause()
            self.state = "paused"

    def resume(self):
        if self.test_run is not None and self.state == "paused":
            self.test_run.resume()
            self.state = "running"

    def set_fps(self, fps):
        self.settings.fps = fps
        self.camera.set_fps(fps)

    def stop(self):
        """Stop the run, or close the feed if no run was started. Returns at once;
        the stream ends once every frame is in."""
        if self.test_run is not None and not self.test_run.finished.is_set():
            self.state = "stopping"
            self.test_run.stop()  # its end triggers _shutdown()
        else:
            threading.Thread(target=self._shutdown, name="camera-close", daemon=True).start()

    def _shutdown(self):
        with self._shutdown_lock:
            if self._shut_down:
                return
            self._shut_down = True
        self.state = "stopping"
        try:
            self.camera.stop()
            self._router_stop.set()
            if self._router is not None:
                self._router.join()
            self.end_burst()  # the burst being captured, with every frame already in
        finally:
            try:
                self.lights.all_off()
            except Exception:
                _logger.exception("Could not switch the fan and LEDs off")
            self.state = "finished"
            self._end_stream()
            self._stopped.set()

    def wait_closed(self, timeout=None):
        return self._stopped.wait(timeout)

    def timeline(self):
        """The test run's timeline (TestRun.timeline), and `minutes`: how far the
        results' time axis reaches once every recording is in, from the start of
        the first to the end of the last. None before the run starts."""
        line = self.test_run.timeline() if self.test_run is not None else None
        if line is None:
            return None
        starts = line["starts"]
        return {**line, "minutes": (starts[-1] - starts[0] + self.settings.recording_seconds) / 60}

    def status(self):
        burst = self._burst
        run = self.test_run
        handler = self.handler
        return {
            "source": self.kind,
            "camera": self.camera.description,
            "state": self.state,
            "feed": self.latest.count,
            "fps": round(self.rate.rate(), 1),
            "fps_set": self.settings.fps,
            "dropped": handler.dropped if handler else 0,
            "incomplete": handler.incomplete if handler else 0,
            "recording": run.recording_count if run else 0,
            "recordings": self.settings.recording_count,
            "recording_name": burst.recording.name if burst else None,
            "frame": len(burst.frames) if burst else 0,
            "frames": self.settings.frame_count,
            "completed": self.completed,
            "next_recording": run.next_recording if run else None,
            "lights": self.lights.state(),
            "timeline": rounded(self.timeline()),
        }


class ReplaySource(LiveSource):
    """A recorded folder, replayed recording by recording as if from the camera."""

    kind = "replay"

    def __init__(self, data_dir, fps=None, gap=2.0):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.folder = FolderSource(self.data_dir)
        self.recordings = self.folder.recordings()
        if not self.recordings:
            raise FileNotFoundError(f"No recordings found in {self.data_dir}")
        self.frame_counts = [len(list((self.data_dir / recording.name).glob("*.bmp"))) for recording in self.recordings]
        self.fps = fps
        self.gap = gap
        self.recording_count = 0
        self.frame = 0
        self.current = None
        self.next_recording = None
        self._playing = None   # (index, recording) being played, from before its first frame
        self._gap_from = None  # when the gap after the recording just played began
        self._ended_at = None  # where on the timeline the replay ended
        self._stop = threading.Event()
        self._unpaused = threading.Event()
        self._unpaused.set()
        self._thread = None

    @property
    def settings_text(self):
        path = self.data_dir / ".settings.txt"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def open(self):
        """Show the first frame in the live feed."""
        first = next(event for event in self.folder.events() if isinstance(event, Frame))
        self.latest.put(first.image)

    def run(self):
        self.state = "running"
        self._thread = threading.Thread(target=self._play, name="replay", daemon=True)
        self._thread.start()

    def _sleep(self, seconds):
        return not self._stop.wait(max(0.0, seconds))

    def _play(self):
        try:
            next_frame = time.monotonic()
            for event in self.folder.events():
                if self._stop.is_set():
                    break
                if isinstance(event, RecordingEnd):
                    self._events.put(event)
                    self.completed += 1
                    self.current = self._playing = None
                    if self.completed < len(self.recordings):
                        self.next_recording = time.time() + self.gap
                        self._gap_from = time.monotonic()
                        if not self._sleep(self.gap):
                            break
                    continue
                if event.index == 0:
                    # As in a test run, a pause takes effect before the next recording.
                    if not self._unpaused.is_set():
                        self.next_recording = None
                        self._unpaused.wait()
                        if self._stop.is_set():
                            break
                    self.frame, self._gap_from = 0, None
                    self._playing = (self.recording_count, event.recording)
                    self.recording_count += 1
                    self.next_recording = None
                    next_frame = time.monotonic()
                fps = self.fps or event.recording.fps
                if not self._sleep(next_frame - time.monotonic()):
                    break
                next_frame += 1.0 / fps
                self.current = event.recording
                self.frame = event.index + 1
                self.rate.tick()
                self.latest.put(event.image)
                self._events.put(event)
            if self.current is not None:
                # Stopped in the middle of a recording: it ends with the frames it has.
                self._events.put(RecordingEnd(self.current))
                self.completed += 1
        except Exception as error:
            _logger.exception("The replay failed")
            self.error = str(error)
        finally:
            self._ended_at = self._position(*self._plan())
            self.current = None
            self.next_recording = None
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

    def set_fps(self, fps):
        self.fps = fps

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

    def _plan(self):
        """When each recording starts on the replay's timeline, and how long it lasts."""
        durations = [count / (self.fps or recording.fps) for recording, count in zip(self.recordings, self.frame_counts)]
        starts = [sum(durations[:index]) + self.gap * index for index in range(len(durations))]
        return starts, durations

    def _position(self, starts, durations):
        """Where the replay is on its timeline: in a recording, or in the gap after one."""
        playing = self._playing
        if playing is not None:
            index, recording = playing
            return starts[index] + self.frame / (self.fps or recording.fps)
        index = self.completed - 1
        if index < 0:
            return 0.0
        gap_from = self._gap_from
        into_gap = 0.0 if gap_from is None else min(self.gap, time.monotonic() - gap_from)
        return starts[index] + durations[index] + into_gap

    def timeline(self):
        """The replay as a test run's timeline (TestRun.timeline): each recording
        lasts its frames at the replay's frame rate, `gap` seconds apart. Its
        `minutes` are those of the folder's recordings, which the results keep."""
        if self.state == "ready":
            return None
        starts, durations = self._plan()
        length = starts[-1] + durations[-1]
        elapsed = self._ended_at if self._ended_at is not None else self._position(starts, durations)
        span = (self.recordings[-1].start - self.recordings[0].start).total_seconds() + durations[-1]
        return {"elapsed": min(elapsed, length), "length": length, "starts": starts, "minutes": span / 60}

    def status(self):
        return {
            "source": self.kind,
            "camera": f"replay of {self.data_dir.name}",
            "state": self.state,
            "feed": self.latest.count,
            "fps": round(self.rate.rate(), 1),
            "fps_set": self.fps,
            "dropped": 0,
            "incomplete": 0,
            "recording": self.recording_count,
            "recordings": len(self.recordings),
            "recording_name": self.current.name if self.current else None,
            "frame": self.frame if self.current else 0,
            "frames": None,
            "completed": self.completed,
            "next_recording": self.next_recording,
            "lights": None,
            "timeline": rounded(self.timeline()),
        }
