"""The pictures of the plate the pages draw on: the first frame (preview.jpg),
and for a live run that added mites, the frame they were found on.
"""

import shutil
from pathlib import Path

import cv2

from classes.files import write_image_whole
from pipeline import paths


def image_size(frame):
    return {"width": int(frame.shape[1]), "height": int(frame.shape[0])}


def write_preview(frame, out_dir):
    """The first frame as preview.jpg, written whole before it takes the name: a
    page may be loading the one it replaces, e.g. a live run's labels page while
    the first recording's results come in."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    write_image_whole(Path(out_dir) / paths.PREVIEW_NAME, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])


def added_previews(data_dir, out_dir, n_recordings, again=True):
    """The picture of the plate for each recording, for the calibration and
    result pages to draw the mites on: the first frame (PREVIEW_NAME), or from a
    recording a live run added mites in, the frame they were found on
    (live_add_mites()), copied to `out_dir` as preview_from_<recording>.jpg. So a
    mite is drawn where it can be seen. Without `again`, a copy already there
    stays: `out_dir` is the run's own (its results), where it can only be this
    run's, and a frame is final once its recording is analysed."""
    previews = [paths.PREVIEW_NAME] * n_recordings
    folder = Path(data_dir) / paths.ADDED_FRAMES_DIRNAME
    added = sorted((int(path.stem.split("_")[1]), path) for path in folder.glob("from_*.jpg")
                   if path.stem.split("_")[1].isdigit()) if folder.is_dir() else []
    for start, path in added:
        if start >= n_recordings:
            continue
        name = f"preview_from_{start}.jpg"
        if again or not (Path(out_dir) / name).is_file():  # anew: `out_dir` may have shown another dataset
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, Path(out_dir) / name)
        previews[start:] = [name] * (n_recordings - start)
    return previews
