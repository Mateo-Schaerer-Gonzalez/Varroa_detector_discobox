"""Marking a detection as not a mite on the labelling page, and taking it back."""

import json
import shutil
from pathlib import Path

import pipeline


def saved(data_dir):
    return json.loads((data_dir / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8"))


def test_marking_adds_a_rejected_entry(tmp_path):
    pipeline.set_rejected(tmp_path, 50.0, 60.0, True)
    assert saved(tmp_path) == [{"x": 50.0, "y": 60.0, "truth": "not_a_mite"}]


def test_marking_twice_keeps_one_entry(tmp_path):
    pipeline.set_rejected(tmp_path, 50.0, 60.0, True)
    pipeline.set_rejected(tmp_path, 52.0, 60.0, True)
    assert len(saved(tmp_path)) == 1


def test_taking_the_mark_back_removes_it(tmp_path):
    pipeline.set_rejected(tmp_path, 50.0, 60.0, True)
    pipeline.set_rejected(tmp_path, 51.0, 60.0, False)
    assert saved(tmp_path) == []


def test_other_ground_truth_is_kept(tmp_path):
    other = {"x": 10.0, "y": 10.0, "truth": ["moving", "still"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([other]), encoding="utf-8")
    pipeline.set_rejected(tmp_path, 50.0, 60.0, True)
    pipeline.set_rejected(tmp_path, 50.0, 60.0, False)
    assert saved(tmp_path) == [other]


def test_marking_a_calibrated_mite_replaces_its_labels(tmp_path):
    entry = {"x": 50.0, "y": 60.0, "truth": ["moving", "still"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([entry]), encoding="utf-8")
    pipeline.set_rejected(tmp_path, 50.0, 60.0, True)
    assert saved(tmp_path) == [{"x": 50.0, "y": 60.0, "truth": "not_a_mite"}]


def test_unmarking_clears_only_the_rejection(tmp_path):
    entry = {"x": 50.0, "y": 60.0, "truth": ["not_a_mite", "moving"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([entry]), encoding="utf-8")
    pipeline.set_rejected(tmp_path, 50.0, 60.0, False)
    assert saved(tmp_path) == [{"x": 50.0, "y": 60.0, "truth": [None, "moving"]}]


def test_taking_the_mark_back_restores_the_labels_it_replaced(tmp_path):
    entry = {"x": 50.0, "y": 60.0, "truth": ["moving", "still"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([entry]), encoding="utf-8")
    replaced = pipeline.set_rejected(tmp_path, 50.0, 60.0, True)
    assert replaced == ["moving", "still"]
    pipeline.set_rejected(tmp_path, 51.0, 60.0, False, restore=replaced)
    assert saved(tmp_path) == [entry]


def test_marking_a_detection_already_marked_replaces_nothing(tmp_path):
    assert pipeline.set_rejected(tmp_path, 50.0, 60.0, True) is None
    assert pipeline.set_rejected(tmp_path, 50.0, 60.0, True) is None


def test_restoring_keeps_labels_given_since(tmp_path):
    # the mark was taken back in the calibration window and the mite labelled there
    entry = {"x": 50.0, "y": 60.0, "truth": ["moving", "still"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([entry]), encoding="utf-8")
    replaced = pipeline.set_rejected(tmp_path, 50.0, 60.0, True)
    relabelled = {"x": 50.0, "y": 60.0, "truth": ["still", "still"]}
    (tmp_path / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([relabelled]), encoding="utf-8")
    pipeline.set_rejected(tmp_path, 50.0, 60.0, False, restore=replaced)
    assert saved(tmp_path) == [relabelled]


def test_the_labelling_page_reads_marks_kept_only_in_the_library(tmp_path):
    """A folder without its ground_truth.json, e.g. dropped again after its copy in
    recordings/ was deleted, shows the detections its saved dataset marks "not a mite", as
    the calibration window does."""
    root = Path(pipeline.__file__).resolve().parent
    data_dir = tmp_path / "plate"
    recording = next(path for path in sorted((root / "sample_data").iterdir()) if path.is_dir())
    (data_dir / recording.name).mkdir(parents=True)
    shutil.copy(sorted(recording.glob("*.bmp"))[0], data_dir / recording.name)
    coords, library = root / pipeline.DEFAULT_COORDS_FILE, tmp_path / "library"
    [first, *_] = pipeline.open_session(data_dir, tmp_path / "out", coords, library_dir=library)["mites"]

    dataset = library / pipeline.dataset_id(data_dir)
    dataset.mkdir(parents=True)
    (dataset / pipeline.DATASET_NAME).write_text(json.dumps({
        "data_dir": str(data_dir), "times": [0.0], "mites": [{**first, "id": "0"}], "truth": {"0": ["not_a_mite"]},
    }), encoding="utf-8")
    mites = pipeline.open_session(data_dir, tmp_path / "out", coords, library_dir=library)["mites"]
    assert next(mite for mite in mites if mite["id"] == first["id"])["rejected"]
