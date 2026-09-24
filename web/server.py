"""HTTP layer: turns requests into pipeline calls and results into JSON.

Deliberately contains no analysis logic. It may import `pipeline` and nothing else
from the project -- no cv2, pandas, matplotlib, numpy or classes.* -- which
`unit_tests/test_layering.py` enforces.

Run it with start.bat, or:  python -m uvicorn web.server:app --port 8000
"""

import os
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional, Union
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
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
    # What earlier versions wrote to output/, uploads/ and outputs/ moves to today's folders.
    for line in pipeline.tidy_folders():
        print(f"Folders: {line}", flush=True)
    if AUTO_STOP:
        threading.Thread(target=watch_pages, daemon=True).start()
    yield
    # Ctrl+C on the server: a live run stops cleanly and writes its results.
    pipeline.close_all_live()


app = FastAPI(title="Varroa discobox", lifespan=lifespan)

# A session's files go to its out_dir: results/<recording>/ for an analysis or a
# live run, calibration_data/reports/<date time name>/ for a calibration.
sessions: dict[str, dict] = {}
# Every change to a ground truth reads what is saved and writes it back; one at a
# time, so two windows saving at once cannot undo each other's change.
truth_lock = threading.Lock()


class OpenRequest(BaseModel):
    data_dir: str


class LabelsRequest(BaseModel):
    labels: dict[str, str] = {}
    # frames scored together; by default a whole recording
    pool_size: Optional[int] = None


class RejectRequest(BaseModel):
    x: float
    y: float
    rejected: bool
    # taking a mark back: the labels marking replaced, as it returned them, to put back
    restore: Union[list[Optional[str]], str, None] = None


class UploadedFile(BaseModel):
    path: str
    size: int


class ManifestRequest(BaseModel):
    files: list[UploadedFile]


# mite id -> the statuses changed on screen, by recording index ("moving", "still",
# "not_a_mite" or null), or a list with every recording's status
TruthChanges = dict[str, Union[dict[int, Optional[str]], list[Optional[str]]]]


class TruthRequest(BaseModel):
    truth: TruthChanges = {}


class EvaluateRequest(BaseModel):
    # statuses changed on screen, saved first; everything else, or everything when
    # this is left out, keeps the saved ground truth
    truth: Optional[TruthChanges] = None
    # ids of the saved datasets to pool; by default only this session's own
    datasets: Optional[list[str]] = None
    # the movement score to try; by default the one in config.yaml
    metric: Optional[str] = None
    params: Optional[dict[str, float]] = None


class ThresholdRequest(BaseModel):
    value: float


class MovementScoreRequest(BaseModel):
    metric: str
    params: dict[str, float] = {}
    threshold: float


def safe_join(root: Path, relative: str) -> Path:
    """Resolve a browser-supplied relative path, refusing anything that escapes root."""
    parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or ".." in parts or ":" in relative:
        raise HTTPException(status_code=400, detail=f"Bad path: {relative}")
    return root.joinpath(*parts)


def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Unknown session. Open a folder again.")
    return sessions[session_id]


@app.post("/api/session")
def open_session(request: OpenRequest):
    """Point the app at a folder of recordings and get back the zones to label."""
    session_id = uuid.uuid4().hex[:8]
    out_dir = pipeline.results_dir(request.data_dir)
    try:
        session = pipeline.open_session(request.data_dir, out_dir)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))

    sessions[session_id] = {"data_dir": session["data_dir"], "out_dir": out_dir}
    return {"session_id": session_id, "results_dir": str(out_dir), **session}


@app.post("/api/uploads/{name}/manifest")
def upload_manifest(name: str, request: ManifestRequest):
    """Say which files of a dropped folder still need sending.

    A file already here with the same size is skipped, so dropping the same folder
    twice is instant. A labels.json already here is never replaced: it holds the
    labels typed in this app, which are newer than the copy in the dropped folder.
    The same holds for a ground_truth.json entered during calibration.
    """
    folder = safe_join(UPLOAD_ROOT, name)
    missing = []
    for file in request.files:
        target = safe_join(folder, file.path)
        kept = (pipeline.LABELS_FILENAME, pipeline.GROUND_TRUTH_FILENAME)
        if target.name in kept and target.is_file():
            continue
        if not target.is_file() or target.stat().st_size != file.size:
            missing.append(file.path)
    return {"data_dir": str(folder), "missing": missing}


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
    if session.get("live"):
        pipeline.live_refresh(session_id)
    return {"saved": len(request.labels)}


@app.post("/api/session/{session_id}/reject")
def reject_detection(session_id: str, request: RejectRequest):
    """Mark a detection as not a mite, or take the mark back, before a run. Marking
    returns the movement labels it replaced, for taking the mark back to restore."""
    session = get_session(session_id)
    with truth_lock:
        replaced = pipeline.set_rejected(session["data_dir"], request.x, request.y, request.rejected, request.restore)
    if session.get("live"):
        pipeline.live_refresh(session_id)
    return {"rejected": request.rejected, "replaced": replaced}


@app.post("/api/session/{session_id}/run")
def run_analysis(session_id: str, request: LabelsRequest):
    """Run the full analysis. Synchronous: the browser waits with a spinner."""
    session = get_session(session_id)
    pipeline.save_labels(session["data_dir"], request.labels)
    try:
        results = pipeline.run_analysis(session["data_dir"], session["out_dir"], request.labels, pool_size=request.pool_size)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    session["pool_size"] = request.pool_size  # the clips of the results are of its pools
    return results


@app.get("/api/session/{session_id}/clip/{recording}")
@app.get("/api/session/{session_id}/clip/{recording}/{zone_id}")
def analysis_clip(session_id: str, recording: int, zone_id: Optional[int] = None):
    """Frames of one recording, of one zone or the whole plate, cached on first request."""
    session = get_session(session_id)
    if session.get("live") and not session.get("save_frames"):
        raise HTTPException(status_code=400, detail="This test run does not save its recordings, so there is no clip to play.")
    try:
        return pipeline.analysis_clip(session["data_dir"], session["out_dir"], recording, zone_id,
                                      pool_size=session.get("pool_size"))
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


def new_calibration_session(name, open_it):
    """Run `open_it(out_dir)` in a fresh calibration session and remember it.
    Its folder is named by when it began and by `name`, what it opened."""
    session_id = uuid.uuid4().hex[:8]
    out_dir = pipeline.new_calibration_report_dir(name)
    try:
        calibration = open_it(out_dir)
    except (FileNotFoundError, ValueError) as error:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error))

    sessions[session_id] = {
        "data_dir": calibration["data_dir"],
        "out_dir": out_dir,
        "dataset_id": calibration["dataset_id"],
    }
    return {"session_id": session_id, **calibration}


@app.post("/api/calibration")
def open_calibration(request: OpenRequest):
    """Detect and score the mites of a calibration recording. Slow: decodes every frame."""
    return new_calibration_session(Path(request.data_dir).name,
                                   lambda out_dir: pipeline.open_calibration(request.data_dir, out_dir))


@app.get("/api/calibration/datasets")
def list_datasets():
    """The ground truth saved so far, one dataset per calibration recording."""
    return {"datasets": pipeline.list_calibration_datasets()}


@app.post("/api/calibration/datasets/{dataset_id}/open")
def open_dataset(dataset_id: str):
    """Reopen a saved dataset to go on labelling it. Fast: nothing is decoded."""
    return new_calibration_session(dataset_id, lambda out_dir: pipeline.open_saved_calibration(dataset_id, out_dir))


@app.get("/api/calibration/datasets/{dataset_id}/preview")
def dataset_preview(dataset_id: str):
    """The first frame of a saved dataset, for the error map of a pooled report."""
    try:
        return FileResponse(pipeline.dataset_preview(dataset_id))
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error))


@app.get("/api/calibration/metrics")
def movement_scores():
    """The movement scores a calibration can try, with their parameters."""
    return pipeline.movement_scores()


@app.delete("/api/calibration/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    try:
        return {"deleted": pipeline.delete_calibration_dataset(dataset_id)}
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/calibration/pooled")
def open_pooled():
    """A session for reports on saved datasets alone, with no recording opened."""
    session_id = uuid.uuid4().hex[:8]
    out_dir = pipeline.new_calibration_report_dir("pooled")
    sessions[session_id] = {"data_dir": None, "out_dir": out_dir, "dataset_id": None}
    return {"session_id": session_id}


@app.post("/api/calibration/{session_id}/dataset/{dataset_id}")
def switch_dataset(session_id: str, dataset_id: str):
    """Show another saved dataset in this session, e.g. the one a mite clicked in a
    pooled report comes from. The session's report files stay where they are."""
    session = get_session(session_id)
    try:
        calibration = pipeline.open_saved_calibration(dataset_id, session["out_dir"])
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))
    session.update(data_dir=calibration["data_dir"], dataset_id=calibration["dataset_id"])
    return {"session_id": session_id, **calibration}


@app.get("/api/calibration/{session_id}/clip/{recording}/{zone_id}")
def calibration_clip(session_id: str, recording: int, zone_id: int):
    """Frames of one zone during one recording, cropped and cached on first request."""
    session = get_session(session_id)
    try:
        return pipeline.calibration_clip(session["out_dir"], recording, zone_id)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/calibration/{session_id}/truth")
def get_ground_truth(session_id: str):
    """The ground truth saved for this session's mites, which another window may have changed."""
    session = get_session(session_id)
    try:
        return {"truth": pipeline.load_calibration_truth(session["out_dir"])}
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/calibration/{session_id}/truth")
def save_ground_truth(session_id: str, request: TruthRequest):
    """Persist the statuses that changed, next to the recordings and in the library,
    so they survive a restart. Everything else keeps what is saved."""
    session = get_session(session_id)
    try:
        with truth_lock:
            return {"truth": pipeline.update_ground_truth(session["out_dir"], request.truth)}
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/calibration/{session_id}/evaluate")
def evaluate_calibration(session_id: str, request: EvaluateRequest):
    """Compare the detector's calls with the ground truth, pooled over the chosen datasets."""
    session = get_session(session_id)
    datasets = request.datasets if request.datasets is not None else [session["dataset_id"]]
    try:
        if session["dataset_id"] and request.truth is not None:
            with truth_lock:
                pipeline.update_ground_truth(session["out_dir"], request.truth)
        return pipeline.evaluate_calibration(session["out_dir"], datasets, request.metric, request.params)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/threshold")
def save_threshold(request: ThresholdRequest):
    """Make a new movement threshold the default for every later analysis."""
    try:
        return {"threshold": pipeline.save_threshold(request.value)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/movement-score")
def save_movement_score(request: MovementScoreRequest):
    """Make a metric, its parameters and its threshold the default for every later analysis."""
    try:
        return pipeline.save_movement_score(request.metric, request.params, request.threshold)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


# --- live runs -------------------------------------------------------------------
#
# A live run is a session like one opened from a folder: its folder is the run's
# folder in recordings/, where its recordings, labels and "not a mite" marks go, so
# the label and result pages and their clips work on it unchanged. Its results go
# to results/<run name>/.

LIVE_ERRORS = (FileNotFoundError, ValueError, pipeline.CameraError)


class LiveOpenRequest(BaseModel):
    run_name: str
    source: str = "camera"  # or "replay": a recorded folder, as if from the camera
    camera_id: Optional[str] = None
    serial_port: str = "auto"
    replay_dir: Optional[str] = None
    replay_fps: Optional[float] = None
    replay_gap: float = 2.0
    save_frames: bool = True
    pool_size: Optional[int] = None


class LiveSettingsRequest(BaseModel):
    settings: dict[str, float]
    session_id: Optional[str] = None


class LightRequest(BaseModel):
    device: str
    on: Optional[bool] = None
    level: Optional[int] = None


def live_call(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except LIVE_ERRORS as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/live/options")
def live_options():
    """The cameras, serial ports and saved test-run settings, and any run still open."""
    return pipeline.live_options()


@app.post("/api/live")
def open_live(request: LiveOpenRequest):
    """Open the camera (or a replay) and start the live feed; nothing is recorded yet."""
    session_id = uuid.uuid4().hex[:8]
    status = live_call(pipeline.open_live, session_id, None, request.run_name, source=request.source,
                       camera_id=request.camera_id, replay_dir=request.replay_dir, replay_fps=request.replay_fps,
                       replay_gap=request.replay_gap, serial_port=request.serial_port,
                       save_frames=request.save_frames, pool_size=request.pool_size)
    sessions[session_id] = {"data_dir": status["run_dir"], "out_dir": Path(status["out_dir"]), "live": True,
                            "pool_size": request.pool_size, "save_frames": request.save_frames}
    return {"session_id": session_id, **status}


def live_session(session_id):
    session = get_session(session_id)
    if not session.get("live"):
        raise HTTPException(status_code=404, detail="Not a live run.")
    return session


def attach_live(session_id, status):
    """A run left open by a page that was closed or reloaded, as a session again."""
    if session_id not in sessions:
        sessions[session_id] = {"data_dir": status["run_dir"], "out_dir": Path(status["out_dir"]), "live": True,
                                "pool_size": status["pool_size"], "save_frames": status["save_frames"]}


@app.post("/api/live/settings")
def save_live_settings(request: LiveSettingsRequest):
    """Change the test-run settings; an open camera takes a new frame rate at once."""
    return {"settings": live_call(pipeline.save_live_settings, request.settings, request.session_id)}


@app.post("/api/live/{session_id}/attach")
def reattach_live(session_id: str):
    status = live_call(pipeline.live_status, session_id)
    attach_live(session_id, status)
    return {"session_id": session_id, **status}


@app.post("/api/live/{session_id}/light")
def set_live_light(session_id: str, request: LightRequest):
    """Switch the fan or an LED to check the settings, as the Discobox settings window does."""
    live_session(session_id)
    return {"lights": live_call(pipeline.set_live_light, session_id, request.device, request.on, request.level)}


@app.post("/api/live/{session_id}/preview")
def live_preview(session_id: str):
    """Detect the mites on the newest frame, to label the plates."""
    session = live_session(session_id)
    return {"session_id": session_id, **live_call(pipeline.live_preview, session_id, session["out_dir"])}


@app.post("/api/live/{session_id}/start")
def start_live(session_id: str, request: LabelsRequest):
    live_session(session_id)
    return live_call(pipeline.start_live, session_id, request.labels)


@app.post("/api/live/{session_id}/{action}")
def control_live(session_id: str, action: str):
    """Pause, resume or stop the test run, or close the camera."""
    live_session(session_id)
    calls = {"pause": pipeline.pause_live, "resume": pipeline.resume_live, "stop": pipeline.stop_live}
    if action == "close":
        live_call(pipeline.close_live, session_id)
        return {"closed": session_id}
    if action not in calls:
        raise HTTPException(status_code=404, detail=f"Unknown action {action}.")
    return live_call(calls[action], session_id)


@app.get("/api/live/{session_id}/status")
def live_status(session_id: str):
    """How capture and analysis are going: polled by the page about twice a second."""
    return live_call(pipeline.live_status, session_id)


@app.get("/api/live/{session_id}/results")
def live_results(session_id: str):
    """The results so far, as a folder run returns them, with their version."""
    return live_call(pipeline.live_results, session_id)


@app.get("/api/live/{session_id}/frame.jpg")
def live_frame(session_id: str, w: int = 960):
    """The newest camera frame, for the live feed."""
    data = live_call(pipeline.live_frame, session_id, w)
    if data is None:
        raise HTTPException(status_code=404, detail="No frame yet.")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/session/{session_id}/file/{name:path}")
def get_file(session_id: str, name: str):
    """Serve one output file (preview, figure, workbook or clip frame) from this session."""
    session = get_session(session_id)

    # Only ever serve a file from this session's own output folder.
    path = safe_join(session["out_dir"], name).resolve()
    if not path.is_file() or session["out_dir"].resolve() not in path.parents:
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
    try:
        return FileResponse(pipeline.recording_results_file(name, filename), filename=f"{name}_{filename}")
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error))


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


class FreshStaticFiles(StaticFiles):
    """The page and its scripts, which the browser must check for a newer version
    on every load: a cached app.js next to an updated server breaks the page."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", FreshStaticFiles(directory=STATIC_DIR, html=True), name="static")
