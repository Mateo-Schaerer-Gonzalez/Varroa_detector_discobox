"""run_settings.json: every analysis writes, next to its workbook, every parameter
the app used for it, so the results can be published with it and made again."""

import json

import cv2
import pandas as pd

import pipeline
import reference
from classes.app_config import get_default_config
from classes.live import settings as live_settings
from classes.results import workbook_sheets
from classes.scoring import analyzer, plate_stabilizer
from pipeline import run_settings


def test_an_analysis_writes_its_settings(tmp_path):
    session = reference.make_small_session(tmp_path / "session")
    out = tmp_path / "out"
    pipeline.run_analysis(session, out, {"4": "control"})

    written = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
    assert written["software"]["commit"] == pipeline.COMMIT
    assert written["software"]["opencv"] == cv2.__version__
    in_use = written["in_use"]
    assert in_use["metric"] == "outline_variability"
    assert in_use["threshold"] == float(get_default_config().mite.motion_threshold)
    assert in_use["zones_per_plate"] == 1
    assert written["config"]["detector"]["min_area"] == get_default_config().detector.min_area
    zone = next(zone for zone in written["zones"] if zone["id"] == 4)
    assert zone["label"] == "control" and zone["x2"] > zone["x1"]
    assert written["recordings"]["folder"] == "session"
    assert written["recordings"]["settings"]["fps"] == 30
    assert written["n_recordings"] == reference.SMALL_RECORDINGS
    assert written["constants"]["classes.scoring.analyzer"]["EDGE_SHARE"] == analyzer.EDGE_SHARE


def test_every_named_constant_is_in_it():
    constants = run_settings.constants()
    score = constants["classes.scoring.analyzer"]
    assert (score["RIM"], score["EDGE_SHARE"], score["ANGLES"], score["REACH"]) == (
        analyzer.RIM, analyzer.EDGE_SHARE, analyzer.ANGLES, analyzer.REACH)
    stabilizer = constants["classes.scoring.plate_stabilizer"]
    assert stabilizer["_RIM"] == plate_stabilizer._RIM
    assert stabilizer["INTERPOLATION"] == plate_stabilizer.INTERPOLATION
    assert constants["classes.live.settings"]["FIXED"] == live_settings.FIXED
    # a class's own constant, and not the names a module imports from another
    assert constants["classes.results.call_corrections"]["CallCorrections.FILENAME"] == "corrections.json"
    assert "LABELS_FILENAME" not in constants.get("pipeline", {})


def test_the_workbook_has_a_sheet_per_group_and_the_settings(tmp_path):
    session = reference.make_small_session(tmp_path / "session")
    out = tmp_path / "out"
    pipeline.run_analysis(session, out, {"4": "control", "7": "venom: 2x"})

    sheets = pd.read_excel(out / "results.xlsx", sheet_name=None)
    scores = sheets["scores"]
    for group, name in [("control", "group control"), ("venom: 2x", "group venom_ 2x"), ("unlabeled", "group unlabeled")]:
        table = sheets[name]
        assert list(table.columns[:3]) == ["mite_ID", "zone_id", "last_moved_min"]
        assert list(table["mite_ID"]) == list(scores.loc[scores["group"] == group, "mite_ID"])
    assert sum(len(table) for name, table in sheets.items() if name.startswith("group ")) == len(scores)

    settings = sheets["settings"].set_index(["section", "parameter"])["value"]
    assert settings["in_use", "threshold"] == get_default_config().mite.motion_threshold
    assert settings["software", "commit"] == pipeline.COMMIT
    assert settings["constants", "classes.scoring.analyzer.EDGE_SHARE"] == analyzer.EDGE_SHARE
    assert settings["zones", "0.x1"] >= 0


def test_group_sheet_names_are_ones_excel_takes():
    names = workbook_sheets.group_sheet_names(["a/b", "x" * 40, "x" * 40 + "y", "Mites"], taken=["mites", "settings"])
    assert names["a/b"] == "group a_b"
    assert all(len(name) <= 31 for name in names.values())
    assert len({name.lower() for name in names.values()} | {"mites", "settings"}) == len(names) + 2
