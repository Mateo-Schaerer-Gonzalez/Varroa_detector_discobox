"""recordings/ holds every recording session the app has: each live test run and
each folder dropped into the page. The pages list them with how they were
recorded, so any of them can be analysed, or calibrated on, again.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import reporting
from classes import calibration
from classes.data_loader import DataLoader
from classes.files import try_json
from classes.live.settings import FIXED as FIXED_SETTINGS, RANGES as SETTING_RANGES
from classes.recording_info import RecordingInfo
from classes.roi_recordings import open_recordings
from classes.zone_layout import ZoneLayout
from pipeline import ground_truth, output_files, paths, plate_zones
from pipeline.live import live_runs

_logger = logging.getLogger(__name__)


def list_recordings(recordings_root=paths.RECORDINGS_ROOT, results_root=paths.RESULTS_ROOT):
    """Every folder in `recordings_root` that holds a recording, the most recently
    recorded first, as describe_recording() describes it, and whether it is the
    live run being recorded now."""
    root = Path(recordings_root)
    if not root.is_dir():
        return []
    output_files.finish_files()  # a list of the results on disk: those still to be written are, first
    recording_now = {run.run_dir.resolve() for run in list(live_runs.open_runs.values())
                     if run.session.state in live_runs.LIVE_STATES}
    listed = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        try:
            described = describe_recording(folder, results_root)
        except Exception:  # one odd folder must not hide the others
            _logger.exception("Could not describe the recording %s", folder)
            continue
        if described is not None:
            now = folder.resolve() in recording_now
            listed.append({**described, "recording_now": now, "state": RecordingInfo.state(described["run"], now)})
    return sorted(listed, key=lambda entry: entry["started"], reverse=True)


def describe_recording(data_dir, results_root=paths.RESULTS_ROOT):
    """One recording folder as the list of recordings shows it (None when it holds
    no recording): when it was recorded, how -- the Discobox settings of its
    .settings.txt and, for a live run, its run.json -- and what the app has of it:
    plate labels, ground truth and results."""
    data_dir = Path(data_dir)
    loader = open_recordings(data_dir)
    recordings = loader.recording_names
    if not recordings:
        return None
    first, last = recordings[0], recordings[-1]
    fps = loader.get_fps(first)
    frames = loader.count_frames(first)
    ended = DataLoader.parse_start_time(last) + timedelta(seconds=loader.count_frames(last) / loader.get_fps(last))

    run = try_json(data_dir / paths.RUN_INFO_NAME)
    if not isinstance(run, dict):
        run = None
    labels = try_json(plate_zones.layout_file(data_dir, paths.LABELS_FILENAME), {})
    groups = [str(group).strip() for group in labels.values() if str(group).strip()] if isinstance(labels, dict) else []
    truth = [entry.get("truth") for entry in ground_truth.load_ground_truth(data_dir) if isinstance(entry, dict)]
    rejected = sum(calibration.is_rejected(value) for value in truth)
    labelled = sum(1 for value in truth
                   if not calibration.is_rejected(value) and any(calibration.per_recording(value, len(recordings))))
    workbook = paths.results_dir(data_dir, results_root) / reporting.EXCEL_NAME
    started = DataLoader.parse_start_time(first)
    # as the Discobox app saved them; None for a folder without .settings.txt
    # the zones per plate are the analysis's, told apart below
    settings = {name: loader.settings[name] for name in ("recording_count", *SETTING_RANGES, *FIXED_SETTINGS)
                if name in loader.settings and name != ZoneLayout.SETTING} or None
    return {
        "name": data_dir.name,
        "path": str(data_dir.resolve()),
        "started": started.isoformat(timespec="seconds"),
        "ended": ended.isoformat(timespec="seconds"),
        # between the times shown, to the second
        "seconds": (ended.replace(microsecond=0) - started.replace(microsecond=0)).total_seconds(),
        "n_recordings": len(recordings),
        "planned": RecordingInfo.planned(run, settings),
        "frames": frames,
        "fps": fps,
        "settings": settings,
        "zones_per_plate": plate_zones.zones_per_plate(data_dir),
        "lights": RecordingInfo.lights(settings),
        "run": run,
        "n_labelled_plates": len(groups),
        "groups": sorted(set(groups)),
        "n_not_a_mite": rejected,
        "n_ground_truth": labelled,
        "results": None if not workbook.is_file() else {
            "file": workbook.name,
            "saved_at": datetime.fromtimestamp(workbook.stat().st_mtime).isoformat(timespec="seconds"),
        },
    }


def recording_results_file(name, filename, results_root=paths.RESULTS_ROOT):
    """The path of one file of a recording's results: results/<name>/<filename>."""
    for part in (name, filename):
        if not part or part in (".", "..") or Path(part).name != part:
            raise ValueError(f"Bad name: {part}")
    path = output_files.results_file(Path(results_root) / name, filename)
    if not path.is_file():
        raise FileNotFoundError(f"{name} has no {filename}.")
    return str(path)
