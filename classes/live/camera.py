"""The Discobox's Allied Vision camera, through vmbpy (the Vimba X SDK).

The camera is found, opened and set up with the Discobox app's own functions
(get_camera, setup_camera, set_feature in classes/discobox/camera_utils.py) and
configured as its show_hide_cam() does: continuous acquisition, triggered at a
fixed rate of `fps` frames per second, automatic exposure. Everything happens
inside `with VmbSystem.get_instance():` and the camera's own context, in a thread
of its own that holds them for as long as the camera is open.

vmbpy calls FrameHandler with every frame. It does as little as it can, since
the frame's buffer goes back to the camera only when it returns: copy the pixels,
put them on a bounded queue, give the buffer back. Whatever reads the queue does
the rest; when it falls behind, frames are dropped and counted, never piled up.
"""

import logging
import queue
import threading
import time

_logger = logging.getLogger(__name__)

BUFFER_COUNT = 10  # frame buffers vmbpy streams into, as in the Discobox app
QUEUE_SIZE = 64    # frames waiting to be read, about two seconds at 30 fps


class CameraError(RuntimeError):
    """The camera, or Vimba X, cannot be used."""


def _vimba():
    """vmbpy and the Discobox camera functions, imported only when a camera is used."""
    try:
        import vmbpy
        from classes.discobox import camera_utils
    except ImportError as error:
        raise CameraError(
            f"vmbpy is not installed ({error}). Install it from the Vimba X SDK, as the Discobox app's "
            "setup-python-env.sh does, to use the camera."
        )
    return vmbpy, camera_utils


def _vimba_errors(vmbpy):
    """Every exception vmbpy raises (it exports no common base class)."""
    return tuple(getattr(vmbpy, name) for name in dir(vmbpy) if name.startswith("Vmb") and (name.endswith("Error") or name == "VmbTimeout"))


def _vimba_failure(error):
    return CameraError(
        f"Vimba X could not start: {error}. Check that Vimba X is installed and GENICAM_GENTL64_PATH "
        "points at its cti folder (run-discobox.sh sets it)."
    )


def list_cameras():
    """Every camera Vimba X sees: id, model, name and serial number."""
    vmbpy, camera_utils = _vimba()
    try:
        with vmbpy.VmbSystem.get_instance():
            return [
                {"id": cam.get_id(), "model": cam.get_model(), "name": cam.get_name(), "serial": cam.get_serial()}
                for cam in camera_utils.get_all_cameras()
            ]
    except _vimba_errors(vmbpy) as error:
        raise _vimba_failure(error)


def print_cameras():
    """Print every camera, as `discobox.py --list` does."""
    vmbpy, camera_utils = _vimba()
    try:
        camera_utils.list_cameras()
    except _vimba_errors(vmbpy) as error:
        raise _vimba_failure(error)


def choose_camera(camera_id=None, cameras=None):
    """The camera to open: `camera_id`, or the only camera there is."""
    if camera_id:
        return camera_id
    cameras = list_cameras() if cameras is None else cameras
    if not cameras:
        raise CameraError("No camera found. Is it switched on and connected?")
    if len(cameras) > 1:
        found = ", ".join(f"{cam['model']} {cam['id']}" for cam in cameras)
        raise CameraError(f"Several cameras found ({found}); choose one with --camera-id.")
    return cameras[0]["id"]


def configure(cam, fps, set_feature):
    """Set the camera up as the Discobox app's show_hide_cam() does."""
    cam.UserSetSelector.set("Default")
    set_feature(cam, "ExposureAuto", "Continuous")
    set_feature(cam, "AcquisitionMode", "Continuous")
    set_feature(cam, "AcquisitionFrameCount", 65535)
    set_feature(cam, "TriggerSelector", "FrameStart")
    set_feature(cam, "TriggerMode", "On")
    set_feature(cam, "TriggerSource", "FixedRate")
    set_feature(cam, "AcquisitionFrameRateAbs", fps)


class FrameHandler:
    """What vmbpy calls with each frame: `(cam, stream, frame)`.

    A complete frame's pixels are copied (vmbpy reuses the buffer) and put on
    `frames` as (frame id, arrival time, image); a full queue drops the frame and
    counts it. The buffer always goes back to the camera.
    """

    def __init__(self, frames, complete_status):
        self.frames = frames
        self.complete_status = complete_status
        self.received = 0
        self.dropped = 0
        self.incomplete = 0

    def __call__(self, cam, stream, frame):
        try:
            if frame.get_status() == self.complete_status:
                image = frame.as_numpy_ndarray()[:, :, 0].copy()
                self.received += 1
                try:
                    self.frames.put_nowait((frame.get_id(), time.monotonic(), image))
                except queue.Full:
                    self.dropped += 1
            else:
                self.incomplete += 1
        finally:
            cam.queue_frame(frame)


class Camera:
    """One camera, open and streaming into `handler` from its own thread until
    stop() is called."""

    def __init__(self, camera_id, fps, frames):
        self.camera_id = camera_id
        self.fps = fps
        self.frames = frames
        self.handler = None
        self.model = None
        self.error = None
        self._commands = queue.Queue()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    @property
    def description(self):
        return f"{self.model} {self.camera_id}" if self.model else str(self.camera_id)

    def open(self, timeout=30):
        """Open the camera and start streaming; raises CameraError if it cannot."""
        vmbpy, _camera_utils = _vimba()
        self.handler = FrameHandler(self.frames, vmbpy.FrameStatus.Complete)
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            self.stop()
            raise CameraError(f"Camera {self.camera_id} did not start streaming within {timeout} s.")
        if self.error is not None:
            raise self.error

    def _run(self):
        vmbpy, camera_utils = _vimba()
        try:
            with vmbpy.VmbSystem.get_instance():
                try:
                    cam = camera_utils.get_camera(self.camera_id)
                except SystemExit:  # the Discobox get_camera() exits when it cannot open the camera
                    raise CameraError(f"Could not open camera {self.camera_id}.")
                with cam:
                    camera_utils.setup_camera(cam)
                    configure(cam, self.fps, camera_utils.set_feature)
                    self.model = cam.get_model()
                    cam.start_streaming(handler=self.handler, buffer_count=BUFFER_COUNT,
                                        allocation_mode=vmbpy.AllocationMode.AnnounceFrame)
                    _logger.info("Camera %s streaming at %s fps", self.description, self.fps)
                    self._ready.set()
                    try:
                        while not self._stop.is_set():
                            try:
                                command = self._commands.get(timeout=0.2)
                            except queue.Empty:
                                continue
                            command(cam, camera_utils)
                    finally:
                        cam.stop_streaming()
                        _logger.info("Camera %s stopped", self.description)
        except CameraError as error:
            self.error = error
        except _vimba_errors(vmbpy) as error:
            self.error = _vimba_failure(error)
        except Exception as error:
            _logger.exception("The camera failed")
            self.error = CameraError(f"The camera failed: {error}")
        finally:
            self._ready.set()

    def set_fps(self, fps):
        """Change the frame rate while streaming, as the Discobox settings window does."""
        self.fps = fps
        self._commands.put(lambda cam, camera_utils: camera_utils.set_feature(cam, "AcquisitionFrameRateAbs", fps))

    def stop(self, timeout=10):
        """Stop streaming and close the camera; returns once it is closed."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
