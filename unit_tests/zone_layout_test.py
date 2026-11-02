"""The zone mask, built in or drawn on the Zones page, is kept with the
recordings and decides the zones of every analysis of them."""

import json
import shutil
from pathlib import Path

import pytest

import folder_camera
import pipeline
from pipeline import plate_zones
from pipeline.live import live_runs
from classes.live.settings import Settings
from classes.storage.upload_plan import UploadPlan
from classes.plate import zone_masks
from classes.plate.zone_layout import ZoneLayout

ROOT = Path(pipeline.__file__).resolve().parent.parent

# Two plates, the lower one with its label area beside it.
TWO_PLATES = [{"type": "mite", "x1": 300, "y1": 500, "x2": 700, "y2": 700},
              {"type": "text", "x1": 100, "y1": 520, "x2": 290, "y2": 680},
              {"type": "mite", "x1": 300, "y1": 200, "x2": 700, "y2": 400}]


def one_frame_folder(tmp_path):
    """A recording folder holding the first frame of sample_data."""
    data_dir = tmp_path / "plate"
    recording = next(path for path in sorted((ROOT / "sample_data").iterdir()) if path.is_dir())
    (data_dir / recording.name).mkdir(parents=True)
    shutil.copy(sorted(recording.glob("*.bmp"))[0], data_dir / recording.name)
    return data_dir


@pytest.fixture
def two_plates():
    """The mask TWO_PLATES as "two_plates", deleted after the test."""
    pipeline.save_mask("two_plates", TWO_PLATES)
    yield "two_plates"
    if zone_masks.exists("two_plates"):
        pipeline.delete_mask("two_plates")


def test_a_folder_has_one_zone_per_plate_until_told_otherwise(tmp_path):
    assert pipeline.zone_mask(tmp_path) == "1"
    ZoneLayout("2").save(tmp_path)
    assert pipeline.zone_mask(tmp_path) == "2"
    assert ZoneLayout.of_folder(tmp_path).coords_file.name == "coords_pixel_2.txt"


def test_saving_the_mask_keeps_the_other_settings_and_drops_the_old_line(tmp_path):
    (tmp_path / pipeline.SETTINGS_FILENAME).write_text("recording_count=6\nzones_per_plate=2\nfps=30\n")
    assert pipeline.zone_mask(tmp_path) == "2"  # the line of earlier versions
    ZoneLayout("1").save(tmp_path)
    assert (tmp_path / pipeline.SETTINGS_FILENAME).read_text() == "recording_count=6\nfps=30\nzone_mask=1\n"


@pytest.mark.parametrize("value", [0, 3, "two", None, "../coords_pixel"])
def test_only_a_mask_there_is_can_be_chosen(value):
    with pytest.raises(ValueError):
        ZoneLayout(value)
    with pytest.raises(ValueError):
        Settings.from_dict({"zone_mask": value})


def test_a_mask_saved_that_is_not_there_reads_as_the_default(tmp_path):
    (tmp_path / pipeline.SETTINGS_FILENAME).write_text("zones_per_plate=5\n")
    assert pipeline.zone_mask(tmp_path) == "1"
    (tmp_path / pipeline.SETTINGS_FILENAME).write_text("zone_mask=deleted_since\n")
    assert pipeline.zone_mask(tmp_path) == "1"
    settings = tmp_path / "settings.txt"
    settings.write_text("zone_mask=deleted_since\nfollow_px=20\n")
    # a live run's: the mask new runs get
    assert (Settings.from_file(settings).zone_mask, Settings.from_file(settings).follow_px) == ("auto", 20)
    settings.write_text("zones_per_plate=2\n")
    assert Settings.from_file(settings).zone_mask == "2"


def test_each_coordinates_file_halves_or_keeps_the_plates():
    one, two = (plate_zones.build_zone_manager(ZoneLayout(mask).coords_file) for mask in ("1", "2"))
    assert len(two.labelled_zones) == 2 * len(one.labelled_zones)
    # every half has its own half of the printed-label area
    assert all(two.text_zone_for(zone) is not None for zone in two.labelled_zones)


def test_a_text_zone_names_one_plate_at_most():
    # the two halves of a plate beside one label area, as near to it as each other
    halves = [{"type": "mite", "x1": 300, "y1": 200, "x2": 700, "y2": 300},
              {"type": "mite", "x1": 300, "y1": 300, "x2": 700, "y2": 400},
              {"type": "text", "x1": 100, "y1": 200, "x2": 290, "y2": 400}]
    numbers = pipeline.number_mask(halves)
    assert numbers["ids"] == [0, 1, None]
    assert numbers["text_of"] == [2, None, None]  # the first in reading order has it, the other none
    # a second label area beside the lower half is its own
    numbers = pipeline.number_mask([*halves, {"type": "text", "x1": 100, "y1": 310, "x2": 290, "y2": 390}])
    assert numbers["text_of"][:2] == [2, 3]


def test_a_mask_drawn_is_kept_numbered_and_deleted(two_plates):
    saved = pipeline.read_mask(two_plates)
    # the upper plate is 0, the lower 1, whose name is read from the text zone beside it
    assert saved["ids"] == [1, None, 0] and saved["text_of"] == [1, None, None]
    assert saved["zones"] == TWO_PLATES
    assert pipeline.number_mask(TWO_PLATES) == {"ids": saved["ids"], "text_of": saved["text_of"]}
    listed = {mask["name"]: mask for mask in pipeline.list_masks()}
    assert list(listed)[:2] == ["1", "2"] and listed[two_plates]["n_mite_zones"] == 2
    assert (zone_masks.folder() / "two_plates.txt").read_text().splitlines()[1] == "0 100.00 520.00 290.00 680.00"
    pipeline.delete_mask(two_plates)
    assert two_plates not in [mask["name"] for mask in pipeline.list_masks()]


@pytest.mark.parametrize("name, zones", [
    ("1", TWO_PLATES), ("2", TWO_PLATES),  # the built-in ones
    ("", TWO_PLATES), ("123", TWO_PLATES), ("a/b", TWO_PLATES), ("x" * 41, TWO_PLATES),
    ("only_text", [TWO_PLATES[1]]), ("no_size", [{**TWO_PLATES[0], "x2": 300}]),
    ("odd_type", [{**TWO_PLATES[0], "type": "plate"}]),
])
def test_a_mask_is_refused_without_a_good_name_or_zones(name, zones):
    with pytest.raises(ValueError):
        pipeline.save_mask(name, zones)


def test_the_built_in_masks_cannot_be_deleted():
    with pytest.raises(ValueError):
        pipeline.delete_mask("1")


def test_the_labels_and_controls_of_each_mask_are_kept_apart(tmp_path, two_plates):
    pipeline.save_labels(tmp_path, {"0": "venom"})
    pipeline.save_controls(tmp_path, [3])
    ZoneLayout("2").save(tmp_path)
    assert pipeline.load_labels(tmp_path) == {} and pipeline.load_controls(tmp_path) == []
    pipeline.save_labels(tmp_path, {"7": "control"})
    assert (tmp_path / "labels_2.json").is_file()
    ZoneLayout(two_plates).save(tmp_path)
    pipeline.save_labels(tmp_path, {"1": "water"})
    assert (tmp_path / "labels_two_plates.json").is_file()
    ZoneLayout("1").save(tmp_path)
    assert pipeline.load_labels(tmp_path) == {"0": "venom"} and pipeline.load_controls(tmp_path) == [3]


def test_a_dropped_folder_brings_the_labels_of_every_mask():
    assert UploadPlan.wanted("labels_2.json") and UploadPlan.wanted("run/controls_2.json")
    assert UploadPlan.wanted("labels_my-mask.json")
    assert not UploadPlan.wanted("labels_a b.json")


def test_the_mask_saved_is_that_of_the_next_session(tmp_path, two_plates):
    data_dir, out_dir = one_frame_folder(tmp_path), tmp_path / "out"
    opened = pipeline.open_session(data_dir, out_dir)
    assert opened["zone_mask"] == "1" and [mask["name"] for mask in opened["zone_masks"]] == ["auto", "1", "2", two_plates]

    halved = pipeline.save_zone_mask(data_dir, out_dir, "2")
    assert halved["zone_mask"] == "2" and len(halved["zones"]) == 2 * len(opened["zones"])
    assert {mite["zone_id"] for mite in halved["mites"]} <= {zone["id"] for zone in halved["zones"]}
    # kept with the recordings: opening them again, or describing them, says the same
    again = pipeline.open_session(data_dir, out_dir)
    assert len(again["zones"]) == len(halved["zones"])
    assert pipeline.describe_recording(data_dir, tmp_path / "results")["zone_mask"] == "2"
    with pytest.raises(ValueError):
        pipeline.save_zone_mask(data_dir, out_dir, "3")

    # a mask drawn by hand: its zones, and its plates' ids in reading order
    drawn = pipeline.save_zone_mask(data_dir, out_dir, two_plates)
    assert [(zone["id"], zone["y1"]) for zone in drawn["zones"]] == [(0, 200), (1, 500)]
    assert drawn["zones"][1]["text_zone"] == {"x1": 100, "y1": 520, "x2": 290, "y2": 680}
    pipeline.delete_mask(two_plates)
    assert pipeline.zone_mask(data_dir) == "1"  # deleted: back to the default


def test_the_first_frame_of_a_recording_is_a_picture_to_draw_on(tmp_path):
    one_frame_folder(tmp_path)
    assert pipeline.recording_picture("plate", tmp_path)[:2] == b"\xff\xd8"  # a JPEG
    for name in ("missing", "..", "plate/.."):
        with pytest.raises(FileNotFoundError):
            pipeline.recording_picture(name, tmp_path)


def test_a_run_uses_the_zones_saved_with_its_recordings(tmp_path):
    data_dir = one_frame_folder(tmp_path)
    ZoneLayout("2").save(data_dir)
    results = pipeline.run_analysis(data_dir, tmp_path / "out")
    assert len(results["zones"]) == len(plate_zones.build_zone_manager(ZoneLayout("2").coords_file).labelled_zones)
    zone = next(zone for zone in results["zones"] if zone["n_mites"])
    clip = pipeline.analysis_clip(data_dir, tmp_path / "out", 0, zone["id"])
    assert clip["height"] <= zone["y2"] - zone["y1"] + 2 * pipeline.CLIP_MARGIN
    pipeline.finish_files(tmp_path / "out")
    analysis = json.loads((tmp_path / "out" / "run_settings.json").read_text())["analysis"]
    assert analysis["zone_mask"] == "2"
    assert analysis["zone_mask_zones"] == ZoneLayout("2").coords_file.read_text().splitlines()


def test_a_live_run_takes_the_mask_of_its_settings_and_the_label_page_can_change_it(tmp_path, monkeypatch):
    data_dir = one_frame_folder(tmp_path)
    ZoneLayout("2").save(data_dir)
    pipeline.save_labels(data_dir, {"4": "venom"})
    settings_path = data_dir / pipeline.SETTINGS_FILENAME
    pipeline.save_death_minutes(data_dir, folder_camera.DEAD_AFTER)  # the settings saved below are this file's
    status = folder_camera.open_live(monkeypatch, "zones-test", tmp_path / "out", "run", data_dir,
                                     recordings_root=tmp_path / "recordings")
    try:
        assert status["zone_mask"] == "2"
        run_dir = Path(status["run_dir"])
        assert pipeline.zone_mask(run_dir) == "2" and pipeline.load_labels(run_dir) == {"4": "venom"}
        preview = pipeline.live_preview("zones-test")
        assert preview["zone_mask"] == "2" and [mask["name"] for mask in preview["zone_masks"]] == ["auto", "1", "2"]
        halves = len(plate_zones.build_zone_manager(ZoneLayout("2").coords_file).labelled_zones)
        assert len(preview["zones"]) == halves

        # the label page's choice, until the run starts: saved as the test run's setting
        pipeline.save_live_settings({"zone_mask": "1"}, "zones-test", settings_path=settings_path)
        preview = pipeline.live_preview("zones-test")
        assert preview["zone_mask"] == "1" and 2 * len(preview["zones"]) == halves
        assert pipeline.load_labels(run_dir) == {}  # the labels of the halves are another mask's
        with pytest.raises(ValueError):
            pipeline.save_live_settings({"zone_mask": "3"}, "zones-test", settings_path=settings_path)

        pipeline.start_live("zones-test")
        assert live_runs.open_runs["zones-test"].session.finished.wait(60)
        assert pipeline.zone_mask(run_dir) == "1"
        with pytest.raises(ValueError, match="cannot change"):
            pipeline.save_live_settings({"zone_mask": "2"}, "zones-test", settings_path=settings_path)
    finally:
        pipeline.close_live("zones-test")
