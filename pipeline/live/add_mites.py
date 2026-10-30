"""Mites added during a live run: the plates are lit between two recordings,
the mites not followed yet detected (and any the detector missed placed by
hand), and those the user keeps followed from the next recording on.
"""

import logging
import time
from pathlib import Path

from classes.storage.files import write_jpeg
from classes.live.lights import DEVICES
from classes.live.progress import RunProgress
from classes.scoring.motion_analysis import DETECTION_LOCK
from classes.plate import hand_mites as hand, positions
from classes.plate.rect import Rect
from classes.plate.zones import mite_ids
from pipeline import hand_mites, paths, plate_labels, plate_zones, preview_images
from pipeline.live import live_runs

_logger = logging.getLogger(__name__)


# The same when lighting the plates to find mites to add (_lit_frame()): between
# recordings the camera has been in the dark, its exposure at its longest, and it
# takes longer to come down than LIGHTS_SETTLE.
FIND_MITES_SETTLE = 10
# Seconds to spare before the next recording's cycle starts, for lighting the
# plates to find mites to add (live_find_mites()): FIND_MITES_SETTLE and the
# wait for a frame after it.
FIND_MITES_SPARE = 20
# Pixels round a mite already followed in which a blob found is that mite.
FOUND_MITE_REACH = 4
ADD_PREVIEW_NAME = "add_mites.jpg"


def live_find_mites(live_id):
    """Light the plates during a run, between two recordings, and detect the
    mites on the camera's frame that are not followed yet, to add some
    (live_add_mites()). The run is held meanwhile: a recording due waits for
    the LEDs to go off again. The frame is written to the results folder as
    ADD_PREVIEW_NAME. Returns what the label page shows, as live_preview() does:
    {preview, image, zones, mites}, the zones with their labels and the number
    of mites `followed` in each (those to add with the next recording
    included), and the mites found [{id, zone_id, x, y, r, x1, y1, x2, y2,
    rejected}], each numbered after the mites of its zone."""
    run = _adding_to(live_id)
    if not run.finding.acquire(blocking=False):
        raise ValueError("Mites are being looked for already.")
    try:
        status = run.source.status()
        if status["recording_name"]:
            raise ValueError("A recording is being captured: try again once it is over.")
        next_seconds = RunProgress(status).next_seconds(status.get("timeline"))
        lit = (any(light["on"] for device, light in status["lights"].items() if device in DEVICES)
               if status["lights"].get("connected") else False)
        if lit or (next_seconds is not None and next_seconds < run.source.settings.cycle_seconds + FIND_MITES_SPARE):
            raise ValueError("The next recording is about to start: try again once it is over.")
        held = run.source.state == "running"
        if held:
            run.session.pause()
        try:
            image = _lit_frame(run)
        finally:
            if held:
                run.session.resume()
        found = _new_mites(run, image)
        zones = _add_zones(run, found)
        run.found_frame = image
    finally:
        run.finding.release()
    write_jpeg(Path(run.out_dir) / ADD_PREVIEW_NAME, image)
    return {"preview": ADD_PREVIEW_NAME, "image": preview_images.image_size(image), "zones": zones, "mites": found}


def _adding_to(live_id):
    """The live run `live_id`, refused unless mites can be added to it now."""
    run = live_runs.get_live(live_id)
    if run.session.state not in ("running", "paused"):
        raise ValueError("Mites can be added while the test run is going on.")
    if not run.analysis.started:
        raise ValueError("Mites can be added once the first recording has begun.")
    return run


def _add_zones(run, found):
    """The zones as the label page shows them while mites are added: their labels,
    whether they are a negative control, the mites `followed` in each (or to be
    added with the next recording), and `n_mites`, those and the ones `found`.
    Each mite found gets the id it would have, numbered after its zone's."""
    analysis = run.analysis
    with run.session.lock:
        zones = plate_zones.describe_zones(analysis.zone_manager, plate_labels.load_labels(run.run_dir))
        followed = {zone.id: len(zone.mites) for zone in analysis.zone_manager.zones if zone.id is not None}
        for box in analysis._pending:
            zone = analysis.zone_manager.zone_of(box)
            if zone is not None:
                followed[zone.id] += 1
    controls = set(plate_labels.load_controls(run.run_dir))
    numbered = dict(followed)
    # the ids they will have (MotionAnalysis._add_all())
    boxes = [Rect(mite["x1"], mite["y1"], mite["x2"], mite["y2"], found=mite) for mite in found]
    for zone_id in dict.fromkeys(mite["zone_id"] for mite in found):
        here = [box for box in boxes if box.found["zone_id"] == zone_id]
        for box, text in mite_ids(here, zone_id, numbered[zone_id]):
            box.found["id"] = text
        numbered[zone_id] += len(here)
    for zone in zones:
        zone["control"] = zone["id"] in controls
        zone["followed"] = followed.get(zone["id"], 0)
        zone["n_mites"] = numbered.get(zone["id"], 0)
    return zones


def _lit_frame(run):
    """A frame of the plates with both LEDs on, which are switched off again after."""
    lights, settings = run.lights, run.source.settings
    count, _image = run.source.latest.get()
    try:
        if lights.connected:
            for device in live_runs.LEDS:
                lights.switch(device, True, getattr(settings, device))
            time.sleep(FIND_MITES_SETTLE)
            count, _image = run.source.latest.get()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:  # a frame taken with the LEDs on
            newer, image = run.source.latest.get()
            if newer > count and image is not None:
                return image
            time.sleep(0.05)
        raise ValueError("No frame came from the camera.")
    finally:
        if lights.connected:
            for device in live_runs.LEDS:
                lights.switch_off(device)


def live_hand_mite(live_id, x, y, mites, remove=False):
    """Place a mite by hand at (x, y) among the mites live_find_mites() found
    to add (`mites`, as it gave them), on the frame they were found on
    (hand_mites.where()); or with `remove` take out the one placed there.
    Returns {zones, mites} as live_find_mites() does, numbered again."""
    run = _adding_to(live_id)
    image = run.found_frame
    if image is None:
        raise ValueError("Look for mites to add first.")
    found = [dict(mite) for mite in mites]
    if remove:
        nearest = positions.nearest([mite for mite in found if mite.get("by_hand")], float(x), float(y))
        if nearest is None:
            raise ValueError("No mite was placed by hand there.")
        found.remove(nearest)
    else:
        analysis = run.analysis
        with run.session.lock:
            others = [((x1 + x2) / 2, (y1 + y2) / 2) for x1, y1, x2, y2 in _known(analysis)]
            point = hand_mites.where(analysis.zone_manager, image, x, y,
                                     others + [(mite["x"], mite["y"]) for mite in found])
            box = hand.box_at(point["x"], point["y"], point["size"])
            zone = analysis.zone_manager.zone_of(box)
        found.append({"id": "", "zone_id": zone.id, "x": point["x"], "y": point["y"], "r": point["size"] / 2,
                      "by_hand": True, "x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3], "rejected": False})
    return {"zones": _add_zones(run, found), "mites": found}


def _known(analysis):
    """The boxes of the mites followed, where last placed, and of those to be added."""
    last = analysis.placed[-1] if analysis.placed else {}
    return [last.get(mite, tuple(mite)) for mite in analysis.mites] + list(analysis._pending)


def _new_mites(run, image):
    """The mites the detector finds on `image` that are not followed already:
    none within FOUND_MITE_REACH of where a mite was last placed, or is to be
    added; only in a zone."""
    analysis = run.analysis
    with run.session.lock:
        known = _known(analysis)
        masked = analysis.zone_manager.mask_image_to_valid_rois(image)
    with DETECTION_LOCK:  # a Mite counts the ids on
        detected = analysis.analyzer.detect(masked)
    found = []
    for mite in detected:
        x, y = mite.home
        if any(x1 - FOUND_MITE_REACH <= x <= x2 + FOUND_MITE_REACH and y1 - FOUND_MITE_REACH <= y <= y2 + FOUND_MITE_REACH
               for x1, y1, x2, y2 in known):
            continue
        zone = analysis.zone_manager.zone_of(mite)
        if zone is not None:
            found.append(plate_zones.mite_view(mite, zone.id, x1=mite.x1, y1=mite.y1, x2=mite.x2, y2=mite.y2, rejected=False))
    return found


def live_add_mites(live_id, boxes):
    """Follow the mites of `boxes` ([x1, y1, x2, y2] each, as live_find_mites()
    found them) from the next recording on, numbered after those of their zone.
    The frame they were found on is kept with the run's recordings
    (ADDED_FRAMES_DIRNAME), so the calibration pages show the plate with them
    from that recording on (preview_images.added_previews())."""
    run = _adding_to(live_id)
    checked = []
    for box in boxes:
        if len(box) != 4:
            raise ValueError("A mite is given as [x1, y1, x2, y2].")
        checked.append(tuple(int(value) for value in box))
    with run.session.lock:
        run.analysis.add_mites(checked)
        start = len(run.analysis.placed)  # the recording they are added in: the next to begin
    if checked and run.save_frames and run.found_frame is not None:
        try:  # several additions before one recording: the last frame shows them all
            (run.run_dir / paths.ADDED_FRAMES_DIRNAME).mkdir(parents=True, exist_ok=True)
            write_jpeg(run.run_dir / paths.ADDED_FRAMES_DIRNAME / f"from_{start}.jpg", run.found_frame, quality=90)
        except Exception:
            _logger.exception("Could not keep the frame the mites were added on")
    return live_runs.live_status(live_id)
