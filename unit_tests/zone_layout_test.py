"""The zones per plate, one or two, are kept with the recordings and decide the
zones of every analysis of them."""

import shutil
from pathlib import Path

import pytest

import folder_camera
import pipeline
from classes.live.settings import Settings
from classes.upload_plan import UploadPlan
from classes.zone_layout import ZoneLayout

ROOT = Path(pipeline.__file__).resolve().parent


def one_frame_folder(tmp_path):
    """A recording folder holding the first frame of sample_data."""
    data_dir = tmp_path / "plate"
    recording = next(path for path in sorted((ROOT / "sample_data").iterdir()) if path.is_dir())
    (data_dir / recording.name).mkdir(parents=True)
    shutil.copy(sorted(recording.glob("*.bmp"))[0], data_dir / recording.name)
    return data_dir


def test_a_folder_has_one_zone_per_plate_until_told_otherwise(tmp_path):
    assert pipeline.zones_per_plate(tmp_path) == 1
    ZoneLayout(2).save(tmp_path)
    assert pipeline.zones_per_plate(tmp_path) == 2
    assert ZoneLayout.of_folder(tmp_path).coords_file.name == "coords_pixel_2.txt"


def test_saving_the_zones_per_plate_keeps_the_other_settings(tmp_path):
    (tmp_path / pipeline.SETTINGS_FILENAME).write_text("recording_count=6\nfps=30\n")
    ZoneLayout(2).save(tmp_path)
    assert (tmp_path / pipeline.SETTINGS_FILENAME).read_text() == "recording_count=6\nfps=30\nzones_per_plate=2\n"
    ZoneLayout(1).save(tmp_path)
    assert (tmp_path / pipeline.SETTINGS_FILENAME).read_text() == "recording_count=6\nfps=30\nzones_per_plate=1\n"


@pytest.mark.parametrize("value", [0, 3, 1.5, "two", None])
def test_only_one_or_two_zones_per_plate_can_be_chosen(value):
    with pytest.raises(ValueError):
        ZoneLayout(value)
    with pytest.raises(ValueError):
        Settings.from_dict({"zones_per_plate": value})


def test_a_choice_saved_that_is_not_one_reads_as_one_zone_per_plate(tmp_path):
    (tmp_path / pipeline.SETTINGS_FILENAME).write_text("zones_per_plate=5\n")
    assert pipeline.zones_per_plate(tmp_path) == 1


def test_each_coordinates_file_halves_or_keeps_the_plates():
    one, two = (pipeline._build_zone_manager(ZoneLayout(zones).coords_file) for zones in (1, 2))
    assert len(two.labelled_zones) == 2 * len(one.labelled_zones)
    # every half has its own half of the printed-label area
    assert all(two.text_zone_for(zone) is not None for zone in two.labelled_zones)


def test_the_labels_and_controls_of_each_layout_are_kept_apart(tmp_path):
    pipeline.save_labels(tmp_path, {"0": "venom"})
    pipeline.save_controls(tmp_path, [3])
    ZoneLayout(2).save(tmp_path)
    assert pipeline.load_labels(tmp_path) == {} and pipeline.load_controls(tmp_path) == []
    pipeline.save_labels(tmp_path, {"7": "control"})
    assert (tmp_path / "labels_2.json").is_file()
    ZoneLayout(1).save(tmp_path)
    assert pipeline.load_labels(tmp_path) == {"0": "venom"} and pipeline.load_controls(tmp_path) == [3]


def test_a_dropped_folder_brings_the_labels_of_both_layouts():
    assert UploadPlan.wanted("labels_2.json") and UploadPlan.wanted("run/controls_2.json")
    assert not UploadPlan.wanted("labels_3.json")


def test_the_zones_saved_are_those_of_the_next_session(tmp_path):
    data_dir, out_dir = one_frame_folder(tmp_path), tmp_path / "out"
    opened = pipeline.open_session(data_dir, out_dir)
    assert (opened["zones_per_plate"], opened["zone_layouts"]) == (1, [1, 2])

    halved = pipeline.save_zones_per_plate(data_dir, out_dir, 2)
    assert halved["zones_per_plate"] == 2 and len(halved["zones"]) == 2 * len(opened["zones"])
    assert {mite["zone_id"] for mite in halved["mites"]} <= {zone["id"] for zone in halved["zones"]}
    # kept with the recordings: opening them again, or describing them, says the same
    again = pipeline.open_session(data_dir, out_dir)
    assert len(again["zones"]) == len(halved["zones"])
    assert pipeline.describe_recording(data_dir, tmp_path / "results")["zones_per_plate"] == 2
    with pytest.raises(ValueError):
        pipeline.save_zones_per_plate(data_dir, out_dir, 3)


def test_a_run_uses_the_zones_saved_with_its_recordings(tmp_path):
    data_dir = one_frame_folder(tmp_path)
    ZoneLayout(2).save(data_dir)
    results = pipeline.run_analysis(data_dir, tmp_path / "out")
    assert len(results["zones"]) == len(pipeline._build_zone_manager(ZoneLayout(2).coords_file).labelled_zones)
    zone = next(zone for zone in results["zones"] if zone["n_mites"])
    clip = pipeline.analysis_clip(data_dir, tmp_path / "out", 0, zone["id"])
    assert clip["height"] <= zone["y2"] - zone["y1"] + 2 * pipeline.CLIP_MARGIN


def test_a_live_run_takes_the_zones_of_its_settings_and_the_label_page_can_change_them(tmp_path, monkeypatch):
    data_dir = one_frame_folder(tmp_path)
    ZoneLayout(2).save(data_dir)
    pipeline.save_labels(data_dir, {"4": "venom"})
    settings_path = data_dir / pipeline.SETTINGS_FILENAME
    pipeline.save_death_minutes(data_dir, folder_camera.DEAD_AFTER)  # the settings saved below are this file's
    status = folder_camera.open_live(monkeypatch, "zones-test", tmp_path / "out", "run", data_dir,
                                     recordings_root=tmp_path / "recordings")
    try:
        assert status["zones_per_plate"] == 2
        run_dir = Path(status["run_dir"])
        assert pipeline.zones_per_plate(run_dir) == 2 and pipeline.load_labels(run_dir) == {"4": "venom"}
        preview = pipeline.live_preview("zones-test")
        assert (preview["zones_per_plate"], preview["zone_layouts"]) == (2, [1, 2])
        halves = len(pipeline._build_zone_manager(ZoneLayout(2).coords_file).labelled_zones)
        assert len(preview["zones"]) == halves

        # the label page's choice, until the run starts: saved as the test run's setting
        pipeline.save_live_settings({"zones_per_plate": 1}, "zones-test", settings_path=settings_path)
        preview = pipeline.live_preview("zones-test")
        assert preview["zones_per_plate"] == 1 and 2 * len(preview["zones"]) == halves
        assert pipeline.load_labels(run_dir) == {}  # the labels of the halves are another layout's
        with pytest.raises(ValueError):
            pipeline.save_live_settings({"zones_per_plate": 3}, "zones-test", settings_path=settings_path)

        pipeline.start_live("zones-test")
        assert pipeline._live["zones-test"].session.finished.wait(60)
        assert pipeline.zones_per_plate(run_dir) == 1
        with pytest.raises(ValueError, match="cannot change"):
            pipeline.save_live_settings({"zones_per_plate": 2}, "zones-test", settings_path=settings_path)
    finally:
        pipeline.close_live("zones-test")
