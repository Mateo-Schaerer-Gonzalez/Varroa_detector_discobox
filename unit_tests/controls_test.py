"""The zones ticked as negative controls are kept next to the recordings."""

import pipeline
import reference


def test_controls_are_saved_and_read_back(tmp_path):
    assert pipeline.load_controls(tmp_path) == []
    assert pipeline.save_controls(tmp_path, [4, 1, 4]) == [1, 4]
    assert pipeline.load_controls(tmp_path) == [1, 4]


def test_a_damaged_controls_file_reads_as_none(tmp_path):
    (tmp_path / pipeline.CONTROLS_FILENAME).write_text("{not json", encoding="utf-8")
    assert pipeline.load_controls(tmp_path) == []
    (tmp_path / pipeline.CONTROLS_FILENAME).write_text('{"1": true}', encoding="utf-8")
    assert pipeline.load_controls(tmp_path) == []


def test_the_labelling_page_gets_the_controls_with_the_zones(tmp_path):
    session = reference.make_small_session(tmp_path / "small_session")
    pipeline.save_controls(session, [1])
    opened = pipeline.open_session(session, tmp_path / "out", library_dir=tmp_path / "library")
    assert [zone["id"] for zone in opened["zones"] if zone["control"]] == [1]
