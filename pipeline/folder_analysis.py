"""The analysis of a folder of recordings from the pages: open it to label the
plates, run the analysis, correct its calls. The last run of each results
folder is kept, so a correction gives new results without decoding again.
"""

import threading
from pathlib import Path

from classes.scoring.analyzer import Analyzer
from classes.results.call_corrections import CallCorrections
from classes.scoring.motion_analysis import detect_mites
from classes.storage.roi_recordings import open_recordings
from classes.plate.zone_layout import ZoneLayout
from pipeline import ground_truth, output_files, paths, plate_labels, plate_zones, preview_images, run_results, scoring


# The last run of each results folder, so a call corrected by hand on its result
# pages gives new results without decoding the recordings again.
_runs = {}
_runs_lock = threading.Lock()


def save_zones_per_plate(data_dir, out_dir, zones):
    """Cut each plate of the recordings in `data_dir` into `zones` zones (1 or 2),
    for this and every later analysis of them: saved in their .settings.txt.
    Returns the session as open_session() does, with the new zones and the mites
    found in them. The last run of `out_dir` is of the other zones, so its calls
    can no longer be corrected; run the analysis again."""
    ZoneLayout(zones).save(data_dir)
    with _runs_lock:
        _runs.pop(paths.folder_key(out_dir), None)
    return open_session(data_dir, out_dir)


def open_session(data_dir, out_dir, coords_file=None):
    """Describe a recording session so its zones can be labelled.

    Decodes a single frame, writes it to `out_dir` as a JPEG, and returns the zone
    rectangles in image pixel coordinates, each with the number of mites detected
    in it -- detection only needs that first frame, so the UI can offer only the
    zones with mites for labelling. Drawing is left to the caller: the UI gets
    numbers, not a picture with boxes burnt into it. The zones are those of the
    layout saved with the recordings (one or two per plate), unless a
    `coords_file` is given.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Recording folder not found: {data_dir}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths.clear_clips(out_dir)

    loader = open_recordings(data_dir)
    n_recordings = loader.count_recordings()
    if n_recordings == 0:
        raise FileNotFoundError(f"No recordings found in {data_dir}")

    frame = loader.load_preview_frame()
    preview_images.write_preview(frame, out_dir)

    zone_manager = plate_zones.zones_of(data_dir, coords_file)
    # The same detection as an analysis run, on the same first frame.
    detect_mites(zone_manager, frame, Analyzer(), getattr(loader, "boxes", None))
    return session_view(zone_manager, frame, data_dir, n_recordings)


def session_view(zone_manager, frame, data_dir, n_recordings):
    """What the labelling page needs: the zones, with their labels and number of
    mites, and every detection, those marked "not a mite" included."""
    # Rejected detections are listed too, marked, so the user can take a mark back.
    rejected = set(map(id, ground_truth.rejected_detections(zone_manager, ground_truth.load_ground_truth(data_dir))))
    mites = [plate_zones.mite_view(mite, zone.id, rejected=id(mite) in rejected)
             for zone in zone_manager.zones for mite in zone.mites]

    zones = plate_zones.describe_zones(zone_manager, plate_labels.load_labels(data_dir))
    controls = set(plate_labels.load_controls(data_dir))
    for zone in zones:
        zone["control"] = zone["id"] in controls
        zone["n_mites"] = sum(1 for m in mites if m["zone_id"] == zone["id"] and not m["rejected"])
    return {
        "data_dir": str(data_dir),
        "preview": paths.PREVIEW_NAME,
        "image": {"width": int(frame.shape[1]), "height": int(frame.shape[0])},
        "n_recordings": n_recordings,
        "zones_per_plate": plate_zones.zones_per_plate(data_dir),
        "zone_layouts": ZoneLayout.choices(),
        "label_reading": plate_labels.label_reading(),
        "zones": zones,
        "mites": mites,
    }


def run_analysis(data_dir, out_dir, labels=None, coords_file=None,
                 files_later=False):
    """Run the whole pipeline and write its results to `out_dir`.

    `labels` maps zone id (as a string) to the group name the user typed, e.g.
    {"0": "venom 2x", "1": "control"}. Each mite gets one score per recording,
    from all of its frames. Returns the output filenames, a summary, and the
    per-zone and per-mite results the UI browses.

    The scores are kept in `out_dir` (classes/storage/kept_scores.py): a run of the same
    recordings, by the same code and settings, reads them back and is done in a
    moment. With `files_later`, the workbook and the figures are written just
    after the results are handed over, as after a correction, so a page need not
    wait for them (finish_files() does).
    """
    run = scoring.detect_and_score(data_dir, coords_file, labels, kept_in=out_dir)
    corrections = CallCorrections(data_dir)
    normalizer = scoring.normalizer_in_use(run.analyzer.config.mite)
    with _runs_lock:
        _runs[paths.folder_key(out_dir)] = (run, labels, corrections, normalizer)
    if not files_later:
        # Files of the run before still to be written are not to be written over this one's.
        output_files.files_later.forget(paths.folder_key(out_dir))
        output_files.finish_files(out_dir)
        return run_results.describe_results(run, out_dir, labels, corrections=corrections, normalizer=normalizer)
    results = run_results.describe_results(run, out_dir, labels, write_files=False, corrections=corrections,
                                           normalizer=normalizer)
    preview_images.write_preview(run.first_frame, out_dir)  # the pages draw on it at once
    output_files.write_files_later(run, out_dir, corrections, normalizer)
    return results


def correct_call(out_dir, mite_id, recording, state=None, checked=False):
    """Change by hand what one mite is in one recording of the last run written to
    `out_dir`: `state` is "moving" or "still" (its call; the detector's again is
    no correction any more), "gone" (the mite is not there in this recording,
    e.g. it fell off) or "gone_from" (nor in any later one); without `state`,
    the next of these. A mite gone is censored there. The change is saved next
    to the recordings (see classes/results/call_corrections.py), so later runs keep it.
    With `checked`, a call is kept as checked by eye, also when it is the
    detector's: the answer to a close call (classes/results/review_band.py).
    Returns the results as run_analysis() does, every number following the
    change. The workbook and the figures are written again a moment later, once
    the corrections pause (finish_files() waits for them)."""
    with _runs_lock:
        kept = _runs.get(paths.folder_key(out_dir))
        if kept is None:
            raise ValueError("Run the analysis again to correct its calls.")
        run, labels, corrections, normalizer = kept
        run_results.change_call(run.zone_manager, corrections, mite_id, int(recording), state,
                                scoring.detected_calls(run, corrections, normalizer), checked=checked)
        results = run_results.describe_results(run, out_dir, labels, write_files=False, corrections=corrections,
                                               normalizer=normalizer)
    output_files.write_files_later(run, out_dir, corrections, normalizer)
    return results


def review_again(out_dir):
    """The results of the last run written to `out_dir` again, with the calls to
    check by eye as they are now; None when that run is no longer kept."""
    with _runs_lock:
        kept = _runs.get(paths.folder_key(out_dir))
        if kept is None:
            return None
        run, labels, corrections, normalizer = kept
        return run_results.describe_results(run, out_dir, labels, write_files=False, corrections=corrections,
                                            normalizer=normalizer)
