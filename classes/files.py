"""Reading and writing the app's own files, one way everywhere.

A file a page or another thread may read while it is written (a preview, a
calibration session, an index of ROIs, kept scores) is written whole under
another name first and only then takes its own, so a reader never sees half of
one. On Windows the rename is refused for a moment while a reader has the file
open; replace() tries again.

OneDrive marks folders read-only, which stops even an emptied folder from being
removed; remove_tree() clears that first.
"""

import json
import os
import shutil
import stat
import time
from pathlib import Path

import cv2

# A path Windows (without long paths) refuses: more characters than this.
WINDOWS_PATH_LIMIT = 259


def read_json(path, default=None):
    """The JSON in `path`; `default` when there is no such file. A damaged file
    raises: it is not to be written over as if it were empty."""
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def try_json(path, default=None):
    """The JSON in `path`; `default` when it is missing or damaged: for files
    that are only a record, or that a damaged one may be replaced by."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def replace(partial, path, attempts=40):
    """os.replace(), again for a moment while Windows refuses it: a reader has
    the file open."""
    for attempt in range(attempts):
        try:
            os.replace(partial, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05)


def write_text(path, text):
    """Write `text` to `path` whole before it takes the name (see the top of this file)."""
    path = Path(path)
    partial = path.with_name(path.name + ".part")
    partial.write_text(text, encoding="utf-8")
    replace(partial, path)


def write_json(path, data, indent=None):
    """write_text() of `data` as JSON."""
    write_text(path, json.dumps(data, indent=indent))


def write_image(path, image, params=()):
    """cv2.imwrite(), which only returns False where it cannot write (a path too
    long for Windows, a folder gone), made to say so."""
    if not cv2.imwrite(str(path), image, list(params)):
        raise OSError(f"Could not write {path} ({len(str(path))} characters"
                      f"{', longer than Windows allows' if len(str(path)) > WINDOWS_PATH_LIMIT else ''}).")


def write_jpeg(path, image, quality=85):
    write_image(path, image, [cv2.IMWRITE_JPEG_QUALITY, quality])


def write_image_whole(path, image, params=()):
    """write_image() whole before it takes the name. The partial file is named
    partial_<name>, not <name>.part: OpenCV picks the format by the extension."""
    path = Path(path)
    partial = path.with_name(f"partial_{path.name}")
    write_image(partial, image, params)
    replace(partial, path)


def remove_tree(path, ignore_errors=False):
    """shutil.rmtree(), read-only files and folders too (OneDrive marks folders
    so); nothing when `path` is not there. With `ignore_errors`, what cannot
    be removed even so (a file a reader has open, on Windows) stays."""
    def again(remove, failed, _error):
        try:
            os.chmod(failed, stat.S_IWRITE)
            remove(failed)
        except OSError:
            if not ignore_errors:
                raise

    if Path(path).exists():
        shutil.rmtree(path, onexc=again)
