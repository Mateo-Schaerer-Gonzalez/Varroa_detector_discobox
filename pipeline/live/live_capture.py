"""A live run going on: start, pause, stop, and after every recording its
results published, its mites counted dead no longer followed, run.json and the
files brought up to date.
"""

import logging
import time
from datetime import datetime

from classes.results.call_corrections import CallCorrections
from classes.storage.files import write_json
from classes.live.progress import ZoneProgress
from classes.live.recorder import Recorder
from classes.storage.roi_recordings import RoiVideo
from classes.scoring.score_normalizer import ScoreNormalizer
from pipeline import hand_mites, output_files, paths, plate_labels, preview_images, run_results, scoring
from pipeline.live import live_runs

_logger = logging.getLogger(__name__)


# Seconds at most between two writes of a live run's workbook and figures while it
# goes on. On a long run they take seconds of work, which grows with every
# recording: too much to do after each one. A download waits for them
# (results_file()), and the end of the run writes them at once.
LIVE_FILES_EVERY = 600


def publish_live(run, write_files):
    """The results of a live run so far, exactly as run_analysis() describes a
    folder: the same labels and "not a mite" marks, read from the run's folder.
    After each recording (`write_files`), run.json says how far the run got,
    and the files follow (_write_live_files_later())."""
    labels = plate_labels.load_labels(run.run_dir)
    # A call corrected after the run's end writes the files again, and nothing else.
    going = write_files and run.session.state != "finished"
    scoring.arrange(run.analysis, run.run_dir, labels, True)
    # The scores are normalised over a whole run, so not while it goes on.
    view = scoring.run_view(run.analysis, live_runs.live_frames(run), run.run_dir)
    results = run_results.describe_results(view, run.out_dir, labels, False,
                                           corrections=CallCorrections(run.run_dir), normalizer=ScoreNormalizer())
    if write_files:
        if not run.preview_written:  # the first frame, which the pages draw on: it never changes
            preview_images.write_preview(run.analysis.first_frame, run.out_dir)
            run.preview_written = True
        _write_live_files_later(run)
    progress = ZoneProgress(results, run_results.death_minutes(run.run_dir))
    run.zones = progress.zones()
    if going:
        _follow_live(run, progress, len(results["times"]))
        _write_run_info(run)
    return results


def _follow_live(run, progress, recordings):
    """After a recording of a running live run: the mites that count as dead are
    no longer followed from the next on, and once every zone is done the run
    stops (classes/live/progress.py)."""
    dead = set(progress.dead_ids())
    run.analysis.stop([mite for mite in run.analysis.mites if mite.text in dead], recordings)
    if progress.all_done(run.zones) and run.session.state in ("running", "paused") and run.stop_reason is None:
        run.stop_reason = "Every mite of every zone is dead."
        _logger.info("Stopping the test run %s: %s", run.run_dir.name, run.stop_reason)
        run.session.stop()


def live_run_ended(run):
    """The test run is over: its run.json says so, and its last files are
    written before the session counts as finished."""
    _write_run_info(run, ended=True)
    output_files.finish_files(run.out_dir)


def _write_live_files_later(run):
    """Write a live run's workbook and figures in the background: at most
    LIVE_FILES_EVERY seconds after the recording that first changed them, and
    at once when its stream has ended. They all go through output_files.files_later, one
    after another, so the last written is always of the latest results."""
    if run.source.state == "finished":
        delay = 0.0
    else:
        now = time.monotonic()
        if run.files_due is None:
            run.files_due = now + LIVE_FILES_EVERY
        delay = max(0.0, run.files_due - now)
    output_files.files_later.later(paths.folder_key(run.out_dir), lambda: _write_live_files(run), delay)


def _write_run_info(run, ended=False):
    """Write run.json next to the recordings: how the test run was made, and how
    far it got. Never fails the run: it is only a record."""
    if run.started_at is None or not run.run_dir.is_dir():
        return
    try:
        status = run.session.status()
        info = {
            "source": status["source"],
            "camera": status["camera"],
            "started_at": run.started_at,
            "ended_at": datetime.now().isoformat(timespec="seconds") if ended else None,
            "recordings_planned": status["recordings"],
            "recordings_analysed": status["analysed"],
            "frames_saved": run.save_frames,
            "frames_dropped": status["dropped"],
            "frames_incomplete": status["incomplete"],
            "error": status["error"] or status["save_error"],
            "stop_reason": run.stop_reason,
        }
        write_json(run.run_dir / paths.RUN_INFO_NAME, info, indent=2)
    except Exception:
        _logger.exception("Could not write %s", paths.RUN_INFO_NAME)


def start_live(live_id, labels=None):
    """Start the test run: record, analyse and publish results as it goes.
    `labels`, when given, are saved as the run's plate labels first."""
    run = live_runs.get_live(live_id)
    if run.session.state != "ready":
        raise ValueError("This test run has already been started.")
    run.source.settings.check_death_time()
    run.analysis.follow = run.source.settings.follow_px or None
    run.analysis.zone_manager.by_hand = hand_mites.points(run.run_dir)  # those placed since it was opened
    if labels is not None:
        plate_labels.save_labels(run.run_dir, labels)
    (run.run_dir / paths.SETTINGS_FILENAME).write_text(run.source.settings_text, encoding="utf-8")
    if run.save_frames:
        RoiVideo.check_codec(run.run_dir)
    run.session.recorder = Recorder(run.run_dir) if run.save_frames else None
    run.started_at = datetime.now().isoformat(timespec="seconds")
    _write_run_info(run)
    run.lights.all_off()  # the LEDs, and the fan if it was switched on to check it: the test run's from here on
    try:
        run.session.start()
    except Exception:
        if run.session.recorder is not None:
            run.session.recorder.close()
            run.session.recorder = None
        if run.session.state == "ready":  # not started: still setting up, so lit
            live_runs.leds_on(run.lights, run.source.settings)
        raise
    return live_runs.live_status(live_id)


def live_correct_call(live_id, mite_id, recording, state=None, checked=False):
    """correct_call() for a live run: the results published next, at once, follow
    the change. Once the run is over, the workbook and the figures are written
    again too, a moment later as correct_call() does; before, they are after
    every recording anyway."""
    run = live_runs.get_live(live_id)
    with run.session.lock:
        run_results.change_call(run.analysis.zone_manager, CallCorrections(run.run_dir), mite_id, int(recording), state,
                                checked=checked)
    run.session.publish(write_files=False)
    if run.session.state == "finished":
        output_files.files_later.later(paths.folder_key(run.out_dir), lambda: _write_live_files(run))
    return live_runs.live_results(live_id)


def _write_live_files(run):
    """The workbook and the figures of a live run, as its recordings and
    corrections are now. The lock is held only to read the run, not while the
    files are written."""
    run.files_due = None  # a recording from now on is in the next write
    with run.session.lock:
        view = scoring.run_view(run.analysis, live_runs.live_frames(run), run.run_dir)
        normalizer = ScoreNormalizer()
        mite_data, _changes = scoring.mite_table(view, CallCorrections(run.run_dir), normalizer)
        annotated = output_files.annotated(view)
    output_files.write_files(annotated, run.out_dir, mite_data, view, normalizer)


def live_refresh(live_id):
    """Describe the results again, e.g. after the plate labels changed."""
    run = live_runs.open_runs.get(live_id)
    if run is not None:
        run.session.publish(write_files=False)


def pause_live(live_id):
    live_runs.get_live(live_id).session.pause()
    return live_runs.live_status(live_id)


def resume_live(live_id):
    live_runs.get_live(live_id).session.resume()
    return live_runs.live_status(live_id)


def stop_live(live_id, wait=False, timeout=None):
    """Stop the test run: capture stops, the frames already captured are analysed
    and saved, and the final results written. With `wait`, returns when done."""
    live_runs.get_live(live_id).session.stop(wait=wait, timeout=timeout)
    return live_runs.live_status(live_id)
