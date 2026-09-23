"""A Discobox test run: the recordings, one every `recording_timeout` minutes,
and the fan and LEDs around each of them.

The timing is the Discobox app's (test_run() in discobox.py). In each cycle the
fan and each LED are switched on so that they run for their set duration and all
end together with the burst of frames; one second after the burst everything is
switched off. Pausing takes effect at the start of the next cycle and pushes every
later cycle back by the length of the pause.

One thing differs on purpose. The app keeps each cycle's actions in a dict keyed
by their start time, so actions due at the same moment overwrite each other: with
equal fan and LED durations (sample_data's 20 s each) only LED 2 was ever
switched on, never the fan or LED 1. Here every action runs.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from classes.live.lights import DEVICES

_logger = logging.getLogger(__name__)

START_DELAY = 0.5  # the app starts the first cycle half a second after "Start"
LIGHTS_AFTER = 1.0  # everything stays on this long after the burst
BURST_GRACE = 10.0  # how long to wait past its planned end for a burst still collecting frames


@dataclass(frozen=True)
class Cycle:
    """When each thing happens in one cycle, in seconds on the run's clock."""

    start: float
    start_recording: float
    stop_recording: float
    switch_on: dict  # device -> when it is switched on


def cycle(start, settings):
    """The Discobox timing of one cycle starting at `start`."""
    recording = settings.recording_seconds
    durations = {"vent": settings.vent_time, "led1": settings.led1_time, "led2": settings.led2_time}
    longest = max(*durations.values(), recording)
    return Cycle(
        start=start,
        start_recording=start + longest - recording,
        stop_recording=start + longest,
        switch_on={device: start + longest - duration for device, duration in durations.items()},
    )


def recording_name(when, fps):
    """A recording's folder name, as the Discobox app names it."""
    return f"{when.strftime('%Y-%m-%d-%H-%M-%S')}_fps-{fps}"


class TestRun:
    """Runs the cycles of a test run in its own thread.

    `start_burst(name)` must start collecting the `frame_count` frames of a
    recording and return an Event set once they are all in; `end_burst()` ends
    a burst still collecting frames long after its planned end (the camera
    dropping frames). When the run is stopped, ending the burst is left to the
    source, once it has taken in every frame already captured. `lights` is a
    Lights (or NoLights). `now()`, `wait(stop_event, seconds)` (returns early
    when the run is stopped) and `wall_clock()` (a datetime, for the recording
    names) are the clock, replaceable in tests.
    """

    __test__ = False  # a Discobox "test run", not a pytest test

    def __init__(self, settings, lights, start_burst, end_burst, now=time.time, wait=None, wall_clock=datetime.now):
        self.settings = settings
        self.lights = lights
        self.start_burst = start_burst
        self.end_burst = end_burst
        self._now = now
        self._stop = threading.Event()
        self._unpaused = threading.Event()
        self._unpaused.set()
        self._wait = wait or (lambda event, seconds: event.wait(max(0.0, seconds)))
        self._wall_clock = wall_clock
        self.recording_count = 0
        self.next_recording = None  # wall-clock time the next burst starts
        self.recordings = []  # names of the recordings started
        self.finished = threading.Event()
        self._thread = None

    @property
    def paused(self):
        return not self._unpaused.is_set()

    @property
    def stopped(self):
        return self._stop.is_set()

    def start(self):
        self._thread = threading.Thread(target=self.run, name="test-run", daemon=True)
        self._thread.start()

    def pause(self):
        self._unpaused.clear()

    def resume(self):
        self._unpaused.set()

    def stop(self):
        self._stop.set()
        self._unpaused.set()

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    def _wait_until(self, when):
        """Wait until `when` on the run's clock; False if the run was stopped."""
        while not self._stop.is_set():
            left = when - self._now()
            if left <= 0:
                return True
            self._wait(self._stop, left)
        return False

    def run(self):
        try:
            self._run()
        except Exception:
            _logger.exception("The test run failed")
            raise
        finally:
            try:
                self.lights.all_off()
            finally:
                self.next_recording = None
                self.finished.set()

    def _run(self):
        settings = self.settings
        start = self._now() + START_DELAY
        timeout = settings.recording_timeout * 60
        while self.recording_count < settings.recording_count and not self._stop.is_set():
            if not self._wait_until(start + timeout * self.recording_count):
                return
            self.recording_count += 1
            if self.paused:
                paused_at = self._now()
                self.next_recording = None
                self._unpaused.wait()
                if self._stop.is_set():
                    return
                start += self._now() - paused_at
            planned = cycle(start + timeout * (self.recording_count - 1), settings)
            self.next_recording = self._wall_clock().timestamp() + planned.start_recording - self._now()

            actions = [(when, "switch", device) for device, when in planned.switch_on.items()]
            actions.append((planned.start_recording, "record", None))
            burst_done = None
            for when, action, device in sorted(actions, key=lambda item: item[0]):
                if not self._wait_until(when):
                    return
                if action == "switch":
                    self.lights.switch(device, True, getattr(settings, device))
                else:
                    name = recording_name(self._wall_clock(), settings.fps)
                    self.recordings.append(name)
                    burst_done = self.start_burst(name)

            # Everything stays on for the whole burst, even one running late
            # because frames were dropped, then one second more.
            deadline = planned.stop_recording + BURST_GRACE
            while not burst_done.is_set() and not self._stop.is_set() and self._now() < deadline:
                self._wait(self._stop, min(0.1, deadline - self._now()))
            if self._stop.is_set():
                # Stopped: the source stops the camera, takes in the frames
                # already captured and ends the burst with them.
                return
            if not burst_done.is_set():
                _logger.warning("Recording %s was still collecting frames at its deadline; ending it.", self.recordings[-1])
                self.end_burst()
            if not self._wait_until(planned.stop_recording + LIGHTS_AFTER):
                return
            for device in DEVICES:
                self.lights.switch_off(device)
            self.next_recording = None
