"""The Discobox hardware parts, with stand-ins for the camera, the serial port and
the clock: the frame handler, the camera set-up, the fan and LED commands, the
test-run schedule, the camera's bursts and connecting to them all."""

import queue
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

import pipeline
from pipeline.live import live_runs, live_setup
from classes.frame_source import Frame, RecordingEnd
from classes.live import camera as live_camera
from classes.live.camera import FrameHandler, choose_camera, configure
from classes.live.lights import COMMANDS, Lights, NoLights, packet
from classes.live.schedule import TestRun, cycle
from classes.live.settings import Settings
from classes.live.sources import CameraSource

COMPLETE = "Complete"


# --- the frame handler ----------------------------------------------------------------

class FakeFrame:
    def __init__(self, frame_id, pixels, status=COMPLETE):
        self.frame_id = frame_id
        self.pixels = pixels
        self.status = status

    def get_status(self):
        return self.status

    def get_id(self):
        return self.frame_id

    def as_numpy_ndarray(self):
        return self.pixels


class FakeCam:
    def __init__(self):
        self.queued = []

    def queue_frame(self, frame):
        self.queued.append(frame)


def test_the_handler_copies_the_frame_and_gives_the_buffer_back():
    frames, cam = queue.Queue(), FakeCam()
    buffer = np.arange(12, dtype=np.uint8).reshape(3, 4, 1)
    frame = FakeFrame(7, buffer)
    FrameHandler(frames, COMPLETE)(cam, None, frame)
    frame_id, _arrived, image = frames.get_nowait()
    buffer[:] = 0  # vmbpy reuses the buffer for the next frame
    assert frame_id == 7 and image.shape == (3, 4) and image[2, 3] == 11
    assert cam.queued == [frame]


def test_a_full_queue_drops_and_counts_the_frame():
    frames, cam = queue.Queue(maxsize=1), FakeCam()
    handler = FrameHandler(frames, COMPLETE)
    for frame_id in range(3):
        handler(cam, None, FakeFrame(frame_id, np.zeros((2, 2, 1), np.uint8)))
    assert (handler.received, handler.dropped, frames.qsize()) == (3, 2, 1)
    assert len(cam.queued) == 3


def test_an_incomplete_frame_is_skipped_but_its_buffer_goes_back():
    frames, cam = queue.Queue(), FakeCam()
    handler = FrameHandler(frames, COMPLETE)
    handler(cam, None, FakeFrame(1, np.zeros((2, 2, 1), np.uint8), status="Incomplete"))
    assert frames.empty() and handler.incomplete == 1 and len(cam.queued) == 1


def test_the_buffer_goes_back_even_when_reading_the_frame_fails():
    class Broken(FakeFrame):
        def as_numpy_ndarray(self):
            raise RuntimeError("bad frame")

    cam = FakeCam()
    with pytest.raises(RuntimeError):
        FrameHandler(queue.Queue(), COMPLETE)(cam, None, Broken(1, None))
    assert len(cam.queued) == 1


# --- the camera set-up -----------------------------------------------------------------

def test_the_camera_is_configured_as_the_discobox_app_does():
    calls = []

    class Selector:
        def set(self, value):
            calls.append(("UserSetSelector", value))

    class Cam:
        UserSetSelector = Selector()

    configure(Cam(), 30, lambda cam, name, value: calls.append((name, value)))
    assert calls == [
        ("UserSetSelector", "Default"),
        ("ExposureAuto", "Continuous"),
        ("AcquisitionMode", "Continuous"),
        ("AcquisitionFrameCount", 65535),
        ("TriggerSelector", "FrameStart"),
        ("TriggerMode", "On"),
        ("TriggerSource", "FixedRate"),
        ("AcquisitionFrameRateAbs", 30),
    ]


class DiscoveredCam:
    def __init__(self, cam_id):
        self.cam_id = cam_id

    def get_id(self):
        return self.cam_id

    def get_extended_id(self):
        return f"extended-{self.cam_id}"


class Discovery:
    """A started Vimba X whose GigE cameras answer the discovery after a while,
    on a clock that moves only when waited on."""

    def __init__(self, answers):
        self.answers = answers  # seconds after start -> camera id
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def get_all_cameras(self):
        return tuple(DiscoveredCam(cam_id) for when, cam_id in sorted(self.answers.items()) if when <= self.t)


def test_discovery_waits_for_a_gige_camera_that_answers_late():
    vmb = Discovery({0.4: "DEV_1"})
    cams = live_camera.discover(vmb, now=vmb.now, sleep=vmb.sleep)
    assert [cam.get_id() for cam in cams] == ["DEV_1"]
    assert vmb.t < 1.5  # it stops soon after the camera answered


def test_discovery_waits_a_moment_more_for_other_cameras():
    vmb = Discovery({0.2: "DEV_1", 0.5: "DEV_2"})
    assert len(live_camera.discover(vmb, now=vmb.now, sleep=vmb.sleep)) == 2


def test_discovery_waits_for_the_camera_asked_for():
    vmb = Discovery({0.1: "DEV_1", 1.2: "DEV_2"})
    cams = live_camera.discover(vmb, wanted="DEV_2", now=vmb.now, sleep=vmb.sleep)
    assert "DEV_2" in [cam.get_id() for cam in cams]


def test_discovery_gives_up_when_no_camera_answers():
    vmb = Discovery({})
    assert live_camera.discover(vmb, now=vmb.now, sleep=vmb.sleep) == ()
    assert live_camera.DISCOVERY_WAIT <= vmb.t < live_camera.DISCOVERY_WAIT + 0.2


def test_streaming_passes_vmbpys_type_check():
    # With vmbpy 1.1 on Python 3.14, start_streaming() failed with "name 'Camera' is
    # not defined": its type check could not resolve the hint of the frame handler.
    # Calling Stream's check on its own, as here, fails the same way on any Python.
    vmbpy = pytest.importorskip("vmbpy")
    from vmbpy.stream import Stream
    from vmbpy.util.runtime_type_check import RuntimeTypeCheckEnable

    live_camera.resolve_type_hint_names(vmbpy)
    check = Stream.start_streaming
    while check is not None and not any(isinstance(getattr(cell, "cell_contents", None), RuntimeTypeCheckEnable)
                                        for cell in check.__closure__ or ()):
        check = getattr(check, "__wrapped__", None)
    if check is None:
        pytest.skip("this vmbpy does not type-check start_streaming")
    handler = FrameHandler(queue.Queue(), vmbpy.FrameStatus.Complete)
    with pytest.raises(AttributeError):  # the check passed; the stand-in stream then cannot stream
        check(object(), handler=handler, buffer_count=10, allocation_mode=vmbpy.AllocationMode.AnnounceFrame)


def test_without_an_id_the_only_camera_is_used():
    one = [{"id": "DEV_1", "model": "Mako"}]
    assert choose_camera(None, one) == "DEV_1"
    assert choose_camera("DEV_9", one) == "DEV_9"
    with pytest.raises(live_camera.CameraError, match="No camera"):
        choose_camera(None, [])
    with pytest.raises(live_camera.CameraError, match="--camera-id"):
        choose_camera(None, one + [{"id": "DEV_2", "model": "Mako"}])


# --- the fan and LEDs ------------------------------------------------------------------

class Port:
    def __init__(self):
        self.sent = b""

    def write(self, data):
        self.sent += data

    def flush(self):
        pass


def test_packets_are_those_of_the_discobox_controller():
    # _get_packet() in the Discobox app's controller.py: [cmd, val, cmd ^ val]
    for command, code in COMMANDS.items():
        for value in (0, 1, 128, 255):
            assert packet(command, value) == bytes([code, value, code ^ value])


def test_switching_sends_what_the_discobox_app_sends():
    port = Port()
    lights = Lights(port="COM9", connection=port)
    lights.switch("vent", True, 200)   # _start_vent(): vent on, then its intensity
    lights.switch_off("led1")         # _stop_all(): each device off
    lights.all_off()
    assert port.sent == packet("vent_on_off", 1) + packet("vent", 200) + packet("led1_on_off", 0) + packet("all_off", 0)
    assert lights.state()["vent"] == {"on": False, "level": 200}


def test_leds_kept_on_are_told_again_until_released():
    port = Port()
    lights = Lights(connection=port)
    lights.on["led1"] = True  # believed on, though the controller may have missed it: told all the same
    lights.keep_on({"led1": 120, "led2": 200}, every=0.02)
    told = packet("led1_on_off", 1) + packet("led1", 120) + packet("led2_on_off", 1) + packet("led2", 200)
    assert port.sent == told
    lights.set_level("led2", 90)  # a reminder is at the intensity set since
    time.sleep(0.15)
    assert port.sent.count(packet("led1_on_off", 1)) > 2 and packet("led2", 90) in port.sent
    lights.switch_off("led2")  # one switched off is not kept on
    time.sleep(0.06)
    after = len(port.sent)
    time.sleep(0.06)
    assert packet("led2_on_off", 1) not in port.sent[after:] and packet("led1_on_off", 1) in port.sent[after:]
    lights.all_off()  # nothing is sent once the run has the lights
    sent = port.sent
    time.sleep(0.1)
    assert port.sent == sent and not any(lights.on.values())


def test_the_first_command_waits_for_the_controller_to_start(monkeypatch):
    port = Port()
    lights = Lights(connection=port)
    lights._ready_at = time.monotonic() + 0.2  # as on a port just opened
    started = time.monotonic()
    lights.switch("led1", True, 255)
    assert time.monotonic() - started >= 0.18 and port.sent
    started = time.monotonic()
    lights.switch("led2", True, 255)
    assert time.monotonic() - started < 0.1


def test_without_a_controller_every_command_does_nothing():
    lights = NoLights()
    lights.switch("led2", True, 10)
    assert not lights.state()["connected"]


# --- the settings ------------------------------------------------------------------------

def test_settings_read_the_discobox_file_format(tmp_path):
    (tmp_path / "settings.txt").write_text(
        "recording_count=6\nrecording_timeout=5\nvent_time=20\nled1_time=20\nled2_time=20\n"
        "frame_count=30\nfps=30\nvent=255\nled1=255\nled2=255\n")
    settings = Settings.from_file(tmp_path / "settings.txt")
    # Six recordings five minutes apart: an experiment of 25 minutes.
    assert (settings.run_minutes, settings.recording_count, settings.recording_timeout, settings.fps) == (25, 6, 5, 30)
    settings.save(tmp_path / "again.txt")
    saved = (tmp_path / "again.txt").read_text()
    assert saved.startswith("recording_count=6\nrun_minutes=25\ndeath_minutes=0\nfollow_px=50\n")
    assert Settings.from_file(tmp_path / "again.txt") == settings
    # An earlier "go on until every mite is dead" is read without it: every run ends so now.
    (tmp_path / "older.txt").write_text("run_minutes=10\ndeath_minutes=5\ndeath_reset=1\n")
    assert Settings.from_file(tmp_path / "older.txt") == Settings(run_minutes=10, death_minutes=5)


def test_every_recording_is_three_seconds_at_30_fps(tmp_path):
    # a file of another frame rate or length is read as the fixed one
    (tmp_path / "settings.txt").write_text("recording_timeout=5\nframe_count=10\nfps=10\n")
    settings = Settings.from_file(tmp_path / "settings.txt")
    assert (settings.frame_count, settings.fps, settings.recording_seconds) == (90, 30, 3.0)
    # the fixed values pass (a saved file's as_dict() holds them), others are refused
    assert Settings.from_dict(settings.as_dict()) == settings
    with pytest.raises(ValueError, match="90 frames at 30 fps"):
        Settings.from_dict({"fps": 10})
    with pytest.raises(ValueError, match="90 frames at 30 fps"):
        Settings.from_dict({"frame_count": 30})


def test_the_run_lasts_the_experiment_and_the_time_to_count_a_mite_dead():
    settings = Settings(run_minutes=25, recording_timeout=5)
    assert settings.recording_count == 6  # at 0, 5, ... 25 min
    assert Settings(run_minutes=24, recording_timeout=5).recording_count == 6  # the last one reaches past it
    settings = Settings(run_minutes=25, death_minutes=12, recording_timeout=5)
    assert settings.recording_count == 9  # at most: through 37 min, the last at 40


def test_a_run_needs_a_time_to_count_a_mite_dead():
    with pytest.raises(ValueError, match="Dead when still for"):
        Settings(death_minutes=0).check_death_time()
    Settings(death_minutes=1).check_death_time()


def test_settings_keep_to_the_discobox_ranges():
    with pytest.raises(ValueError, match="between 0 and 3600"):
        Settings.from_dict({"vent_time": 4000})
    with pytest.raises(ValueError, match="whole number"):
        Settings.from_dict({"led1_time": 2.5})
    with pytest.raises(ValueError, match="longer than"):
        Settings.from_dict({"vent_time": 90, "recording_timeout": 1}).check_cycle()


# --- the schedule ------------------------------------------------------------------------

class FakeClock:
    """Time that passes only when waited for."""

    def __init__(self):
        self.t = 1000.0
        self.base = datetime(2026, 9, 23, 10, 0, 0)

    def now(self):
        return self.t

    def wait(self, event, seconds):
        self.t += max(seconds, 0.001)
        return event.is_set()

    def wall_clock(self):
        return self.base + timedelta(seconds=self.t - 1000.0)


class LoggedLights(NoLights):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.log = []

    def switch(self, device, on, level=None):
        self.log.append((round(self.clock.now() - 1000.5, 3), device, "on", level))

    def switch_off(self, device):
        self.log.append((round(self.clock.now() - 1000.5, 3), device, "off"))

    def all_off(self):
        self.log.append((round(self.clock.now() - 1000.5, 3), "all", "off"))


def run_schedule(settings, **kwargs):
    clock = FakeClock()
    lights = LoggedLights(clock)
    bursts = []

    def start_burst(name):
        bursts.append((round(clock.now() - 1000.5, 3), name))
        done = threading.Event()
        done.set()
        return done

    run = TestRun(settings, lights, start_burst, lambda: None, now=clock.now, wait=clock.wait,
                  wall_clock=clock.wall_clock, **kwargs)
    return run, lights, bursts


def test_the_cycle_is_timed_as_in_the_discobox_app():
    settings = Settings(vent_time=20, led1_time=15, led2_time=10, frame_count=30, fps=30)
    planned = cycle(0.0, settings)
    # longest = 20 s: every device ends with the 1 s burst, which starts at 19 s.
    assert (planned.start_recording, planned.stop_recording) == (19.0, 20.0)
    assert planned.switch_on == {"vent": 0.0, "led1": 5.0, "led2": 10.0}


def test_every_device_is_switched_on_even_with_equal_durations():
    # With equal durations the Discobox app only ever switched on LED 2.
    settings = Settings(run_minutes=5, recording_timeout=5, vent_time=20, led1_time=20, led2_time=20,
                        frame_count=30, fps=30, vent=100, led1=150, led2=200)
    run, lights, bursts = run_schedule(settings)
    run.run()
    first_cycle = [entry for entry in lights.log if entry[0] < 300]
    assert first_cycle[:3] == [(0.0, "vent", "on", 100), (0.0, "led1", "on", 150), (0.0, "led2", "on", 200)]
    assert [entry[1:] for entry in first_cycle[3:6]] == [("vent", "off"), ("led1", "off"), ("led2", "off")]
    assert first_cycle[3][0] == pytest.approx(21.0, abs=0.01)  # one second after the burst ends at 20 s
    assert [when for when, _name in bursts] == [19.0, 319.0]
    assert [name for _when, name in bursts] == ["2026-09-23-10-00-19_fps-30", "2026-09-23-10-05-19_fps-30"]
    assert lights.log[-1][1:] == ("all", "off")
    assert run.finished.is_set()


def test_a_pause_waits_for_the_next_cycle_and_pushes_the_rest_back():
    settings = Settings(run_minutes=2, recording_timeout=1, vent_time=0, led1_time=0, led2_time=0,
                        frame_count=10, fps=10)
    run, _lights, bursts = run_schedule(settings)
    thread = threading.Thread(target=run.run)
    run.pause()
    thread.start()
    time.sleep(0.05)
    assert bursts == [] and thread.is_alive()
    run.resume()
    thread.join(5)
    assert len(bursts) == 3 and bursts[1][0] - bursts[0][0] == pytest.approx(60, abs=0.01)


def test_the_timeline_follows_the_run_and_a_pause_pushes_the_rest_back():
    settings = Settings(run_minutes=2, recording_timeout=1, vent_time=0, led1_time=0, led2_time=0,
                        frame_count=10, fps=10)
    run, lights, bursts = run_schedule(settings)
    assert run.timeline() is None
    run.pause()
    thread = threading.Thread(target=run.run)
    thread.start()
    deadline = time.monotonic() + 5
    while run._held_since is None and time.monotonic() < deadline:
        time.sleep(0.01)
    # Held at its first cycle: three 1 s bursts a minute apart, all off 1 s after the last.
    line = run.timeline()
    assert line["elapsed"] == pytest.approx(0, abs=0.01)
    assert line["starts"] == pytest.approx([0, 60, 120], abs=0.01)
    assert line["length"] == pytest.approx(122, abs=0.01)
    lights.clock.t += 100  # the pause goes on for 100 s: so does the run, and it ends 100 s later
    line = run.timeline()
    assert line["elapsed"] == pytest.approx(100, abs=0.01)
    assert line["starts"] == pytest.approx([100, 160, 220], abs=0.01)
    assert line["length"] == pytest.approx(222, abs=0.01)
    run.resume()
    thread.join(5)
    assert [when for when, _name in bursts] == pytest.approx([100, 160, 220], abs=0.01)
    line = run.timeline()
    assert line["starts"] == pytest.approx([100, 160, 220], abs=0.01)
    assert line["elapsed"] == pytest.approx(line["length"], abs=0.01)


def test_stopping_ends_the_run_without_another_burst():
    settings = Settings(run_minutes=4, recording_timeout=1, frame_count=10, fps=10)
    run, lights, bursts = run_schedule(settings)
    run.stop()
    run.run()
    assert bursts == [] and lights.log[-1][1:] == ("all", "off")


# --- the camera's bursts ---------------------------------------------------------------

class FakeCamera:
    """Streams frames through a real FrameHandler, as vmbpy would, at a set rate.
    Frame ids start at `first_id` and wrap after 65535 like a GigE block id."""

    def __init__(self, frames, fps=200, first_id=1, shape=(8, 10)):
        self.handler = FrameHandler(frames, COMPLETE)
        self.fps = fps
        self.next_id = first_id
        self.shape = shape
        self.description = "Fake camera"
        self._stop = threading.Event()
        self._thread = None
        self.streaming = False

    def open(self):
        self.streaming = True
        self._thread = threading.Thread(target=self._stream, daemon=True)
        self._thread.start()

    def _stream(self):
        cam = FakeCam()
        while not self._stop.is_set():
            pixels = np.full(self.shape + (1,), self.next_id % 256, dtype=np.uint8)
            self.handler(cam, None, FakeFrame(self.next_id, pixels))
            self.next_id = self.next_id % 65535 + 1
            time.sleep(1 / self.fps)

    def set_fps(self, fps):
        self.fps = fps

    def stop(self):
        self._stop.set()
        self._thread.join()
        self.streaming = False


def camera_source(settings, first_id=1, fps=200, lights=None):
    frames = queue.Queue(maxsize=64)
    camera = FakeCamera(frames, fps=fps, first_id=first_id)
    source = CameraSource(None, settings, lights or NoLights(), camera=camera)
    source.frames = frames
    source.camera = camera
    return source


def collect(source, timeout=10):
    events = []
    thread = threading.Thread(target=lambda: events.extend(source.events()), daemon=True)
    thread.start()
    return events, thread


def test_a_burst_is_handed_over_whole_in_file_name_order():
    # The GigE block id wraps from 65535 to 1 in the middle of this burst; folder
    # mode sorts the saved files by name, and so does the burst.
    source = camera_source(Settings(frame_count=6, fps=30), first_id=65533)
    source.open()
    events, reader = collect(source)
    done = source.start_burst("2026-09-23-10-00-19_fps-30")
    assert done.wait(5)
    source.stop()
    reader.join(5)
    frames = [event for event in events if isinstance(event, Frame)]
    names = [frame.filename for frame in frames]
    assert names == sorted(names) and len(frames) == 6
    assert {name[-10:-4] for name in names} >= {"065535", "000001"}
    assert [frame.index for frame in frames] == list(range(6))
    assert isinstance(events[-1], RecordingEnd)
    assert frames[0].image.shape == (8, 10)


def test_stopping_mid_burst_keeps_every_frame_already_captured():
    source = camera_source(Settings(frame_count=10_000, fps=30))
    source.open()
    events, reader = collect(source)
    source.start_burst("2026-09-23-10-00-19_fps-30")
    time.sleep(0.2)
    source.stop()
    assert source.wait_closed(5)
    reader.join(5)
    frames = [event for event in events if isinstance(event, Frame)]
    assert frames and isinstance(events[-1], RecordingEnd)
    assert not source.camera.streaming and source.frames.empty()
    # The last frame taken in before the camera stopped is the burst's last.
    assert frames[-1].image is source.latest.get()[1]  # the camera's own frame, never copied


def test_the_camera_and_schedule_run_a_whole_test_run():
    speed = 200.0
    start, base = time.monotonic(), datetime(2026, 9, 23, 10, 0, 0)
    fast_now = lambda: start + (time.monotonic() - start) * speed  # noqa: E731
    clock = {
        "now": fast_now,
        "wait": lambda event, seconds: event.wait(max(0.0, seconds) / speed),
        "wall_clock": lambda: base + timedelta(seconds=fast_now() - start),
    }
    settings = Settings(run_minutes=2, recording_timeout=1, vent_time=2, led1_time=2, led2_time=2,
                        frame_count=5, fps=30)
    source = camera_source(settings, fps=300)
    source.clock = clock
    source.open()
    events, reader = collect(source)
    source.run()
    reader.join(10)
    ends = [event.recording.name for event in events if isinstance(event, RecordingEnd)]
    assert len(ends) == 3 and len(set(ends)) == 3
    assert sum(isinstance(event, Frame) for event in events) == 15
    assert source.state == "finished" and not source.camera.streaming


def test_the_status_says_how_far_the_run_is():
    settings = Settings(run_minutes=1, recording_timeout=1, vent_time=2, led1_time=2, led2_time=2,
                        frame_count=6, fps=30)
    source = camera_source(settings)
    assert source.status()["timeline"] is None
    source.test_run = SimpleNamespace(recording_count=1, next_recording=None, planned_count=lambda: 2,
                                      timeline=lambda: {"elapsed": 30.04, "length": 63.0, "starts": [1.8, 61.8]})
    # The results' time axis runs from the first burst to the end of the last, 0.2 s long.
    assert source.status()["timeline"] == {"elapsed": 30.0, "length": 63.0, "starts": [1.8, 61.8],
                                           "minutes": round(60.2 / 60, 3)}


# --- connecting --------------------------------------------------------------------------

def test_both_leds_are_on_from_connecting_until_the_run_starts(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.txt"
    Settings(led1=120, led2=200).save(settings_path)
    lights = Lights(connection=Port())
    monkeypatch.setattr(live_setup.live_camera, "choose_camera", lambda camera_id: "DEV_1")
    monkeypatch.setattr(live_setup, "open_lights", lambda port: lights)
    monkeypatch.setattr(live_setup, "CameraSource", lambda _id, settings, lights: camera_source(settings, lights=lights))
    monkeypatch.setattr(live_runs, "LIGHTS_SETTLE", 0)
    pipeline.open_live("leds", tmp_path / "out", "leds", settings_path=settings_path, recordings_root=tmp_path / "recordings")
    try:
        state = pipeline.live_status("leds")["lights"]
        assert (state["led1"], state["led2"]) == ({"on": True, "level": 120}, {"on": True, "level": 200})
        assert not state["vent"]["on"]
        # The fan can be switched to check it, and an LED's intensity set; an LED cannot be switched off.
        assert pipeline.set_live_light("leds", "vent", on=True, level=90)["vent"] == {"on": True, "level": 90}
        assert pipeline.set_live_light("leds", "led1", level=60)["led1"] == {"on": True, "level": 60}
        with pytest.raises(ValueError, match="stay on"):
            pipeline.set_live_light("leds", "led2", on=False)
        state = pipeline.live_status("leds")["lights"]
        assert state["led1"]["on"] and state["led2"] == {"on": True, "level": 200}
        # Were one off all the same, labelling switches it back on.
        lights.switch_off("led2")
        live_runs.light_for_labelling(live_runs.open_runs["leds"])
        assert pipeline.live_status("leds")["lights"]["led2"] == {"on": True, "level": 200}
        # Until the run starts both are kept on, told again even when believed on.
        assert lights._kept == {"led1", "led2"} and lights._keeper is not None
        port = lights.connection
        port.sent = b""
        live_runs.light_for_labelling(live_runs.open_runs["leds"])
        assert packet("led1_on_off", 1) + packet("led1", 60) in port.sent
        # A start that fails leaves them on.
        def refuse():
            raise ValueError("cannot start")
        monkeypatch.setattr(live_runs.open_runs["leds"].session, "start", refuse)
        with pytest.raises(ValueError, match="Dead when still for"):  # a time to count a mite dead first
            pipeline.start_live("leds")
        pipeline.save_live_settings({"death_minutes": 30}, "leds", settings_path=settings_path)
        with pytest.raises(ValueError, match="cannot start"):
            pipeline.start_live("leds")
        state = pipeline.live_status("leds")["lights"]
        assert state["led1"]["on"] and state["led2"]["on"] and lights._keeper is not None
    finally:
        pipeline.close_live("leds")
    assert not any(lights.on.values())


def test_the_results_take_the_death_time_saved_with_the_recordings(tmp_path):
    assert pipeline.death_minutes(tmp_path) == 0
    Settings(death_minutes=400).save(tmp_path / pipeline.SETTINGS_FILENAME)
    assert pipeline.death_minutes(tmp_path) == 400


def test_the_death_time_can_be_set_for_a_folder_keeping_its_other_settings(tmp_path):
    (tmp_path / pipeline.SETTINGS_FILENAME).write_text("recording_count=6\nfps=30\ndeath_minutes=5\n")
    assert pipeline.save_death_minutes(tmp_path, 400) == 400
    assert (tmp_path / pipeline.SETTINGS_FILENAME).read_text() == "recording_count=6\nfps=30\ndeath_minutes=400\n"
    assert pipeline.death_minutes(tmp_path) == 400
    with pytest.raises(ValueError, match="whole number"):
        pipeline.save_death_minutes(tmp_path, 2.5)
    with pytest.raises(ValueError, match="between 0 and"):
        pipeline.save_death_minutes(tmp_path, -1)
    bare = tmp_path / "bare"
    bare.mkdir()
    pipeline.save_death_minutes(bare, 60)
    assert (bare / pipeline.SETTINGS_FILENAME).read_text() == "death_minutes=60\n"


