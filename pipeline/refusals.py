"""The refusals every part makes alike: an id that is not there, a recording
index out of range, recordings no longer where they were, a number that is not
a whole one in range. Each raises a ValueError or FileNotFoundError with a
sentence for the page; web/server.py answers those as HTTP errors.
"""

from pathlib import Path


def whole_number(value, what, lowest, highest=None):
    """`value` as an int from `lowest` (to `highest`, if given), or a ValueError
    saying `what` (e.g. "The time must be a whole number of minutes") it must be."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what}.")
    if number != value or number < lowest or (highest is not None and number > highest):
        raise ValueError(f"{what}, {lowest} or more." if highest is None else f"{what} between {lowest} and {highest}.")
    return number


def find(items, item_id, where, what="mite"):
    """The item of `items` ({id, ...}) whose id is `item_id`, or a ValueError:
    no such `what` in `where`."""
    found = next((item for item in items if item["id"] == str(item_id)), None)
    if found is None:
        raise ValueError(f"No {what} {item_id} in {where}.")
    return found


def check_recording(recording, count, where="this session"):
    """Refuse a recording index that is not one of `count`."""
    if not 0 <= recording < count:
        raise ValueError(f"No recording {recording} in {where}.")


def recordings_dir(source, what):
    """The folder of the recordings of `source` (a calibration session or a
    dataset: its data_dir), or a FileNotFoundError: they are gone, so `what`."""
    folder = Path(source["data_dir"])
    if not folder.is_dir():
        of = f" of {source['name']}" if "name" in source else ""
        raise FileNotFoundError(f"The recordings{of} are no longer at {source['data_dir']}, so {what}.")
    return folder
