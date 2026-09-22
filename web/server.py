"""HTTP layer: turns requests into pipeline calls and results into JSON.

Deliberately contains no analysis logic. It may import `pipeline` and nothing else
from the project -- no cv2, pandas, matplotlib, numpy or classes.* -- which
`unit_tests/test_layering.py` enforces.

Run it with start.bat, or:  python -m uvicorn web.server:app --port 8000
"""

import uuid
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
    """
    folder = safe_join(UPLOAD_ROOT, name)
    missing = []
    for file in request.files:
        target = safe_join(folder, file.path)
        if target.name == pipeline.LABELS_FILENAME and target.is_file():
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
