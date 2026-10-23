"""A folder of whole frames dropped into the page is shrunk to the mites'
surroundings (classes/storage/roi_conversion.py): the results stay those of the whole
frames, a conversion cut short carries on, and nothing is lost where there are
no mites to keep."""

import os
import shutil

import cv2
import numpy as np
import pytest

import pipeline
from pipeline.calibration import dataset_library, score_cache
import reference
from classes.storage.data_loader import DataLoader
from classes.storage.roi_recordings import FIRST_FRAME_NAME, RoiRecordings, is_roi_session


linked_copy = reference.linked_copy


def convert(folder):
    return pipeline.finish_upload(folder.name, folder.parent)["converted"]


@pytest.mark.slow
def test_sample_data_shrunk_gives_the_reference_results(tmp_path):
    if any((reference.SAMPLE_DATA / name).exists() for name in ("labels.json", "ground_truth.json", "corrections.json")):
        pytest.skip("sample_data holds labels, ground truth or corrected calls the reference was made without.")
    folder = linked_copy(reference.SAMPLE_DATA, tmp_path / "uploads" / "sample")
    assert convert(folder) == 6
    assert not list(folder.rglob("*.bmp")) and (folder / FIRST_FRAME_NAME).is_file()
    run = reference.run_folder(folder, tmp_path / "out")
    expected = reference.load("folder_sample_data")
    found = reference.differences({**expected["results"], "frames": "rois"}, run["results"])
    assert not found, "\n".join(found)
    assert not reference.differences(expected["excel"], run["excel"])


def test_a_small_session_shrunk_gives_its_results_and_the_same_labels_page(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    folder = linked_copy(small, tmp_path / "uploads" / "small")
    before = reference.run_folder(small, tmp_path / "before")
    page_before = pipeline.open_session(small, tmp_path / "page_before")
    assert convert(folder) == 3
    after = reference.run_folder(folder, tmp_path / "after")
    assert not reference.differences({**before["results"], "frames": "rois"}, after["results"])
    page_after = pipeline.open_session(folder, tmp_path / "page_after")
    assert page_after["mites"] == page_before["mites"] and page_after["zones"] == page_before["zones"]
    assert convert(folder) == 0  # nothing left to do


def test_ground_truth_and_a_poke_test_stay_as_they_were(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    folder = linked_copy(small, tmp_path / "uploads" / "small")
    out = tmp_path / "calibration"
    mites = pipeline.open_calibration(folder, out)["mites"]
    pipeline.save_ground_truth(out, {mites[0]["id"]: ["moving", "still", "still"], mites[1]["id"]: ["not_a_mite"] * 3})
    pipeline.edit_poke(out, "add", 0)
    pipeline.edit_poke(out, "set", 0, mite=mites[0]["id"], state="unmoved")
    dataset = dataset_library.read_dataset(pipeline.dataset_id(folder), folder.parent)
    scores = score_cache._score_mites(dataset, "outline_variability", folder, stabilize=True)
    truth, poke = pipeline.load_calibration_truth(out), pipeline.poke_view(out)
    before = reference.run_folder(folder, tmp_path / "before")
    assert mites[1]["id"] not in {mite["id"] for mite in before["results"]["mites"]}

    assert pipeline.finish_upload(folder.name, folder.parent)["converted"] == 3

    assert (folder / pipeline.GROUND_TRUTH_FILENAME).is_file() and (folder / pipeline.POKE_FILENAME).is_file()
    again = tmp_path / "calibration_again"
    pipeline.open_calibration(folder, again)
    assert pipeline.load_calibration_truth(again) == truth
    assert pipeline.poke_view(again) == poke
    after = reference.run_folder(folder, tmp_path / "after")
    assert not reference.differences({**before["results"], "frames": "rois"}, after["results"])
    # the dataset is the same mites, labels and scores
    shrunk = dataset_library.read_dataset(pipeline.dataset_id(folder), folder.parent)
    assert {k: shrunk[k] for k in ("mites", "truth", "times")} == {k: dataset[k] for k in ("mites", "truth", "times")}
    assert score_cache._score_mites(shrunk, "outline_variability", folder, stabilize=True) == scores


def test_recordings_added_later_join_the_shrunk_ones_and_a_cut_short_conversion_carries_on(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    names = DataLoader(small).recording_names
    folder = linked_copy(small, tmp_path / "uploads" / "small", recordings=2)
    assert convert(folder) == 2
    # the same folder dropped again with one more recording, and the frames of
    # one already shrunk, as a conversion stopped before removing them leaves them
    linked_copy(small, tmp_path / "again", recordings=3)
    for name in (names[0], names[2]):
        shutil.copytree(tmp_path / "again" / name, folder / name, copy_function=os.link)
    assert convert(folder) == 1
    assert RoiRecordings(folder).recording_names == names and not list(folder.rglob("*.bmp"))
    before = reference.run_folder(small, tmp_path / "before")
    after = reference.run_folder(folder, tmp_path / "after")
    assert not reference.differences({**before["results"], "frames": "rois"}, after["results"])


def test_an_older_recording_cannot_join_the_shrunk_ones(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    names = DataLoader(small).recording_names
    folder = tmp_path / "uploads" / "small"
    linked_copy(small, folder)
    shutil.rmtree(folder / names[0])
    convert(folder)
    shutil.copytree(small / names[0], folder / names[0])
    with pytest.raises(ValueError, match="older"):
        convert(folder)
    assert (folder / names[0]).is_dir()  # its frames stay


def test_without_mites_the_frames_stay_whole(tmp_path):
    folder = tmp_path / "uploads" / "blank"
    (folder / "2025-09-04-09-28-17_fps-30").mkdir(parents=True)
    shutil.copy2(reference.SAMPLE_DATA / ".settings.txt", folder / ".settings.txt")
    for index in range(3):
        cv2.imwrite(str(folder / "2025-09-04-09-28-17_fps-30" / f"frame_{index:06}.bmp"),
                    np.full((1544, 2064), 200, dtype=np.uint8))
    assert convert(folder) == 0
    assert not is_roi_session(folder) and len(list(folder.rglob("*.bmp"))) == 3


def test_dropping_a_shrunk_folder_again_sends_none_of_its_frames(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    linked_copy(small, tmp_path / "uploads" / "small")
    convert(tmp_path / "uploads" / "small")
    files = [{"path": str(path.relative_to(small)).replace("\\", "/"), "size": path.stat().st_size}
             for path in small.rglob("*") if path.is_file()]
    plan = pipeline.plan_upload("small", files, tmp_path / "uploads")
    assert plan["missing"] == []
