"""The ground truth being entered on the ground-truth page (classes/truth_draft.py
and pipeline's truth_view / edit_truth / save_truth): what a click or a fill
button does, and saving it on top of what another window saved."""

import pytest

import pipeline
from calibration_library_test import make_session
from classes.truth_draft import TruthDraft

MITES = [{"id": "0", "zone_id": 1}, {"id": "1", "zone_id": 1}, {"id": "2", "zone_id": 2}]
ZONES = [{"id": 0}, {"id": 1}, {"id": 2}]


def draft(saved=None):
    return TruthDraft(MITES, ZONES, 3, saved)


def test_a_click_steps_through_the_statuses():
    d = draft()
    d.cycle("0", 1)
    assert d.states("0") == [None, "moving", None]
    d.cycle("0", 1)
    assert d.states("0") == [None, "still", None]
    d.cycle("0", 1, backwards=True)
    assert d.states("0") == [None, "moving", None]
    d.cycle("0", 1, backwards=True)
    assert d.states("0") == [None, None, None]


def test_not_a_mite_marks_every_recording_and_leaving_it_brings_the_labels_back():
    d = draft({"0": ["moving", "still", None]})
    d.set("0", 2, "not_a_mite")
    assert d.states("0") == ["not_a_mite"] * 3
    d.cycle("0", 2)  # past "not a mite": unlabelled in this recording, the others as before
    assert d.states("0") == ["moving", "still", None]


def test_a_mite_marked_before_the_page_opened_comes_back_unlabelled():
    d = draft({"0": ["not_a_mite"] * 3})
    d.set("0", 0, "still")
    assert d.states("0") == ["still", None, None]


def test_fill_labels_only_the_unlabelled_mites_of_a_zone():
    d = draft({"0": ["moving", None, None]})
    d.fill(1, 0, "still")
    assert (d.states("0")[0], d.states("1")[0]) == ("moving", "still")
    assert d.states("2") == [None, None, None]  # another zone
    d.fill(1, 1, "previous")
    assert (d.states("0")[1], d.states("1")[1]) == ("moving", "still")
    d.fill(1, 1, "clear")
    assert (d.states("0")[1], d.states("1")[1]) == (None, None)
    with pytest.raises(ValueError):
        d.fill(1, 1, "sideways")


def test_clear_leaves_not_a_mite():
    d = draft({"0": ["not_a_mite"] * 3})
    d.fill(1, 0, "clear")
    assert d.states("0") == ["not_a_mite"] * 3


def test_only_the_statuses_changed_wait_to_be_saved():
    d = draft({"0": ["moving", "still", None]})
    d.cycle("0", 2)
    assert d.unsaved == {"0": {2: "moving"}}
    # Another window saves meanwhile; the change still goes on top.
    d.load({"0": ["still", "still", None]})
    assert d.states("0") == ["still", "still", "moving"]


def test_a_change_made_while_saving_waits_for_the_next_save():
    d = draft()
    d.cycle("0", 0)
    sent = d.unsaved_now()
    d.cycle("0", 0)  # moving -> still while the save is on its way
    d.cycle("1", 0)
    d.saved_as(sent, {"0": ["moving", None, None]})
    assert d.unsaved == {"0": {0: "still"}, "1": {0: "moving"}}
    assert d.states("0") == ["still", None, None]


def test_the_view_counts_what_is_done():
    d = draft({"0": ["moving", "still", "still"], "2": ["not_a_mite"] * 3})
    view = d.view()
    assert (view["cells"], view["done"]) == (9, 6)  # mite 1 unlabelled
    assert view["zones_with_mites"] == [1, 2]
    assert view["zones"][1]["done"] == [False, False, False] and view["zones"][2]["complete"]
    assert view["zones"][1]["counts"][0] == {"moving": 1, "still": 0, "not_a_mite": 0, "unset": 1}
    assert view["counts"][0] == {"moving": 1, "still": 0, "not_a_mite": 1, "unset": 1}
    assert view["next"] == [1, 0]
    assert view["ready"] and view["unsaved"] == 0
    assert view["states"] == {"0": ["moving", "still", "still"], "2": ["not_a_mite"] * 3}


def test_not_ready_without_a_moving_or_still_label():
    assert not draft({"2": ["not_a_mite"] * 3}).view()["ready"]


def test_unknown_mites_and_recordings_are_refused():
    with pytest.raises(ValueError):
        draft().cycle("9", 0)
    with pytest.raises(ValueError):
        draft().cycle("0", 3)


def test_the_pipeline_keeps_the_changes_until_saved(tmp_path):
    library = tmp_path / "library"
    data_dir, out_dir = make_session(tmp_path, "a", 2)
    view = pipeline.edit_truth(out_dir, "cycle", mite="0", recording=0, library_dir=library)
    assert view["states"] == {"0": ["moving", None]} and view["unsaved"] == 1 and view["changed"]
    assert pipeline.load_calibration_truth(out_dir, library) == {}  # nothing saved yet

    saved = pipeline.save_truth(out_dir, library)
    assert saved["unsaved"] == 0 and saved["version"] > view["version"]
    assert pipeline.load_calibration_truth(out_dir, library) == {"0": ["moving", None]}
    assert pipeline.list_calibration_datasets(library)[0]["n_moving"] == 1


def test_the_view_follows_a_change_saved_elsewhere(tmp_path):
    library = tmp_path / "library"
    _data_dir, out_dir = make_session(tmp_path, "a", 2)
    pipeline.edit_truth(out_dir, "fill", zone=0, recording=1, kind="still", library_dir=library)
    # e.g. another window, or a mite marked "not a mite" before a run
    pipeline.update_ground_truth(out_dir, {"0": {0: "moving"}}, library_dir=library)
    view = pipeline.truth_view(out_dir, library)
    assert view["changed"]
    assert view["states"] == {"0": ["moving", "still"], "1": [None, "still"]}
    assert view["unsaved"] == 2
