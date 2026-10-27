"""HTTP layer: turns requests into pipeline calls and results into JSON, and
serves the page (web/static/, the front end).

Deliberately contains no analysis logic. It may import `pipeline` and nothing else
from the project -- no cv2, pandas, matplotlib, numpy or classes.* -- which
`unit_tests/test_layering.py` enforces.

This module puts the app together; the routes are in web/routes/, one module per
part of the page:

    routes/recordings.py    the recordings kept, and folders dropped into the page
    routes/analysis.py      a folder opened for analysis: labels, run, corrections; session files
    routes/playback.py      what the result pages play: clips, playback sheets, outlines
    routes/calibration.py   the calibration pages: ground truth, poke test, report
    routes/live.py          the live pages: camera, settings, run, adding mites, feed
    page_watch.py           stopping the server when the last page closes
    page_sessions.py        the pages' sessions, and what several routes ask of them
    http_helpers.py         pipeline's refusals as HTTP errors, large replies, safe paths

Run it with start.bat, or:  python -m uvicorn web.server:app --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

import pipeline
from web import page_watch
from web.routes import analysis, calibration, live, playback, recordings

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app):
    pipeline.remove_empty_pooled_reports()
    page_watch.start()
    yield
    # Ctrl+C on the server: a live run stops cleanly and writes its results.
    pipeline.close_all_live()


app = FastAPI(title="Varroa discobox", lifespan=lifespan)
for routes in (analysis, recordings, playback, calibration, live, page_watch):
    app.include_router(routes.router)


APP_DIR = Path(__file__).resolve().parent.parent


@app.get("/api/version", response_class=PlainTextResponse)
def version():
    """Folder, commit and whether a live run is going, one per line. start.sh
    restarts the server to load the new version, unless a live run is going."""
    return f"{APP_DIR}\n{pipeline.COMMIT}\n{int(pipeline.live_running())}\n"


class FreshStaticFiles(StaticFiles):
    """The page and its scripts, which the browser must check for a newer version
    on every load: a cached script next to an updated server breaks the page."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", FreshStaticFiles(directory=STATIC_DIR, html=True), name="static")
