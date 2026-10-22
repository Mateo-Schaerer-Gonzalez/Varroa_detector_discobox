"""The sessions of the pages: a folder opened for analysis, a calibration, or a
live run, each by its id, with the folders it works in.

A session's files go to its out_dir: results/<recording>/ for an analysis or a
live run, results/<recording>/calibration/ for a calibration of it. A
calibration's report goes to its report_dir: that same folder, or
results/pooled/<date time>/ for a report pooled over several recordings.

A live run is a session like one opened from a folder: its folder is the run's
folder in recordings/, where its recordings, labels and "not a mite" marks go, so
the label and result pages and their clips work on it unchanged. Its results go
to results/<run name>/.
"""

import threading
from pathlib import Path

from fastapi import HTTPException

import pipeline
from web.http_helpers import answer, as_it_is, new_id, refused

sessions: dict[str, dict] = {}
# Every change to a ground truth reads what is saved and writes it back; one at a
# time, so two windows saving at once cannot undo each other's change.
truth_lock = threading.Lock()


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Unknown session. Open a folder again.")
    return sessions[session_id]


def session_results(session_id):
    """The results the session's pages show: its last run's, or a live run's so
    far; None before there are any."""
    session = get_session(session_id)
    if session.get("live"):
        return answer(pipeline.live_results, session_id)["results"]
    return session.get("results")


def refresh_live(session_id):
    """A live run's results take what was saved with its recordings at once, as a new version."""
    if get_session(session_id).get("live"):
        pipeline.live_refresh(session_id)


def survival_of(session_id, results):
    """The survival numbers of `results`, by the time a mite must be still to count
    as dead and the negative controls saved with the session's recordings."""
    data_dir = get_session(session_id)["data_dir"]
    return pipeline.describe_survival(results, pipeline.death_minutes(data_dir), pipeline.load_controls(data_dir))


def for_pages(session_id, results):
    """`results` as the result pages take them: with the movement numbers, the time
    a mite must be still to count as dead, the mites to check by eye (the
    recordings' own number and config.yaml's), the negative controls, and the
    survival numbers these make."""
    data_dir = get_session(session_id)["data_dir"]
    return {**pipeline.describe_movement(results), "death_minutes": pipeline.death_minutes(data_dir),
            "death_range": pipeline.death_minutes_range(),
            "review_mites": {"mites": pipeline.review_mites(data_dir), "default": pipeline.review_mites()},
            "controls": pipeline.load_controls(data_dir), "survival": survival_of(session_id, results)}


def survival_now(session_id):
    """The survival numbers of the session's results as the recordings' settings
    and controls are now; None before there are results."""
    results = session_results(session_id)
    return None if results is None else survival_of(session_id, results)


def played(session_id, what):
    """The session, and its results so far: what plays a recording needs both.
    A live run that saves no recordings has nothing to play, so `what`."""
    session = get_session(session_id)
    if session.get("live") and not session.get("save_frames"):
        raise HTTPException(status_code=400, detail=f"This test run does not save its recordings, so {what}.")
    results = session_results(session_id)
    if results is None:
        raise HTTPException(status_code=400, detail="No results yet.")
    return session, results


def new_calibration_session(data_dir, open_it, live_id=None):
    """Run `open_it(out_dir)` in a new calibration session of the recordings in
    `data_dir` and remember it; it works in their results/<name>/calibration/.
    A session on a live run's recordings keeps the run's `live_id`, to grow with it."""
    session_id = new_id()
    out_dir = pipeline.calibration_dir(data_dir)
    with refused():
        calibration = open_it(out_dir)

    sessions[session_id] = {
        "data_dir": calibration["data_dir"],
        "out_dir": out_dir,
        "report_dir": out_dir,
        "dataset_id": calibration["dataset_id"],
        "live_id": live_id,
    }
    return as_it_is({"session_id": session_id, **calibration})


def live_session(session_id):
    session = get_session(session_id)
    if not session.get("live"):
        raise HTTPException(status_code=404, detail="Not a live run.")
    return session


def label_live_plates(session_id):
    """Detect the mites on the newest frame of a live run, to label the plates;
    the session keeps them for the "not a mite" marks."""
    session = live_session(session_id)
    preview = answer(pipeline.live_preview, session_id, session["out_dir"])
    session["mites"] = preview["mites"]  # the detections of the label page, for the "not a mite" marks
    return {"session_id": session_id, **preview}


def attach_live(session_id, status):
    """A live run as a session: one just opened, or one left open by a page that
    was closed or reloaded."""
    if session_id not in sessions:
        sessions[session_id] = {"data_dir": status["run_dir"], "out_dir": Path(status["out_dir"]), "live": True,
                                "save_frames": status["save_frames"]}
