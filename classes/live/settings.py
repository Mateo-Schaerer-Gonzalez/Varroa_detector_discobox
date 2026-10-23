"""The settings of a Discobox test run, in the Discobox app's own file format.

The fields, their defaults and their ranges are those of the Discobox app
(src/settings.py and src/settings_view.py), but for the length of the run: the
app asks for a number of recordings, this app for how long the experiment lasts.
A test run is a recording every `recording_timeout` minutes for at most
`run_minutes`, then `death_minutes` more, the time a mite must be still to count
as dead, so a mite alive at the end of the experiment can still be told from a
dead one. It ends sooner once every mite of every zone is dead
(pipeline/live/live_capture.py, classes/live/progress.py); `death_minutes` must
not be 0 for that. Between two
recordings a mite is followed at most `follow_px` pixels (0: not at all; see
classes/scoring/motion_analysis.py). Each recording is a burst of FRAME_COUNT frames
at FPS, with the fan (`vent`) and the two LEDs switched on at their intensity
(0-255) for their duration in seconds, ending with the burst. `zones_per_plate`
is how many zones each plate is cut into for the analysis (classes/plate/zone_layout.py).

The burst is fixed, not a setting: 3 s at 30 fps. A score's threshold only fits
recordings of the length and frame rate it was calibrated on, and a longer
recording tells moving from still far better than a faster one
(notebooks/poke_run_followed.ipynb, section 9). `frame_count`
and `fps` stay fields, as the file and the code read them, but no file, page or
command line sets them: a saved file's values are read as these, and from_dict()
refuses others.

The file is `key=value` lines, the format DataLoader reads from a session's
.settings.txt, so a live run's settings are written next to its recordings. It
still holds the Discobox app's `recording_count`, the recordings planned at
most. A file with `death_reset` (an earlier "go on until every mite is dead")
is read without it: every run now ends once every mite is dead.
"""

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# Every recording: FRAME_COUNT frames at FPS (3 s). The camera (Mako G-319B) takes at most 33 fps.
FPS = 30
FRAME_COUNT = 90
FIXED = {"frame_count": FRAME_COUNT, "fps": FPS}

# name: (label, unit, lowest, highest).
RANGES = {
    "run_minutes": ("Experiment duration, at most", "min", 0, 43200),
    "death_minutes": ("Dead when still for", "min", 0, 43200),
    "follow_px": ("Most a mite moves between recordings", "px", 0, 500),
    "recording_timeout": ("Time between recordings", "min", 1, 1440),
    "vent_time": ("Fan duration", "s", 0, 3600),
    "led1_time": ("LED 1 duration", "s", 0, 3600),
    "led2_time": ("LED 2 duration", "s", 0, 3600),
    "vent": ("Fan intensity", "", 0, 255),
    "led1": ("LED 1 intensity", "", 0, 255),
    "led2": ("LED 2 intensity", "", 0, 255),
    "zones_per_plate": ("Zones per plate", "", 1, 2),
}


@dataclass
class Settings:
    run_minutes: int = 10
    death_minutes: int = 0
    follow_px: int = 50
    recording_timeout: int = 1
    vent_time: int = 10
    led1_time: int = 10
    led2_time: int = 10
    frame_count: int = FRAME_COUNT
    fps: int = FPS
    vent: int = 255
    led1: int = 255
    led2: int = 255
    zones_per_plate: int = 1

    @classmethod
    def from_dict(cls, values):
        """Settings from `values` (name -> number), each checked against RANGES.
        Names not given keep their default. `frame_count` and `fps` may only be
        given at their fixed values (FIXED)."""
        checked = {}
        for name, value in values.items():
            if name in FIXED:
                if value != FIXED[name]:
                    raise ValueError(f"Every recording is {FRAME_COUNT} frames at {FPS} fps; {name} cannot be changed.")
                continue
            if name not in RANGES:
                raise ValueError(f"Unknown setting {name!r}.")
            label, _unit, lowest, highest = RANGES[name]
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{label} must be a whole number, not {value!r}.")
            if float(value) != number:
                raise ValueError(f"{label} must be a whole number, not {value!r}.")
            if not lowest <= number <= highest:
                raise ValueError(f"{label} must be between {lowest} and {highest}.")
            checked[name] = number
        return cls(**checked)

    @classmethod
    def from_file(cls, path):
        """The settings saved in `path`; the defaults if there is no such file."""
        path = Path(path)
        if not path.is_file():
            return cls()
        values = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        # A file of the Discobox app, or of this app before the run had a length:
        # its recordings, one every `recording_timeout` minutes, last this long.
        if "run_minutes" not in values and "recording_count" in values:
            try:
                count, every = int(values["recording_count"]), int(values.get("recording_timeout", cls.recording_timeout))
                values["run_minutes"] = max(0, count - 1) * every
            except ValueError:
                pass
        return cls.from_dict({key: value for key, value in values.items() if key in RANGES})

    def save(self, path):
        Path(path).write_text(str(self), encoding="utf-8")

    def __str__(self):
        lines = [f"{field.name}={getattr(self, field.name)}\n" for field in fields(self)]
        return f"recording_count={self.recording_count}\n" + "".join(lines)

    def as_dict(self):
        return asdict(self)

    def recordings_until(self, minutes):
        """How many recordings, the first at 0 and one every `recording_timeout`
        minutes, it takes to reach `minutes`."""
        return math.ceil(minutes / self.recording_timeout - 1e-9) + 1

    @property
    def recording_count(self):
        """The recordings planned at most: through the experiment and the time a
        mite must be still to count as dead. The run ends sooner once every mite is dead."""
        return self.recordings_until(self.run_minutes + self.death_minutes)

    @property
    def recording_seconds(self):
        return self.frame_count / float(self.fps)

    @property
    def cycle_seconds(self):
        """How long one recording takes, from the first device switched on to
        everything off again (one second after the burst)."""
        return max(self.vent_time, self.led1_time, self.led2_time, self.recording_seconds) + 1

    def plan(self):
        """The run these settings make, for the live page: each recording's burst
        and whole cycle in seconds, and the recordings planned at most and the
        minutes they span."""
        return {
            "recording_seconds": self.recording_seconds,
            "cycle_seconds": self.cycle_seconds,
            "recordings": self.recording_count,
            "minutes": (self.recording_count - 1) * self.recording_timeout,
        }

    def check_death_time(self):
        """A run stops following a mite once it counts as dead, and ends once
        all do: that needs a time to count one as dead."""
        if not self.death_minutes:
            label = RANGES["death_minutes"][0]
            raise ValueError(f"Set '{label}': a mite still for that long counts as dead, is no longer followed, "
                             "and the run ends once every mite is dead.")

    def check_cycle(self):
        """A recording must be over before the next one is due."""
        if self.cycle_seconds > self.recording_timeout * 60:
            raise ValueError(
                f"One recording takes {self.cycle_seconds:.0f} s (the fan, the LEDs and the burst), longer than "
                f"the {self.recording_timeout} min between recordings."
            )
