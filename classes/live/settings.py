"""The settings of a Discobox test run, in the Discobox app's own file format.

The fields, their defaults and their ranges are those of the Discobox app
(src/settings.py and src/settings_view.py), but for the length of the run: the
app asks for a number of recordings, this app for how long the experiment lasts.
A test run is a recording every `recording_timeout` minutes for at most
`run_minutes`, then `death_minutes` more, the time a mite must be still to count
as dead, so a mite alive at the end of the experiment can still be told from a
dead one. It ends sooner once every mite of every zone is dead
(pipeline/live/live_capture.py, classes/live/progress.py) unless `stop_when_dead`
is 0 (the user's choice of 2026-11-17: optional, on by default; from 2026-11-19 a run
without it follows, scores and saves every mite, dead ones too, in every recording for
the whole duration: more storage); `death_minutes` must not be 0 either way, as the
zone circles and the stop rule need it. Between two
recordings a mite is followed at most `follow_px` pixels (0: not at all; see
classes/scoring/motion_analysis.py). Each recording is a burst of FRAME_COUNT frames
at FPS, with the fan (`vent`) and the two LEDs switched on at their intensity
(0-255) for their duration in seconds, ending with the burst. `zone_mask` is
the zone mask the plates are cut into for the analysis (classes/plate/zone_masks.py),
the only setting that is a name, not a number; a file of earlier versions gives
`zones_per_plate` (1 or 2), the built-in mask of that name.

The burst's length (`recording_length`, whole seconds) and frame rate (`fps`)
are settings again since 2026-11-17 (the user's choice, after they were fixed at
3 s / 30 fps from 2026-10-20): the default stays 3 s at 30 fps, and the page says
that a threshold only fits recordings of the length and frame rate it was
calibrated on (a longer recording tells moving from still far better than a
faster one, notebooks/poke_run_followed.ipynb, section 9). `frame_count` stays the
field the file, DataLoader and the camera read: `recording_length` x `fps`. A file
without a `recording_length` line was written while the burst was fixed (or by
the Discobox app), so its `frame_count` and `fps` are read as 3 s at 30 fps, as
they were then.

The file is `key=value` lines, the format DataLoader reads from a session's
.settings.txt, so a live run's settings are written next to its recordings. It
still holds the Discobox app's `recording_count`, the recordings planned at
most. A file with `death_reset` (an earlier "go on until every mite is dead")
is read without it: every run now ends once every mite is dead.
"""

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from classes.plate import zone_masks

# Every recording by default: FRAME_COUNT frames at FPS (3 s). The camera (Mako G-319B) takes at most 33 fps.
FPS = 30
SECONDS = 3
FRAME_COUNT = SECONDS * FPS

# name: (label, unit, lowest, highest).
RANGES = {
    "run_minutes": ("Experiment duration, at most", "min", 0, 43200),
    "death_minutes": ("Dead when still for", "min", 0, 43200),
    "stop_when_dead": ("Stop once every mite is dead", "", 0, 1),
    "follow_px": ("Most a mite moves between recordings", "px", 0, 500),
    "recording_timeout": ("Time between recordings", "min", 1, 1440),
    "vent_time": ("Fan duration", "s", 0, 3600),
    "led1_time": ("LED 1 duration", "s", 0, 3600),
    "led2_time": ("LED 2 duration", "s", 0, 3600),
    "recording_length": ("Recording length", "s", 1, 60),
    "fps": ("Frame rate", "fps", 1, 33),
    "vent": ("Fan intensity", "", 0, 255),
    "led1": ("LED 1 intensity", "", 0, 255),
    "led2": ("LED 2 intensity", "", 0, 255),
}
MASK = "zone_mask"
OLD_MASK = "zones_per_plate"  # of earlier versions: 1 or 2


@dataclass
class Settings:
    run_minutes: int = 10
    death_minutes: int = 0
    stop_when_dead: int = 1
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
    zone_mask: str = zone_masks.NEW

    @classmethod
    def from_dict(cls, values):
        """Settings from `values` (name -> number), each checked against RANGES,
        and the name of a zone mask there is. Names not given keep their default.
        `recording_length` (s) sets `frame_count` to that many seconds at `fps`;
        `frame_count` may be given instead (the tests' short bursts)."""
        checked = {}
        length = None
        for name, value in values.items():
            if name in (MASK, OLD_MASK):
                checked[MASK] = zone_masks.check(value)
                continue
            if name == "frame_count":
                checked[name] = _whole(value, "Frames per recording", 1, 10**6)
                continue
            if name not in RANGES:
                raise ValueError(f"Unknown setting {name!r}.")
            label, _unit, lowest, highest = RANGES[name]
            number = _whole(value, label, lowest, highest)
            if name == "recording_length":
                length = number
            else:
                checked[name] = number
        if length is not None:
            checked["frame_count"] = length * checked.get("fps", FPS)
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
        # a mask deleted since: the default one
        for name in (MASK, OLD_MASK):
            if name in values and not zone_masks.exists(values[name]):
                del values[name]
        # written while the burst was fixed, or by the Discobox app: 3 s at 30 fps, as then
        if "recording_length" not in values:
            values.pop("fps", None)
        return cls.from_dict({key: value for key, value in values.items() if key in (*RANGES, MASK, OLD_MASK)})

    def save(self, path):
        Path(path).write_text(str(self), encoding="utf-8")

    def __str__(self):
        lines = [f"{field.name}={getattr(self, field.name)}\n" for field in fields(self)]
        return f"recording_count={self.recording_count}\nrecording_length={self.recording_length}\n" + "".join(lines)

    def as_dict(self):
        """Every field, and `recording_length`, the burst's length in whole seconds, as the page sets it."""
        return {**asdict(self), "recording_length": self.recording_length}

    @property
    def recording_length(self):
        """The burst's length in whole seconds (at least 1), as the page shows and sets it."""
        return max(1, round(self.frame_count / self.fps))

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


def _whole(value, label, lowest, highest):
    """`value` as a whole number from `lowest` to `highest`; ValueError naming `label` otherwise."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number, not {value!r}.")
    if float(value) != number:
        raise ValueError(f"{label} must be a whole number, not {value!r}.")
    if not lowest <= number <= highest:
        raise ValueError(f"{label} must be between {lowest} and {highest}.")
    return number
