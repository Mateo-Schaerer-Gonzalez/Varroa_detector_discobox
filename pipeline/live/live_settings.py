"""The settings of a live test run (settings.txt, classes/live/settings.py) and
what the live page offers before a run: the cameras, serial ports, settings
with their ranges, and a run name not taken yet.
"""

from datetime import date

from classes.live import camera as live_camera
from classes.live.lights import serial_ports
from classes.live.settings import RANGES as SETTING_RANGES, Settings
from classes.scoring.motion_analysis import MotionAnalysis
from classes.plate.zone_layout import ZoneLayout
from pipeline import paths
from pipeline.live import live_runs


LIVE_SETTINGS_FILE = paths.APP_DIR / "settings.txt"


def _setting_ranges():
    return {name: {"label": label, "unit": unit, "min": low, "max": high}
            for name, (label, unit, low, high) in SETTING_RANGES.items()}


def live_options(settings_path=LIVE_SETTINGS_FILE, recordings_root=paths.RECORDINGS_ROOT):
    """What the live page offers before a run: the cameras (or why there are none),
    the serial ports, the saved test-run settings with their ranges, and a run
    name not taken yet."""
    cameras, camera_error = [], None
    try:
        cameras = live_camera.list_cameras()
    except live_camera.CameraError as error:
        camera_error = str(error)
    return {
        "cameras": cameras,
        "camera_error": camera_error,
        "serial_ports": serial_ports(),
        "settings": Settings.from_file(settings_path).as_dict(),
        "plan": Settings.from_file(settings_path).plan(),
        "ranges": _setting_ranges(),
        "run_name": default_run_name(recordings_root),
        "recordings_root": str(recordings_root),
        "open": [live_runs.live_status(live_id) for live_id in list(live_runs.open_runs)],
    }


def print_cameras():
    """Print every camera Vimba X sees, as the Discobox app's --list does."""
    live_camera.print_cameras()


def default_run_name(recordings_root=paths.RECORDINGS_ROOT):
    """test_run_<today>, as the Discobox app names a run, with a number added if
    that name is taken."""
    return paths.free_name(f"test_run_{date.today():%Y-%m-%d}", recordings_root, "_")


def save_live_settings(values, live_id=None, settings_path=LIVE_SETTINGS_FILE):
    """Change the saved test-run settings (only the names in `values`), checked
    against their ranges; with an open live run not started yet, it uses them
    too."""
    settings = Settings.from_dict({**Settings.from_file(settings_path).as_dict(), **values})
    run = live_runs.open_runs.get(live_id) if live_id else None
    if run is not None and run.session.state != "ready":
        raise ValueError("The settings cannot change while the test run is going on.")
    settings.save(settings_path)
    if run is not None:
        run.source.settings = settings
        if settings.zones_per_plate != run.layout.zones_per_plate:
            _set_live_layout(run, ZoneLayout(settings.zones_per_plate))
    return settings.as_dict()


def live_plan(settings):
    """Settings.plan() of `settings` (name -> value): how long each recording and
    the whole test run take."""
    return Settings.from_dict(settings).plan()


def _set_live_layout(run, layout):
    """Cut the plates of a live run not started yet into other zones: nothing is
    analysed yet, so its analysis starts again on them."""
    with run.session.lock:
        run.layout = layout
        layout.save(run.run_dir)
        run.analysis = run.session.analysis = MotionAnalysis(live_runs.live_zone_manager(run))
    paths.clear_clips(run.out_dir)
