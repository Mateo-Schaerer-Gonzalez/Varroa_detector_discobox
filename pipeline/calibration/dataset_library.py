"""Datasets: the recordings with ground truth.

A dataset is a recording folder in recordings/ whose ground truth
(ground_truth.json, by position) labels any mite; its id is the folder's name.
What a report needs of it -- its mites, zones and recordings, and the ground
truth by mite id -- is worked out from the folder itself, as a calibration
session of it finds them (session_file.describe_calibration()): a session saved
as the mites' ROIs keeps the mites found when it was saved. scores/ in the
folder caches the scores reports computed (calibration/score_cache.py).

A calibration keeps its ground truth with the recordings, in recordings/: a
folder opened elsewhere by its path is copied there first (calibration_folder()),
its frames shrunk to the mites' surroundings as a folder dropped into the page
is, and calibrated there.
"""

import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

from classes.ground_truth import calibration
from classes.storage.data_loader import DataLoader
from classes.storage.files import remove_tree
from classes.storage.roi_recordings import ROI_DIRNAME, is_roi_session, open_recordings
from pipeline import clips, ground_truth, paths, plate_zones, preview_images, refusals, uploads
from pipeline.calibration import session_file, truth_entry


# What read_dataset() worked out, by folder and what it was worked out from.
_described = {}
_described_lock = threading.Lock()


def dataset_clip(out_dir, dataset, recording, recordings_root=paths.RECORDINGS_ROOT):
    """Frames of the whole plate, scaled down, during one recording of a saved
    dataset, for the test report to draw the calls on. Like calibration_clip(),
    written to `out_dir` once and reused after."""
    saved = read_dataset(dataset, recordings_root)
    refusals.check_recording(recording, len(saved["recordings"]), saved["name"])
    recordings_dir = Path(saved["data_dir"])
    source = saved["recordings"][recording]
    return clips.write_clip(open_recordings(recordings_dir), source["name"], source["fps"], (0, 0, 10**6, 10**6),
                            out_dir, f"clip_{clips.clip_key(dataset)}_r{recording}_plate", clips.PLATE_CLIP_WIDTH)


def dataset_dir(dataset, recordings_root):
    """The recording folder of the dataset `dataset`, in `recordings_root`."""
    dataset = str(dataset)
    if not dataset or dataset in (".", "..") or Path(dataset).name != dataset or "/" in dataset or "\\" in dataset:
        raise ValueError(f"Bad dataset: {dataset}")
    folder = Path(recordings_root) / dataset
    if not folder.is_dir():
        raise FileNotFoundError(f"No recording called {dataset}.")
    return folder


def dataset_folder(dataset, recordings_root=paths.RECORDINGS_ROOT):
    """The recording folder of the dataset `dataset` (its name)."""
    return str(dataset_dir(dataset, recordings_root))


def read_dataset(dataset, recordings_root=paths.RECORDINGS_ROOT):
    """A dataset as a report needs it: what a calibration session of its folder
    stores (session_file.describe_calibration()) with its name, the ground truth by mite id
    ("truth") and when that was saved ("saved_at"). Worked out again only when
    the folder's ground truth, labels or recordings changed."""
    folder = dataset_dir(dataset, recordings_root)
    truth_file = folder / paths.GROUND_TRUTH_FILENAME
    if not ground_truth.labelled(ground_truth.load_ground_truth(folder)):
        raise FileNotFoundError(f"No ground truth is saved for {dataset}.")
    changed = [path.stat().st_mtime_ns if path.exists() else None
               for path in (truth_file, plate_zones.layout_file(folder, paths.LABELS_FILENAME),
                            folder / paths.SETTINGS_FILENAME,
                            folder / ROI_DIRNAME / "index.json", folder)]
    key = (str(folder.resolve()), *changed)
    with _described_lock:
        stored = _described.get(key)
    if stored is None:
        stored, _first_frame = session_file.describe_calibration(folder)
        with _described_lock:
            _described[key] = stored
    return {**stored, "name": folder.name,
            "saved_at": datetime.fromtimestamp(truth_file.stat().st_mtime).isoformat(timespec="seconds"),
            "truth": truth_entry.saved_truth(stored)}


def _label_counts(truth, n_recordings):
    """Mites with a movement label, and moving and still labels, in ground truth
    (its statuses, one entry per mite)."""
    states = [calibration.per_recording(value, n_recordings) for value in truth]
    states = [s for s in states if not calibration.is_rejected(s)]
    return {
        "n_mites": sum(any(s) for s in states),
        "n_moving": sum(s.count(calibration.MOVING) for s in states),
        "n_still": sum(s.count(calibration.STILL) for s in states),
    }


def list_calibration_datasets(recordings_root=paths.RECORDINGS_ROOT):
    """Every recording in `recordings_root` with a mite labelled moving or still
    in its ground truth, the most recently saved first. Read from the files
    alone: nothing is decoded. The labels are counted over every recording
    labelled, should the folder hold fewer."""
    datasets = []
    for folder in sorted(Path(recordings_root).iterdir()) if Path(recordings_root).is_dir() else []:
        entries = ground_truth.load_ground_truth(folder) if folder.is_dir() else []
        if not ground_truth.labelled(entries):
            continue
        try:
            n_recordings = open_recordings(folder).count_recordings()
        except (OSError, ValueError):
            continue
        counts = _label_counts([entry.get("truth") for entry in entries],
                               max([n_recordings, 1] + [len(entry["truth"]) for entry in entries
                                                        if isinstance(entry.get("truth"), list)]))
        if not counts["n_moving"] + counts["n_still"]:
            continue  # only "not a mite" marks, from the label page: nothing to calibrate with
        datasets.append(
            {
                "id": folder.name,
                "name": folder.name,
                "data_dir": str(folder.resolve()),
                "saved_at": datetime.fromtimestamp((folder / paths.GROUND_TRUTH_FILENAME).stat().st_mtime)
                .isoformat(timespec="seconds"),
                "n_recordings": n_recordings,
                **counts,
            }
        )
    return sorted(datasets, key=lambda d: d["saved_at"], reverse=True)


def dataset_preview(dataset, recordings_root=paths.RECORDINGS_ROOT, results_root=paths.RESULTS_ROOT):
    """Path of a dataset's first frame: the preview of its results, written
    when there is none yet."""
    folder = dataset_dir(dataset, recordings_root)
    path = paths.results_dir(folder, results_root) / paths.PREVIEW_NAME
    if not path.is_file():
        preview_images.write_preview(open_recordings(folder).load_preview_frame(), path.parent)
    return str(path)


def delete_calibration_dataset(dataset, recordings_root=paths.RECORDINGS_ROOT):
    """Delete the ground truth of a recording -- its ground_truth.json and
    poke_test.json -- and the scores cached for it. The recordings stay."""
    folder = dataset_dir(dataset, recordings_root)
    if not ground_truth.labelled(ground_truth.load_ground_truth(folder)):
        raise FileNotFoundError(f"No ground truth is saved for {dataset}.")
    for name in (paths.GROUND_TRUTH_FILENAME, paths.POKE_FILENAME):
        (folder / name).unlink(missing_ok=True)
    remove_tree(folder / paths.SCORES_DIRNAME)
    return dataset


# Files never written again once they have their name: the frames, the mites'
# videos (a stitch writes a new one) and a session's whole first frame.
_WRITTEN_ONCE = {".bmp", ".mkv", ".png"}


def _keep_once(source, target):
    """`target`, a copy of a recording file. A frame is never written again once
    it has its name, so its copy is a hard link where one can be made: on disk
    once. The folder's own files (settings, labels, ground truth, a session's
    index of ROIs) are written in place, so they are copied."""
    if source.suffix.lower() in _WRITTEN_ONCE:
        try:
            os.link(source, target)
            return
        except OSError:
            pass
    shutil.copy2(source, target)


def _copy_recordings(data_dir, target):
    """Copy a recording folder to `target`: its own files (settings, labels,
    ground truth, poke test) and every recording in it, each frame linked
    rather than copied where it can be (_keep_once()). A file still being
    written (*.part) is not one yet."""
    data_dir = Path(data_dir)
    files = [path for path in data_dir.iterdir() if path.is_file()]
    if is_roi_session(data_dir):
        rois_dir = data_dir / ROI_DIRNAME
        files += [path for path in rois_dir.rglob("*") if path.is_file()
                  and not any(part.endswith(".part") or part == "stitching" for part in path.relative_to(rois_dir).parts)]
    else:
        for name in DataLoader(data_dir).recording_names:
            files += [path for path in (data_dir / name).rglob("*") if path.is_file()]
    for source in (path for path in files if path.suffix != ".part"):
        copy = target / source.relative_to(data_dir)
        copy.parent.mkdir(parents=True, exist_ok=True)
        partial = copy.with_name(copy.name + ".part")
        partial.unlink(missing_ok=True)  # left by a copy cut short: a link needs the name free
        _keep_once(source, partial)
        partial.replace(copy)  # only a complete file ever has the real name


ORIGIN_NAME = "copied_from.txt"  # in a copy calibration_folder() made: the folder it is a copy of


def calibration_folder(data_dir, recordings_root=paths.RECORDINGS_ROOT):
    """The folder in `recordings_root` a calibration of `data_dir` works on:
    `data_dir` itself when it is there, else its copy there -- made now, its
    frames shrunk to the mites' surroundings, the first time; the one made
    before after. Its ground truth, poke test and labels come along."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")
    if data_dir.resolve().parent == Path(recordings_root).resolve():
        uploads.shrink_pending(data_dir)  # a folder dropped into the page, its mites placed
        return data_dir
    origin = os.path.normcase(str(data_dir.resolve()))
    for folder in sorted(Path(recordings_root).glob(f"*/{ORIGIN_NAME}")):
        if folder.read_text(encoding="utf-8").strip() == origin:
            return folder.parent
    target = Path(recordings_root) / paths.free_name(paths.folder_name(data_dir), recordings_root)
    partial = target.with_name(target.name + ".copying")
    remove_tree(partial)
    _copy_recordings(data_dir, partial)
    (partial / ORIGIN_NAME).write_text(origin, encoding="utf-8")
    partial.rename(target)
    uploads.convert_folder(target)
    return target
