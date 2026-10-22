"""The recordings kept in recordings/, and folders dropped into the page, which
are copied there file by file."""

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

import pipeline
from web.http_helpers import REFUSALS, refused, safe_join

router = APIRouter()

# Folders dropped into the browser are copied to recordings/, one subfolder per
# folder name, next to the live runs.
UPLOAD_ROOT = pipeline.RECORDINGS_ROOT


class UploadedFile(BaseModel):
    path: str
    size: int


class ManifestRequest(BaseModel):
    files: list[UploadedFile]


@router.post("/api/uploads/{name}/manifest")
def upload_manifest(name: str, request: ManifestRequest):
    """Say which files of a dropped folder still need sending, and where they go
    (pipeline.plan_upload): every file of the folder is listed, the server picks."""
    with refused():
        return pipeline.plan_upload(name, [{"path": file.path, "size": file.size} for file in request.files], UPLOAD_ROOT)


@router.post("/api/uploads/{name}/finish")
def upload_finish(name: str):
    """Every file of a dropped folder is in: shrink its frames to the mites'
    surroundings (pipeline.finish_upload)."""
    with refused(errors=(*REFUSALS, RuntimeError)):
        return pipeline.finish_upload(name, UPLOAD_ROOT)


@router.put("/api/uploads/{name}/file")
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


@router.get("/api/recordings")
def list_recordings():
    """Every recording in recordings/, with how it was recorded: the live runs and
    the folders dropped into the page."""
    return {"recordings": pipeline.list_recordings(), "root": str(pipeline.RECORDINGS_ROOT),
            "results_root": str(pipeline.RESULTS_ROOT)}


@router.get("/api/recordings/{name}/results/{filename}")
def recording_results(name: str, filename: str):
    """A file of the last analysis of a recording, e.g. its results.xlsx."""
    with refused(404):
        return FileResponse(pipeline.recording_results_file(name, filename), filename=f"{name}_{filename}")
