"""The automatic zone mask: the slides and their written zones found on a
recording's first frame, once, kept with it, and what new recordings get."""

import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

import folder_camera
import pipeline
from pipeline import auto_zones, plate_zones
from pipeline.live import live_runs
from classes.live.settings import Settings
from classes.plate import slide_finder, zone_masks
from classes.plate.zone_layout import ZoneLayout

ROOT = Path(pipeline.__file__).resolve().parent.parent


def one_frame_folder(tmp_path):
    """A recording folder holding the first frame of sample_data."""
    data_dir = tmp_path / "plate"
    recording = next(path for path in sorted((ROOT / "sample_data").iterdir()) if path.is_dir())
    (data_dir / recording.name).mkdir(parents=True)
    shutil.copy(sorted(recording.glob("*.bmp"))[0], data_dir / recording.name)
    return data_dir


def first_frame():
    recording = next(path for path in sorted((ROOT / "sample_data").iterdir()) if path.is_dir())
    return cv2.imread(str(sorted(recording.glob("*.bmp"))[0]), cv2.IMREAD_GRAYSCALE)


def test_the_slides_of_sample_data_are_found_with_their_writing_beside_the_plate():
    slides = slide_finder.find_slides(first_frame())
    assert len(slides) == 5  # five slides in the middle column, each written on its left end
    for slide in slides:
        text, plate = slide["text"], slide["plate"]
        assert slide["side"] == "right" and text[2] == plate[0] and text[0] < plate[0] < plate[2]
        assert 190 <= plate[3] - plate[1] <= 240 and 400 <= plate[2] - plate[0] <= 520
    tops = sorted(slide["plate"][1] for slide in slides)
    assert all(lower - upper > 190 for upper, lower in zip(tops, tops[1:]))  # one slide each, none twice


def test_the_mites_of_sample_data_are_found_in_the_automatic_zones_as_in_the_hand_made_ones(tmp_path):
    data_dir = one_frame_folder(tmp_path)
    hand = pipeline.open_session(data_dir, tmp_path / "hand")
    ZoneLayout(zone_masks.AUTO).save(data_dir)
    found = pipeline.open_session(data_dir, tmp_path / "auto")
    assert len(found["zones"]) == 5 < len(hand["zones"])  # only the slides in use are zones
    position = lambda mite: (round(mite["x"]), round(mite["y"]))  # noqa: E731
    assert sorted(map(position, found["mites"])) == sorted(map(position, hand["mites"]))


def test_the_zones_are_found_once_and_kept_with_the_recordings(tmp_path, monkeypatch):
    data_dir = one_frame_folder(tmp_path)
    ZoneLayout(zone_masks.AUTO).save(data_dir)
    calls = []
    finder = slide_finder.find_slides
    monkeypatch.setattr(slide_finder, "find_slides", lambda image: calls.append(1) or finder(image))
    path = plate_zones.coords_file_of(data_dir)
    assert path == data_dir / pipeline.paths.AUTO_ZONES_NAME
    plate_zones.zones_of(data_dir)
    assert len(calls) == 1
    lines = path.read_text().splitlines()
    assert [line.split()[0] for line in lines] == ["1", "0"] * 5


def test_without_a_slide_the_zones_are_the_fallback_mask(tmp_path):
    path = auto_zones.find(tmp_path, np.full((1544, 2064), 200, np.uint8))
    assert path.read_text() == zone_masks.coords_file(zone_masks.FALLBACK).read_text()
    # a folder with no frame to find them on uses the fallback mask's without keeping it
    assert auto_zones.coords_file(tmp_path / "empty") == zone_masks.coords_file(zone_masks.FALLBACK)


def test_the_automatic_mask_is_offered_but_cannot_be_drawn_saved_or_deleted():
    assert zone_masks.exists("auto") and zone_masks.names()[0] == "auto"
    assert "auto" in [choice["name"] for choice in ZoneLayout.choices()]
    assert "auto" not in [mask["name"] for mask in pipeline.list_masks()]
    with pytest.raises(FileNotFoundError):
        pipeline.read_mask("auto")
    with pytest.raises(ValueError):
        pipeline.save_mask("auto", [{"type": "mite", "x1": 0, "y1": 0, "x2": 10, "y2": 10}])
    with pytest.raises(ValueError):
        pipeline.delete_mask("auto")
    assert ZoneLayout("auto").filename("labels.json") == "labels_auto.json"


def test_new_recordings_get_the_automatic_mask_and_folders_known_before_keep_theirs(tmp_path):
    assert Settings().zone_mask == zone_masks.NEW == zone_masks.AUTO
    assert pipeline.zone_mask(tmp_path) == zone_masks.DEFAULT == "1"  # a folder of an earlier version
    recordings, results = tmp_path / "recordings", tmp_path / "results"
    for name in ("new", "labelled", "opened", "chosen"):
        (recordings / name / "rec").mkdir(parents=True)
    pipeline.save_labels(recordings / "labelled", {"3": "venom"})
    (results / "opened").mkdir(parents=True)
    ZoneLayout("2").save(recordings / "chosen")
    for name in ("new", "labelled", "opened", "chosen"):
        pipeline.finish_upload(name, recordings, results)
    masks = {name: pipeline.zone_mask(recordings / name) for name in ("new", "labelled", "opened", "chosen")}
    assert masks == {"new": "auto", "labelled": "1", "opened": "1", "chosen": "2"}


def test_a_live_run_finds_its_zones_on_the_lit_frame_before_it_starts(tmp_path, monkeypatch):
    data_dir = one_frame_folder(tmp_path)
    settings_path = data_dir / pipeline.SETTINGS_FILENAME
    pipeline.save_death_minutes(data_dir, folder_camera.DEAD_AFTER)
    status = folder_camera.open_live(monkeypatch, "auto-test", tmp_path / "out", "run", data_dir,
                                     recordings_root=tmp_path / "recordings", settings={"zone_mask": "auto"})
    try:
        run_dir = Path(status["run_dir"])
        assert status["zone_mask"] == "auto" and pipeline.zone_mask(run_dir) == "auto"
        preview = pipeline.live_preview("auto-test")
        assert (run_dir / pipeline.paths.AUTO_ZONES_NAME).is_file() and len(preview["zones"]) == 5
        run = live_runs.open_runs["auto-test"]
        assert len(run.analysis.zone_manager.labelled_zones) == 5  # the analysis is of the zones found
        pipeline.start_live("auto-test")
        assert run.session.finished.wait(60)
        kept = (run_dir / pipeline.paths.AUTO_ZONES_NAME).read_text()
        assert plate_zones.coords_file_of(run_dir).read_text() == kept  # a replay of the run uses the same zones
    finally:
        pipeline.close_live("auto-test")
    assert settings_path.is_file()
