"""The calibration library: ground truth and a copy of the recordings saved
without scores, reopened, and scored with the metric in use when evaluated.

Sessions are built from a hand-written session file, and scoring is stubbed out
unless a test writes real frames, so nothing is decoded.
"""

import json
import shutil

import cv2
import numpy as np
import pytest

import pipeline
from classes.app_config import get_default_config


def make_session(tmp_path, name, n_mites, times=(0.0, 5.0)):
    """A calibration session as open_calibration() leaves it: a recording folder
    and an out_dir holding the detected mites. One zone, `n_mites` mites."""
    data_dir = tmp_path / name
    data_dir.mkdir()
    out_dir = tmp_path / f"out_{name}"
    out_dir.mkdir()
    stored = {
        "data_dir": str(data_dir),
        "times": list(times),
        "recordings": [{"name": f"r{i}", "fps": 30} for i in range(len(times))],
        "image": {"width": 100, "height": 100},
        "zones": [{"id": 0, "x1": 0, "y1": 0, "x2": 100, "y2": 100, "text_zone": None, "label": "control"}],
        "mites": [{"id": str(i), "zone_id": 0, "x": 10.0 * i + 10, "y": 10.0, "r": 3.0} for i in range(n_mites)],
    }
    (out_dir / pipeline.CALIBRATION_SESSION_NAME).write_text(json.dumps(stored), encoding="utf-8")
    (out_dir / pipeline.PREVIEW_NAME).write_bytes(b"jpeg")
    return data_dir, out_dir


@pytest.fixture
def library(tmp_path):
    return tmp_path / "library"


@pytest.fixture
def scorer(monkeypatch):
    """Stub out the decoding: `scorer.scores[dataset name]` is what scoring returns,
    and `scorer.calls` counts how often it ran."""
    class Scorer:
        scores = {}
        calls = []

        def __call__(self, dataset, metric, _recordings_dir, params=None):
            self.calls.append((dataset["name"], metric, params))
            return self.scores[dataset["name"]]

    stub = Scorer()
    monkeypatch.setattr(pipeline, "_score_mites", stub)
    return stub


def test_saving_ground_truth_adds_the_dataset_to_the_library(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 2)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)

    [listed] = pipeline.list_calibration_datasets(library)
    assert listed["id"] == pipeline.dataset_id(data_dir)
    assert (listed["name"], listed["n_mites"], listed["n_moving"], listed["n_still"]) == ("a", 1, 1, 1)
    assert listed["recordings_available"]
    assert (data_dir / pipeline.GROUND_TRUTH_FILENAME).is_file()


def test_the_library_keeps_no_scores(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    saved = json.loads((library / pipeline.dataset_id(data_dir) / pipeline.DATASET_NAME).read_text(encoding="utf-8"))
    assert "metric" not in saved
    assert "scores" not in saved["mites"][0]


def test_saving_the_same_folder_again_replaces_its_dataset(tmp_path, library):
    _data_dir, out_dir = make_session(tmp_path, "a", 2)
    pipeline.save_ground_truth(out_dir, {"0": ["still", None]}, library_dir=library)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"], "1": ["moving", None]}, library_dir=library)
    [listed] = pipeline.list_calibration_datasets(library)
    assert listed["n_mites"] == 2


def test_clearing_every_label_removes_the_dataset(tmp_path, library):
    _data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", None]}, library_dir=library)
    pipeline.save_ground_truth(out_dir, {}, library_dir=library)
    assert pipeline.list_calibration_datasets(library) == []


def test_a_saved_dataset_reopens_with_its_labels(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)

    reopened = tmp_path / "reopened"
    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), reopened, library_dir=library)
    assert view["truth"] == {"0": ["still", "moving"]}
    assert "scores" not in view["mites"][0]
    assert (reopened / pipeline.PREVIEW_NAME).is_file()
    # the reopened session saves back to the same dataset
    pipeline.save_ground_truth(reopened, {"0": ["moving", "moving"]}, library_dir=library)
    [listed] = pipeline.list_calibration_datasets(library)
    assert listed["n_moving"] == 2


def test_old_datasets_with_scores_are_scored_again(tmp_path, library, scorer):
    """A dataset saved when the library still kept scores: those are ignored."""
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    path = library / pipeline.dataset_id(data_dir) / pipeline.DATASET_NAME
    old = json.loads(path.read_text(encoding="utf-8"))
    old["metric"] = "some_old_metric"
    old["mites"][0]["scores"] = [100, 100]
    path.write_text(json.dumps(old), encoding="utf-8")

    scorer.scores = {"a": {"0": [1, 9]}}
    result = pipeline.evaluate_calibration(tmp_path / "report", [pipeline.dataset_id(data_dir)], library_dir=library)
    assert result["metric"] == get_default_config().mite.metric
    assert [row["score"] for row in result["observations"]] == [1, 9]


def test_evaluation_pools_the_chosen_datasets(tmp_path, library, scorer):
    a, out_a = make_session(tmp_path, "a", 1)
    b, out_b = make_session(tmp_path, "b", 2, times=(0.0, 6.0, 12.0))
    scorer.scores = {"a": {"0": [1, 9]}, "b": {"0": [2, 7, 5], "1": [3, 3, 3]}}
    pipeline.save_ground_truth(out_a, {"0": ["still", "moving"]}, library_dir=library)
    pipeline.save_ground_truth(out_b, {"0": ["still", "moving"], "1": ["still", "not_a_mite"]}, library_dir=library)

    ids = [pipeline.dataset_id(a), pipeline.dataset_id(b)]
    result = pipeline.evaluate_calibration(tmp_path / "report", ids, library_dir=library)
    assert result["n_mites"] == 2  # mite "0" of each; b's mite "1" is not a mite
    assert (result["n_moving"], result["n_still"]) == (2, 2)
    assert result["n_not_a_mite"] == 1
    assert result["times"] == [0.0, 5.5, 12.0]
    assert {row["dataset"] for row in result["observations"]} == set(ids)
    assert [z["dataset"] for z in result["zones"]] == sorted(ids)

    only_a = pipeline.evaluate_calibration(tmp_path / "report", ids[:1], library_dir=library)
    assert only_a["n_moving"] + only_a["n_still"] == 2


def test_scores_are_cached_per_version_of_the_metric(tmp_path, library, scorer, monkeypatch):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    ids = [pipeline.dataset_id(data_dir)]

    pipeline.evaluate_calibration(tmp_path / "report", ids, library_dir=library)
    pipeline.evaluate_calibration(tmp_path / "report", ids, library_dir=library)
    assert len(scorer.calls) == 1

    # Editing the scoring code is a new version of the metric: scored again.
    monkeypatch.setattr(pipeline.inspect, "getsource", lambda _obj: "tuned")
    pipeline.evaluate_calibration(tmp_path / "report", ids, library_dir=library)
    assert len(scorer.calls) == 2


RECORDING = "2025-01-01-00-00-00_fps-30"


def write_frames(data_dir):
    """One real recording: the box of the mite at (40, 10) flickers, the rest is still."""
    (data_dir / RECORDING).mkdir(parents=True, exist_ok=True)
    (data_dir / ".settings.txt").write_text("fps=30")
    for index in range(4):
        frame = np.full((40, 60, 3), 100, np.uint8)
        frame[7:13, 37:43] = 100 + 50 * (index % 2)
        cv2.imwrite(str(data_dir / RECORDING / f"{index:03d}.bmp"), frame)


def test_scoring_reads_each_mite_box_from_the_frames(tmp_path):
    data_dir = tmp_path / "rec"
    write_frames(data_dir)
    dataset = {
        "name": "rec",
        "data_dir": str(data_dir),
        "recordings": [{"name": RECORDING, "fps": 30}],
        "mites": [{"id": "0", "x": 10.0, "y": 10.0, "r": 3.0}, {"id": "1", "x": 40.0, "y": 10.0, "r": 3.0}],
    }
    scores = pipeline._score_mites(dataset, "mean_diff", data_dir)
    assert scores["0"] == [0.0]
    assert scores["1"] == [50.0]


def test_the_library_keeps_a_copy_of_the_recording_folder(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    write_frames(data_dir)
    (data_dir / "unrelated").mkdir()
    (data_dir / "unrelated" / "notes.txt").write_text("not a recording")
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)

    copy = library / pipeline.dataset_id(data_dir) / pipeline.RECORDINGS_DIRNAME
    assert sorted(p.name for p in (copy / RECORDING).iterdir()) == ["000.bmp", "001.bmp", "002.bmp", "003.bmp"]
    assert (copy / ".settings.txt").is_file()
    assert (copy / pipeline.GROUND_TRUTH_FILENAME).is_file()
    assert not (copy / "unrelated").exists()

    # the ground truth changes, the copy follows
    pipeline.save_ground_truth(out_dir, {"0": ["moving", "moving"]}, library_dir=library)
    assert (copy / pipeline.GROUND_TRUTH_FILENAME).read_text() == (data_dir / pipeline.GROUND_TRUTH_FILENAME).read_text()


def test_a_dataset_works_from_its_copy_once_the_original_is_gone(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 4, times=(0.0,))
    write_frames(data_dir)
    session = json.loads((out_dir / pipeline.CALIBRATION_SESSION_NAME).read_text(encoding="utf-8"))
    session["recordings"] = [{"name": RECORDING, "fps": 30}]
    (out_dir / pipeline.CALIBRATION_SESSION_NAME).write_text(json.dumps(session), encoding="utf-8")
    pipeline.save_ground_truth(out_dir, {"0": ["still"], "3": ["moving"]}, library_dir=library)
    shutil.rmtree(data_dir)
    key = pipeline.dataset_id(data_dir)

    [listed] = pipeline.list_calibration_datasets(library)
    assert listed["recordings_available"]
    result = pipeline.evaluate_calibration(tmp_path / "report", [key], library_dir=library)
    assert {row["mite_id"]: row["movement"] for row in result["observations"]} == {"0": "still", "3": "moving"}

    reopened = tmp_path / "reopened"
    view = pipeline.open_saved_calibration(key, reopened, library_dir=library)
    assert view["recordings_available"]
    clip = pipeline.calibration_clip(reopened, 0, 0, library_dir=library)
    assert len(clip["frames"]) == 4
    # labels saved now land next to the copy
    pipeline.save_ground_truth(reopened, {"0": ["moving"]}, library_dir=library)
    copy = library / key / pipeline.RECORDINGS_DIRNAME
    assert json.loads((copy / pipeline.GROUND_TRUTH_FILENAME).read_text())[0]["truth"] == ["moving"]


def test_recordings_with_no_copy_cannot_be_scored(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    shutil.rmtree(data_dir)
    shutil.rmtree(library / pipeline.dataset_id(data_dir) / pipeline.RECORDINGS_DIRNAME)
    with pytest.raises(FileNotFoundError, match="no copy"):
        pipeline.evaluate_calibration(tmp_path / "report", [pipeline.dataset_id(data_dir)], library_dir=library)


def test_dataset_ids_cannot_leave_the_library(library):
    with pytest.raises(ValueError):
        pipeline.open_saved_calibration("../outside", library / "x", library_dir=library)


def test_deleting_a_dataset(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    pipeline.delete_calibration_dataset(pipeline.dataset_id(data_dir), library_dir=library)
    assert pipeline.list_calibration_datasets(library) == []
    assert (data_dir / pipeline.GROUND_TRUTH_FILENAME).is_file()


def test_another_movement_score_can_be_tried_without_editing_the_config(tmp_path, library, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    ids = [pipeline.dataset_id(data_dir)]

    result = pipeline.evaluate_calibration(tmp_path / "report", ids, "topN_variability", {"n": 25}, library_dir=library)
    assert (result["metric"], result["metric_params"]) == ("topN_variability", {"n": 25})
    assert scorer.calls[-1] == ("a", "topN_variability", {"n": 25})
    assert result["in_use"]["metric"] == get_default_config().mite.metric
    assert not result["threshold_fits"]

    # other parameters are another score: scored again, not taken from the cache
    pipeline.evaluate_calibration(tmp_path / "report", ids, "topN_variability", {"n": 5}, library_dir=library)
    assert len(scorer.calls) == 2

    in_use = pipeline.evaluate_calibration(tmp_path / "report", ids, library_dir=library)
    assert in_use["threshold_fits"]


def test_bad_movement_scores_are_refused(tmp_path, library, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    ids = [pipeline.dataset_id(data_dir)]
    for metric, params in [("no_such_metric", None), ("topN_variability", {"k": 3}),
                           ("topN_variability", {"n": 0}), ("topN_variability", {"n": 2.5})]:
        with pytest.raises(ValueError):
            pipeline.evaluate_calibration(tmp_path / "report", ids, metric, params, library_dir=library)


def test_every_observation_says_where_it_comes_from(tmp_path, library, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    result = pipeline.evaluate_calibration(tmp_path / "report", [pipeline.dataset_id(data_dir)], library_dir=library)
    assert [(row["dataset_name"], row["recording_name"]) for row in result["observations"]] == [("a", "r0"), ("a", "r1")]
    [summary] = result["datasets"]
    assert summary["image"] == {"width": 100, "height": 100}
    assert [zone["id"] for zone in summary["zones"]] == [0]


def test_a_session_can_switch_to_another_saved_dataset(tmp_path, library):
    a, out_a = make_session(tmp_path, "a", 1)
    b, out_b = make_session(tmp_path, "b", 2)
    pipeline.save_ground_truth(out_a, {"0": ["still", "moving"]}, library_dir=library)
    pipeline.save_ground_truth(out_b, {"1": ["moving", "moving"]}, library_dir=library)

    session = tmp_path / "session"
    pipeline.open_saved_calibration(pipeline.dataset_id(a), session, library_dir=library)
    view = pipeline.open_saved_calibration(pipeline.dataset_id(b), session, library_dir=library)
    assert view["dataset_id"] == pipeline.dataset_id(b)
    assert view["truth"] == {"1": ["moving", "moving"]}
    assert view["recordings"] == ["r0", "r1"]
    # labels saved now go to b, and a is untouched
    pipeline.save_ground_truth(session, {"1": ["still", "moving"]}, library_dir=library)
    counts = {d["name"]: (d["n_moving"], d["n_still"]) for d in pipeline.list_calibration_datasets(library)}
    assert counts == {"a": (1, 1), "b": (1, 1)}
    assert pipeline.dataset_preview(pipeline.dataset_id(b), library_dir=library).endswith(pipeline.PREVIEW_NAME)


def test_a_save_keeps_what_another_window_changed(tmp_path, library):
    """Saving the mites changed on screen leaves the others as saved, e.g. a
    detection marked "not a mite" on the labelling page since the page opened."""
    data_dir, out_dir = make_session(tmp_path, "a", 3)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    pipeline.set_rejected(data_dir, 30.0, 10.0, True, library_dir=library)  # mite "2"

    truth = pipeline.update_ground_truth(out_dir, {"0": ["moving", "moving"]}, library_dir=library)
    assert truth == {"0": ["moving", "moving"], "2": ["not_a_mite", "not_a_mite"]}
    assert pipeline.load_calibration_truth(out_dir, library_dir=library) == truth

    # a mite cleared on screen is cleared in the saved ground truth too
    truth = pipeline.update_ground_truth(out_dir, {"0": [None, None]}, library_dir=library)
    assert truth == {"2": ["not_a_mite", "not_a_mite"]}


def test_marking_a_detection_updates_the_saved_dataset(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 3)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]}, library_dir=library)
    pipeline.set_rejected(data_dir, 30.0, 10.0, True, library_dir=library)

    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), tmp_path / "reopened", library_dir=library)
    assert view["truth"] == {"0": ["still", "moving"], "2": ["not_a_mite", "not_a_mite"]}

    pipeline.set_rejected(data_dir, 30.0, 10.0, False, library_dir=library)
    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), tmp_path / "reopened", library_dir=library)
    assert view["truth"] == {"0": ["still", "moving"]}


def test_a_save_keeps_entries_of_detections_not_in_the_session(tmp_path, library):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    far = {"x": 90.0, "y": 90.0, "truth": "not_a_mite"}
    (data_dir / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([far]), encoding="utf-8")
    pipeline.update_ground_truth(out_dir, {"0": ["still", None]}, library_dir=library)
    assert far in json.loads((data_dir / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8"))
