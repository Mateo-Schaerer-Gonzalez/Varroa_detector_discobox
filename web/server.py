"""HTTP layer: turns requests into pipeline calls and results into JSON.

Deliberately contains no analysis logic. It may import `pipeline` and nothing else
from the project -- no cv2, pandas, matplotlib, numpy or classes.* -- which
`unit_tests/test_layering.py` enforces.

Run it with start.bat, or:  python -m uvicorn web.server:app --port 8000
"""

import uuid
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import pipeline

STATIC_DIR = Path(__file__).parent / "static"
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "outputs"
# Folders dropped into the browser are copied here, one subfolder per folder name.
UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads"

app = FastAPI(title="Varroa discobox")

# Everything a run produces lives in outputs/<session id>/.
sessions: dict[str, dict] = {}


class OpenRequest(BaseModel):
    data_dir: str


class LabelsRequest(BaseModel):
    labels: dict[str, str] = {}


class UploadedFile(BaseModel):
    path: str
    size: int


class ManifestRequest(BaseModel):
    files: list[UploadedFile]


class TruthRequest(BaseModel):
    # mite id -> one status per recording: "moving", "still", "not_a_mite" or null
    truth: dict[str, list[Optional[str]]] = {}


class EvaluateRequest(BaseModel):
    # the ground truth on screen, saved first; left out, the saved one is used as it is
    # (an empty dict would clear it)
    truth: Optional[dict[str, list[Optional[str]]]] = None
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
    out_dir = OUTPUT_ROOT / session_id
    try:
        session = pipeline.open_session(request.data_dir, out_dir)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))

    sessions[session_id] = {"data_dir": session["data_dir"], "out_dir": out_dir}
    return {"session_id": session_id, **session}


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
    """Persist the typed labels next to the recordings so they survive a restart."""
    session = get_session(session_id)
    pipeline.save_labels(session["data_dir"], request.labels)
    return {"saved": len(request.labels)}


@app.post("/api/session/{session_id}/run")
def run_analysis(session_id: str, request: LabelsRequest):
    """Run the full analysis. Synchronous: the browser waits with a spinner."""
    session = get_session(session_id)
    pipeline.save_labels(session["data_dir"], request.labels)
    try:
        return pipeline.run_analysis(session["data_dir"], session["out_dir"], request.labels)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


def new_calibration_session(open_it):
    """Run `open_it(out_dir)` in a fresh calibration session and remember it."""
    session_id = uuid.uuid4().hex[:8]
    out_dir = OUTPUT_ROOT / f"calibration_{session_id}"
    try:
        calibration = open_it(out_dir)
    except (FileNotFoundError, ValueError) as error:
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
    return new_calibration_session(lambda out_dir: pipeline.open_calibration(request.data_dir, out_dir))


@app.get("/api/calibration/datasets")
def list_datasets():
    """The ground truth saved so far, one dataset per calibration recording."""
    return {"datasets": pipeline.list_calibration_datasets()}


@app.post("/api/calibration/datasets/{dataset_id}/open")
def open_dataset(dataset_id: str):
    """Reopen a saved dataset to go on labelling it. Fast: nothing is decoded."""
    return new_calibration_session(lambda out_dir: pipeline.open_saved_calibration(dataset_id, out_dir))


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
    sessions[session_id] = {"data_dir": None, "out_dir": OUTPUT_ROOT / f"calibration_{session_id}", "dataset_id": None}
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


@app.post("/api/calibration/{session_id}/truth")
def save_ground_truth(session_id: str, request: TruthRequest):
    """Persist the ground truth next to the recordings so it survives a restart."""
    session = get_session(session_id)
    try:
        return {"saved": pipeline.save_ground_truth(session["out_dir"], request.truth)}
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.post("/api/calibration/{session_id}/evaluate")
def evaluate_calibration(session_id: str, request: EvaluateRequest):
    """Compare the detector's calls with the ground truth, pooled over the chosen datasets."""
    session = get_session(session_id)
    datasets = request.datasets if request.datasets is not None else [session["dataset_id"]]
    try:
        if session["dataset_id"] and request.truth is not None:
            pipeline.save_ground_truth(session["out_dir"], request.truth)
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


@app.get("/api/session/{session_id}/file/{name}")
def get_file(session_id: str, name: str):
    """Serve one output file (preview, figure or workbook) from this session."""
    session = get_session(session_id)

    # Only ever serve a plain filename from this session's own output folder.
    path = (session["out_dir"] / Path(name).name).resolve()
    if not path.is_file() or session["out_dir"].resolve() not in path.parents:
        raise HTTPException(status_code=404, detail=f"No such file: {name}")
    return FileResponse(path)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
