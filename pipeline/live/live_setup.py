"""Opening a live run: the camera, the fan and LEDs, naming the run, labelling
the plates on the live feed, checking the lights; and closing it after.
"""

import re
import shutil
from pathlib import Path

import cv2

from classes.analyzer import Analyzer
from classes.live import camera as live_camera
from classes.live.lights import DEVICES, open_lights
from classes.live.session import LiveSession
from classes.live.settings import Settings
from classes.live.sources import CameraSource
from classes.motion_analysis import MotionAnalysis, detect_mites
from classes.roi_recordings import open_recordings
from classes.zone_layout import ZoneLayout
from pipeline import folder_analysis, output_files, paths, plate_labels, preview_images
from pipeline.live import live_capture, live_runs, live_settings


LIVE_FEED_WIDTH = 960


def _run_dir_for(run_name, recordings_root):
    """The folder of a test run called `run_name`, a name no recording has yet."""
    run_name = (run_name or "").strip()
    if not run_name:
        raise ValueError("Enter a name for the test run.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", run_name) or run_name.endswith("."):
        raise ValueError("A test run name may only hold letters, digits, spaces, dots, dashes and underscores.")
    run_dir = Path(recordings_root) / run_name
    if run_dir.exists():
        raise ValueError(f"A recording called {run_name} already exists in {recordings_root}.")
    return run_dir


def open_live(live_id, out_dir, run_name, camera_id=None, serial_port="auto", save_frames=True,
              settings_path=live_settings.LIVE_SETTINGS_FILE, settings=None, recordings_root=paths.RECORDINGS_ROOT,
              results_root=paths.RESULTS_ROOT, coords_file=None):
    """Open the camera, with the fan and LEDs, for a live run called `run_name`,
    whose recordings go to recordings_root/run_name and whose results go to
    `out_dir` (by default results_root/run_name). The live feed starts, with
    both LEDs on so the plates can be seen; nothing is recorded until
    start_live(), which switches them off and leaves them to the test run. Until
    then the run's name and whether it is saved can still change
    (set_live_options()), and so can its settings (save_live_settings()).
    Only one live run can be open: opening another closes the one that is open,
    unless that one is running.

    The test run's settings are those saved in `settings_path`, with `settings`
    (name -> value, e.g. {"death_minutes": 240}) overriding them for this run only. Its
    zones per plate are among them."""
    with live_runs.open_runs_lock:
        _close_all_but_running()
        settings = Settings.from_dict({**Settings.from_file(settings_path).as_dict(), **(settings or {})})
        source, lights, run_dir = _open_camera(camera_id, serial_port, settings, run_name, recordings_root)
        # Without its LEDs the Discobox is dark: both stay on, for the camera's
        # image and for labelling, until the run starts and switches them itself.
        live_runs.leds_on(lights, settings)

        # Results in results/<run name>/ follow the run when it is renamed.
        own_results = out_dir is None
        out_dir = paths.results_dir(run_dir, results_root) if own_results else Path(out_dir)
        new_results = not out_dir.exists()
        paths.clear_clips(out_dir)
        layout = ZoneLayout(settings.zones_per_plate)
        # With the run's folder from the start: its plate labels go by the layout.
        layout.save(run_dir)
        run = live_runs.LiveRun(live_id=live_id, source=source, lights=lights, run_dir=run_dir, out_dir=out_dir,
                                results_root=Path(results_root) if own_results else None, new_results=new_results,
                                save_frames=bool(save_frames), coords_file=coords_file, layout=layout)
        run.analysis = MotionAnalysis(live_runs.live_zone_manager(run))
        run.session = LiveSession(source, run.analysis,
                                  publish=lambda session, write: live_capture.publish_live(run, write),
                                  on_finish=lambda session: live_capture.live_run_ended(run))
        live_runs.open_runs[live_id] = run
    return live_runs.live_status(live_id)


def _close_all_but_running():
    """Close every live run open, refused while one is going on: only one can be
    open. Called holding live_runs.open_runs_lock."""
    for other_id, other in list(live_runs.open_runs.items()):
        if other.session.state in live_runs.LIVE_STATES:
            raise ValueError(f"The test run {other.run_dir.name} is still going on; stop it first.")
        _close_live(other_id)


def _open_camera(camera_id, serial_port, settings, run_name, recordings_root):
    """(source, lights, run_dir): the camera streaming (a CameraSource), the fan
    and LEDs, and the new folder of the run called `run_name`. On a failure,
    the lights are closed and the folder removed again."""
    camera_id = live_camera.choose_camera(camera_id)
    lights = open_lights(serial_port)
    source = CameraSource(camera_id, settings, lights)
    run_dir = None
    try:
        run_dir = _run_dir_for(run_name, recordings_root)
        run_dir.mkdir(parents=True)
        source.open()
    except Exception:
        lights.close()
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
        raise
    return source, lights, run_dir


def set_live_options(live_id, run_name=None, save_frames=None):
    """Change what open_live() was told of a live run not started yet: its name
    (its folder in recordings/ takes it, with the plate labels and marks already
    in it, and so does its results folder unless one was given) and whether its
    recordings are saved. What is None stays as it is."""
    with live_runs.open_runs_lock:
        run = live_runs.get_live(live_id)
        if run.session.state != "ready":
            raise ValueError("The test run has started: its name and whether it is saved can no longer change.")
        if run_name is not None and run_name.strip() != run.run_dir.name:
            _rename_live(run, run_name)
        if save_frames is not None:
            run.save_frames = bool(save_frames)
    return live_runs.live_status(live_id)


def _rename_live(run, run_name):
    run_dir = _run_dir_for(run_name, run.run_dir.parent)
    with run.session.lock:
        run.run_dir.rename(run_dir)
        run.run_dir = run_dir
        if run.results_root is None:
            return
        old, run.out_dir = run.out_dir, paths.results_dir(run_dir, run.results_root)
        made, run.new_results = run.new_results, not run.out_dir.exists()
        paths.clear_clips(run.out_dir)
        if old.is_dir():
            # the picture the label page shows, and what was read from it
            shutil.copytree(old, run.out_dir, dirs_exist_ok=True)
            if made:  # results of an earlier recording of the old name are not this run's to remove
                shutil.rmtree(old, ignore_errors=True)


def live_preview(live_id, out_dir=None):
    """Detect the mites on a frame so the plates can be labelled, as
    open_session() does for a folder: on the newest frame before the run, and on
    the frame the run's results come from once it has one."""
    run = live_runs.get_live(live_id)
    with run.session.lock:
        frame = run.analysis.first_frame
    if frame is None:
        live_runs.light_for_labelling(run)
        _count, frame = run.source.latest.get()
        if frame is None:
            raise ValueError("No frame has come from the camera yet.")
    out_dir = Path(out_dir or run.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    preview_images.write_preview(frame, out_dir)
    zone_manager = live_runs.live_zone_manager(run)
    detect_mites(zone_manager, frame, Analyzer())
    return folder_analysis.session_view(zone_manager, frame, run.run_dir, run.source.completed)


def live_read_labels(live_id, out_dir, mites):
    """read_labels() for a live run: the names on the picture live_preview() made."""
    run = live_runs.get_live(live_id)
    return plate_labels.read_zone_labels(live_runs.live_zone_manager(run), run.run_dir, out_dir or run.out_dir, mites)


def set_live_light(live_id, device, on=None, level=None):
    """Switch the fan on or off, or set the intensity of the fan or of an LED,
    to check the settings before the run. Both LEDs stay on until it starts."""
    run = live_runs.get_live(live_id)
    if device not in DEVICES:
        raise ValueError(f"Unknown device {device!r}; it is one of {', '.join(DEVICES)}.")
    if run.session.state != "ready":
        raise ValueError("The fan and LEDs are the test run's to switch while it is going on.")
    if device in live_runs.LEDS and on is False:
        raise ValueError("Both LEDs stay on until the test run starts.")
    if on is None:
        run.lights.set_level(device, level)
    elif on:
        run.lights.switch(device, True, level)
    else:
        run.lights.switch_off(device)
    return run.lights.state()


def live_frame(live_id, width=LIVE_FEED_WIDTH):
    """The newest frame as JPEG bytes, at most `width` pixels wide (None before
    the first frame). Encoded once per frame and width, whoever asks."""
    run = live_runs.get_live(live_id)
    count, image = run.source.latest.get()
    if image is None:
        return None
    width = max(64, min(int(width), 4096))
    with run.feed_lock:
        key, data = run.feed
        if key == (count, width):
            return data
        if image.shape[1] > width:
            height = round(image.shape[0] * width / image.shape[1])
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        data = encoded.tobytes() if ok else None
        run.feed = ((count, width), data)
        return data


def close_live(live_id):
    """Stop the run if it is going on, release the camera and the fan and LEDs,
    and forget the run. A run folder with nothing recorded in it is removed."""
    with live_runs.open_runs_lock:
        _close_live(live_id)


def _close_live(live_id):
    run = live_runs.open_runs.pop(live_id, None)
    if run is None:
        return
    run.session.stop(wait=True, timeout=60)
    run.source.wait_closed(30)
    run.lights.close()
    if run.run_dir.is_dir() and not open_recordings(run.run_dir).recording_names:
        shutil.rmtree(run.run_dir, ignore_errors=True)


def close_all_live():
    """Stop every live run cleanly and release the camera: on shutdown. The
    files a correction left to write are written first."""
    output_files.finish_files()
    with live_runs.open_runs_lock:
        for live_id in list(live_runs.open_runs):
            _close_live(live_id)
