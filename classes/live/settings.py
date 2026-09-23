"""The settings of a Discobox test run, in the Discobox app's own file format.

The fields, their defaults and their ranges are those of the Discobox app
(src/settings.py and src/settings_view.py): a test run is `recording_count`
recordings, one every `recording_timeout` minutes. Each recording is a burst of
`frame_count` frames at `fps`, with the fan (`vent`) and the two LEDs switched on
at their intensity (0-255) for their duration in seconds, ending with the burst.

The file is `key=value` lines, the format DataLoader reads from a session's
.settings.txt, so a live run's settings are written next to its recordings.
"""

from dataclasses import asdict, dataclass, fields
from pathlib import Path

# name: (label, unit, lowest, highest). The frame rate and frame count limits are
# those of the Discobox camera (Mako G-319B).
RANGES = {
    "recording_count": ("Number of recordings", "", 1, 576),
    "recording_timeout": ("Time between recordings", "min", 1, 1440),
    "vent_time": ("Fan duration", "s", 0, 3600),
    "led1_time": ("LED 1 duration", "s", 0, 3600),
    "led2_time": ("LED 2 duration", "s", 0, 3600),
    "frame_count": ("Frames per recording", "", 1, 65535),
    "fps": ("Frames per second", "", 1, 33),
    "vent": ("Fan intensity", "", 0, 255),
    "led1": ("LED 1 intensity", "", 0, 255),
    "led2": ("LED 2 intensity", "", 0, 255),
}


@dataclass
class Settings:
    recording_count: int = 10
    recording_timeout: int = 1
    vent_time: int = 10
    led1_time: int = 10
    led2_time: int = 10
    frame_count: int = 10
    fps: int = 10
    vent: int = 255
    led1: int = 255
    led2: int = 255

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
                if key.strip() in RANGES:
                    values[key.strip()] = value.strip()
        return cls.from_dict(values)

    def save(self, path):
        Path(path).write_text(str(self), encoding="utf-8")

    def __str__(self):
        return "".join(f"{field.name}={getattr(self, field.name)}\n" for field in fields(self))

    def as_dict(self):
        return asdict(self)

    @property
    def recording_seconds(self):
        return self.frame_count / float(self.fps)

    @property
    def cycle_seconds(self):
        """How long one recording takes, from the first device switched on to
        everything off again (one second after the burst)."""
        return max(self.vent_time, self.led1_time, self.led2_time, self.recording_seconds) + 1

    def check_cycle(self):
        """A recording must be over before the next one is due."""
        if self.cycle_seconds > self.recording_timeout * 60:
            raise ValueError(
                f"One recording takes {self.cycle_seconds:.0f} s (the fan, the LEDs and the burst), longer than "
                f"the {self.recording_timeout} min between recordings."
            )
