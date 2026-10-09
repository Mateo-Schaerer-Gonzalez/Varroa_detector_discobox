"""TEMPORARY, with the page web/static/overlap.html: where the scores of the two
labels overlap (classes/truth_overlap.py), and what the page asks of pipeline.

The datasets are built from hand-written session files and scoring is stubbed
out, as in calibration_library_test.py; only the clip reads real frames.
"""

import json

import cv2
import numpy as np
import pytest

import pipeline
from classes.truth_overlap import ABOVE, BELOW, IN, TruthOverlap

RECORDING = "2025-01-01-00-00-00_fps-30"


def rows(still, moving):
    return ([{"score": float(score), "movement": "still"} for score in still]
            + [{"score": float(score), "movement": "moving"} for score in moving])


# Still mites score low, with a tail up to 1.0; moving ones from 0.5 on. One
# recording labelled moving lies deep among the still ones, one labelled still
# high among the moving ones.
STILL = np.concatenate([np.linspace(0.01, 0.1, 200), np.linspace(0.3, 1.0, 20), [4.0]])
MOVING = np.concatenate([[0.02], np.linspace(0.5, 5.0, 100)])


def test_the_band_runs_from_the_lowest_moving_to_the_highest_still_where_both_are_common():
    assert TruthOverlap(rows(STILL, MOVING)).suggested_band() == pytest.approx((0.5, 1.0))


def test_a_stray_label_does_not_stretch_the_band_and_is_listed_beyond_it():
    described = TruthOverlap(rows(STILL, MOVING)).describe()
    beyond = {(point["score"], point["movement"]): point["where"] for point in described["datapoints"] if point["where"] != IN}
    assert beyond == {(0.02, "moving"): BELOW, (4.0, "still"): ABOVE}
    assert described["counts"] == {"n_moving": 101, "n_still": 221,
                                   "moving": int(((MOVING >= 0.5) & (MOVING <= 1.0)).sum()),
                                   "still": int(((STILL >= 0.5) & (STILL <= 1.0)).sum()),
                                   "moving_below": 1, "still_above": 1}


def test_the_datapoints_are_those_in_the_band_in_the_order_of_their_scores():
    described = TruthOverlap(rows(STILL, MOVING)).describe(beyond=False)
    scores = [point["score"] for point in described["datapoints"]]
    assert scores == sorted(scores)
    assert all(0.5 <= score <= 1.0 for score in scores)
    assert len(scores) == described["counts"]["moving"] + described["counts"]["still"]
    assert {point["where"] for point in described["datapoints"]} == {IN}


def test_labels_a_score_separates_do_not_overlap():
    described = TruthOverlap(rows(np.linspace(0.01, 0.4, 100), np.linspace(0.5, 5.0, 100))).describe()
    assert described["suggested"] is None and described["band"] is None
    assert described["datapoints"] == []


def test_the_page_may_set_another_band():
    overlap = TruthOverlap(rows(STILL, MOVING))
    described = overlap.describe(low=0.05, high=0.6)
    assert described["band"] == {"low": 0.05, "high": 0.6}
    assert described["suggested"] == {"low": pytest.approx(0.5), "high": pytest.approx(1.0)}
    assert described["counts"]["still"] == int(((STILL >= 0.05) & (STILL <= 0.6)).sum())
    assert described["counts"]["moving_below"] == 1                      # 0.02 is still below it
    assert described["counts"]["still_above"] == int((STILL > 0.6).sum())
    # one edge given: the other is the suggested one
    assert overlap.describe(low=0.7)["band"] == {"low": 0.7, "high": pytest.approx(1.0)}
    with pytest.raises(ValueError):
        overlap.describe(low=2.0, high=1.0)


def test_the_histogram_counts_every_recording_once():
    histogram = TruthOverlap(rows([0.0, 0.004, 0.05, 0.05], [0.05, 3.0, 12.5])).histogram()
    edges = histogram["edges"]
    assert edges[0] == TruthOverlap.LOWEST and edges[-1] >= 12.5
    assert len(histogram["still"]) == len(histogram["moving"]) == len(edges) - 1
    assert sum(histogram["still"]) == 4 and sum(histogram["moving"]) == 3
    assert histogram["still"][0] == 2          # the scores under the first edge
    assert histogram["moving"][-1] == 1        # the highest score


# ---- what the page asks of pipeline ----

def make_dataset(tmp_path, library, truth, n_mites=3, times=(0.0, 5.0, 10.0)):
    """A saved dataset of `n_mites` mites in one zone, labelled `truth`; returns
    (its recording folder, its id)."""
    data_dir = tmp_path / "run"
    data_dir.mkdir()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stored = {
        "data_dir": str(data_dir),
        "times": list(times),
        "recordings": [{"name": RECORDING, "fps": 30}] * len(times),
        "image": {"width": 100, "height": 100},
        "zones": [{"id": 0, "x1": 0, "y1": 0, "x2": 100, "y2": 100, "text_zone": None, "label": ""}],
        "mites": [{"id": str(i), "zone_id": 0, "x": 20.0 * i + 10, "y": 10.0, "r": 3.0} for i in range(n_mites)],
    }
    (out_dir / pipeline.CALIBRATION_SESSION_NAME).write_text(json.dumps(stored), encoding="utf-8")
    (out_dir / pipeline.PREVIEW_NAME).write_bytes(b"jpeg")
    pipeline.save_ground_truth(out_dir, truth, library_dir=library)
    return data_dir, pipeline.dataset_id(data_dir)


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "OVERLAP_DIR", tmp_path / "overlap")
    return tmp_path / "library"


TRUTH = {"0": ["still", "still", "still"], "1": ["moving", "still", None], "2": ["moving", "moving", "moving"]}
SCORES = {"0": [0.1, 1.5, 0.2], "1": [1.2, 0.3, 9.0], "2": [5.0, 0.4, 6.0]}


def test_the_overlap_of_a_saved_dataset(tmp_path, library, monkeypatch):
    _data_dir, dataset = make_dataset(tmp_path, library, TRUTH)
    monkeypatch.setattr(pipeline, "_score_mites", lambda *args, **kwargs: SCORES)

    overlap = pipeline.truth_overlap([dataset], low=1.0, high=2.0, library_dir=library)
    assert overlap["metric"] == pipeline.OVERLAP_METRIC
    assert [(d["id"], d["chosen"]) for d in overlap["datasets"]] == [(dataset, True)]
    points = {(p["mite_id"], p["recording"]): p for p in overlap["datapoints"]}
    # in the band: still at 1.5, moving at 1.2; below it and labelled moving: 0.4; the unlabelled 9.0 is no datapoint
    assert {key: p["where"] for key, p in points.items()} == {("0", 1): IN, ("1", 0): IN, ("2", 1): BELOW}
    assert points[("0", 1)]["r"] == 3.0 and points[("0", 1)]["dataset"] == dataset
    assert overlap["mites"][f"{dataset}/1"] == {"states": "ms-", "scores": SCORES["1"]}
    assert set(overlap["mites"]) == {f"{dataset}/{mite}" for mite in "012"}
    assert set(pipeline.truth_overlap([dataset], low=1.0, high=2.0, beyond=False, library_dir=library)["mites"]) == {
        f"{dataset}/0", f"{dataset}/1"}
    with pytest.raises(ValueError):
        pipeline.truth_overlap([], library_dir=library)


def test_a_label_changed_on_the_page_is_saved_at_once(tmp_path, library):
    data_dir, dataset = make_dataset(tmp_path, library, TRUTH)
    assert pipeline.set_overlap_label(dataset, "0", 1, "moving", library_dir=library) == {"movement": "moving", "states": "sms"}

    beside = {entry["x"]: entry["truth"] for entry in pipeline.load_ground_truth(data_dir)}
    assert beside == {10.0: ["still", "moving", "still"], 30.0: TRUTH["1"], 50.0: TRUTH["2"]}
    saved = json.loads((library / dataset / pipeline.DATASET_NAME).read_text(encoding="utf-8"))
    assert saved["truth"] == {**TRUTH, "0": ["still", "moving", "still"]}
    assert (library / dataset / pipeline.PREVIEW_NAME).read_bytes() == b"jpeg"

    assert pipeline.set_overlap_label(dataset, "0", 1, None, library_dir=library)["states"] == "s-s"
    assert pipeline.load_calibration_truth(tmp_path / "out", library)["0"] == ["still", None, "still"]


def test_a_label_the_page_may_not_set_changes_nothing(tmp_path, library):
    data_dir, dataset = make_dataset(tmp_path, library, {"0": ["still", None, None], "1": ["not_a_mite"] * 3})
    before = (data_dir / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8")
    for mite, recording, state in (("0", 0, "not_a_mite"),   # only moving, still or none
                                   ("7", 0, "still"),         # no such mite
                                   ("0", 3, "still"),         # no such recording
                                   ("1", 0, "still")):        # marked not a mite
        with pytest.raises(ValueError):
            pipeline.set_overlap_label(dataset, mite, recording, state, library_dir=library)
    assert (data_dir / pipeline.GROUND_TRUTH_FILENAME).read_text(encoding="utf-8") == before


def test_the_last_label_of_a_dataset_stays(tmp_path, library):
    # saving a dataset without a label lets it go, with its copy of the recordings
    _data_dir, dataset = make_dataset(tmp_path, library, {"0": ["still", None, None]})
    with pytest.raises(ValueError):
        pipeline.set_overlap_label(dataset, "0", 0, None, library_dir=library)
    assert json.loads((library / dataset / pipeline.DATASET_NAME).read_text(encoding="utf-8"))["truth"] == {"0": ["still", None, None]}


def test_a_mites_clip_is_cut_around_it_and_made_once(tmp_path, library):
    data_dir, dataset = make_dataset(tmp_path, library, TRUTH)
    (data_dir / RECORDING).mkdir()
    for index in range(4):
        frame = np.full((100, 100, 3), 200, dtype=np.uint8)
        frame[8:13, 28 + index:33 + index] = 20            # mite 1, moving to the right
        cv2.imwrite(str(data_dir / RECORDING / f"{index:03d}.bmp"), frame)

    clip = pipeline.overlap_clip(dataset, "1", 0, library_dir=library)
    assert (clip["x"], clip["y"], clip["width"], clip["height"]) == (0, 0, 70, 50)   # 40 pixels around (30, 10), cut at the image's edge
    assert len(clip["frames"]) == 4 and clip["interval_ms"] == 33
    first = cv2.imread(str(pipeline.OVERLAP_DIR / clip["frames"][0]))
    assert first.shape == (50, 70, 3) and first[10, 30].tolist() == [20, 20, 20] and first[40, 60].tolist() == [200, 200, 200]
    variation = cv2.imread(str(pipeline.OVERLAP_DIR / clip["variation"]))
    assert variation[40, 60].tolist() == [0, 0, 0]          # the plate does not vary
    assert variation[10, 28].sum() > 300                    # where the mite came and went

    for path in (data_dir / RECORDING).iterdir():
        path.unlink()
    assert pipeline.overlap_clip(dataset, "1", 0, library_dir=library) == clip
    with pytest.raises(ValueError):
        pipeline.overlap_clip(dataset, "9", 0, library_dir=library)
