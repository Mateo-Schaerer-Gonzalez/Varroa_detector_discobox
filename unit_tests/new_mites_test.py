"""Mites put on the plates of a folder of frames after its first recording
(classes/scoring/new_mites.py, pipeline/new_mites.py): found on each
recording's first frame when at least `detector.min_new_mites` appear in a zone
at once, analysed from the recording they appear in, shown on the label page on
that recording's frame, and kept as a live run keeps its added mites when the
folder is shrunk to ROIs."""

import json

import cv2
import pytest

import pipeline
from pipeline import uploads
import reference
from classes import app_config
from classes.storage.data_loader import DataLoader
from classes.storage.roi_recordings import INDEX_NAME, ROI_DIRNAME

# Empty spots of the small session: three in zone 3, one in zone 5.
ZONE_3 = [(400, 300), (460, 300), (520, 300)]
ZONE_5 = [(1700, 300)]


@pytest.fixture
def least():
    """Set detector.min_new_mites for one test; config.default.yaml's after."""
    yield app_config.save_min_new_mites
    app_config.save_min_new_mites(3)


def painted(target, spots=ZONE_3 + ZONE_5, start=1):
    """The small session with a dark disc (a mite to the detector) at each of
    `spots` in every frame from recording `start` on."""
    folder = reference.make_small_session(target)
    loader = DataLoader(folder)
    for name in loader.recording_names[start:]:
        for path in loader.frame_paths(name):
            image = loader.read_image(path)
            for spot in spots:
                cv2.circle(image, spot, 6, 30, -1)
            assert cv2.imwrite(str(path), image)
    return folder


def later(results):
    return dict(results["started"]) if "started" in results else {}


def test_mites_put_on_together_are_analysed_from_the_recording_they_appear_in(tmp_path):
    folder = painted(tmp_path / "small")
    run = reference.run_folder(folder, tmp_path / "out")["results"]
    assert later(run) == {"3.1": 1, "3.2": 1, "3.3": 1}  # zone 5's one alone is left out
    assert not any(mite["zone_id"] == 5 for mite in run["mites"])
    assert (tmp_path / "out" / "kept" / pipeline.NEW_MITES_NAME).is_file()  # the search, kept
    assert run["previews"] == [pipeline.PREVIEW_NAME, "preview_from_1.jpg", "preview_from_1.jpg"]
    # censored before they were there
    assert {mite: recordings for mite, recordings in run["censored"].items() if mite.startswith("3.")} == \
        {"3.1": [0], "3.2": [0], "3.3": [0]}


def test_the_least_per_zone_decides_what_is_taken(tmp_path, least):
    folder = painted(tmp_path / "small")
    least(1)
    assert set(later(reference.run_folder(folder, tmp_path / "one")["results"])) == {"3.1", "3.2", "3.3", "5.1"}
    least(4)
    assert later(reference.run_folder(folder, tmp_path / "four")["results"]) == {}
    least(0)
    page = pipeline.open_session(folder, tmp_path / "page")
    assert page["new_mites"] == {"least": 0, "applies": True}
    assert len(page["mites"]) == 31 and page["steps"] == [{"from": 0, "preview": pipeline.PREVIEW_NAME}]


def test_a_folder_without_mites_put_on_later_runs_as_before(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    page = pipeline.open_session(small, tmp_path / "page")
    assert {mite["from"] for mite in page["mites"]} == {0} and len(page["steps"]) == 1
    run = reference.run_folder(small, tmp_path / "out")["results"]
    assert "started" not in run and "previews" not in run


def test_the_label_page_shows_them_on_the_frame_they_appeared_on(tmp_path):
    folder = painted(tmp_path / "small")
    out_dir = tmp_path / "page"
    page = pipeline.open_session(folder, out_dir)
    added = {mite["id"]: mite["from"] for mite in page["mites"] if mite["from"]}
    assert added == {"3.1": 1, "3.2": 1, "3.3": 1}
    assert page["steps"] == [{"from": 0, "preview": pipeline.PREVIEW_NAME}, {"from": 1, "preview": "preview_from_1.jpg"}]
    assert (out_dir / "preview_from_1.jpg").is_file()
    assert page["new_mites"] == {"least": 3, "applies": True}
    assert [zone["n_mites"] for zone in page["zones"] if zone["id"] == 3] == [3]


def test_a_folder_shrunk_keeps_them_and_gives_the_same_results(tmp_path):
    folder = painted(tmp_path / "small")
    copy = reference.linked_copy(folder, tmp_path / "uploads" / "small")
    before = reference.run_folder(folder, tmp_path / "before")["results"]
    pipeline.finish_upload(copy.name, copy.parent)  # shrunk when first analysed
    assert uploads.shrink_pending(copy, copy.parent.parent / "results") == 3
    index = json.loads((copy / ROI_DIRNAME / INDEX_NAME).read_text())
    assert [mite.get("from", 0) for mite in index["mites"]].count(1) == 3
    assert (copy / pipeline.ADDED_FRAMES_DIRNAME / "from_1.jpg").is_file()
    after = reference.run_folder(copy, tmp_path / "after")["results"]
    expected = {key: value for key, value in before.items() if key != "previews"}
    found = reference.differences({**expected, "frames": "rois"}, {k: v for k, v in after.items() if k != "previews"})
    assert not found, "\n".join(found)
    page = pipeline.open_session(copy, tmp_path / "page")
    assert {mite["id"] for mite in page["mites"] if mite["from"]} == {"3.1", "3.2", "3.3"}
    assert page["new_mites"]["applies"] is False  # its mites are those saved


def test_the_setting_is_saved_in_the_detector_section(tmp_path):
    config = tmp_path / "config.yaml"  # one made before the setting: without its line
    lines = app_config.TEMPLATE_CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    config.write_text("".join(line for line in lines if "min_new_mites:" not in line), encoding="utf-8")
    assert app_config.AppConfig(config).detector.min_new_mites == 3
    assert app_config.save_min_new_mites(2, config) == 2
    assert app_config.AppConfig(config).detector.min_new_mites == 2
    app_config.save_min_new_mites(5, config)
    text = config.read_text(encoding="utf-8")
    assert text.count("min_new_mites") == 1 and "min_new_mites: 5" in text and "min_area: 58.067" in text
    with pytest.raises(ValueError):
        app_config.save_min_new_mites(-1, config)
