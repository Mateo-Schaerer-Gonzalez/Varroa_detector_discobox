"""Folders dropped into the page: which of their files to copy into
recordings/, and once copied, their frames shrunk to the mites' surroundings.
"""

from pathlib import Path

from classes.storage.roi_conversion import RoiConversion
from classes.storage.roi_recordings import RoiRecordings, is_roi_session
from classes.storage.upload_plan import UploadPlan
from pipeline import paths, plate_zones


def plan_upload(name, files, uploads_root=paths.RECORDINGS_ROOT):
    """Which files of the folder `name` dropped into the page to copy, of `files`
    ([{path, size}], every file in it): {name (of the folder they go to in
    `uploads_root`), data_dir (that folder), missing ([{path (as dropped),
    target (in that folder)}])}. See classes/storage/upload_plan.py."""
    plan = UploadPlan(name, files)
    folder = Path(uploads_root) / plan.name

    def size_of(target):
        path = folder.joinpath(*target.split("/"))
        return path.stat().st_size if path.is_file() else None

    # recordings dropped before, whose frames were shrunk to the mites' surroundings since
    converted = set(RoiRecordings(folder).recording_names) if is_roi_session(folder) else set()
    return {"name": plan.name, "data_dir": str(folder), "missing": plan.missing(size_of, converted)}


def finish_upload(name, uploads_root=paths.RECORDINGS_ROOT):
    """Once every file of a dropped folder is in: its recordings of whole frames
    are shrunk to what a live run saves, the mites' surroundings
    (classes/storage/roi_conversion.py), so they take a thirtieth of the space and give
    the same results. {data_dir, converted (recordings)}."""
    UploadPlan.check_part(name)
    folder = Path(uploads_root) / name
    if not folder.is_dir():
        raise FileNotFoundError(f"Nothing was copied to {folder}.")
    return {"data_dir": str(folder), "converted": convert_folder(folder)}


def convert_folder(folder, results_root=paths.RESULTS_ROOT):
    """Shrink the recordings of whole frames in `folder` to the mites'
    surroundings (classes/storage/roi_conversion.py). Returns how many were."""
    folder = Path(folder)
    converted = RoiConversion(folder, plate_zones.zones_of(folder)).run()
    if converted:
        # clips of the whole frames, which are gone: those of its analysis and of its calibration
        paths.clear_clips(paths.results_dir(folder, results_root))
        paths.clear_clips(paths.results_dir(folder, results_root) / paths.CALIBRATION_DIRNAME)
    return converted
