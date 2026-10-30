"""Folders dropped into the page: which of their files to copy into
recordings/, and their frames shrunk to the mites' surroundings: when the
folder is first analysed or calibrated, so mites the detector missed can be
placed by hand on its whole frames before (pipeline/hand_mites.py).
"""

from pathlib import Path

from classes.storage.files import write_jpeg
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
    """Once every file of a dropped folder is in. A folder of whole frames is
    marked to be shrunk to what a live run saves, the mites' surroundings
    (classes/storage/roi_conversion.py), when it is first analysed or calibrated
    (shrink_pending()): until then mites can be placed by hand on it. Recordings
    added to a folder shrunk already are shrunk now, with its mites.
    {data_dir, converted (recordings shrunk now)}."""
    UploadPlan.check_part(name)
    folder = Path(uploads_root) / name
    if not folder.is_dir():
        raise FileNotFoundError(f"Nothing was copied to {folder}.")
    if not is_roi_session(folder):
        (folder / paths.SHRINK_PENDING_NAME).write_text(
            "Dropped into the page: shrunk to the mites' surroundings when first analysed or calibrated.\n",
            encoding="utf-8")
        return {"data_dir": str(folder), "converted": 0}
    return {"data_dir": str(folder), "converted": convert_folder(folder)}


def shrink_pending(folder, results_root=paths.RESULTS_ROOT):
    """Shrink a dropped folder marked to be (finish_upload()) to the mites'
    surroundings, the mites placed by hand on it among them; nothing for any
    other folder. Returns how many recordings were."""
    folder = Path(folder)
    marker = folder / paths.SHRINK_PENDING_NAME
    if not marker.is_file():
        return 0
    converted = convert_folder(folder, results_root)
    marker.unlink()
    return converted


def convert_folder(folder, results_root=paths.RESULTS_ROOT):
    """Shrink the recordings of whole frames in `folder` to the mites'
    surroundings (classes/storage/roi_conversion.py). Returns how many were.
    Mites put on after the first recording are kept as a live run keeps those
    it added, with the frame they appeared on (ADDED_FRAMES_DIRNAME)."""
    folder = Path(folder)
    conversion = RoiConversion(folder, plate_zones.zones_of(folder))
    converted = conversion.run()
    for start, image in conversion.added_frames.items():
        (folder / paths.ADDED_FRAMES_DIRNAME).mkdir(parents=True, exist_ok=True)
        write_jpeg(folder / paths.ADDED_FRAMES_DIRNAME / f"from_{start}.jpg", image, quality=90)
    if converted:
        # clips of the whole frames, which are gone: those of its analysis and of its calibration
        paths.clear_clips(paths.results_dir(folder, results_root))
        paths.clear_clips(paths.results_dir(folder, results_root) / paths.CALIBRATION_DIRNAME)
    return converted
