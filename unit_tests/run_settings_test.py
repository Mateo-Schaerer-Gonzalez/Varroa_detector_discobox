"""run_settings.json and the workbook's settings sheet: every analysis records the
settings its recordings were made and analysed with, so the results can be
published with them and made again; the workbook has a sheet per group."""

import json

import cv2
import pandas as pd
import pytest

import pipeline
import reference
from classes.app_config import get_default_config
from classes.results import workbook_sheets
from classes.scoring import analyzer


def test_an_analysis_writes_its_settings(tmp_path):
    session = reference.make_small_session(tmp_path / "session")
    out = tmp_path / "out"
    pipeline.run_analysis(session, out)

    written = json.loads((out / "run_settings.json").read_text(encoding="utf-8"))
    assert set(written) == {"written", "code", "recording", "detector", "analysis"}
    assert written["code"]["commit"] == pipeline.COMMIT
    assert written["code"]["opencv"] == cv2.__version__
    assert written["recording"]["recordings"] == reference.SMALL_RECORDINGS
    assert written["recording"]["fps"] == 30
    assert written["detector"]["min_area"] == get_default_config().detector.min_area
    analysis = written["analysis"]
    assert analysis["metric"] == "outline_variability"
    assert analysis["threshold"] == float(get_default_config().mite.motion_threshold)
    assert analysis["edge_share"] == analyzer.EDGE_SHARE
    assert analysis["stabilizer_interpolation"] == "lanczos"
    assert analysis["zones_per_plate"] == 1
    assert analysis["mites_corrected_by_hand"] == 0


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
    assert settings["analysis", "threshold"] == get_default_config().mite.motion_threshold
    assert settings["code", "commit"] == pipeline.COMMIT
    assert settings["detector", "min_circularity"] == get_default_config().detector.min_circularity
    assert len(settings) < 62


def test_the_group_summary_has_the_percent_alive_the_page_shows(tmp_path):
    session = reference.make_small_session(tmp_path / "session")
    pipeline.save_death_minutes(session, 20)
    out = tmp_path / "out"
    results = pipeline.run_analysis(session, out, {"4": "control", "7": "venom: 2x"})

    sheet = pd.read_excel(out / "results.xlsx", sheet_name="group_summary", header=None)
    title = next(row for row in range(len(sheet)) if str(sheet.iat[row, 0]).startswith("Percent alive"))
    assert "20 min" in sheet.iat[title, 0]
    alive = pd.read_excel(out / "results.xlsx", sheet_name="group_summary", skiprows=title + 1)
    assert len(alive) == len(results["times"])
    for group in pipeline.describe_survival(results, 20)["groups"]:
        expected = [float("nan") if value is None else value for value in group["alive"]]
        assert alive[group["group"]].tolist() == pytest.approx(expected, nan_ok=True)


def test_group_sheet_names_are_ones_excel_takes():
    names = workbook_sheets.group_sheet_names(["a/b", "x" * 40, "x" * 40 + "y", "Mites"], taken=["mites", "settings"])
    assert names["a/b"] == "group a_b"
    assert all(len(name) <= 31 for name in names.values())
    assert len({name.lower() for name in names.values()} | {"mites", "settings"}) == len(names) + 2
