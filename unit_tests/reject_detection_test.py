"""Marking a detection as not a mite on the labelling page, and taking it back."""

import json

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
