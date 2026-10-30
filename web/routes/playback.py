"""What the result pages play of the recordings: clips of a zone, the plate or
a mite, the playback page's sheets, and the outlines the score sees."""

from typing import Optional

from fastapi import APIRouter, HTTPException

import pipeline
from web.http_helpers import refused
from web.page_sessions import get_session, played

router = APIRouter()


@router.get("/api/session/{session_id}/clip/{recording}")
@router.get("/api/session/{session_id}/clip/{recording}/{zone_id}")
def analysis_clip(session_id: str, recording: int, zone_id: Optional[int] = None):
    """Frames of one recording, of one zone or the whole plate, cached on first request."""
    session = get_session(session_id)
    if session.get("live") and not session.get("save_frames"):
        raise HTTPException(status_code=400, detail="This test run does not save its recordings, so there is no clip to play.")
    with refused():
        return pipeline.analysis_clip(session["data_dir"], session["out_dir"], recording, zone_id)


@router.get("/api/session/{session_id}/mite-clip/{recording}/{mite}")
def analysis_mite_clip(session_id: str, recording: int, mite: str):
    """Frames of one mite during one recording, cut close around it: the clip of
    a session saved as the mites' ROIs. Cached on first request."""
    session, results = played(session_id, "there is no clip to play")
    with refused():
        return pipeline.analysis_mite_clip(session["data_dir"], session["out_dir"], recording, mite, results["mites"])


@router.get("/api/session/{session_id}/playback")
def playback_timeline(session_id: str):
    """What the playback page plays of each recording, one after the other."""
    session, results = played(session_id, "there is nothing to play back")
    with refused():
        return pipeline.playback_timeline(session["data_dir"], results)


@router.get("/api/session/{session_id}/playback/{recording}/{zone_id}")
def playback_sheet(session_id: str, recording: int, zone_id: int):
    """Every mite of one zone in every frame of one recording, for the playback
    page (pipeline.playback_sheet). Cached on first request."""
    session, results = played(session_id, "there is nothing to play back")
    with refused():
        return pipeline.playback_sheet(session["data_dir"], session["out_dir"], recording, zone_id, results)


@router.get("/api/session/{session_id}/outline/{recording}/{zone_id}")
def analysis_outlines(session_id: str, recording: int, zone_id: int):
    """What the score sees of each mite of one zone in one recording: the dots
    the result pages draw round the mites. Cached on first request."""
    session, results = played(session_id, "the outlines cannot be drawn")
    with refused():
        return pipeline.analysis_outlines(session["data_dir"], session["out_dir"], recording, zone_id, results)
