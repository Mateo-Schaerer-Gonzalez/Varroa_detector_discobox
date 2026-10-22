"""The live runs open, by id, and what every part of a live run shares.

A live run is a Discobox test run: the camera streams all the time for the live
feed, and every `recording_timeout` minutes the fan and LEDs come on and a burst
of frames is recorded. Each burst is analysed as soon as it is complete, by the
same core as a folder (MotionAnalysis), and its results are described by the
same scoring.arrange() and run_results.describe_results() as a folder's, so the
live pages are the folder pages, filling in. The bursts are saved, as the
Discobox app saves them, to recordings/<run name>/, which is then a folder like
any other: folder mode reads it back and gets exactly the same results. Its
results go to results/<run name>/.

The plate labels and "not a mite" marks of a run live in its folder, as for any
folder, so the label page works on a live run unchanged. So does run.json: how
the run was made (the camera, frames dropped), kept up to date after every
recording.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from classes.live import camera as live_camera
from classes.live.progress import RunProgress
from pipeline import plate_zones

_logger = logging.getLogger(__name__)


CameraError = live_camera.CameraError  # the camera or Vimba X cannot be used


class LiveRunNotOpen(ValueError):
    """No live run is open by that id: closed, or the server restarted since."""


LIVE_STATES = ("running", "paused", "stopping")
LEDS = ("led1", "led2")
# Seconds for the camera's automatic exposure to follow the LEDs coming on.
LIGHTS_SETTLE = 1.5


@dataclass(eq=False)
class LiveRun:
    """One open live run: what its parts share. live_setup.open_live() makes it."""
    live_id: str
    source: "CameraSource"            # the camera's frames and the test run's schedule (classes/live/sources.py)
    lights: "Lights"                  # the fan and LEDs (classes/live/lights.py)
    run_dir: Path                     # recordings/<run name>/, where its recordings go; renamed with the run
    out_dir: Path                     # where its results go
    results_root: Optional[Path]      # results/ when out_dir is results/<run name>/ and follows a rename
    new_results: bool                 # out_dir was made for this run, so a rename moves it
    save_frames: bool                 # its recordings are saved (the mites' ROIs); else only analysed
    coords_file: Optional[str]        # its zones, when not those of `layout`
    layout: "ZoneLayout"              # one zone per plate or two
    analysis: "MotionAnalysis" = None  # the analysis core it feeds, set right after
    session: "LiveSession" = None     # capture and analysis in their threads, set right after
    feed: tuple = (None, None)        # ((frame count, width), JPEG) of the live feed last encoded
    feed_lock: threading.Lock = field(default_factory=threading.Lock)
    started_at: Optional[str] = None  # when start_live() started it
    preview_written: bool = False     # its first frame is in out_dir as the preview
    files_due: Optional[float] = None  # when its workbook and figures are written next (time.monotonic())
    zones: list = field(default_factory=list)  # the zones' progress (ZoneProgress.zones())
    stop_reason: Optional[str] = None  # why it stopped by itself, if it did
    finding: threading.Lock = field(default_factory=threading.Lock)  # held while mites to add are looked for
    found_frame: object = None        # the lit frame the mites to add were last found on (add_mites.py)


open_runs = {}  # live id -> its LiveRun
open_runs_lock = threading.Lock()


def live_zone_manager(run):
    return plate_zones.build_zone_manager(run.coords_file or run.layout.coords_file)


def get_live(live_id):
    run = open_runs.get(live_id)
    if run is None:
        raise LiveRunNotOpen("This live run is not open any more.")
    return run


def leds_on(lights, settings):
    """Switch both LEDs on, one that is off at its set intensity, and keep them
    on until the run starts (Lights.keep_on()): they are told again even when
    believed on, as the controller may have missed it. True if either was off.
    A failure is only logged: the camera works without its light."""
    if not lights.connected:
        return False
    off = [device for device in LEDS if not lights.on[device]]
    try:
        lights.keep_on({device: getattr(settings, device) if device in off else lights.level[device] for device in LEDS})
    except Exception:
        _logger.exception("Could not switch the LEDs on")
        return False
    return bool(off)


def light_for_labelling(run):
    """The mites can only be found on a lit plate: before the run starts, switch
    on any LED that is off, and give the camera's exposure time to follow."""
    if run.session.state == "ready" and leds_on(run.lights, run.source.settings):
        time.sleep(LIGHTS_SETTLE)


def live_frames(run):
    """What a live run saves of its recordings (see scoring.run_view()): the mites' ROIs, or nothing."""
    return "rois" if run.save_frames else "none"


def live_status(live_id):
    run = get_live(live_id)
    status = {
        **run.session.status(),
        "live_id": live_id,
        "run_name": run.run_dir.name,
        "run_dir": str(run.run_dir),
        "out_dir": str(run.out_dir),
        "save_frames": run.save_frames,
        "zones_per_plate": run.layout.zones_per_plate,
        "stop_reason": run.stop_reason,  # why the run stopped by itself, if it did
        "pending_mites": len(run.analysis._pending),  # mites to add when the next recording begins
    }
    # the zones' circles over the live result pages
    return {**status, "progress": RunProgress(status, run.zones).describe()}


def live_results(live_id):
    """The results published last (None before the first recording is
    analysed), and their version, which changes with every update."""
    run = get_live(live_id)
    return {"version": run.session.version, "results": run.session.results}


def live_running():
    """Whether a live run is recording, paused or finishing."""
    return any(run.session.state in LIVE_STATES for run in list(open_runs.values()))
