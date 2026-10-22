"""The calibration pages: opening a recording or a saved dataset, its clips, the
ground truth and the poke test, the report, and saving a new movement score."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import pipeline
from web.http_helpers import answer, as_it_is, new_id, refused
from web.page_sessions import get_session, new_calibration_session, sessions, truth_lock
from web.routes.analysis import OpenRequest

router = APIRouter()


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


@router.post("/api/calibration")
def open_calibration(request: OpenRequest):
    """Detect the mites of a calibration recording. A folder outside recordings/
    is copied there first, its frames shrunk (pipeline.calibration_folder)."""
    with refused():
        data_dir = pipeline.calibration_folder(request.data_dir)
    return new_calibration_session(data_dir, lambda out_dir: pipeline.open_calibration(data_dir, out_dir))


@router.get("/api/calibration/datasets")
def list_datasets():
    """The recordings with ground truth saved, one dataset each."""
    return {"datasets": pipeline.list_calibration_datasets()}


@router.post("/api/calibration/datasets/{dataset_id}/open")
def open_dataset(dataset_id: str):
    """Reopen a recording with ground truth to go on labelling it."""
    with refused():
        data_dir = pipeline.dataset_folder(dataset_id)
    return new_calibration_session(data_dir, lambda out_dir: pipeline.open_saved_calibration(dataset_id, out_dir))


@router.get("/api/calibration/datasets/{dataset_id}/preview")
def dataset_preview(dataset_id: str):
    """The first frame of a saved dataset, for the error map of a pooled report."""
    with refused(404):
        return FileResponse(pipeline.dataset_preview(dataset_id))


@router.get("/api/calibration/metrics")
def movement_scores():
    """The movement scores a calibration can try, with their parameters."""
    return pipeline.movement_scores()


@router.delete("/api/calibration/datasets/{dataset_id}")
def delete_dataset(dataset_id: str):
    with refused():
        return {"deleted": pipeline.delete_calibration_dataset(dataset_id)}


@router.post("/api/calibration/pooled")
def open_pooled():
    """A session for reports on saved datasets alone, with no recording opened."""
    session_id = new_id()
    out_dir = pipeline.new_pooled_report_dir()
    sessions[session_id] = {"data_dir": None, "out_dir": out_dir, "report_dir": out_dir, "dataset_id": None}
    return {"session_id": session_id}


@router.post("/api/calibration/{session_id}/dataset/{dataset_id}")
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


@router.post("/api/calibration/{session_id}/grow")
def grow_calibration(session_id: str):
    """A calibration session on a live run's recordings, with those analysed since
    it was opened or last grown (pipeline.grow_live_calibration)."""
    session = get_session(session_id)
    if not session.get("live_id"):
        raise HTTPException(status_code=400, detail="This calibration is not of a live run.")
    return as_it_is({"session_id": session_id,
                     **answer(pipeline.grow_live_calibration, session["out_dir"], session["live_id"])})


@router.get("/api/calibration/{session_id}/clip/{recording}/{zone_id}")
def calibration_clip(session_id: str, recording: int, zone_id: int):
    """Frames of one zone during one recording, cropped and cached on first request."""
    session = get_session(session_id)
    with refused():
        return pipeline.calibration_clip(session["out_dir"], recording, zone_id)


@router.get("/api/calibration/{session_id}/mite-clip/{recording}/{mite}")
def calibration_mite_clip(session_id: str, recording: int, mite: str):
    """Frames of one mite during one recording, cut close around it, with a picture
    of where its pixels change; cached on first request."""
    session = get_session(session_id)
    with refused():
        return pipeline.calibration_mite_clip(session["out_dir"], recording, mite)


@router.get("/api/calibration/{session_id}/plate-clip/{dataset_id}/{recording}")
def dataset_clip(session_id: str, dataset_id: str, recording: int):
    """Frames of the whole plate during one recording of a saved dataset, for the
    test report; kept with this session's files."""
    session = get_session(session_id)
    with refused():
        return pipeline.dataset_clip(session["out_dir"], dataset_id, recording)


@router.get("/api/calibration/{session_id}/truth")
def get_ground_truth(session_id: str):
    """The ground truth of this session's mites as saved now, which another window
    may have changed, with the changes not saved yet on top (pipeline.truth_view)."""
    session = get_session(session_id)
    with refused():
        return as_it_is(pipeline.truth_view(session["out_dir"]))


@router.post("/api/calibration/{session_id}/truth/edit")
def edit_ground_truth(session_id: str, request: TruthEdit):
    """A change on the ground-truth page; the page saves it next (save_ground_truth)."""
    session = get_session(session_id)
    with refused():
        return as_it_is(pipeline.edit_truth(session["out_dir"], request.action, mite=request.mite, zone=request.zone,
                                            recording=request.recording, backwards=request.backwards, kind=request.kind,
                                            state=request.state))


@router.post("/api/calibration/{session_id}/truth")
def save_ground_truth(session_id: str):
    """Save the changes made on the ground-truth page next to the recordings, so
    they survive a restart. Everything else keeps what is saved."""
    session = get_session(session_id)
    with truth_lock, refused():
        return as_it_is(pipeline.save_truth(session["out_dir"]))


@router.get("/api/calibration/{session_id}/poke")
def get_poke_test(session_id: str):
    """The poke test of this session's mites, round by round (pipeline.poke_view)."""
    session = get_session(session_id)
    with refused():
        return as_it_is(pipeline.poke_view(session["out_dir"]))


@router.post("/api/calibration/{session_id}/poke")
def edit_poke_test(session_id: str, request: PokeEdit):
    """A change on the poke-test page, saved at once next to the recordings."""
    session = get_session(session_id)
    with truth_lock, refused():
        return as_it_is(pipeline.edit_poke(session["out_dir"], request.action, request.after, mite=request.mite,
                                           zone=request.zone, state=request.state))


@router.post("/api/calibration/{session_id}/evaluate")
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


@router.post("/api/threshold")
def save_threshold(request: ThresholdRequest):
    """Make a new movement threshold the default for every later analysis."""
    with refused():
        return {"threshold": pipeline.save_threshold(request.value)}


@router.post("/api/movement-score")
def save_movement_score(request: MovementScoreRequest):
    """Make a metric, its parameters and its threshold the default for every later analysis."""
    with refused():
        return pipeline.save_movement_score(request.metric, request.params, request.threshold, request.stabilize,
                                            request.normalize_brightness, request.normalize_floor,
                                            review_band=request.review_band)
