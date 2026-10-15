"""How fast a live run can capture before it suffers: frames dropped, a
recording still being analysed when the next is due, or memory running short.

The live path is run as it is (classes/live/): the camera's frame handler
(copying each frame out of the camera's buffer), the frame router, the burst,
the Recorder saving the mites' ROIs, LiveSession, and MotionAnalysis scoring every mite.
Only the camera is a stand-in: it streams real frames of a recording folder,
grey and full size, at the frame rate asked, and its frames go through the
real FrameHandler. The GigE transfer itself, the fan and the LEDs are not
part of it, nor the results the page is sent after each recording (about
0.1 s, and the workbook every 10 minutes: see the CPU measurements).

Each measurement runs in a process of its own, so one leaves nothing behind
for the next (memory, threads, mite ids), and with the code of any checkout
(--code), e.g. a commit before a change, to compare.

    python scripts/frame_rate_limits.py sample_data --fps 10 33 --seconds 1 3
    python scripts/frame_rate_limits.py <recordings> --fps 33 --frames 10 100 300 --back-to-back

Prints one JSON line per measurement (measure()). notebooks/frame_rate_limits.ipynb
runs the sweeps and draws them.
"""
import argparse
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve()
FRAMES_KEPT = 30  # real frames the stand-in camera streams, over and over
SAMPLE_EVERY = 0.02  # seconds between two readings of the process's memory


class _CameraFrame:
    """What vmbpy hands FrameHandler: a complete frame and its buffer, (H, W, 1)."""

    def __init__(self, frame_id, image):
        self._id = frame_id
        self._image = image

    def get_status(self):
        return "complete"

    def get_id(self):
        return self._id

    def as_numpy_ndarray(self):
        return self._image[:, :, None]


class StreamingCamera:
    """Stands in for classes.live.camera.Camera: streams `images` (grey) one
    after the other at `fps` through the real FrameHandler, from a thread of its
    own, into `frames`, the queue CameraSource reads. A frame it delivers more
    than one frame period late counts as `late`: the computer could not keep
    the pace at all."""

    def __init__(self, images, fps, frames):
        from classes.live.camera import FrameHandler

        self.images = images
        self.fps = fps
        self.frames = frames
        self.handler = FrameHandler(frames, "complete")
        self.description = "stand-in camera"
        self.late = 0
        self._stop = threading.Event()
        self._thread = None

    def open(self):
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()

    def _run(self):
        due, frame_id = time.perf_counter(), 1
        while not self._stop.is_set():
            self.handler(self, None, _CameraFrame(frame_id, self.images[frame_id % len(self.images)]))
            frame_id += 1
            due += 1 / self.fps
            wait = due - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            elif wait < -1 / self.fps:
                self.late += 1
                due = time.perf_counter()

    def queue_frame(self, frame):
        pass  # the buffer goes back to the camera

    def set_fps(self, fps):
        self.fps = fps

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join()


class MemoryWatch:
    """The process's memory (resident set), read every SAMPLE_EVERY seconds;
    `peak` is the most it reached."""

    def __init__(self):
        import psutil

        self._process = psutil.Process()
        self.peak = self.now()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="memory", daemon=True)
        self._thread.start()

    def now(self):
        return self._process.memory_info().rss

    def _watch(self):
        while not self._stop.wait(SAMPLE_EVERY):
            self.peak = max(self.peak, self.now())

    def stop(self):
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, self.now())
        return self.peak


def load_images(data_dir, count=FRAMES_KEPT):
    """The first `count` frames of the folder's recordings, grey, as the camera gives them."""
    import cv2

    paths = sorted(Path(data_dir).glob("*/*.bmp"))[:count]
    if not paths:
        raise FileNotFoundError(f"No recordings in {data_dir}")
    return [cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) for path in paths]


def measure(data_dir, fps, frame_count, recordings=2, back_to_back=False):
    """One live run of `recordings` bursts of `frame_count` frames at `fps`,
    the frames of `data_dir`'s recordings streamed by the stand-in camera.

    The bursts are started as the test run starts them: each once the one
    before is analysed (a recording is due every minute at the least, and is
    analysed long before), or with `back_to_back` each as soon as the one
    before is captured, while it is still being analysed: what happens when
    the analysis falls behind. Returns a dict:

        dropped     frames the router did not take in time (the queue was full)
        late        frames the stand-in camera itself delivered late
        capture_s   seconds a burst took to capture (mean); it should be frame_count / fps
        score_s     seconds scoring one recording took (mean), every mite
        analysed_s  seconds from a burst's end to its recording analysed and on disk (mean)
        peak_mb     the most memory the run took, above what the process held before it
        frame_mb    one frame's size; a recording's frames are frame_count of them
        cpu         processors kept busy over the run, on average (1 = one)
    """
    import psutil

    import pipeline
    from classes.live.lights import NoLights
    from classes.live.recorder import Recorder
    from classes.live.session import LiveSession
    from classes.live.settings import Settings
    from classes.live.sources import CameraSource
    from classes.motion_analysis import MotionAnalysis

    images = load_images(data_dir)
    run_dir = Path(tempfile.mkdtemp(prefix="zzfr"))
    settings = Settings(fps=fps, frame_count=frame_count)
    source = CameraSource("stand-in", settings, NoLights(), camera=object())
    source.camera = StreamingCamera(images, fps, source.frames)
    source.run = lambda: setattr(source, "state", "running")  # no test run: the bursts are started here
    analysis = MotionAnalysis(pipeline._build_zone_manager(pipeline._coords_file(data_dir)))
    scored = []
    add_recording = analysis.add_recording

    def timed(frames):
        start = time.perf_counter()
        add_recording(frames)
        scored.append(time.perf_counter() - start)

    analysis.add_recording = timed
    session = LiveSession(source, analysis, Recorder(run_dir))

    process = psutil.Process()
    source.open()
    time.sleep(1.0)  # the stream settles
    watch = MemoryWatch()
    before = watch.now()
    cpu_before, wall_before = sum(process.cpu_times()[:2]), time.perf_counter()
    session.start()
    start = datetime(2026, 1, 1, 12, 0, 0)
    captured, analysed = [], []
    try:
        for number in range(recordings):
            name = f"{(start + timedelta(minutes=number)):%Y-%m-%d-%H-%M-%S}_fps-{fps}"
            began = time.perf_counter()
            source.start_burst(name).wait()
            ended = time.perf_counter()
            captured.append(ended - began)
            if not back_to_back:
                while len(session.recordings) <= number and not session.finished.is_set():
                    time.sleep(0.005)
                analysed.append(time.perf_counter() - ended)
        source.stop()
        session.finished.wait()
        if back_to_back:
            analysed.append(time.perf_counter() - ended)  # the last recording, after the others
    finally:
        peak = watch.stop()
        shutil.rmtree(run_dir, ignore_errors=True)
    wall = time.perf_counter() - wall_before
    mean = lambda values: round(sum(values) / len(values), 3) if values else None  # noqa: E731
    return {
        "fps": fps,
        "frame_count": frame_count,
        "seconds": round(frame_count / fps, 3),
        "recordings": recordings,
        "back_to_back": back_to_back,
        "mites": len(analysis.mites),
        "dropped": source.handler.dropped,
        "late": source.camera.late,
        "capture_s": mean(captured),
        "expected_s": round(frame_count / fps, 3),
        "score_s": mean(scored),
        "analysed_s": mean(analysed),
        "peak_mb": round((peak - before) / 2**20, 1),
        "frame_mb": round(images[0].nbytes / 2**20, 2),
        "cpu": round((sum(process.cpu_times()[:2]) - cpu_before) / wall, 2),
        "error": session.error or (session.recorder.error if session.recorder else None),
    }


def measure_apart(data_dir, fps, frame_count, recordings=2, back_to_back=False, code=ROOT, python=sys.executable):
    """measure() in a process of its own, with the code of the checkout `code`."""
    args = [python, str(HERE), str(Path(data_dir).resolve()), "--code", str(code), "--fps", str(fps),
            "--frames", str(frame_count), "--recordings", str(recordings), "--one"]
    if back_to_back:
        args.append("--back-to-back")
    done = subprocess.run(args, capture_output=True, text=True, cwd=str(code))
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    if done.returncode != 0 or not lines:
        raise RuntimeError(f"The measurement failed:\n{done.stderr[-2000:]}")
    return json.loads(lines[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_dir", help="a recording folder: its frames are streamed")
    parser.add_argument("--fps", type=float, nargs="+", default=[10])
    parser.add_argument("--seconds", type=float, nargs="*", default=[], help="burst lengths: frames = fps x seconds")
    parser.add_argument("--frames", type=int, nargs="*", default=[], help="frames per recording")
    parser.add_argument("--recordings", type=int, default=2)
    parser.add_argument("--back-to-back", action="store_true")
    parser.add_argument("--code", default=str(ROOT), help="the checkout whose code is measured")
    parser.add_argument("--one", action="store_true", help="measure here, in this process")
    args = parser.parse_args()
    if args.one:
        sys.path.insert(0, args.code)
        fps = int(args.fps[0]) if float(args.fps[0]).is_integer() else args.fps[0]
        print(json.dumps(measure(args.data_dir, fps, args.frames[0], args.recordings, args.back_to_back)), flush=True)
        return
    for fps in args.fps:
        counts = [*args.frames, *(max(1, round(fps * seconds)) for seconds in args.seconds)] or [10]
        for frame_count in counts:
            print(json.dumps(measure_apart(args.data_dir, fps, frame_count, args.recordings, args.back_to_back, args.code)),
                  flush=True)


if __name__ == "__main__":
    main()
