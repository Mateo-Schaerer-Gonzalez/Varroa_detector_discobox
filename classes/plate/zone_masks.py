"""The zone masks: where on the picture the plates are (mite zones, where mites
are found and scored) and their printed-label areas (text zones, masked out
before detection, where a plate's name is read), one coordinates file each.

A coordinates file has one line per zone, `type x1 y1 x2 y2` in image pixels:
type 1 a mite zone, 0 a text zone. Two masks are built in, next to the app and
in git: "1", one zone per plate (coords_pixel.txt), and "2", each plate cut into
its upper and lower half (coords_pixel_2.txt); they cannot be changed. The mask
"auto" is found on each recording's own first frame (classes/plate/slide_finder.py,
pipeline/auto_zones.py): it is the mask new recordings get (NEW), and has no file
here (coords_file() gives FALLBACK's, which its recordings use where no slide is
found). The masks made on the Zones page are masks/<name>.txt (DISCOBOX_MASKS sets another folder;
the tests use their own). A name is letters, digits, - and _, with a letter in
it, so it is never one of the built-in ones and makes a file name everywhere.
"""

import os
import re
from pathlib import Path

from classes.storage import files

APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT = "1"   # recordings without a mask saved with them, those of earlier versions
AUTO = "auto"   # found on each recording's first frame
NEW = AUTO      # the mask new recordings get: uploaded folders and live runs
FALLBACK = "1"  # the zones of the automatic mask where no slide is found
# name -> (title, its coordinates file next to the app)
BUILT_IN = {"1": ("One zone per slide", "coords_pixel.txt"),
            "2": ("Two zones per slide (upper and lower half)", "coords_pixel_2.txt")}
NAME = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9_-]{1,40}$")
# a zone's type as the pages name it -> as the coordinates file writes it
TYPES = {"mite": "1", "text": "0"}
SUFFIX = ".txt"


def folder():
    """Where the masks made on the Zones page are kept."""
    return Path(os.environ.get("DISCOBOX_MASKS") or APP_DIR / "masks")


def made():
    """The names of the masks made on the Zones page, in alphabetical order."""
    path = folder()
    if not path.is_dir():
        return []
    return sorted((file.stem for file in path.glob(f"*{SUFFIX}") if NAME.match(file.stem)), key=str.lower)


def names():
    """Every mask: the automatic one, the built-in ones, then those made."""
    return [AUTO, *BUILT_IN, *made()]


def exists(name):
    return str(name) in (AUTO, *BUILT_IN) or (NAME.match(str(name)) is not None and _made_file(name).is_file())


def title(name):
    """What the pages call the mask `name`."""
    if name == AUTO:
        return "Found on the first frame (automatic)"
    return BUILT_IN[name][0] if name in BUILT_IN else name


def check(name):
    """`name` as the name of a mask there is, or a ValueError."""
    name = str(name).strip() if name is not None else ""
    if not exists(name):
        raise ValueError(f"There is no zone mask {name!r}.")
    return name


def coords_file(name):
    """The coordinates file of the mask `name`, which must exist (check()); for
    the automatic mask, whose zones each recording keeps itself, FALLBACK's."""
    name = check(name)
    if name == AUTO:
        name = FALLBACK
    return APP_DIR / BUILT_IN[name][1] if name in BUILT_IN else _made_file(name)


def read(name):
    """The zones of the mask `name` as the pages know them: [{type ("mite" or
    "text"), x1, y1, x2, y2}], in the order of its file."""
    by_number = {number: kind for kind, number in TYPES.items()}
    zones = []
    for line in coords_file(name).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        number, *corners = line.split()
        zones.append({"type": by_number.get(number, number),
                      **dict(zip(("x1", "y1", "x2", "y2"), (round(float(value), 2) for value in corners)))})
    return zones


def save(name, zones):
    """Keep `zones` ([{type, x1, y1, x2, y2}], as read() gives them) as the mask
    `name`, a new one or one made before: never a built-in one. At least one
    mite zone, each with its corners in order."""
    name = str(name or "").strip()
    if name == AUTO:
        raise ValueError("The automatic mask is found on each recording's first frame; save yours under another name.")
    if name in BUILT_IN:
        raise ValueError(f"The built-in mask {name!r} cannot be changed; save it under another name.")
    if not NAME.match(name):
        raise ValueError("A mask's name is up to 40 letters, digits, - and _, with at least one letter.")
    lines = []
    for number, zone in enumerate(zones, start=1):
        if zone.get("type") not in TYPES:
            raise ValueError(f"Zone {number} is neither a mite zone nor a text zone.")
        try:
            x1, y1, x2, y2 = (float(zone[corner]) for corner in ("x1", "y1", "x2", "y2"))
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Zone {number} has no corners.")
        if not (0 <= x1 < x2 and 0 <= y1 < y2):
            raise ValueError(f"Zone {number} has no size, or lies outside the picture.")
        lines.append(f"{TYPES[zone['type']]} {x1:.2f} {y1:.2f} {x2:.2f} {y2:.2f}\n")
    if not any(zone.get("type") == "mite" for zone in zones):
        raise ValueError("A mask needs at least one mite zone.")
    folder().mkdir(parents=True, exist_ok=True)
    files.write_text(_made_file(name), "".join(lines))
    return name


def delete(name):
    """Remove the mask `name` made on the Zones page. The recordings that used it
    go back to the default mask."""
    name = check(name)
    if name in (AUTO, *BUILT_IN):
        raise ValueError(f"The built-in mask {name!r} cannot be deleted.")
    _made_file(name).unlink()


def _made_file(name):
    return folder() / f"{name}{SUFFIX}"
