"""A recording folder's .settings.txt: one name=value per line, as the Discobox
app writes it next to its recordings (classes/live/settings.py writes the same).
The app adds lines of its own to it: the zones per plate (classes/plate/zone_layout.py),
the time a mite must be still to count as dead and the mites to check by eye.
A recording's own folder may hold one too, which overrides the session's
(DataLoader.get_settings()).
"""

from pathlib import Path

FILENAME = ".settings.txt"


def parse(path):
    """{name: value} of the settings file `path`; a value that is a whole number as an int."""
    settings = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        try:
            settings[key] = int(value)
        except ValueError:
            settings[key] = value
    return settings


def of_folder(folder):
    """parse() of the settings file in `folder`; {} without one."""
    path = Path(folder) / FILENAME
    return parse(path) if path.is_file() else {}


def whole_number(folder, name, default):
    """The setting `name` of the folder as a whole number, 0 or more; `default`
    without one, or when it is no whole number or the file cannot be read."""
    try:
        value = of_folder(folder).get(name)
        return default if value is None else max(0, int(value))
    except (OSError, TypeError, ValueError):
        return default


def save(folder, name, value):
    """Make `name=value` a line of the settings file in `folder`, added or
    replaced, every other line kept as it is."""
    path = Path(folder) / FILENAME
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    lines = [line for line in lines if line.split("=", 1)[0].strip() != name]
    path.write_text("".join(f"{line}\n" for line in [*lines, f"{name}={value}"]), encoding="utf-8")


def remove(folder, name):
    """Take the `name=` line out of the settings file in `folder`, if it has one."""
    path = Path(folder) / FILENAME
    if not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.split("=", 1)[0].strip() != name]
    if kept != lines:
        path.write_text("".join(f"{line}\n" for line in kept), encoding="utf-8")
