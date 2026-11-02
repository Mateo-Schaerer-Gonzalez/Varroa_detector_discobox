"""The Zones page: the zone masks (where the plates and their label areas are on
the picture), drawn by hand on the first frame of a recording or on an image
the page reads itself, and the masks kept."""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

import pipeline
from web.http_helpers import answer, refused

router = APIRouter()


class MaskZone(BaseModel):
    type: str  # "mite" or "text"
    x1: float
    y1: float
    x2: float
    y2: float


class ZonesOfMask(BaseModel):
    zones: list[MaskZone]


@router.get("/api/masks")
def list_masks():
    return {"masks": pipeline.list_masks()}


@router.post("/api/masks/numbers")
def number_mask(request: ZonesOfMask):
    """How the analysis will number the zones drawn: each plate's id, and the
    label area its name is read from."""
    return answer(pipeline.number_mask, [zone.model_dump() for zone in request.zones])


@router.get("/api/masks/picture/{recording}")
def recording_picture(recording: str):
    """The first frame of a recording kept in recordings/, to draw a mask on."""
    with refused(404):
        data = pipeline.recording_picture(recording)
    return Response(content=data, media_type="image/jpeg")


@router.get("/api/masks/{name}")
def read_mask(name: str):
    with refused(404):
        return pipeline.read_mask(name)


@router.put("/api/masks/{name}")
def save_mask(name: str, request: ZonesOfMask):
    return answer(pipeline.save_mask, name, [zone.model_dump() for zone in request.zones])


@router.delete("/api/masks/{name}")
def delete_mask(name: str):
    return answer(pipeline.delete_mask, name)
