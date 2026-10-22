"""HTTP layer: turns requests into pipeline calls and results into JSON.

Deliberately contains no analysis logic. It may import `pipeline` and nothing else
from the project -- no cv2, pandas, matplotlib, numpy or classes.* -- which
`unit_tests/test_layering.py` enforces.

Run it with start.bat, or:  python -m uvicorn web.server:app --port 8000
"""

import os
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pipeline

STATIC_DIR = Path(__file__).parent / "static"
# Folders dropped into the browser are copied to recordings/, one subfolder per
# folder name, next to the live runs.
UPLOAD_ROOT = pipeline.RECORDINGS_ROOT

# --- stopping when the last page closes ---------------------------------------
# start.bat and start.sh set DISCOBOX_AUTO_STOP=1, so the server does not keep
# running (with old code) after the last browser tab is closed. A server started
# by hand keeps running.
AUTO_STOP = os.environ.get("DISCOBOX_AUTO_STOP") == "1"
# Browsers let a hidden tab run its timers only about once a minute, so a page
# that has not checked in for this long is taken to be gone.
PAGE_TIMEOUT = 150
# After the last page closes, time for a reload to check in again.
CLOSE_GRACE = 10

pages: dict[str, float] = {}  # page id -> when it last checked in
last_activity = time.monotonic()
any_page_seen = False


def watch_pages():
    """Stop the process once no page is open. Runs in a background thread."""
    global last_activity
    previous = time.monotonic()
    while True:
        time.sleep(2)
        now = time.monotonic()
        if now - previous > 30:
            # The computer slept: the pages did not go away, they just could not check in.
            for page in list(pages):
                pages[page] = now
            last_activity = now
        previous = now

        for page, seen in list(pages.items()):
            if now - seen > PAGE_TIMEOUT:
                pages.pop(page, None)
        # A live test run goes on with no page open; the server waits for its end.
        if pipeline.live_running():
            last_activity = now
            continue
        # Before the first page loads, allow time for the browser to start.
        grace = CLOSE_GRACE if any_page_seen else PAGE_TIMEOUT
        if not pages and now - last_activity > grace:
            print("No page open any more - stopping the server.", flush=True)
            pipeline.close_all_live()  # release the camera, switch the fan and LEDs off
            os._exit(0)


@asynccontextmanager
async def lifespan(app):
    pipeline.remove_empty_pooled_reports()
    if AUTO_STOP:
        threading.Thread(target=watch_pages, daemon=True).start()
    yield
    # Ctrl+C on the server: a live run stops cleanly and writes its results.
    pipeline.close_all_live()


app = FastAPI(title="Varroa discobox", lifespan=lifespan)

# A session's files go to its out_dir: results/<recording>/ for an analysis or a
# live run, results/<recording>/calibration/ for a calibration of it. A
# calibration's report goes to its report_dir: that same folder, or
# results/pooled/<date time>/ for a report pooled over several recordings.
sessions: dict[str, dict] = {}
# Every change to a ground truth reads what is saved and writes it back; one at a
# time, so two windows saving at once cannot undo each other's change.
truth_lock = threading.Lock()


class OpenRequest(BaseModel):
    data_dir: str


class LabelsRequest(BaseModel):
    labels: dict[str, str] = {}


class LabelReadingRequest(BaseModel):
    enabled: bool


class ControlsRequest(BaseModel):
    controls: list[int] = []


class DeathRequest(BaseModel):
    minutes: float


class ZonesRequest(BaseModel):
    zones_per_plate: int  # 1 or 2


class CorrectRequest(BaseModel):
    mite: str       # the mite's id in the results
    recording: int  # the recording whose call to change
    # "moving", "still", "gone" (in this recording) or "gone_from" (from it on); the next of these without
    state: Optional[str] = None
    checked: bool = False  # the answer to a close call: kept as checked by eye, also when it is the detector's


class ReviewMitesRequest(BaseModel):
    # how many mites to check by eye for these recordings; None for config.yaml's number
    mites: Optional[float] = None


class RejectRequest(BaseModel):
    mite: str       # the detection's id, as the label page lists it
    rejected: bool


class UploadedFile(BaseModel):
    path: str
    size: int


class ManifestRequest(BaseModel):
    files: list[UploadedFile]


class TruthEdit(BaseModel):
    """A click or a fill button on the ground-truth page (pipeline.edit_truth)."""
    action: str                 # "set", "dead", "cycle" or "fill"
    recording: int
    mite: Optional[str] = None  # cycle: the mite clicked
    backwards: bool = False     # cycle: to the previous status (shift-click)
    zone: Optional[int] = None  # fill: the zone
    kind: Optional[str] = None  # fill: "moving", "still", "previous", "dead" or "clear"
    state: Optional[str] = None  # set: "moving", "still", "not_a_mite", or none for unlabelled


class PokeEdit(BaseModel):
    """A change on the poke-test page (pipeline.edit_poke)."""
    action: str                  # "add", "remove", "set" or "fill"
    after: int                   # the round: the recording it was poked after, -1 before the first
    mite: Optional[str] = None   # set: the mite clicked
    zone: Optional[int] = None   # fill: the zone; every zone without one
    state: Optional[str] = None  # set, fill: "moved", "unmoved", or none for not poked


class EvaluateRequest(BaseModel):
    # ids of the saved datasets to pool; by default only this session's own
    datasets: Optional[list[str]] = None
    # the movement score to try; by default the one in config.yaml
    metric: Optional[str] = None
    params: Optional[dict[str, float]] = None
    # follow a shaking plate; by default as in config.yaml
    stabilize: Optional[bool] = None
    # put each dataset's scores on one scale per mite; by default as in config.yaml
    normalize_brightness: Optional[bool] = None
    normalize_floor: Optional[bool] = None
    # also call every observation with the Discobox's original software
    benchmark: bool = False
    # checks by eye per mite the suggested band may ask for; by default pipeline.REVIEW_CHECKS
    checks_per_mite: Optional[float] = None
    # also compare each mite's outline from one recording to the next (the test report)
    between: bool = False


class ThresholdRequest(BaseModel):
    value: float


class MovementScoreRequest(BaseModel):
    metric: str
    params: dict[str, float] = {}
    threshold: float
    # plate stabilization and the normalisations of the scores, saved with the
    # threshold; each left as it is when None
    stabilize: Optional[bool] = None
    normalize_brightness: Optional[bool] = None
    normalize_floor: Optional[bool] = None
    # [low, high]: the band around the threshold whose calls are checked by eye, saved with it; left as it is when None
    review_band: Optional[list[float]] = None


def safe_join(root: Path, relative: str) -> Path:
    """Resolve a browser-supplied relative path, refusing anything that escapes root."""
    parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or ".." in parts or ":" in relative:
        raise HTTPException(status_code=400, detail=f"Bad path: {relative}")
    return root.joinpath(*parts)


def as_it_is(content):
    """A large reply, sent as pipeline made it. It is plain data already; FastAPI
    would go through it value by value before sending it, which for the results
    of a long run takes longer than working them out."""
    try:
        return JSONResponse(content)
    except TypeError:  # not plain after all: FastAPI's way
        return content


# What pipeline raises when it refuses a request, e.g. a folder that is not there.
REFUSALS = (FileNotFoundError, ValueError, pipeline.CameraError)


@contextmanager
def refused(status=400, errors=REFUSALS):
    """Answer what pipeline refuses in the block with `status` and its reason; a
    live run no longer open (e.g. the server restarted: the page lets it go)
    with 404."""
    try:
        yield
    except pipeline.LiveRunNotOpen as error:
        raise HTTPException(status_code=404, detail=str(error))
    except errors as error:
        raise HTTPException(status_code=status, detail=str(error))


def answer(call, *args, **kwargs):
    """call(*args, **kwargs), what it refuses answered as refused() answers it."""
    with refused():
        return call(*args, **kwargs)


def new_id():
    return uuid.uuid4().hex[:8]


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Unknown session. Open a folder again.")
    return sessions[session_id]


@app.post("/api/session")
def open_session(request: OpenRequest):
    """Point the app at a folder of recordings and get back the zones to label."""
    session_id = new_id()
    out_dir = pipeline.results_dir(request.data_dir)
    with refused():
        session = pipeline.open_session(request.data_dir, out_dir)

    # the detections of the label page, for the "not a mite" marks
    sessions[session_id] = {"data_dir": session["data_dir"], "out_dir": out_dir, "mites": session["mites"]}
    return {"session_id": session_id, "results_dir": str(out_dir), **session}


@app.post("/api/uploads/{name}/manifest")
def upload_manifest(name: str, request: ManifestRequest):
    """Say which files of a dropped folder still need sending, and where they go
    (pipeline.plan_upload): every file of the folder is listed, the server picks."""
    with refused():
        return pipeline.plan_upload(name, [{"path": file.path, "size": file.size} for file in request.files], UPLOAD_ROOT)


@app.post("/api/uploads/{name}/finish")
def upload_finish(name: str):
    """Every file of a dropped folder is in: shrink its frames to the mites'
    surroundings (pipeline.finish_upload)."""
    with refused(errors=(*REFUSALS, RuntimeError)):
        return pipeline.finish_upload(name, UPLOAD_ROOT)


@app.put("/api/uploads/{name}/file")
async def upload_file(name: str, path: str, request: Request):
    """Receive one file of a dropped folder as the raw request body."""
    target = safe_join(safe_join(UPLOAD_ROOT, name), path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    with open(partial, "wb") as handle:
        async for chunk in request.stream():
            handle.write(chunk)
    partial.replace(target)  # only a complete file ever has the real name
    return {"saved": path}


@app.post("/api/session/{session_id}/labels")
def save_labels(session_id: str, request: LabelsRequest):
    """Persist the typed labels next to the recordings so they survive a restart.
    A live run's results take them at once."""
    session = get_session(session_id)
    pipeline.save_labels(session["data_dir"], request.labels)
    refresh_live(session_id)
    return {"saved": len(request.labels)}


@app.post("/api/label-reading")
def save_label_reading(request: LabelReadingRequest):
    """The label page's box "Read the names from the plates", saved in config.yaml."""
    return pipeline.save_label_reading(request.enabled)


@app.post("/api/session/{session_id}/read-labels")
def read_labels(session_id: str):
    """Read the names written beside the plates with no name yet (Google Gemini),
    for the label page to fill in. Nothing is saved until the page saves them."""
    session = get_session(session_id)
    mites = session.get("mites", [])
    with refused():
        try:
            if session.get("live"):
                return {"labels": pipeline.live_read_labels(session_id, session["out_dir"], mites)}
            return {"labels": pipeline.read_labels(session["data_dir"], session["out_dir"], mites)}
        except pipeline.LabelReadError as error:
            raise HTTPException(status_code=502, detail=str(error))


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


@app.post("/api/session/{session_id}/controls")
def save_controls(session_id: str, request: ControlsRequest):
    """The zones ticked as negative controls, saved next to the recordings. The
    results compare every other zone with them, with no need to run again: the
    survival numbers come back with the change. A live run's results take them
    at once too, as a new version."""
    session = get_session(session_id)
    controls = pipeline.save_controls(session["data_dir"], request.controls)
    refresh_live(session_id)
    return {"controls": controls, "survival": survival_now(session_id)}


@app.post("/api/session/{session_id}/reject")
def reject_detection(session_id: str, request: RejectRequest):
    """Mark a detection as not a mite, or take the mark back, before a run; taking it
    back puts back the labels the mark replaced. Returns every detection's mark and
    how many mites each zone has left (pipeline.mark_detection)."""
    session = get_session(session_id)
    with truth_lock, refused():
        marks = pipeline.mark_detection(session["data_dir"], session.get("mites", []), request.mite, request.rejected)
    refresh_live(session_id)
    return marks


@app.post("/api/session/{session_id}/death")
def save_death_minutes(session_id: str, request: DeathRequest):
    """How long a mite must be still to count as dead, saved with the recordings.
    The survival numbers of the results come back with the change."""
    session = get_session(session_id)
    with refused():
        death = pipeline.save_death_minutes(session["data_dir"], request.minutes)
    return {"death_minutes": death, "survival": survival_now(session_id)}


@app.post("/api/session/{session_id}/zones")
def save_zones_per_plate(session_id: str, request: ZonesRequest):
    """Cut each plate into one zone or two, saved with the recordings for every
    later analysis of them. The label page gets the session again, with the new
    zones and their mites; the results of the other zones are let go. A test run
    not started yet takes them too, and keeps them as its setting."""
    session = get_session(session_id)
    if session.get("live"):
        answer(pipeline.save_live_settings, {"zones_per_plate": request.zones_per_plate}, session_id)
        return live_preview(session_id)
    with refused():
        opened = pipeline.save_zones_per_plate(session["data_dir"], session["out_dir"], request.zones_per_plate)
    session["mites"] = opened["mites"]
    session.pop("results", None)
    return {"session_id": session_id, "results_dir": str(session["out_dir"]), **opened}


@app.post("/api/session/{session_id}/run")
def run_analysis(session_id: str, request: LabelsRequest):
    """Run the full analysis. Synchronous: the browser waits with a spinner."""
    session = get_session(session_id)
    pipeline.save_labels(session["data_dir"], request.labels)
    with refused():
        results = pipeline.run_analysis(session["data_dir"], session["out_dir"], request.labels, files_later=True)
    session["results"] = results  # for the survival numbers, which follow the controls and the time to count dead
    return as_it_is(for_pages(session_id, results))


@app.post("/api/session/{session_id}/correct")
def correct_call(session_id: str, request: CorrectRequest):
    """Change by hand one mite's call in one recording, or mark it gone, e.g. fallen
    off (pipeline.correct_call): the results come back, every number following
    it. A live run's come with their version."""
    session = get_session(session_id)
    if session.get("live"):
        live = answer(pipeline.live_correct_call, session_id, request.mite, request.recording, request.state,
                      request.checked)
        return as_it_is({**live, "results": for_pages(session_id, live["results"])})
    with refused():
        results = pipeline.correct_call(session["out_dir"], request.mite, request.recording, request.state,
                                        request.checked)
    session["results"] = results
    return as_it_is({"results": for_pages(session_id, results)})


@app.post("/api/session/{session_id}/review-mites")
def save_review_mites(session_id: str, request: ReviewMitesRequest):
    """How many mites to check by eye, saved with the recordings
    (pipeline.save_review_mites): the results come back with the calls to check
    as the band fitted to that number makes them. A live run's come with their
    version."""
    session = get_session(session_id)
    with refused():
        pipeline.save_review_mites(session["data_dir"], request.mites)
    if session.get("live"):
        refresh_live(session_id)
        live = answer(pipeline.live_results, session_id)
        return as_it_is({**live, "results": for_pages(session_id, live["results"])})
    results = pipeline.review_again(session["out_dir"]) if session.get("results") else None
    if results is None:
        raise HTTPException(status_code=400, detail="The number is saved. Run the analysis again to see what to check.")
    session["results"] = results
    return as_it_is({"results": for_pages(session_id, results)})


@app.get("/api/session/{session_id}/clip/{recording}")
@app.get("/api/session/{session_id}/clip/{recording}/{zone_id}")
def analysis_clip(session_id: str, recording: int, zone_id: Optional[int] = None):
    """Frames of one recording, of one zone or the whole plate, cached on first request."""
    session = get_session(session_id)
    if session.get("live") and not session.get("save_frames"):
        raise HTTPException(status_code=400, detail="This test run does not save its recordings, so there is no clip to play.")
    with refused():
        return pipeline.analysis_clip(session["data_dir"], session["out_dir"], recording, zone_id)


@app.get("/api/session/{session_id}/mite-clip/{recording}/{mite}")
def analysis_mite_clip(session_id: str, recording: int, mite: str):
    """Frames of one mite during one recording, cut close around it: the clip of
    a session saved as the mites' ROIs. Cached on first request."""
    session, results = played(session_id, "there is no clip to play")
    with refused():
        return pipeline.analysis_mite_clip(session["data_dir"], session["out_dir"], recording, mite, results["mites"])


@app.get("/api/session/{session_id}/playback")
def playback_timeline(session_id: str):
    """What the playback page plays of each recording, one after the other."""
    session, results = played(session_id, "there is nothing to play back")
    with refused():
        return pipeline.playback_timeline(session["data_dir"], results)


@app.get("/api/session/{session_id}/playback/{recording}/{zone_id}")
def playback_sheet(session_id: str, recording: int, zone_id: int):
    """Every mite of one zone in every frame of one recording, for the playback
    page (pipeline.playback_sheet). Cached on first request."""
    session, results = played(session_id, "there is nothing to play back")
    with refused():
        return pipeline.playback_sheet(session["data_dir"], session["out_dir"], recording, zone_id, results)


@app.get("/api/session/{session_id}/outline/{recording}/{zone_id}")
def analysis_outlines(session_id: str, recording: int, zone_id: int):
    """What the score sees of each mite of one zone in one recording: the dots and
    the arrow the result pages draw over the mites. Cached on first request."""
    session, results = played(session_id, "the outlines cannot be drawn")
    with refused():
        return pipeline.analysis_outlines(session["data_dir"], session["out_dir"], recording, zone_id, results)


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


@app.post("/api/calibration")
def open_calibration(request: OpenRequest):
    """Detect the mites of a calibration recording. A folder outside recordings/
    is copied there first, its frames shrunk (pipeline.calibration_folder)."""
    with refused():
        data_dir = pipeline.calibration_folder(request.data_dir)
    return new_calibration_session(data_dir, lambda out_dir: pipeline.open_calibration(data_dir, out_dir))


@app.get("/api/calibration/datasets")
def list_datasets():
    """The recordings with ground truth saved, one dataset each."""
    return {"datasets": pipeline.list_calibration_datasets()}


@app.post("/api/calibration/datasets/{dataset_id}/open")
def open_dataset(dataset_id: str):
    """Reopen a recording with ground truth to go on labelling it."""
    with refused():
        data_dir = pipeline.dataset_folder(dataset_id)
    return new_calibration_session(data_dir, lambda out_dir: pipeline.open_saved_calibration(dataset_id, out_dir))


@app.get("/api/calibration/datasets/{dataset_id}/preview")
def dataset_preview(dataset_id: str):
    """The first frame of a saved dataset, for the error map of a pooled report."""
    with refused(404):
        return FileResponse(pipeline.dataset_preview(dataset_id))


@app.get("/api/calibration/metrics")
def movement_scores():
    """The movement scores a calibration can try, with their parameters."""
    return pipeline.movement_scores()


@app.delete("/api/calibration/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    with refused():
        return {"deleted": pipeline.delete_calibration_dataset(dataset_id)}


@app.post("/api/calibration/pooled")
def open_pooled():
    """A session for reports on saved datasets alone, with no recording opened."""
    session_id = new_id()
    out_dir = pipeline.new_pooled_report_dir()
    sessions[session_id] = {"data_dir": None, "out_dir": out_dir, "report_dir": out_dir, "dataset_id": None}
    return {"session_id": session_id}


@app.post("/api/calibration/{session_id}/dataset/{dataset_id}")
def switch_dataset(session_id: str, dataset_id: str):
    """Show another saved dataset in this session, e.g. the one a mite clicked in a
    pooled report comes from: the session works in that recording's calibration
    folder from now on. Its report stays where it was made."""
    session = get_session(session_id)
    with refused():
        out_dir = pipeline.calibration_dir(pipeline.dataset_folder(dataset_id))
        calibration = pipeline.open_saved_calibration(dataset_id, out_dir)
    session.update(data_dir=calibration["data_dir"], dataset_id=calibration["dataset_id"], out_dir=out_dir)
    return as_it_is({"session_id": session_id, **calibration})


@app.post("/api/calibration/{session_id}/grow")
def grow_calibration(session_id: str):
    """A calibration session on a live run's recordings, with those analysed since
    it was opened or last grown (pipeline.grow_live_calibration)."""
    session = get_session(session_id)
    if not session.get("live_id"):
        raise HTTPException(status_code=400, detail="This calibration is not of a live run.")
    return as_it_is({"session_id": session_id,
                     **answer(pipeline.grow_live_calibration, session["out_dir"], session["live_id"])})


@app.get("/api/calibration/{session_id}/clip/{recording}/{zone_id}")
def calibration_clip(session_id: str, recording: int, zone_id: int):
    """Frames of one zone during one recording, cropped and cached on first request."""
    session = get_session(session_id)
    with refused():
        return pipeline.calibration_clip(session["out_dir"], recording, zone_id)


@app.get("/api/calibration/{session_id}/mite-clip/{recording}/{mite}")
def calibration_mite_clip(session_id: str, recording: int, mite: str):
    """Frames of one mite during one recording, cut close around it, with a picture
    of where its pixels change; cached on first request."""
    session = get_session(session_id)
    with refused():
        return pipeline.calibration_mite_clip(session["out_dir"], recording, mite)


@app.get("/api/calibration/{session_id}/plate-clip/{dataset_id}/{recording}")
def dataset_clip(session_id: str, dataset_id: str, recording: int):
    """Frames of the whole plate during one recording of a saved dataset, for the
    test report; kept with this session's files."""
    session = get_session(session_id)
    with refused():
        return pipeline.dataset_clip(session["out_dir"], dataset_id, recording)


@app.get("/api/calibration/{session_id}/truth")
def get_ground_truth(session_id: str):
    """The ground truth of this session's mites as saved now, which another window
    may have changed, with the changes not saved yet on top (pipeline.truth_view)."""
    session = get_session(session_id)
    with refused():
        return as_it_is(pipeline.truth_view(session["out_dir"]))


@app.post("/api/calibration/{session_id}/truth/edit")
def edit_ground_truth(session_id: str, request: TruthEdit):
    """A change on the ground-truth page; the page saves it next (save_ground_truth)."""
    session = get_session(session_id)
    with refused():
        return as_it_is(pipeline.edit_truth(session["out_dir"], request.action, mite=request.mite, zone=request.zone,
                                            recording=request.recording, backwards=request.backwards, kind=request.kind,
                                            state=request.state))


@app.post("/api/calibration/{session_id}/truth")
def save_ground_truth(session_id: str):
    """Save the changes made on the ground-truth page next to the recordings, so
    they survive a restart. Everything else keeps what is saved."""
    session = get_session(session_id)
    with truth_lock, refused():
        return as_it_is(pipeline.save_truth(session["out_dir"]))


@app.get("/api/calibration/{session_id}/poke")
def get_poke_test(session_id: str):
    """The poke test of this session's mites, round by round (pipeline.poke_view)."""
    session = get_session(session_id)
    with refused():
        return as_it_is(pipeline.poke_view(session["out_dir"]))


@app.post("/api/calibration/{session_id}/poke")
def edit_poke_test(session_id: str, request: PokeEdit):
    """A change on the poke-test page, saved at once next to the recordings."""
    session = get_session(session_id)
    with truth_lock, refused():
        return as_it_is(pipeline.edit_poke(session["out_dir"], request.action, request.after, mite=request.mite,
                                           zone=request.zone, state=request.state))


@app.post("/api/calibration/{session_id}/evaluate")
def evaluate_calibration(session_id: str, request: EvaluateRequest):
    """Compare the detector's calls with the ground truth, pooled over the chosen datasets."""
    session = get_session(session_id)
    datasets = request.datasets if request.datasets is not None else [session["dataset_id"]]
    with refused():
        return as_it_is(pipeline.evaluate_calibration(session["report_dir"], datasets, request.metric, request.params,
                                                      stabilize=request.stabilize, benchmark=request.benchmark,
                                                      normalize_brightness=request.normalize_brightness,
                                                      normalize_floor=request.normalize_floor,
                                                      checks_per_mite=request.checks_per_mite,
                                                      between=request.between))


@app.post("/api/threshold")
def save_threshold(request: ThresholdRequest):
    """Make a new movement threshold the default for every later analysis."""
    with refused():
        return {"threshold": pipeline.save_threshold(request.value)}


@app.post("/api/movement-score")
def save_movement_score(request: MovementScoreRequest):
    """Make a metric, its parameters and its threshold the default for every later analysis."""
    with refused():
        return pipeline.save_movement_score(request.metric, request.params, request.threshold, request.stabilize,
                                            request.normalize_brightness, request.normalize_floor,
                                            review_band=request.review_band)


# --- live runs -------------------------------------------------------------------
#
# A live run is a session like one opened from a folder: its folder is the run's
# folder in recordings/, where its recordings, labels and "not a mite" marks go, so
# the label and result pages and their clips work on it unchanged. Its results go
# to results/<run name>/.

class LiveOpenRequest(BaseModel):
    run_name: str
    camera_id: Optional[str] = None
    serial_port: str = "auto"
    save_frames: bool = True


class LiveOptionsRequest(BaseModel):
    # each left as it is when None
    run_name: Optional[str] = None
    save_frames: Optional[bool] = None


class LiveSettingsRequest(BaseModel):
    settings: dict[str, float]
    session_id: Optional[str] = None


class LightRequest(BaseModel):
    device: str
    on: Optional[bool] = None
    level: Optional[int] = None


class AddMitesRequest(BaseModel):
    boxes: list[list[float]]  # [x1, y1, x2, y2] each, as find-mites gave them


@app.get("/api/live/options")
def live_options():
    """The cameras, serial ports and saved test-run settings, and any run still open."""
    return pipeline.live_options()


@app.post("/api/live")
def open_live(request: LiveOpenRequest):
    """Open the camera and start the live feed; nothing is recorded yet."""
    session_id = new_id()
    status = answer(pipeline.open_live, session_id, None, request.run_name, camera_id=request.camera_id,
                       serial_port=request.serial_port, save_frames=request.save_frames)
    attach_live(session_id, status)
    return {"session_id": session_id, **status}


def live_session(session_id):
    session = get_session(session_id)
    if not session.get("live"):
        raise HTTPException(status_code=404, detail="Not a live run.")
    return session


def attach_live(session_id, status):
    """A live run as a session: one just opened, or one left open by a page that
    was closed or reloaded."""
    if session_id not in sessions:
        sessions[session_id] = {"data_dir": status["run_dir"], "out_dir": Path(status["out_dir"]), "live": True,
                                "save_frames": status["save_frames"]}


@app.post("/api/live/settings")
def save_live_settings(request: LiveSettingsRequest):
    """Change the test-run settings; an open camera takes a new frame rate at once."""
    settings = answer(pipeline.save_live_settings, request.settings, request.session_id)
    return {"settings": settings, "plan": pipeline.live_plan(settings)}


@app.post("/api/live/{session_id}/attach")
def reattach_live(session_id: str):
    status = answer(pipeline.live_status, session_id)
    attach_live(session_id, status)
    return {"session_id": session_id, **status}


@app.post("/api/live/{session_id}/options")
def set_live_options(session_id: str, request: LiveOptionsRequest):
    """Rename a test run not started yet, or choose whether its recordings are
    saved: its session follows its folders to their new names."""
    session = live_session(session_id)
    status = answer(pipeline.set_live_options, session_id, request.run_name, request.save_frames)
    session.update(data_dir=status["run_dir"], out_dir=Path(status["out_dir"]), save_frames=status["save_frames"])
    return {"session_id": session_id, **status}


@app.post("/api/live/{session_id}/light")
def set_live_light(session_id: str, request: LightRequest):
    """Switch the fan, or set an intensity, to check the settings; both LEDs stay on until the run starts."""
    live_session(session_id)
    return {"lights": answer(pipeline.set_live_light, session_id, request.device, request.on, request.level)}


@app.post("/api/live/{session_id}/preview")
def live_preview(session_id: str):
    """Detect the mites on the newest frame, to label the plates."""
    session = live_session(session_id)
    preview = answer(pipeline.live_preview, session_id, session["out_dir"])
    session["mites"] = preview["mites"]  # the detections of the label page, for the "not a mite" marks
    return {"session_id": session_id, **preview}


@app.post("/api/live/{session_id}/start")
def start_live(session_id: str, request: LabelsRequest):
    live_session(session_id)
    return answer(pipeline.start_live, session_id, request.labels)


@app.post("/api/live/{session_id}/find-mites")
def find_live_mites(session_id: str):
    """Light the plates between two recordings and detect the mites not followed
    yet; the frame is the session's file ADD_PREVIEW_NAME."""
    live_session(session_id)
    return answer(pipeline.live_find_mites, session_id)


@app.post("/api/live/{session_id}/add-mites")
def add_live_mites(session_id: str, request: AddMitesRequest):
    """Follow the mites chosen of those found from the next recording on."""
    live_session(session_id)
    return answer(pipeline.live_add_mites, session_id, request.boxes)


@app.post("/api/live/{session_id}/calibration")
def calibrate_live(session_id: str):
    """A calibration session on the test run's recordings so far, to enter their
    ground truth and poke test while it goes on (pipeline.open_live_calibration)."""
    session = live_session(session_id)
    return new_calibration_session(session["data_dir"],
                                   lambda out_dir: pipeline.open_live_calibration(session_id, out_dir),
                                   live_id=session_id)


@app.post("/api/live/{session_id}/{action}")
def control_live(session_id: str, action: str):
    """Pause, resume or stop the test run, or close the camera."""
    live_session(session_id)
    calls = {"pause": pipeline.pause_live, "resume": pipeline.resume_live, "stop": pipeline.stop_live}
    if action == "close":
        answer(pipeline.close_live, session_id)
        return {"closed": session_id}
    if action not in calls:
        raise HTTPException(status_code=404, detail=f"Unknown action {action}.")
    return answer(calls[action], session_id)


@app.get("/api/live/{session_id}/status")
def live_status(session_id: str):
    """How capture and analysis are going: polled by the page about twice a second."""
    return answer(pipeline.live_status, session_id)


@app.get("/api/live/{session_id}/results")
def live_results(session_id: str):
    """The results so far, as a folder run returns them, with their version."""
    live = answer(pipeline.live_results, session_id)
    if live["results"] is not None:
        live = {**live, "results": for_pages(session_id, live["results"])}
    return as_it_is(live)


@app.get("/api/live/{session_id}/frame.jpg")
def live_frame(session_id: str, w: int = 960):
    """The newest camera frame, for the live feed."""
    data = answer(pipeline.live_frame, session_id, w)
    if data is None:
        raise HTTPException(status_code=404, detail="No frame yet.")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/session/{session_id}/file/{name:path}")
def get_file(session_id: str, name: str):
    """Serve one output file (preview, figure, workbook or clip frame) from this session."""
    session = get_session(session_id)

    # Only ever serve a file from this session's own output folder; a
    # calibration report's workbook from the folder of the session that made it.
    folder = session.get("report_dir") if name == pipeline.CALIBRATION_REPORT_NAME else None
    folder = Path(folder or session["out_dir"])
    safe_join(folder, name)
    path = pipeline.results_file(folder, name).resolve()
    if not path.is_file() or folder.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail=f"No such file: {name}")
    return FileResponse(path)


# --- the recordings kept -------------------------------------------------------------


@app.get("/api/recordings")
def list_recordings():
    """Every recording in recordings/, with how it was recorded: the live runs and
    the folders dropped into the page."""
    return {"recordings": pipeline.list_recordings(), "root": str(pipeline.RECORDINGS_ROOT),
            "results_root": str(pipeline.RESULTS_ROOT)}


@app.get("/api/recordings/{name}/results/{filename}")
def recording_results(name: str, filename: str):
    """A file of the last analysis of a recording, e.g. its results.xlsx."""
    with refused(404):
        return FileResponse(pipeline.recording_results_file(name, filename), filename=f"{name}_{filename}")


@app.post("/api/page/{page_id}/alive")
def page_alive(page_id: str):
    """An open page checking in, so the server knows to keep running."""
    global last_activity, any_page_seen
    pages[page_id] = last_activity = time.monotonic()
    any_page_seen = True
    return {}


@app.post("/api/page/{page_id}/closed")
def page_closed(page_id: str):
    """A page being closed or reloaded."""
    global last_activity
    pages.pop(page_id, None)
    last_activity = time.monotonic()
    return {}


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=APP_DIR, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# Read once: the code this process runs, even if the folder is updated meanwhile.
APP_DIR = Path(__file__).resolve().parent.parent
COMMIT = _git_commit()


@app.get("/api/version", response_class=PlainTextResponse)
def version():
    """Folder, commit and whether a live run is going, one per line. start.sh
    restarts the server to load the new version, unless a live run is going."""
    return f"{APP_DIR}\n{COMMIT}\n{int(pipeline.live_running())}\n"


class FreshStaticFiles(StaticFiles):
    """The page and its scripts, which the browser must check for a newer version
    on every load: a cached script next to an updated server breaks the page."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", FreshStaticFiles(directory=STATIC_DIR, html=True), name="static")
