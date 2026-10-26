import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# The tests run with the settings the app is shipped with, config.default.yaml,
# in a copy of their own: this machine's config.yaml, with the threshold saved
# from its calibration page, is neither read nor written. Set before the app is
# imported, and in the environment, so the command line the tests run takes it too.
_config_dir = tempfile.mkdtemp(prefix="discobox_test_config_")
atexit.register(shutil.rmtree, _config_dir, ignore_errors=True)
os.environ["DISCOBOX_CONFIG"] = str(Path(_config_dir) / "config.yaml")
shutil.copyfile(Path(__file__).resolve().parent.parent / "config.default.yaml", os.environ["DISCOBOX_CONFIG"])

import pipeline  # noqa: E402
from pipeline import output_files, run_results  # noqa: E402


@pytest.fixture(autouse=True)
def no_review_band(monkeypatch):
    """Every run in a test is without calls to check by eye: they add to the
    results, which the references were made without. A test of them takes them
    back (see review_band_test.py)."""
    monkeypatch.setattr(run_results, "review_calls", lambda *args: None)


@pytest.fixture(autouse=True)
def no_files_left_to_write():
    """The files a test left to be written a moment later (after a correction,
    a calibration report) are not written during the tests after it."""
    yield
    output_files.files_later.forget()
