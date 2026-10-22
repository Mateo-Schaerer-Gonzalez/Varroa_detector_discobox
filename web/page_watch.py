"""Stopping the server when the last page closes.

start.bat and start.sh set DISCOBOX_AUTO_STOP=1, so the server does not keep
running (with old code) after the last browser tab is closed. A server started
by hand keeps running. Every open page checks in (its routes are here).
"""

import os
import threading
import time

from fastapi import APIRouter

import pipeline

router = APIRouter()

AUTO_STOP = os.environ.get("DISCOBOX_AUTO_STOP") == "1"
# Browsers let a hidden tab run its timers only about once a minute, so a page
# that has not checked in for this long is taken to be gone.
PAGE_TIMEOUT = 150
# After the last page closes, time for a reload to check in again.
CLOSE_GRACE = 10

pages: dict[str, float] = {}  # page id -> when it last checked in
last_activity = time.monotonic()
any_page_seen = False


def start():
    """Watch the pages in a background thread, if the server is to stop by itself."""
    if AUTO_STOP:
        threading.Thread(target=watch_pages, daemon=True).start()


def watch_pages():
    """Stop the process once no page is open. Runs in a background thread."""
    global last_activity
    previous = time.monotonic()
    while True:
        time.sleep(2)
        now = time.monotonic()
        if now - previous > 30:
            # The computer slept: the pages did not go away, they just could not check in.
            for page in list(pages):
                pages[page] = now
            last_activity = now
        previous = now

        for page, seen in list(pages.items()):
            if now - seen > PAGE_TIMEOUT:
                pages.pop(page, None)
        # A live test run goes on with no page open; the server waits for its end.
        if pipeline.live_running():
            last_activity = now
            continue
        # Before the first page loads, allow time for the browser to start.
        grace = CLOSE_GRACE if any_page_seen else PAGE_TIMEOUT
        if not pages and now - last_activity > grace:
            print("No page open any more - stopping the server.", flush=True)
            pipeline.close_all_live()  # release the camera, switch the fan and LEDs off
            os._exit(0)


@router.post("/api/page/{page_id}/alive")
def page_alive(page_id: str):
    """An open page checking in, so the server knows to keep running."""
    global last_activity, any_page_seen
    pages[page_id] = last_activity = time.monotonic()
    any_page_seen = True
    return {}


@router.post("/api/page/{page_id}/closed")
def page_closed(page_id: str):
    """A page being closed or reloaded."""
    global last_activity
    pages.pop(page_id, None)
    last_activity = time.monotonic()
    return {}
