"""The label page of a saved live run that added mites (pipeline.open_session):
those mites have the ids the analysis gives them, say the recording they were
added in, and are shown on the frame they were found on, not on the first."""

import json

import pipeline
from pipeline import scoring, uploads
import reference
from classes.storage.roi_recordings import INDEX_NAME, ROI_DIRNAME


def saved_run(tmp_path, added):
    """A small session shrunk to ROIs, its last `added` mites (or all, with
    None) counted as added in recording 1 of a live run, with the frame they
    were found on."""
    small = reference.make_small_session(tmp_path / "small")
    folder = reference.linked_copy(small, tmp_path / "uploads" / "run")
    pipeline.finish_upload(folder.name, folder.parent)  # shrunk when first analysed
    assert uploads.shrink_pending(folder, folder.parent.parent / "results") == 3
    index_path = folder / ROI_DIRNAME / INDEX_NAME
    index = json.loads(index_path.read_text())
    mites = index["mites"]
    for mite in mites[-added if added else 0:]:
        mite["from"] = 1
    index_path.write_text(json.dumps(index))
    (folder / pipeline.ADDED_FRAMES_DIRNAME).mkdir()
    (folder / pipeline.ADDED_FRAMES_DIRNAME / "from_1.jpg").write_bytes(b"frame found on")
    return folder, len(mites)


def analysed_ids(folder):
    """Mite id to (x, y) as the analysis numbers them."""
    zones = scoring.counted_analysis(folder).zone_manager
    return {mite.text: tuple(round(float(v), 1) for v in mite.home) for mite in zones.mites}


def test_mites_added_have_the_analysis_ids_and_are_shown_on_the_frame_they_were_found_on(tmp_path):
    folder, n_mites = saved_run(tmp_path, added=2)
    out_dir = tmp_path / "out"
    page = pipeline.open_session(folder, out_dir)
    assert len(page["mites"]) == n_mites
    assert sorted(mite["from"] for mite in page["mites"]) == [0] * (n_mites - 2) + [1, 1]
    assert {mite["id"]: (mite["x"], mite["y"]) for mite in page["mites"]} == analysed_ids(folder)
    assert page["steps"] == [{"from": 0, "preview": pipeline.PREVIEW_NAME}, {"from": 1, "preview": "preview_from_1.jpg"}]
    assert (out_dir / "preview_from_1.jpg").read_bytes() == b"frame found on"
    # each mite added is numbered after those of its zone found on the first frame
    for mite in (m for m in page["mites"] if m["from"]):
        first = [m for m in page["mites"] if m["zone_id"] == mite["zone_id"] and not m["from"]]
        assert int(mite["id"].split(".")[1]) > len(first)


def test_a_run_whose_mites_were_all_added_lists_them_all(tmp_path):
    folder, n_mites = saved_run(tmp_path, added=None)
    page = pipeline.open_session(folder, tmp_path / "out")
    assert [mite["from"] for mite in page["mites"]] == [1] * n_mites
    assert sum(zone["n_mites"] for zone in page["zones"]) == n_mites  # their zones are there to label
    assert {mite["id"]: (mite["x"], mite["y"]) for mite in page["mites"]} == analysed_ids(folder)


def test_a_session_without_mites_added_has_one_step(tmp_path):
    page = pipeline.open_session(reference.make_small_session(tmp_path / "small"), tmp_path / "out")
    assert page["steps"] == [{"from": 0, "preview": pipeline.PREVIEW_NAME}]
    assert {mite["from"] for mite in page["mites"]} == {0}
