"""The zones per plate, one or two, are kept with the recordings and decide the
zones of every analysis of them."""

import shutil
from pathlib import Path

import pytest

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
    data_dir, out_dir, library = one_frame_folder(tmp_path), tmp_path / "out", tmp_path / "library"
    opened = pipeline.open_session(data_dir, out_dir, library_dir=library)
    assert (opened["zones_per_plate"], opened["zone_layouts"]) == (1, [1, 2])

    halved = pipeline.save_zones_per_plate(data_dir, out_dir, 2, library_dir=library)
    assert halved["zones_per_plate"] == 2 and len(halved["zones"]) == 2 * len(opened["zones"])
    assert {mite["zone_id"] for mite in halved["mites"]} <= {zone["id"] for zone in halved["zones"]}
    # kept with the recordings: opening them again, or describing them, says the same
    again = pipeline.open_session(data_dir, out_dir, library_dir=library)
    assert len(again["zones"]) == len(halved["zones"])
    assert pipeline.describe_recording(data_dir, tmp_path / "results", library)["zones_per_plate"] == 2
    with pytest.raises(ValueError):
        pipeline.save_zones_per_plate(data_dir, out_dir, 3, library_dir=library)


def test_a_run_uses_the_zones_saved_with_its_recordings(tmp_path):
    data_dir, library = one_frame_folder(tmp_path), tmp_path / "library"
    ZoneLayout(2).save(data_dir)
    results = pipeline.run_analysis(data_dir, tmp_path / "out", library_dir=library)
    assert len(results["zones"]) == len(pipeline._build_zone_manager(ZoneLayout(2).coords_file).labelled_zones)
    zone = next(zone for zone in results["zones"] if zone["n_mites"])
    clip = pipeline.analysis_clip(data_dir, tmp_path / "out", 0, zone["id"])
    assert clip["height"] <= zone["y2"] - zone["y1"] + 2 * pipeline.CLIP_MARGIN


def test_a_replay_takes_the_zones_of_its_folder(tmp_path):
    data_dir = one_frame_folder(tmp_path)
    ZoneLayout(2).save(data_dir)
    pipeline.save_labels(data_dir, {"4": "venom"})
    status = pipeline.open_live("zones-test", tmp_path / "out", "run", source="replay", replay_dir=str(data_dir),
                                replay_gap=0, recordings_root=tmp_path / "recordings", library_dir=tmp_path / "library")
    try:
        assert status["zones_per_plate"] == 2
        run_dir = Path(status["run_dir"])
        assert pipeline.zones_per_plate(run_dir) == 2 and pipeline.load_labels(run_dir) == {"4": "venom"}
        preview = pipeline.live_preview("zones-test")
        assert preview["zones_per_plate"] == 2
        assert len(preview["zones"]) == len(pipeline._build_zone_manager(ZoneLayout(2).coords_file).labelled_zones)
    finally:
        pipeline.close_live("zones-test")
