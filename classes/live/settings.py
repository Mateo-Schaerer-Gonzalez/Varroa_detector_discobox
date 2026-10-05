"""The settings of a Discobox test run, in the Discobox app's own file format.

The fields, their defaults and their ranges are those of the Discobox app
(src/settings.py and src/settings_view.py), but for the length of the run: the
app asks for a number of recordings, this app for how long the experiment lasts.
A test run is a recording every `recording_timeout` minutes for `run_minutes`,
then `death_minutes` more, the time a mite must be still to count as dead, so a
mite alive at the end of the experiment can still be told from a dead one. With
`death_reset`, the length depends on the mites alone: `run_minutes` is set aside
(but kept, for when `death_reset` is switched off again) and the run goes on
until no mite has moved for `death_minutes`, so every mite is dead at its end. Each recording is a burst of `frame_count` frames
at `fps`, with the fan (`vent`) and the two LEDs switched on at their intensity
(0-255) for their duration in seconds, ending with the burst. `zones_per_plate`
is how many zones each plate is cut into for the analysis (classes/zone_layout.py).

The file is `key=value` lines, the format DataLoader reads from a session's
.settings.txt, so a live run's settings are written next to its recordings. It
still holds the Discobox app's `recording_count`, the recordings planned.
"""

import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# name: (label, unit, lowest, highest). The frame rate and frame count limits are
# those of the Discobox camera (Mako G-319B).
RANGES = {
    "run_minutes": ("Experiment duration", "min", 0, 43200),
    "death_minutes": ("Dead when still for", "min", 0, 43200),
    "death_reset": ("Go on until every mite is dead", "", 0, 1),
    "recording_timeout": ("Time between recordings", "min", 1, 1440),
    "vent_time": ("Fan duration", "s", 0, 3600),
    "led1_time": ("LED 1 duration", "s", 0, 3600),
    "led2_time": ("LED 2 duration", "s", 0, 3600),
    "frame_count": ("Frames per recording", "", 1, 65535),
    "fps": ("Frames per second", "", 1, 33),
    "vent": ("Fan intensity", "", 0, 255),
    "led1": ("LED 1 intensity", "", 0, 255),
    "led2": ("LED 2 intensity", "", 0, 255),
    "zones_per_plate": ("Zones per plate", "", 1, 2),
}


@dataclass
class Settings:
    run_minutes: int = 10
    death_minutes: int = 0
    death_reset: int = 0
    recording_timeout: int = 1
    vent_time: int = 10
    led1_time: int = 10
    led2_time: int = 10
    frame_count: int = 10
    fps: int = 10
    vent: int = 255
    led1: int = 255
    led2: int = 255
    zones_per_plate: int = 1

    @classmethod
    def from_dict(cls, values):
        """Settings from `values` (name -> number), each checked against RANGES.
        Names not given keep their default."""
        checked = {}
        for name, value in values.items():
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
    def until_all_dead(self):
        """The run goes on until every mite is dead: `death_reset`, with a time
        to count a mite as dead."""
        return bool(self.death_reset and self.death_minutes)

    @property
    def experiment_minutes(self):
        """The set length of the experiment; none when the mites alone decide it."""
        return 0 if self.until_all_dead else self.run_minutes

    @property
    def recording_count(self):
        """The recordings planned: through the experiment and the time a mite
        must be still to count as dead. Until every mite is dead, the run can take more."""
        return self.recordings_until(self.experiment_minutes + self.death_minutes)

    def recordings_after_movement(self, last_moved):
        """The recordings the run takes when the last movement of any mite was in
        recording `last_moved` (from 0; -1 for none yet). Until every mite is
        dead, that is through that movement and `death_minutes` more; otherwise
        the recordings planned."""
        if not self.until_all_dead or last_moved < 0:
            return self.recording_count
        return max(self.recording_count, self.recordings_until(last_moved * self.recording_timeout + self.death_minutes))

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
        and whole cycle in seconds, and the recordings planned and the minutes they
        span (at least that many, when the run goes on until every mite is dead),
        and whether it can go on until every mite is dead: that needs a time to
        count a mite as dead."""
        return {
            "recording_seconds": self.recording_seconds,
            "cycle_seconds": self.cycle_seconds,
            "recordings": self.recording_count,
            "minutes": (self.recording_count - 1) * self.recording_timeout,
            "until_all_dead": self.until_all_dead,
            "can_run_until_all_dead": bool(self.death_minutes),
        }

    def check_cycle(self):
        """A recording must be over before the next one is due."""
        if self.cycle_seconds > self.recording_timeout * 60:
            raise ValueError(
                f"One recording takes {self.cycle_seconds:.0f} s (the fan, the LEDs and the burst), longer than "
                f"the {self.recording_timeout} min between recordings."
            )
