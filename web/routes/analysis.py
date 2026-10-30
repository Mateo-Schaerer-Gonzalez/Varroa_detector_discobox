"""A folder opened for analysis: the label page (labels, controls, "not a mite"
marks, zones per plate), the run, and the result pages' changes (corrected
calls, death time, mites to check); and the files of any session."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import pipeline
from web.http_helpers import answer, as_it_is, new_id, refused, safe_join
from web.page_sessions import (for_pages, get_session, label_live_plates, refresh_live, sessions, survival_now,
                               truth_lock)

router = APIRouter()


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


class HandMiteRequest(BaseModel):
    x: float  # where it is clicked, in image pixels
    y: float
    remove: bool = False  # forget the mite placed by hand there


@router.post("/api/session")
def open_session(request: OpenRequest):
    """Point the app at a folder of recordings and get back the zones to label."""
    session_id = new_id()
    out_dir = pipeline.results_dir(request.data_dir)
    with refused():
        session = pipeline.open_session(request.data_dir, out_dir)

    # the detections of the label page, for the "not a mite" marks
    sessions[session_id] = {"data_dir": session["data_dir"], "out_dir": out_dir, "mites": session["mites"]}
    return {"session_id": session_id, "results_dir": str(out_dir), **session}


@router.post("/api/session/{session_id}/labels")
def save_labels(session_id: str, request: LabelsRequest):
    """Persist the typed labels next to the recordings so they survive a restart.
    A live run's results take them at once."""
    session = get_session(session_id)
    pipeline.save_labels(session["data_dir"], request.labels)
    refresh_live(session_id)
    return {"saved": len(request.labels)}


@router.post("/api/label-reading")
def save_label_reading(request: LabelReadingRequest):
    """The label page's box "Read the names from the plates", saved in config.yaml."""
    return pipeline.save_label_reading(request.enabled)


@router.post("/api/session/{session_id}/read-labels")
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


@router.post("/api/session/{session_id}/controls")
def save_controls(session_id: str, request: ControlsRequest):
    """The zones ticked as negative controls, saved next to the recordings. The
    results compare every other zone with them, with no need to run again: the
    survival numbers come back with the change. A live run's results take them
    at once too, as a new version."""
    session = get_session(session_id)
    controls = pipeline.save_controls(session["data_dir"], request.controls)
    refresh_live(session_id)
    return {"controls": controls, "survival": survival_now(session_id)}


@router.post("/api/session/{session_id}/reject")
def reject_detection(session_id: str, request: RejectRequest):
    """Mark a detection as not a mite, or take the mark back, before a run; taking it
    back puts back the labels the mark replaced. Returns every detection's mark and
    how many mites each zone has left (pipeline.mark_detection)."""
    session = get_session(session_id)
    with truth_lock, refused():
        marks = pipeline.mark_detection(session["data_dir"], session.get("mites", []), request.mite, request.rejected)
    refresh_live(session_id)
    return marks


@router.post("/api/session/{session_id}/hand-mite")
def place_hand_mite(session_id: str, request: HandMiteRequest):
    """Place a mite by hand where the detector found none, or forget one placed
    so; every later detection on these recordings finds it. The label page gets
    the session again, with it. A test run not started yet has it placed on the
    camera's newest frame (pipeline.place_mite, pipeline.live_place_mite)."""
    session = get_session(session_id)
    if session.get("live"):
        opened = answer(pipeline.live_place_mite, session_id, request.x, request.y, request.remove, session["out_dir"])
    else:
        with refused():
            opened = pipeline.place_mite(session["data_dir"], session["out_dir"], request.x, request.y, request.remove)
    session["mites"] = opened["mites"]  # the detections of the label page, for the "not a mite" marks
    return {"session_id": session_id, **opened}


@router.post("/api/session/{session_id}/death")
def save_death_minutes(session_id: str, request: DeathRequest):
    """How long a mite must be still to count as dead, saved with the recordings.
    The survival numbers of the results come back with the change."""
    session = get_session(session_id)
    with refused():
        death = pipeline.save_death_minutes(session["data_dir"], request.minutes)
    return {"death_minutes": death, "survival": survival_now(session_id)}


@router.post("/api/session/{session_id}/zones")
def save_zones_per_plate(session_id: str, request: ZonesRequest):
    """Cut each plate into one zone or two, saved with the recordings for every
    later analysis of them. The label page gets the session again, with the new
    zones and their mites; the results of the other zones are let go. A test run
    not started yet takes them too, and keeps them as its setting."""
    session = get_session(session_id)
    if session.get("live"):
        answer(pipeline.save_live_settings, {"zones_per_plate": request.zones_per_plate}, session_id)
        return label_live_plates(session_id)
    with refused():
        opened = pipeline.save_zones_per_plate(session["data_dir"], session["out_dir"], request.zones_per_plate)
    session["mites"] = opened["mites"]
    session.pop("results", None)
    return {"session_id": session_id, "results_dir": str(session["out_dir"]), **opened}


@router.post("/api/session/{session_id}/run")
def run_analysis(session_id: str, request: LabelsRequest):
    """Run the full analysis. Synchronous: the browser waits with a spinner."""
    session = get_session(session_id)
    pipeline.save_labels(session["data_dir"], request.labels)
    with refused():
        results = pipeline.run_analysis(session["data_dir"], session["out_dir"], request.labels, files_later=True)
    session["results"] = results  # for the survival numbers, which follow the controls and the time to count dead
    return as_it_is(for_pages(session_id, results))


@router.post("/api/session/{session_id}/correct")
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


@router.post("/api/session/{session_id}/review-mites")
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


@router.get("/api/session/{session_id}/file/{name:path}")
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
