from vmbpy import *
from typing import Optional
import logging
import sys

_logger = logging.getLogger(__name__)


def abort(reason: str, return_code: int = 1):
    """ Prints `reason` to the console and exits the program with `return_code`.
    """
    _logger.info(reason + '\n')
    sys.exit(return_code)


def get_all_cameras():
    """ Lists all available cameras
    """
    with VmbSystem.get_instance() as vmb:
        cams = vmb.get_all_cameras()
        print('Cameras found: {}'.format(len(cams)))
        return cams


def list_cameras():
    """ Lists all available cameras
    """
    cams = get_all_cameras()
    for cam in cams:
        print_camera(cam)


def print_camera(cam: Camera):
    """ Prints all relevant information about a camera to the console.
    """
    print('/// Camera Name   : {}'.format(cam.get_name()))
    print('/// Model Name    : {}'.format(cam.get_model()))
    print('/// Camera ID     : {}'.format(cam.get_id()))
    print('/// Serial Number : {}'.format(cam.get_serial()))
    print('/// Interface ID  : {}\n'.format(cam.get_interface_id()))


def get_camera(camera_id: Optional[str]) -> Camera:
    """ Loads the camera specified by `camera_id` from the Vimba API.
    If `camera_id` is not provided, loads the first available camera.

    :param camera_id: (optional) ID of the camera to load
    """
    with VmbSystem.get_instance() as vmb:
        if camera_id:
            try:
                return vmb.get_camera_by_id(camera_id)
            except VmbCameraError:
                abort('Failed to access Camera \'{}\'. Abort.'.format(camera_id))
        else:
            cams = vmb.get_all_cameras()
            if not cams:
                abort('No Cameras accessible. Abort.')
            return cams[0]


def setup_camera(cam: Camera):
    cam.set_pixel_format(PixelFormat.Mono8)

    with cam:
        # Try to adjust GeV packet size. This Feature is only available for GigE - Cameras.
        try:
            stream = cam.get_streams()[0]
            stream.GVSPAdjustPacketSize.run()
            while not stream.GVSPAdjustPacketSize.is_done():
                pass
        except (AttributeError, VmbFeatureError):
            pass


def get_feature(cam: Camera, feat_name):
    if not hasattr(cam, feat_name):
        _logger.warning(f'Feature does not exist: {feat_name}')
        return
    _logger.info(f'Get feature {feat_name}')
    return getattr(cam, feat_name).get()


def set_feature(cam: Camera, feat_name, value):
    if not hasattr(cam, feat_name):
        _logger.warning(f'Feature does not exist: {feat_name}')
        return
    _logger.info(f'Set feature {feat_name} to {value}')
    getattr(cam, feat_name).set(value)


def exec_command(cam: Camera, feat_name):
    if not hasattr(cam, feat_name):
        _logger.warning(f'Feature does not exist: {feat_name}')
        return
    _logger.info(f'Run feature {feat_name}')
    getattr(cam, feat_name).run()
