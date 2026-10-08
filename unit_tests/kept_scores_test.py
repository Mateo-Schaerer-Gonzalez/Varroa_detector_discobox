"""The scores of a run are kept with its results, and read back only for the
very frames, mites, metric and code they were worked out with
(classes/kept_scores.py)."""

import json
import os

import numpy as np
import pytest

import pipeline
import reference
from classes.app_config import get_default_config
from classes.frame_source import FolderSource
from classes.kept_scores import KeptScores
from classes.mite import Mite

FRAMES = [["2025-09-04-09-28-17_fps-30", [["a.bmp", 100, 1], ["b.bmp", 100, 2]]]]
FIRST = np.arange(48, dtype=np.uint8).reshape(4, 4, 3)


def mites(n=2):
    return [Mite(10 * index, 10, 10 * index + 8, 18, config=get_default_config()) for index in range(n)]


def key(these=None, stabilize=True, pool_size=None, frames=FRAMES, first=FIRST):
    return KeptScores.key(these or mites(), stabilize, pool_size, frames, first)


# --- the key

def test_the_same_run_has_the_same_key():
    assert key() == key()
    assert key(first=FIRST.copy()) == key()


def test_anything_a_score_follows_from_changes_the_key():
    moved = mites()
    moved[1].x1 += 1
    other_metric = mites()
    other_metric[0].metric, other_metric[0].metric_params = "mean_diff", {}
    other_params = mites()
    for mite in other_params:
        mite.metric, mite.metric_params = "topN_variability", {"n": 3}
    same_params = mites()
    for mite in same_params:
        mite.metric, mite.metric_params = "topN_variability", {"n": 10}  # its default, said or not
    unsaid = mites()
    for mite in unsaid:
        mite.metric, mite.metric_params = "topN_variability", {}
    rewritten = [[FRAMES[0][0], [["a.bmp", 100, 1], ["b.bmp", 100, 3]]]]  # written again, later
    one_less = [[FRAMES[0][0], FRAMES[0][1][:1]]]
    brighter = FIRST.copy()
    brighter[0, 0, 0] += 1
    keys = {key(), key(moved), key(other_metric), key(mites(3)), key(stabilize=False), key(pool_size=4),
            key(frames=rewritten), key(frames=one_less), key(first=brighter)}
    assert len(keys) == 9
    assert key(other_params) != key(same_params) == key(unsaid)


def test_a_change_to_the_scoring_code_changes_the_key(monkeypatch):
    before = key()
    import inspect
    real = inspect.getsource
    monkeypatch.setattr(inspect, "getsource", lambda module: real(module) + "# changed")
    assert key() != before


# --- keeping and giving back

AWKWARD = [0.1 + 0.2, 1e-17, 3.4760000000000004, 123456.789012345678, 0.0]


def scored(n_pools=len(AWKWARD)):
    these = mites()
    for index, mite in enumerate(these):
        for score in AWKWARD[:n_pools]:
            mite.record_motion(score + index, brightness=100.5 + index)
    return these


def test_the_scores_come_back_to_the_last_digit(tmp_path):
    kept = KeptScores(tmp_path)
    kept.keep("a key", scored())
    back = mites()
    assert kept.give("a key", back, len(AWKWARD))
    for mite, original in zip(back, scored()):
        assert mite.motion_scores == original.motion_scores and mite.brightness == original.brightness
        assert mite.color == original.color  # drawn as moving or still by its last score, as when scored


def test_nothing_comes_back_under_another_key_or_for_other_mites_or_pools(tmp_path):
    kept = KeptScores(tmp_path)
    assert not kept.give("a key", mites(), 5)  # nothing kept yet
    kept.keep("a key", scored())
    for wrong in (("another key", mites(), len(AWKWARD)), ("a key", mites(3), len(AWKWARD)), ("a key", mites(), 4)):
        these = wrong[1]
        assert not kept.give(*wrong)
        assert all(mite.motion_scores == [] for mite in these)


def test_a_damaged_file_is_as_good_as_none(tmp_path):
    kept = KeptScores(tmp_path)
    kept.keep("a key", scored())
    kept.path.write_text('{"key": "a key", "scores": [[1.0]]', encoding="utf-8")
    assert not kept.give("a key", mites(), len(AWKWARD))
    kept.path.write_text(json.dumps({"key": "a key", "scores": "no list", "brightness": []}), encoding="utf-8")
    assert not kept.give("a key", mites(), len(AWKWARD))


def test_the_file_is_beside_the_results_not_among_them(tmp_path):
    KeptScores(tmp_path).keep("a key", scored())
    assert [path.name for path in tmp_path.iterdir()] == [KeptScores.DIRNAME]


# --- a folder's frames, told apart without reading them

def test_a_folders_frames_are_listed_with_what_tells_them_apart(tmp_path):
    session = reference.make_small_session(tmp_path / "small_session")
    listed = FolderSource(session).frame_files()
    assert len(listed) == reference.SMALL_RECORDINGS and all(len(files) == reference.SMALL_FRAMES for _name, files in listed)
    name, files = listed[0]
    first = session / name / files[0][0]
    assert files[0] == [first.name, first.stat().st_size, first.stat().st_mtime_ns]
    assert [file for file, _size, _time in files] == sorted(path.name for path in (session / name).glob("*.bmp"))
    json.dumps(listed)  # plain, as the key takes it


# --- on a run

@pytest.fixture
def decoded(monkeypatch):
    """Counts the frames decoded."""
    count = []
    read = FolderSource._read
    monkeypatch.setattr(FolderSource, "_read", staticmethod(lambda path: count.append(path) or read(path)))
    return count


@pytest.mark.slow
def test_the_same_recordings_are_scored_once(tmp_path, decoded):
    session = reference.make_small_session(tmp_path / "small_session")
    out, library = tmp_path / "out", tmp_path / "library"
    n_frames = reference.SMALL_RECORDINGS * reference.SMALL_FRAMES
    first = pipeline.run_analysis(session, out, library_dir=library)
    assert len(decoded) == n_frames + 1  # the first frame once more, to find the mites before anything is scored

    del decoded[:]
    again = pipeline.run_analysis(session, out, library_dir=library)
    assert len(decoded) == 1  # the first frame, for the mites: the scores are read back
    assert again == first

    # other labels, and a detection marked not a mite, change no score
    del decoded[:]
    labelled = pipeline.run_analysis(session, out, {"0": "control"}, library_dir=library)
    assert len(decoded) == 1
    assert [mite["scores"] for mite in labelled["mites"]] == [mite["scores"] for mite in first["mites"]]


@pytest.mark.slow
def test_other_frames_or_another_metric_are_scored_again(tmp_path, decoded, monkeypatch):
    session = reference.make_small_session(tmp_path / "small_session")
    out, library = tmp_path / "out", tmp_path / "library"
    n_frames = reference.SMALL_RECORDINGS * reference.SMALL_FRAMES
    first = pipeline.run_analysis(session, out, library_dir=library)

    # a frame written again, though as it was: it could have been another one
    frame = sorted(sorted(d for d in session.iterdir() if d.is_dir())[1].glob("*.bmp"))[2]
    stat = frame.stat()
    os.utime(frame, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    del decoded[:]
    assert pipeline.run_analysis(session, out, library_dir=library) == first
    assert len(decoded) == n_frames + 1

    # another metric: its own scores, and those are kept from then on
    mite_config = get_default_config().mite
    monkeypatch.setattr(mite_config, "metric", "mean_diff")
    monkeypatch.setattr(mite_config, "motion_threshold", 1.0)
    del decoded[:]
    other = pipeline.run_analysis(session, out, library_dir=library)
    assert len(decoded) == n_frames + 1
    assert [mite["scores"] for mite in other["mites"]] != [mite["scores"] for mite in first["mites"]]
    del decoded[:]
    assert pipeline.run_analysis(session, out, library_dir=library) == other and len(decoded) == 1

    # another results folder knows nothing of these
    del decoded[:]
    pipeline.run_analysis(session, tmp_path / "elsewhere", library_dir=library)
    assert len(decoded) == n_frames + 1


@pytest.mark.slow
def test_a_calibration_decodes_one_frame_to_find_the_mites(tmp_path, decoded):
    session = reference.make_small_session(tmp_path / "small_session")
    view = pipeline.open_calibration(session, tmp_path / "out", library_dir=tmp_path / "library")
    assert len(decoded) == 1
    assert view["n_recordings"] == reference.SMALL_RECORDINGS and view["mites"]


@pytest.mark.slow
def test_a_pages_run_has_its_files_a_moment_later(tmp_path):
    session = reference.make_small_session(tmp_path / "small_session")
    library = tmp_path / "library"
    at_once = pipeline.run_analysis(session, tmp_path / "at_once", library_dir=library)
    later = pipeline.run_analysis(session, tmp_path / "later", library_dir=library, files_later=True)
    assert later == at_once
    assert (tmp_path / "later" / later["preview"]).is_file()  # the pages draw on it at once
    workbook = pipeline.results_file(tmp_path / "later", later["excel"])  # waits for it
    assert workbook.is_file()
    assert reference.outputs(tmp_path / "later") == reference.outputs(tmp_path / "at_once")
