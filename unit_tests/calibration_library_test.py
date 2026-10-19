"""The datasets: the recordings with ground truth saved next to them, without
scores, reopened, and scored with the metric in use when evaluated.

Sessions are built from a hand-written session file, which stands in for what
the folder's recordings hold (the `described` fixture), and scoring is stubbed
out unless a test writes real frames, so nothing is decoded.
"""

import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest

import pipeline
from classes.app_config import get_default_config


# Recording folder -> the session file standing in for what its recordings hold.
SESSIONS = {}


def make_session(tmp_path, name, n_mites, times=(0.0, 5.0)):
    """A calibration session as open_calibration() leaves it: a recording folder,
    in tmp_path/recordings, and an out_dir holding the detected mites. One
    zone, `n_mites` mites."""
    data_dir = tmp_path / "recordings" / name
    data_dir.mkdir(parents=True)
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
    SESSIONS[str(data_dir.resolve())] = out_dir / pipeline.CALIBRATION_SESSION_NAME
    return data_dir, out_dir


@pytest.fixture
def recordings(tmp_path):
    return tmp_path / "recordings"


@pytest.fixture(autouse=True)
def described(monkeypatch):
    """What the recordings of a folder made by make_session() hold: its session
    file, as it is now, with a blank first frame."""
    describe = pipeline._describe_calibration

    def stand_in(data_dir, coords_file=None, names=None):
        session = SESSIONS.get(str(Path(data_dir).resolve()))
        if session is None:
            return describe(data_dir, coords_file, names)
        stored = json.loads(session.read_text(encoding="utf-8"))
        return {**stored, "data_dir": str(Path(data_dir).resolve())}, np.zeros((100, 100), np.uint8)

    monkeypatch.setattr(pipeline, "_describe_calibration", stand_in)


@pytest.fixture
def scorer(monkeypatch):
    """Stub out the decoding: `scorer.scores[dataset name]` is what scoring returns,
    and `scorer.calls` counts how often it ran."""
    class Scorer:
        scores = {}
        calls = []

        stabilized = []

        def __call__(self, dataset, metric, _recordings_dir, params=None, stabilize=False):
            self.calls.append((dataset["name"], metric, params))
            self.stabilized.append(stabilize)
            return self.scores[dataset["name"]]

    stub = Scorer()
    monkeypatch.setattr(pipeline, "_score_mites", stub)
    return stub


def test_saving_ground_truth_adds_the_dataset_to_the_library(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "a", 2)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})

    [listed] = pipeline.list_calibration_datasets(recordings)
    assert listed["id"] == pipeline.dataset_id(data_dir) == "a"
    assert (listed["name"], listed["n_mites"], listed["n_moving"], listed["n_still"]) == ("a", 1, 1, 1)
    assert (data_dir / pipeline.GROUND_TRUTH_FILENAME).is_file()
    assert not (tmp_path / "calibration_data").exists()


def test_saving_the_same_folder_again_replaces_its_dataset(tmp_path, recordings):
    _data_dir, out_dir = make_session(tmp_path, "a", 2)
    pipeline.save_ground_truth(out_dir, {"0": ["still", None]})
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"], "1": ["moving", None]})
    [listed] = pipeline.list_calibration_datasets(recordings)
    assert listed["n_mites"] == 2


def test_clearing_every_label_removes_the_dataset(tmp_path, recordings):
    _data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", None]})
    pipeline.save_ground_truth(out_dir, {})
    assert pipeline.list_calibration_datasets(recordings) == []


def test_a_saved_dataset_reopens_with_its_labels(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})

    reopened = tmp_path / "reopened"
    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), reopened, recordings_root=recordings)
    assert view["truth"] == {"0": ["still", "moving"]}
    assert "scores" not in view["mites"][0]
    assert (reopened / pipeline.PREVIEW_NAME).is_file()
    # the reopened session saves back to the same dataset
    pipeline.save_ground_truth(reopened, {"0": ["moving", "moving"]})
    [listed] = pipeline.list_calibration_datasets(recordings)
    assert listed["n_moving"] == 2


def test_evaluation_pools_the_chosen_datasets(tmp_path, recordings, scorer):
    a, out_a = make_session(tmp_path, "a", 1)
    b, out_b = make_session(tmp_path, "b", 2, times=(0.0, 6.0, 12.0))
    scorer.scores = {"a": {"0": [1, 9]}, "b": {"0": [2, 7, 5], "1": [3, 3, 3]}}
    pipeline.save_ground_truth(out_a, {"0": ["still", "moving"]})
    pipeline.save_ground_truth(out_b, {"0": ["still", "moving"], "1": ["still", "not_a_mite"]})

    ids = [pipeline.dataset_id(a), pipeline.dataset_id(b)]
    result = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    assert result["n_mites"] == 2  # mite "0" of each; b's mite "1" is not a mite
    assert (result["n_moving"], result["n_still"]) == (2, 2)
    assert result["n_not_a_mite"] == 1
    assert result["times"] == [0.0, 5.5, 12.0]
    assert {row["dataset"] for row in result["observations"]} == set(ids)
    assert [z["dataset"] for z in result["zones"]] == sorted(ids)

    only_a = pipeline.evaluate_calibration(tmp_path / "report", ids[:1], recordings_root=recordings)
    assert only_a["n_moving"] + only_a["n_still"] == 2


def test_scores_are_cached_per_version_of_the_metric(tmp_path, recordings, scorer, monkeypatch):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    ids = [pipeline.dataset_id(data_dir)]

    pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    assert len(scorer.calls) == 1

    # Editing the scoring code is a new version of the metric: scored again.
    monkeypatch.setattr(pipeline.inspect, "getsource", lambda _obj: "tuned")
    pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
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


def test_the_benchmark_reads_each_mite_box_from_the_frames(tmp_path):
    data_dir = tmp_path / "rec"
    write_frames(data_dir)
    dataset = {
        "name": "rec",
        "data_dir": str(data_dir),
        "recordings": [{"name": RECORDING, "fps": 30}],
        "mites": [{"id": "0", "x": 10.0, "y": 10.0, "r": 3.0}, {"id": "1", "x": 40.0, "y": 10.0, "r": 3.0}],
    }
    assert pipeline._benchmark_mites(dataset, data_dir) == {"0": [False], "1": [True]}


def test_a_report_with_the_benchmark_compares_it_on_the_same_observations(tmp_path, recordings, scorer, monkeypatch):
    data_dir, out_dir = make_session(tmp_path, "a", 2, times=(0.0, 5.0, 10.0))
    scorer.scores = {"a": {"0": [9, 9, 1], "1": [1, 1, 1]}}
    pipeline.save_ground_truth(out_dir, {"0": ["moving", "moving", "still"], "1": ["still", "still", "still"]})
    runs = []

    def benchmark(dataset, _recordings_dir):
        runs.append(dataset["name"])
        return {"0": [True, True, True], "1": [True, False, False]}

    monkeypatch.setattr(pipeline, "_benchmark_mites", benchmark)
    drawn = []
    monkeypatch.setattr(pipeline, "_benchmark_circles", lambda _recordings_dir, name: drawn.append(name) or [[10, 10]])
    ids = [pipeline.dataset_id(data_dir)]

    result = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, benchmark=True)
    called = result["benchmark"]
    assert (called["moving_called_moving"], called["still_called_moving"], called["moving_called_still"]) == (2, 2, 0)
    assert called["precision"] == pytest.approx(0.5) and called["sensitivity"] == 1
    assert [row["benchmark_call"] for row in result["observations"]] == ["moving", "moving", "moving", "moving", "still", "still"]
    # mite 0 never stops by the benchmark; mite 1 moved once and is dead by the next recording
    assert result["survival"]["benchmark"]["alive"] == [100.0, 50.0, 50.0]
    assert "benchmark" in result["groups"][0]["survival"]
    # so by the benchmark both die one recording later than by the labels; the detector is right
    assert (result["death_error"]["benchmark"]["mae"], result["death_error"]["benchmark"]["n_late"]) == (1.0, 2)
    assert (result["death_error"]["current"]["mae"], result["death_error"]["current"]["n_exact"]) == (0.0, 2)

    # The last recording, every mite with both calls; the benchmark's circles on it are drawn once.
    last = result["datasets"][0]["last_recording"]
    assert (last["recording"], last["recording_name"], last["time"]) == (2, "r2", 10.0)
    assert [(m["id"], m["call"], m["benchmark_call"], m["movement"]) for m in last["mites"]] == [
        ("0", "still", "moving", "still"), ("1", "still", "still", "still")]
    assert last["mites"][0]["box"] == [7, 7, 13, 13]
    assert (last["circles"], last["circle_radius"]) == ([[10, 10]], 20)

    # Its calls are kept with the dataset, like the scores.
    again = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, benchmark=True)
    assert runs == ["a"] and drawn == ["r2"]
    assert again["datasets"][0]["last_recording"]["circles"] == [[10, 10]]

    without = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    assert without["benchmark"] is None and "benchmark" not in without["survival"]
    assert set(without["death_error"]) == {"current", "suggested"}
    assert "benchmark_call" not in without["observations"][0]
    last = without["datasets"][0]["last_recording"]
    assert last["circles"] is None and "benchmark_call" not in last["mites"][0]


def test_cached_scores_and_calls_are_made_again_once_the_run_has_recorded_more(tmp_path, monkeypatch):
    mites = [{"id": "0", "x": 10.0, "y": 10.0, "r": 3.0}]
    dataset = {"name": "rec", "data_dir": str(tmp_path), "mites": mites, "recordings": [{"name": "r0", "fps": 30}]}
    made = []

    def per_recording(value):
        return lambda dataset, *_args: made.append(len(dataset["recordings"])) or {"0": [value] * len(dataset["recordings"])}

    monkeypatch.setattr(pipeline, "_benchmark_mites", per_recording(True))
    monkeypatch.setattr(pipeline, "_score_mites", per_recording(1.0))
    monkeypatch.setattr(pipeline, "_brightness_mites", per_recording(50.0))
    fetch = [lambda: pipeline._dataset_benchmark("rec", dataset),
             lambda: pipeline._dataset_scores("rec", dataset, "outline_variability", {}),
             lambda: pipeline._dataset_brightness("rec", dataset, 16)]
    assert [f() for f in fetch] == [{"0": [True]}, {"0": [1.0]}, {"0": [50.0]}]
    assert [f() for f in fetch] == [{"0": [True]}, {"0": [1.0]}, {"0": [50.0]}] and made == [1, 1, 1]

    # A live run labelled while it ran records on: the caches it left are too short for it now.
    dataset["recordings"].append({"name": "r1", "fps": 30})
    assert [f() for f in fetch] == [{"0": [True, True]}, {"0": [1.0, 1.0]}, {"0": [50.0, 50.0]}]
    assert made == [1, 1, 1, 2, 2, 2]


def test_the_last_recording_leaves_out_what_is_not_a_mite_and_keeps_the_unlabelled(tmp_path, recordings, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 3)
    scorer.scores = {"a": {"0": [9, 9], "1": [1, 1], "2": [9, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["moving", None], "1": ["still", "still"], "2": "not_a_mite"})
    result = pipeline.evaluate_calibration(tmp_path / "report", [pipeline.dataset_id(data_dir)], recordings_root=recordings)
    assert [(m["id"], m["call"], m["movement"]) for m in result["datasets"][0]["last_recording"]["mites"]] == [
        ("0", "moving", None), ("1", "still", "still")]


def test_a_saved_dataset_plays_its_whole_plate(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "rec", 1, times=(0.0,))
    write_frames(data_dir)
    stored = json.loads((out_dir / pipeline.CALIBRATION_SESSION_NAME).read_text(encoding="utf-8"))
    stored["recordings"] = [{"name": RECORDING, "fps": 30}]
    (out_dir / pipeline.CALIBRATION_SESSION_NAME).write_text(json.dumps(stored), encoding="utf-8")
    pipeline.save_ground_truth(out_dir, {"0": ["still"]})
    key = pipeline.dataset_id(data_dir)

    clip = pipeline.dataset_clip(tmp_path / "report", key, 0, recordings_root=recordings)
    assert (clip["x"], clip["y"], clip["width"], clip["height"]) == (0, 0, 60, 40)
    assert len(clip["frames"]) == 4 and (tmp_path / "report" / clip["frames"][0]).is_file()
    with pytest.raises(ValueError):
        pipeline.dataset_clip(tmp_path / "report", key, 1, recordings_root=recordings)


def test_recordings_gone_cannot_be_scored(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    shutil.rmtree(data_dir)
    with pytest.raises(FileNotFoundError, match="No recording called a"):
        pipeline.evaluate_calibration(tmp_path / "report", [pipeline.dataset_id(data_dir)], recordings_root=recordings)


def test_dataset_ids_cannot_leave_recordings(recordings):
    with pytest.raises(ValueError):
        pipeline.open_saved_calibration("../outside", recordings / "x", recordings_root=recordings)


def test_deleting_a_dataset(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    pipeline.edit_poke(out_dir, "add", 0)
    (data_dir / pipeline.SCORES_DIRNAME).mkdir()
    pipeline.delete_calibration_dataset(pipeline.dataset_id(data_dir), recordings_root=recordings)
    assert pipeline.list_calibration_datasets(recordings) == []
    # its ground truth, poke test and scores go; its recordings stay
    assert data_dir.is_dir() and not any(data_dir.iterdir())
    with pytest.raises(FileNotFoundError):
        pipeline.delete_calibration_dataset("a", recordings_root=recordings)


def test_another_movement_score_can_be_tried_without_editing_the_config(tmp_path, recordings, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    ids = [pipeline.dataset_id(data_dir)]

    result = pipeline.evaluate_calibration(tmp_path / "report", ids, "topN_variability", {"n": 25}, recordings_root=recordings)
    assert (result["metric"], result["metric_params"]) == ("topN_variability", {"n": 25})
    assert scorer.calls[-1] == ("a", "topN_variability", {"n": 25})
    assert result["in_use"]["metric"] == get_default_config().mite.metric
    assert not result["threshold_fits"]

    # other parameters are another score: scored again, not taken from the cache
    pipeline.evaluate_calibration(tmp_path / "report", ids, "topN_variability", {"n": 5}, recordings_root=recordings)
    assert len(scorer.calls) == 2

    in_use = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    assert in_use["threshold_fits"]


def test_plate_stabilization_can_be_tried_without_editing_the_config(tmp_path, recordings, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    scorer.stabilized = []
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    ids = [pipeline.dataset_id(data_dir)]
    in_config = get_default_config().mite.stabilize_plate

    result = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    assert result["stabilize_plate"] == result["in_use"]["stabilize_plate"] == in_config
    assert result["threshold_fits"]

    other = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, stabilize=not in_config)
    assert other["stabilize_plate"] == (not in_config)
    assert not other["threshold_fits"]
    # scored again, not taken from the cache
    assert scorer.stabilized == [in_config, not in_config]


def test_the_normalisations_can_be_tried_without_editing_the_config(tmp_path, recordings, scorer, monkeypatch):
    data_dir, out_dir = make_session(tmp_path, "a", 3, times=(0.0, 5.0, 10.0))
    # mite 1 is still on a high floor; mite 2 was marked not a mite
    scorer.scores = {"a": {"0": [2.0, 2.0, 5.0], "1": [2.6, 2.8, 2.6], "2": [9.0, 9.0, 9.0]}}
    truth = {"0": ["still", "still", "moving"], "1": ["still", "still", "still"], "2": ["not_a_mite"] * 3}
    pipeline.save_ground_truth(out_dir, truth)
    ids = [pipeline.dataset_id(data_dir)]
    mite_config = get_default_config().mite
    monkeypatch.setattr(mite_config, "normalize_floor", False)
    monkeypatch.setattr(mite_config, "normalize_brightness", False)

    def scores(result):
        return {(row["mite_id"], row["recording"]): row["score"] for row in result["observations"]}

    plain = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    assert (plain["normalize_floor"], plain["normalize_brightness"], plain["threshold_fits"]) == (False, False, True)
    assert scores(plain)[("1", 1)] == 2.8

    floor = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, normalize_floor=True)
    assert floor["normalize_floor"] and not floor["threshold_fits"]
    # the floors, 2.0 and 2.6, both moved to 2.3; the detection that is no mite counts in neither
    assert [scores(floor)[("1", r)] for r in range(3)] == pytest.approx([2.3, 2.5, 2.3])
    assert [scores(floor)[("0", r)] for r in range(3)] == pytest.approx([2.3, 2.3, 5.3])

    monkeypatch.setattr(pipeline, "_brightness_mites", lambda dataset, _dir, pad=0, stabilize=False:
                        {"0": [100.0] * 3, "1": [130.0] * 3, "2": [50.0] * 3})
    bright = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, normalize_brightness=True)
    assert bright["normalize_brightness"] and not bright["normalize_floor"]
    # the typical brightness of the two mites is 115
    assert scores(bright)[("0", 2)] == pytest.approx(5.75) and scores(bright)[("1", 0)] == pytest.approx(2.3)

    # config.yaml's are used unless others are given
    monkeypatch.setattr(mite_config, "normalize_floor", True)
    in_use = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings)
    assert in_use["normalize_floor"] and in_use["in_use"]["normalize_floor"] and in_use["threshold_fits"]
    assert scores(in_use) == scores(floor)


def test_bad_movement_scores_are_refused(tmp_path, recordings, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    ids = [pipeline.dataset_id(data_dir)]
    for metric, params in [("no_such_metric", None), ("topN_variability", {"k": 3}),
                           ("topN_variability", {"n": 0}), ("topN_variability", {"n": 2.5})]:
        with pytest.raises(ValueError):
            pipeline.evaluate_calibration(tmp_path / "report", ids, metric, params, recordings_root=recordings)


def test_every_observation_says_where_it_comes_from(tmp_path, recordings, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [1, 9]}}
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    result = pipeline.evaluate_calibration(tmp_path / "report", [pipeline.dataset_id(data_dir)], recordings_root=recordings)
    assert [(row["dataset_name"], row["recording_name"]) for row in result["observations"]] == [("a", "r0"), ("a", "r1")]
    [summary] = result["datasets"]
    assert summary["image"] == {"width": 100, "height": 100}
    assert [zone["id"] for zone in summary["zones"]] == [0]


def test_a_session_can_switch_to_another_saved_dataset(tmp_path, recordings):
    a, out_a = make_session(tmp_path, "a", 1)
    b, out_b = make_session(tmp_path, "b", 2)
    pipeline.save_ground_truth(out_a, {"0": ["still", "moving"]})
    pipeline.save_ground_truth(out_b, {"1": ["moving", "moving"]})

    session = tmp_path / "session"
    pipeline.open_saved_calibration(pipeline.dataset_id(a), session, recordings_root=recordings)
    view = pipeline.open_saved_calibration(pipeline.dataset_id(b), session, recordings_root=recordings)
    assert view["dataset_id"] == pipeline.dataset_id(b)
    assert view["truth"] == {"1": ["moving", "moving"]}
    assert view["recordings"] == ["r0", "r1"]
    # labels saved now go to b, and a is untouched
    pipeline.save_ground_truth(session, {"1": ["still", "moving"]})
    counts = {d["name"]: (d["n_moving"], d["n_still"]) for d in pipeline.list_calibration_datasets(recordings)}
    assert counts == {"a": (1, 1), "b": (1, 1)}
    # its first frame, written into its results when they have none yet
    write_frames(b)
    preview = pipeline.dataset_preview(pipeline.dataset_id(b), recordings, tmp_path / "results")
    assert preview == str(tmp_path / "results" / "b" / pipeline.PREVIEW_NAME) and Path(preview).is_file()


def test_a_save_keeps_what_another_window_changed(tmp_path, recordings):
    """Saving the mites changed on screen leaves the others as saved, e.g. a
    detection marked "not a mite" on the labelling page since the page opened."""
    data_dir, out_dir = make_session(tmp_path, "a", 3)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    pipeline.set_rejected(data_dir, 30.0, 10.0, True)  # mite "2"

    truth = pipeline.update_ground_truth(out_dir, {"0": ["moving", "moving"]})
    assert truth == {"0": ["moving", "moving"], "2": ["not_a_mite", "not_a_mite"]}
    assert pipeline.load_calibration_truth(out_dir) == truth

    # a mite cleared on screen is cleared in the saved ground truth too
    truth = pipeline.update_ground_truth(out_dir, {"0": [None, None]})
    assert truth == {"2": ["not_a_mite", "not_a_mite"]}


def test_a_save_keeps_other_recordings_of_the_same_mite(tmp_path, recordings):
    """Only the recordings changed on screen are saved, so a page that has not
    caught up with a change to another recording of the same mite keeps it."""
    data_dir, out_dir = make_session(tmp_path, "a", 1, times=(0.0, 5.0, 10.0))
    pipeline.save_ground_truth(out_dir, {"0": ["still", "still", "still"]})
    pipeline.update_ground_truth(out_dir, {"0": {0: "moving"}})
    truth = pipeline.update_ground_truth(out_dir, {"0": {2: "moving"}})
    assert truth == {"0": ["moving", "still", "moving"]}
    assert pipeline.load_calibration_truth(out_dir) == truth


def test_a_detection_marked_by_mistake_and_unmarked_keeps_its_labels(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "a", 2)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"], "1": ["moving", "moving"]})
    replaced = pipeline.set_rejected(data_dir, 10.0, 10.0, True)  # mite "0"
    pipeline.set_rejected(data_dir, 10.0, 10.0, False, restore=replaced)

    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), tmp_path / "reopened", recordings_root=recordings)
    assert view["truth"] == {"0": ["still", "moving"], "1": ["moving", "moving"]}


def test_marking_a_detection_updates_the_saved_dataset(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "a", 3)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    pipeline.set_rejected(data_dir, 30.0, 10.0, True)

    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), tmp_path / "reopened", recordings_root=recordings)
    assert view["truth"] == {"0": ["still", "moving"], "2": ["not_a_mite", "not_a_mite"]}

    pipeline.set_rejected(data_dir, 30.0, 10.0, False)
    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), tmp_path / "reopened", recordings_root=recordings)
    assert view["truth"] == {"0": ["still", "moving"]}


def test_a_save_keeps_entries_of_detections_not_in_the_session(tmp_path, recordings):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    far = {"x": 90.0, "y": 90.0, "truth": "not_a_mite"}
    (data_dir / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([far]), encoding="utf-8")
    pipeline.update_ground_truth(out_dir, {"0": ["still", None]})
    assert far in json.loads((data_dir / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8"))


def test_reopening_a_dataset_reads_the_ground_truth_next_to_the_recordings(tmp_path, recordings):
    # e.g. a mark written there before the saved dataset was kept in line with it
    data_dir, out_dir = make_session(tmp_path, "a", 2)
    pipeline.save_ground_truth(out_dir, {"0": ["still", "moving"]})
    entries = json.loads((data_dir / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8"))
    entries.append({"x": 20.0, "y": 10.0, "truth": ["moving", "moving"]})
    (data_dir / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps(entries), encoding="utf-8")

    view = pipeline.open_saved_calibration(pipeline.dataset_id(data_dir), tmp_path / "reopened", recordings_root=recordings)
    assert view["truth"] == {"0": ["still", "moving"], "1": ["moving", "moving"]}


def test_the_report_suggests_the_threshold_and_the_band_that_put_the_deaths_right(tmp_path, recordings, scorer):
    # mite 0: a weak last movement (3) and, later, a still recording scoring 4; mite 1 is clear
    data_dir, out_dir = make_session(tmp_path, "a", 2, times=(0.0, 5.0, 10.0, 15.0, 20.0, 25.0))
    scorer.scores = {"a": {"0": [9, 3, 1, 4, 1, 1], "1": [9, 1, 1, 1, 1, 1]}}
    pipeline.save_ground_truth(out_dir, {"0": ["moving", "moving", "still", "still", "still", "still"],
                                         "1": ["moving"] + ["still"] * 5})
    ids = [pipeline.dataset_id(data_dir)]
    result = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, checks_per_mite=1)

    # no threshold tells the 3 from the 4: one mite's death is off whatever it is
    suggested = result["suggested_threshold"]
    assert result["death_error"]["suggested"]["mae"] > 0
    curve = result["death_curve"]
    assert suggested in curve["thresholds"] and min(curve["mae"]) == result["death_error"]["suggested"]["mae"]

    # the band holds both, and with its two close calls checked the deaths are right
    band = result["review_band"]
    assert band["checks_allowed"] == 1 and band["low"] <= 3 < 4 < band["high"] and band["low"] <= suggested <= band["high"]
    assert (band["mae"], band["checks_per_mite"], band["exact"]) == (0, 1, 1)
    assert band["frontier"][0]["checks_per_mite"] == 0 and band["frontier"][-1]["mae"] == 0
    json.dumps(result, allow_nan=False)  # what the server's JSON needs
    # the workbook is written a moment after the report is handed over: this waits for it
    sheets = pd.read_excel(pipeline.results_file(tmp_path / "report", result["excel"]), sheet_name=None)
    assert {"death_by_threshold", "review_band"} <= set(sheets)

    # without checks allowed there is no band: the threshold alone
    none = pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, checks_per_mite=0)["review_band"]
    assert none["low"] == none["high"] == suggested and none["checks_per_mite"] == 0
    with pytest.raises(ValueError):
        pipeline.evaluate_calibration(tmp_path / "report", ids, recordings_root=recordings, checks_per_mite=-1)


def test_the_poke_test_is_saved_next_to_the_recordings_and_reported(tmp_path, recordings, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 3, times=(0.0, 5.0, 10.0))
    # mite 0 moves to the end, mite 1 only at first, mite 2 is not a mite
    scorer.scores = {"a": {"0": [9, 9, 9], "1": [9, 0, 0], "2": [0, 0, 0]}}
    pipeline.save_ground_truth(out_dir, {"0": ["moving", None, None], "2": ["not_a_mite"] * 3})

    pipeline.edit_poke(out_dir, "add", 2)
    pipeline.edit_poke(out_dir, "set", 2, mite="0", state="unmoved")
    view = pipeline.edit_poke(out_dir, "fill", 2, state="moved")
    assert view["mites"] == ["0", "1"]  # the detection marked not a mite cannot be poked
    assert view["rounds"] == [{"after": 2, "states": {"0": "unmoved", "1": "moved"},
                               "counts": {"moved": 1, "unmoved": 1, "unset": 0}}]
    assert pipeline.poke_view(out_dir) == view
    saved = json.loads((data_dir / pipeline.POKE_FILENAME).read_text(encoding="utf-8"))
    assert saved["rounds"][0]["mites"][0] == {"x": 10.0, "y": 10.0, "state": "unmoved"}

    key = pipeline.dataset_id(data_dir)
    poke = pipeline.evaluate_calibration(tmp_path / "report", [key], recordings_root=recordings)["poke"]
    # mite 0 did not answer the poke after the last recording, where the detector saw nothing;
    # mite 1 answered it, yet the detector has it dead from the second recording
    assert poke["times"] == [0.0, 5.0, 10.0, 15.0] and poke["final_poke"]
    assert (poke["poke"]["n_mites"], poke["poke"]["n_dead"], poke["n_left_out"]) == (2, 1, 0)
    assert poke["poke"]["alive"] == [100, 100, 100, 50]
    assert poke["detector"]["alive"] == [100, 50, 50, None]

    again = pipeline.evaluate_calibration(tmp_path / "report", [key], recordings_root=recordings)
    assert again["poke"] == poke
    json.dumps(again, allow_nan=False)
    sheets = pd.read_excel(pipeline.results_file(tmp_path / "report", again["excel"]), sheet_name=None)
    assert list(sheets["poke_survival"]["survival_by_poke"]) == [100, 100, 100, 50]


def test_a_report_without_a_poke_test_has_none(tmp_path, recordings, scorer):
    data_dir, out_dir = make_session(tmp_path, "a", 1)
    scorer.scores = {"a": {"0": [9, 0]}}
    pipeline.save_ground_truth(out_dir, {"0": ["moving", "still"]})
    assert pipeline.evaluate_calibration(tmp_path / "report", [pipeline.dataset_id(data_dir)], recordings_root=recordings)["poke"] is None


@pytest.fixture
def outliner(monkeypatch):
    """Stub out decoding for the outline change: `outliner.changes[dataset name]`
    is what measuring returns, `outliner.calls` counts how often it ran."""
    class Outliner:
        changes = {}
        calls = []

        def __call__(self, dataset, _recordings_dir, stabilize=False):
            self.calls.append(dataset["name"])
            return self.changes[dataset["name"]]

    stub = Outliner()
    monkeypatch.setattr(pipeline, "_outline_mites", stub)
    return stub


def test_the_test_report_compares_the_outline_between_recordings(tmp_path, recordings, scorer, outliner):
    data_dir, out_dir = make_session(tmp_path, "a", 3, times=(0.0, 5.0, 10.0, 15.0))
    scorer.scores = {"a": {"0": [9, 9, 0, 0], "1": [9, 0, 0, 0], "2": [0, 0, 0, 0]}}
    big, small = 1.0, 0.01
    # mite 0 changes into the third and fourth recordings, so moved in the fourth; mite 1 never
    outliner.changes = {"a": {"0": [None, small, big, big], "1": [None, big, small, big], "2": [None] + [small] * 3}}
    pipeline.save_ground_truth(out_dir, {"0": ["moving", "moving", "still", "still"],
                                         "1": ["moving", "still", "still", "still"], "2": ["not_a_mite"] * 4})
    pipeline.edit_poke(out_dir, "add", 1)
    pipeline.edit_poke(out_dir, "fill", 1, state="moved")
    key = pipeline.dataset_id(data_dir)

    plain = pipeline.evaluate_calibration(tmp_path / "report", [key], recordings_root=recordings)
    assert plain["between_recordings"] is None and "outline" not in plain["survival"] and not outliner.calls

    result = pipeline.evaluate_calibration(tmp_path / "report", [key], recordings_root=recordings, between=True)
    rows = {(row["mite_id"], row["recording"]): row for row in result["observations"]}
    assert rows[("0", 3)]["outline_call"] == "moving" and rows[("0", 2)]["outline_call"] == "still"
    assert rows[("0", 2)]["outline_change"] == big and rows[("0", 0)]["outline_change"] is None
    # by the labels mite 1 dies first (at the second recording), mite 0 at the third; by the outline mite 0 lives to the end
    figure = result["between_recordings"]
    assert [(m["mite_id"], m["death"], m["outline_death"]) for m in figure["mites"]] == [("1", 1, None), ("0", 2, 4)]
    assert result["survival"]["outline"]["n_mites"] == 1 and result["survival"]["outline"]["n_left_out"] == 1
    assert result["death_error"]["outline"]["n_mites"] == 2
    assert result["poke"]["others"]["outline"]["n_mites"] == 2
    json.dumps(result, allow_nan=False)
    sheets = pd.read_excel(pipeline.results_file(tmp_path / "report", result["excel"]), sheet_name=None)
    assert "survival_by_outline" in sheets["poke_survival"] and "outline_change" in set(sheets["survival"]["curve"])
    assert "outline_call" in sheets["observations"]

    # the changes are kept with the scores
    pipeline.evaluate_calibration(tmp_path / "report", [key], recordings_root=recordings, between=True)
    assert outliner.calls == ["a"]
    assert list((data_dir / pipeline.SCORES_DIRNAME).glob("outline-*.json"))
