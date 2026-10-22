"""What every route shares: what pipeline refuses answered as HTTP errors, large
replies sent as they are, and paths from the browser checked."""

import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse

import pipeline


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
