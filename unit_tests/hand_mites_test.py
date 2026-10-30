"""Mites placed by hand where the detector missed them: found with the
detector's wherever mites are found on whole frames, kept as ROIs when the
frames are shrunk, refused where there are no frames for them."""

import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from classes.plate import hand_mites as hand
from classes.plate.mite import Mite
from classes.plate.zones import Zone, ZoneManager
from classes.storage.roi_recordings import RoiRecordings
from pipeline import hand_mites, scoring
from pipeline.live import live_runs
import folder_camera
import pipeline
import reference

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data"


def plate():
    """A plate of 200 x 200 px, light, with a dark mite at (60, 70)."""
    image = np.full((240, 240), 200, dtype=np.uint8)
    image[66:75, 56:65] = 40
    zone_manager = ZoneManager([Zone(20, 20, 220, 220, "mite")])
    return image, zone_manager


def test_box_is_square_round_the_point():
    assert hand.box_at(100, 50, 13) == (93, 43, 107, 57)
    assert hand.box_at(100.4, 50.6, 12) == (94, 45, 106, 57)


def test_box_size_follows_the_detections():
    mites = [Mite(0, 0, 12, 12), Mite(0, 0, 14, 14), Mite(0, 0, 9, 9)]
    assert hand.box_size(mites, radius=8) == 12
    assert hand.box_size([], radius=8) == 16


def test_click_snaps_to_the_darkest_spot_near():
    image, _zones = plate()
    assert hand.centre_near(image, 64, 66) == (60, 70)
    # beyond its reach the mite is not found
    assert hand.centre_near(image, 100, 100) != (60, 70)


def test_points_near_a_detection_are_that_detection():
    detected = [Mite(50, 50, 62, 62)]  # centre (56, 56)
    made = hand.missing([{"x": 60, "y": 60, "size": 12}, {"x": 120, "y": 90, "size": 12}], detected)
    assert [mite.home for mite in made] == [(120, 90)]
    assert made[0].by_hand


def test_zones_take_the_mites_placed_by_hand():
    _image, zone_manager = plate()
    zone_manager.by_hand = [{"x": 150, "y": 150, "size": 12}]
    assigned = zone_manager.assign_mites([Mite(50, 50, 62, 62)])
    assert len(assigned) == 2 and [mite.text for mite in zone_manager.mites] == ["0.1", "0.2"]
    assert getattr(zone_manager.mites[1], "by_hand", False)


def test_placing_keeps_the_point_and_removing_forgets_it(tmp_path):
    image, zone_manager = plate()
    point = hand_mites.place(tmp_path, zone_manager, image, 63, 67)
    assert point == {"x": 60, "y": 70, "size": 16}
    assert hand_mites.points(tmp_path) == [point]
    hand_mites.remove(tmp_path, 58, 71)
    assert hand_mites.points(tmp_path) == []
    with pytest.raises(ValueError, match="No mite was placed"):
        hand_mites.remove(tmp_path, 58, 71)


def test_placing_is_refused_off_a_plate_and_on_a_mite(tmp_path):
    image, zone_manager = plate()
    with pytest.raises(ValueError, match="inside a plate"):
        hand_mites.place(tmp_path, zone_manager, image, 5, 5)
    zone_manager.assign_mites([Mite(55, 65, 66, 76)])
    with pytest.raises(ValueError, match="already"):
        hand_mites.place(tmp_path, zone_manager, image, 62, 68)
    assert not (tmp_path / pipeline.HAND_MITES_FILENAME).exists()


def _copy_sample(target):
    """sample_data in `target`: frames linked, the small files copied, no labels."""
    target.mkdir(parents=True)
    for path in SAMPLE.rglob("*"):
        copy = target / path.relative_to(SAMPLE)
        if path.is_dir():
            copy.mkdir(parents=True, exist_ok=True)
        elif path.suffix.lower() == ".bmp":
            copy.parent.mkdir(parents=True, exist_ok=True)
            os.link(path, copy)
        elif path.name in (".settings.txt",):
            shutil.copy2(path, copy)
    return target


@pytest.mark.slow
def test_a_mite_placed_by_hand_on_a_dropped_folder_is_analysed_and_kept_as_roi(tmp_path):
    data_dir = _copy_sample(tmp_path / "recordings" / "hand")
    out_dir = tmp_path / "results" / "hand"
    pipeline.finish_upload("hand", tmp_path / "recordings")  # dropped into the page: whole until analysed
    opened = pipeline.open_session(data_dir, out_dir)
    assert opened["place_by_hand"] and not any(mite.get("by_hand") for mite in opened["mites"])
    zone = opened["zones"][3]
    x, y = (zone["x1"] + zone["x2"]) / 2, (zone["y1"] + zone["y2"]) / 2
    opened = pipeline.place_mite(data_dir, out_dir, x, y)
    placed = [mite for mite in opened["mites"] if mite.get("by_hand")]
    assert len(placed) == 1

    run = scoring.detect_and_score(data_dir, None)
    by_hand = [mite for mite in run.zone_manager.mites if getattr(mite, "by_hand", False)]
    assert [mite.text for mite in by_hand] == [placed[0]["id"]]
    assert all(score is not None for score in by_hand[0].motion_scores)

    # analysed, it is shrunk to the mites' surroundings, those of the mite placed by hand among them
    pipeline.run_analysis(data_dir, out_dir)
    assert tuple(by_hand[0]) in RoiRecordings(data_dir).boxes
    again = scoring.detect_and_score(data_dir, None)
    kept = next(mite for mite in again.zone_manager.mites if tuple(mite) == tuple(by_hand[0]))
    assert kept.motion_scores == by_hand[0].motion_scores
    assert not pipeline.open_session(data_dir, out_dir)["place_by_hand"]
    with pytest.raises(ValueError, match="surroundings"):
        pipeline.place_mite(data_dir, out_dir, x + 60, y)
    assert json.loads((data_dir / pipeline.HAND_MITES_FILENAME).read_text(encoding="utf-8"))


@pytest.mark.slow
def test_a_live_run_follows_mites_placed_by_hand_before_it_and_among_those_added(tmp_path, monkeypatch):
    session = reference.make_small_session(tmp_path / "small")
    folder_camera.open_live(monkeypatch, "hand", tmp_path / "out", "hand", session, gap=3,
                            recordings_root=tmp_path / "recordings")
    first = reference.load("folder_sample_data")["results"]["mites"][0]  # 4.1
    preview = pipeline.live_place_mite("hand", first["x"] + 30, first["y"])  # an empty spot of its zone
    assert preview["place_by_hand"] and len([mite for mite in preview["mites"] if mite.get("by_hand")]) == 1
    pipeline.start_live("hand")
    run = live_runs.open_runs["hand"]
    try:
        deadline = time.monotonic() + 60
        while pipeline.live_status("hand")["analysed"] < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len([mite for mite in run.analysis.mites if getattr(mite, "by_hand", False)]) == 1
        with pytest.raises(ValueError, match="before the test run starts"):
            pipeline.live_place_mite("hand", 1100, 300)
        run.found_frame = run.analysis.first_frame  # as live_find_mites() leaves it
        found = pipeline.live_hand_mite("hand", 1100, 300, [])
        assert [(mite["id"], mite["by_hand"]) for mite in found["mites"]] == [("4.7", True)]
        with pytest.raises(ValueError, match="already"):
            pipeline.live_hand_mite("hand", 1102, 301, found["mites"])
        assert pipeline.live_hand_mite("hand", 1102, 301, found["mites"], remove=True)["mites"] == []
        pipeline.live_add_mites("hand", [[mite[key] for key in ("x1", "y1", "x2", "y2")] for mite in found["mites"]])
        assert run.session.finished.wait(120)
    finally:
        live_runs.open_runs.pop("hand")
    live = reference.plain(run.session.results)
    assert len(live["mites"]) == 32
    again = reference.run_folder(run.run_dir, tmp_path / "folder_out", pipeline.load_labels(run.run_dir) or None)
    differences = reference.differences(again["results"], live)
    assert not differences, "The live results differ from the saved run's:\n  " + "\n  ".join(differences)
