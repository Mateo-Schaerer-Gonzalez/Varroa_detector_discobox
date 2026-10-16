"""The one-off move of what earlier versions kept in calibration_data/ home to
recordings/ and results/ (pipeline.dissolve_calibration_library()): every
dataset's ground truth, poke test and cached scores end up with its recordings,
and nothing is lost or written over."""

import json

import pipeline
import reference
from classes.roi_recordings import is_roi_session

ENTRY = {"x": 50.0, "y": 50.0, "truth": ["moving", "still", "still"]}
EXTRA = {"x": 90.0, "y": 90.0, "truth": ["not_a_mite"] * 3}
POKE = {"rounds": [{"after": 0, "mites": [{"x": 50.0, "y": 50.0, "state": "moved"}]}]}


def write_dataset(library, name, data_dir, copy_from=None, truth=(), poke=None, dataset_truth=None, scores=()):
    """A dataset as an earlier version saved it: dataset.json, a copy of the
    recordings (of `copy_from`) with its own ground truth and poke test, and
    cached scores."""
    folder = library / name
    folder.mkdir(parents=True)
    mites = [{"id": "1.1", "zone_id": 1, "x": 50.0, "y": 50.0, "r": 4.0},
             {"id": "1.2", "zone_id": 1, "x": 20.0, "y": 20.0, "r": 4.0}]
    (folder / pipeline.DATASET_NAME).write_text(json.dumps({
        "data_dir": str(data_dir), "name": name.rsplit("-", 1)[0], "times": [0.0, 5.0, 10.0], "mites": mites,
        "truth": dataset_truth or {}}), encoding="utf-8")
    if copy_from is not None:
        copy = reference.linked_copy(copy_from, folder / pipeline.RECORDINGS_DIRNAME)
        (copy / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps(list(truth)), encoding="utf-8")
        if poke is not None:
            (copy / pipeline.POKE_FILENAME).write_text(json.dumps(poke), encoding="utf-8")
    for cached in scores:
        (folder / pipeline.SCORES_DIRNAME).mkdir(exist_ok=True)
        (folder / pipeline.SCORES_DIRNAME / cached).write_text("{}", encoding="utf-8")
    return folder


def test_every_dataset_goes_home_with_its_ground_truth_poke_test_and_scores(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    library, recordings, results = tmp_path / "calibration_data", tmp_path / "recordings", tmp_path / "results"

    # 1. its recordings are in recordings/: its ground truth there wins, the library's others are added
    run = reference.linked_copy(small, recordings / "run")
    (run / pipeline.GROUND_TRUTH_FILENAME).write_text(json.dumps([ENTRY]), encoding="utf-8")
    write_dataset(library, "run-1111aaaa", run, copy_from=small, truth=[{**ENTRY, "truth": ["still"] * 3}],
                  poke=POKE, dataset_truth={"1.2": ["moving", None, None]}, scores=["abc.json"])
    # 2. its recordings are gone, as on a computer it was copied to: the library's copy comes home
    gone = "/home/localuser/Varroa_detector_discobox/recordings/discobox_run"
    write_dataset(library, "discobox_run-2222bbbb", gone, copy_from=small, truth=[ENTRY, EXTRA], poke=POKE,
                  scores=["benchmark-def.json"])
    # 3. its recordings are elsewhere: copied in, shrunk
    elsewhere = reference.linked_copy(small, tmp_path / "elsewhere" / "outside")
    (elsewhere / pipeline.POKE_FILENAME).write_text(json.dumps({"rounds": []}), encoding="utf-8")
    write_dataset(library, "outside-3333cccc", elsewhere, copy_from=small, truth=[ENTRY], poke=POKE)
    # 4. a report, a session without one, and what the scripts wrote
    reports = library / "reports"
    (reports / "2026-10-01 10-00-00 run").mkdir(parents=True)
    (reports / "2026-10-01 10-00-00 run" / "calibration.xlsx").write_bytes(b"x")
    (reports / "2026-10-01 11-00-00 nothing").mkdir()
    (reports / "optuna_metrics.db").write_bytes(b"study")

    said = []
    pipeline.dissolve_calibration_library(library, recordings, results, said.append)

    assert not library.exists()
    # 1.
    assert pipeline.load_ground_truth(run) == [ENTRY, {"x": 20.0, "y": 20.0, "truth": ["moving", None, None]}]
    assert json.loads((run / pipeline.POKE_FILENAME).read_text()) == POKE
    assert (run / pipeline.SCORES_DIRNAME / "abc.json").is_file()
    # 2.
    home = recordings / "discobox_run"
    assert pipeline.load_ground_truth(home) == [ENTRY, EXTRA] and json.loads((home / pipeline.POKE_FILENAME).read_text()) == POKE
    assert (home / pipeline.SCORES_DIRNAME / "benchmark-def.json").is_file()
    # 3. the folder outside stays as it was; its copy keeps its poke test, the library's beside it
    inside = recordings / "outside"
    assert is_roi_session(inside) and (inside / pipeline.ORIGIN_NAME).is_file()
    assert pipeline.load_ground_truth(inside) == [ENTRY] and not (elsewhere / pipeline.GROUND_TRUTH_FILENAME).exists()
    assert json.loads((inside / pipeline.POKE_FILENAME).read_text()) == {"rounds": []}
    assert json.loads((inside / "poke_test.from_library.json").read_text()) == POKE
    assert list(elsewhere.rglob("*.bmp"))
    # 4.
    assert (results / pipeline.EARLIER_REPORTS / "2026-10-01 10-00-00 run" / "calibration.xlsx").is_file()
    assert not (results / pipeline.EARLIER_REPORTS / "2026-10-01 11-00-00 nothing").exists()
    assert (results / pipeline.SCRIPTS_OUTPUT_DIRNAME / "optuna_metrics.db").read_bytes() == b"study"
    assert any("discobox_run" in line for line in said)

    # the calibration page lists all three, from recordings/ alone
    assert sorted(d["name"] for d in pipeline.list_calibration_datasets(recordings)) == ["discobox_run", "outside", "run"]
    # nothing left to do
    pipeline.dissolve_calibration_library(library, recordings, results)
    assert sorted(path.name for path in recordings.iterdir()) == ["discobox_run", "outside", "run"]


def test_a_name_taken_in_recordings_gets_a_number_and_nothing_is_written_over(tmp_path):
    small = reference.make_small_session(tmp_path / "small")
    library, recordings = tmp_path / "calibration_data", tmp_path / "recordings"
    (recordings / "discobox_run").mkdir(parents=True)  # another recording of that name
    (recordings / "discobox_run" / "notes.txt").write_text("mine")
    write_dataset(library, "discobox_run-2222bbbb", "/home/localuser/recordings/discobox_run", copy_from=small,
                  truth=[ENTRY])
    write_dataset(library, "lost-4444dddd", "/home/localuser/recordings/lost")  # no recordings, no copy: left

    pipeline.dissolve_calibration_library(library, recordings, tmp_path / "results")
    assert (recordings / "discobox_run" / "notes.txt").read_text() == "mine"
    assert pipeline.load_ground_truth(recordings / "discobox_run-2") == [ENTRY]
    assert (library / "lost-4444dddd" / pipeline.DATASET_NAME).is_file()  # nothing to bring home: kept


def test_scores_cached_under_the_ids_of_an_earlier_version_are_renamed_to_todays(tmp_path):
    old = [{"id": "0", "x": 10.0, "y": 10.0, "r": 3.0}, {"id": "1", "x": 30.0, "y": 10.0, "r": 3.0}]
    new = [{"id": "1.1", "x": 10.0, "y": 10.0, "r": 3.0}, {"id": "1.2", "x": 30.0, "y": 10.0, "r": 3.0}]
    params = {"pad": 16}
    name = pipeline._metric_version("outline_variability", params, old, True)
    (tmp_path / f"{name}.json").write_text(json.dumps(
        {"metric": "outline_variability", "params": params, "scores": {"0": [1.0, 2.0], "1": [3.0, 4.0]}}))
    (tmp_path / "0123456789ab.json").write_text(json.dumps({"metric": "mean_diff", "scores": {"0": [1.0]}}))  # older code

    assert pipeline._rekeyed_scores(tmp_path, old, new) == 1
    renamed = json.loads((tmp_path / f"{pipeline._metric_version('outline_variability', params, new, True)}.json").read_text())
    assert renamed["scores"] == {"1.1": [1.0, 2.0], "1.2": [3.0, 4.0]} and renamed["params"] == params
    # a mite that is not where it was: nothing is renamed
    moved = [new[0], {**new[1], "x": 31.0}]
    assert pipeline._rekeyed_scores(tmp_path, old, moved) == 0
