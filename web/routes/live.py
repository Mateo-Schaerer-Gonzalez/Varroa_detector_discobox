"""The live pages: opening the camera, the run's settings and lights, labelling
on the live feed, starting and controlling the run, adding mites, and its
status, results and feed. A live run is a session (web/page_sessions.py)."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import pipeline
from web.http_helpers import answer, as_it_is, new_id
from web.page_sessions import attach_live, for_pages, label_live_plates, live_session, new_calibration_session
from web.routes.analysis import LabelsRequest

router = APIRouter()


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


@router.get("/api/live/options")
def live_options():
    """The cameras, serial ports and saved test-run settings, and any run still open."""
    return pipeline.live_options()


@router.post("/api/live")
def open_live(request: LiveOpenRequest):
    """Open the camera and start the live feed; nothing is recorded yet."""
    session_id = new_id()
    status = answer(pipeline.open_live, session_id, None, request.run_name, camera_id=request.camera_id,
                       serial_port=request.serial_port, save_frames=request.save_frames)
    attach_live(session_id, status)
    return {"session_id": session_id, **status}


@router.post("/api/live/settings")
def save_live_settings(request: LiveSettingsRequest):
    """Change the test-run settings; an open camera takes a new frame rate at once."""
    settings = answer(pipeline.save_live_settings, request.settings, request.session_id)
    return {"settings": settings, "plan": pipeline.live_plan(settings)}


@router.post("/api/live/{session_id}/attach")
def reattach_live(session_id: str):
    status = answer(pipeline.live_status, session_id)
    attach_live(session_id, status)
    return {"session_id": session_id, **status}


@router.post("/api/live/{session_id}/options")
def set_live_options(session_id: str, request: LiveOptionsRequest):
    """Rename a test run not started yet, or choose whether its recordings are
    saved: its session follows its folders to their new names."""
    session = live_session(session_id)
    status = answer(pipeline.set_live_options, session_id, request.run_name, request.save_frames)
    session.update(data_dir=status["run_dir"], out_dir=Path(status["out_dir"]), save_frames=status["save_frames"])
    return {"session_id": session_id, **status}


@router.post("/api/live/{session_id}/light")
def set_live_light(session_id: str, request: LightRequest):
    """Switch the fan, or set an intensity, to check the settings; both LEDs stay on until the run starts."""
    live_session(session_id)
    return {"lights": answer(pipeline.set_live_light, session_id, request.device, request.on, request.level)}


@router.post("/api/live/{session_id}/preview")
def live_preview(session_id: str):
    """Detect the mites on the newest frame, to label the plates."""
    return label_live_plates(session_id)


@router.post("/api/live/{session_id}/start")
def start_live(session_id: str, request: LabelsRequest):
    live_session(session_id)
    return answer(pipeline.start_live, session_id, request.labels)


@router.post("/api/live/{session_id}/find-mites")
def find_live_mites(session_id: str):
    """Light the plates between two recordings and detect the mites not followed
    yet; the frame is the session's file ADD_PREVIEW_NAME."""
    live_session(session_id)
    return answer(pipeline.live_find_mites, session_id)


@router.post("/api/live/{session_id}/add-mites")
def add_live_mites(session_id: str, request: AddMitesRequest):
    """Follow the mites chosen of those found from the next recording on."""
    live_session(session_id)
    return answer(pipeline.live_add_mites, session_id, request.boxes)


@router.post("/api/live/{session_id}/calibration")
def calibrate_live(session_id: str):
    """A calibration session on the test run's recordings so far, to enter their
    ground truth and poke test while it goes on (pipeline.open_live_calibration)."""
    session = live_session(session_id)
    return new_calibration_session(session["data_dir"],
                                   lambda out_dir: pipeline.open_live_calibration(session_id, out_dir),
                                   live_id=session_id)


@router.post("/api/live/{session_id}/{action}")
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


@router.get("/api/live/{session_id}/status")
def live_status(session_id: str):
    """How capture and analysis are going: polled by the page about twice a second."""
    return answer(pipeline.live_status, session_id)


@router.get("/api/live/{session_id}/results")
def live_results(session_id: str):
    """The results so far, as a folder run returns them, with their version."""
    live = answer(pipeline.live_results, session_id)
    if live["results"] is not None:
        live = {**live, "results": for_pages(session_id, live["results"])}
    return as_it_is(live)


@router.get("/api/live/{session_id}/frame.jpg")
def live_frame(session_id: str, w: int = 960):
    """The newest camera frame, for the live feed."""
    data = answer(pipeline.live_frame, session_id, w)
    if data is None:
        raise HTTPException(status_code=404, detail="No frame yet.")
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
