"""Turns the mite score table into files on disk (one Excel workbook and the figures)
and into plain data the web page can browse zone by zone and mite by mite.

Runs head-less (the Agg backend) so it behaves the same from the CLI and the server.
"""

import json
import math

import matplotlib

matplotlib.use("Agg")  # must be set before pyplot is imported anywhere

import matplotlib.pyplot as plt
import pandas as pd
import cv2
from pathlib import Path

from classes.plotter import Plotter

EXCEL_NAME = "results.xlsx"
DETECTIONS_NAME = "detections.jpg"


def _observed(mite_data):
    """The rows in which the mite was there: without those of the recordings in
    which the user marked it gone (classes/call_corrections.py)."""
    return mite_data[~mite_data["censored"]] if "censored" in mite_data else mite_data


def _last_recording(mite_data):
    """Each mite's row from the final recording of the session."""
    return mite_data[mite_data["time"] == mite_data["time"].max()]


def summarise_by_group(mite_data):
    """One row per user-defined group: how many mites, how often they were seen
    moving, and their score statistics."""
    summary = (
        mite_data.groupby("group")
        .agg(
            n_mites=("mite_ID", "nunique"),
            n_observations=("motion_score", "size"),
            mean_score=("motion_score", "mean"),
            std_score=("motion_score", "std"),
            median_score=("motion_score", "median"),
            min_score=("motion_score", "min"),
            max_score=("motion_score", "max"),
        )
    )
    moving = mite_data.groupby("group")["moving"].agg(["sum", "mean"])
    summary.insert(2, "n_moving_observations", moving["sum"].astype(int))
    summary.insert(3, "fraction_moving", moving["mean"])
    moving_last = _last_recording(mite_data).groupby("group")["moving"].sum()
    summary.insert(4, "n_moving_last_recording", moving_last.reindex(summary.index, fill_value=0).astype(int))
    return summary.reset_index().sort_values("group")


def moving_table(mite_data):
    """Long-form movement: per group and per zone, how many mites moved in each
    recording. One row per (level, name, time)."""
    tables = []
    for level, key in [("group", "group"), ("zone", "zone_id")]:
        table = (
            mite_data.groupby([key, "time"])
            .agg(n_mites=("mite_ID", "nunique"), n_moving=("moving", "sum"))
            .reset_index()
            .rename(columns={key: "name"})
        )
        table.insert(0, "level", level)
        tables.append(table)

    moving = pd.concat(tables, ignore_index=True)
    moving["n_moving"] = moving["n_moving"].astype(int)
    moving["fraction_moving"] = moving["n_moving"] / moving["n_mites"]
    return moving


def write_excel(mite_data, out_dir):
    """Write the long-form measurements, the per-group summary and movement over
    time; the last two without the recordings in which a mite was marked gone."""
    path = Path(out_dir) / EXCEL_NAME
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        mite_data.to_excel(writer, sheet_name="measurements", index=False)
        summarise_by_group(_observed(mite_data)).to_excel(writer, sheet_name="group_summary", index=False)
        moving_table(_observed(mite_data)).to_excel(writer, sheet_name="moving", index=False)
    return path.name


# Every figure: its file name and the Plotter method that draws it, most useful first.
FIGURES = [
    ("moving_by_group.png", "plot_moving_by_group"),
    ("distribution_by_group.png", "plot_distribution_by_group"),
    ("score_over_time.png", "plot_score_over_time"),
    ("score_distribution.png", "plot_score_distribution"),
]


def write_figures(mite_data, out_dir):
    """Save every figure as a PNG and return their filenames, most useful first."""
    plotter = Plotter(_observed(mite_data))
    figures = {name: getattr(plotter, method)() for name, method in FIGURES}

    names = []
    for name, figure in figures.items():
        figure.savefig(Path(out_dir) / name, dpi=110)
        plt.close(figure)  # free the figure; the server never shows it
        names.append(name)
    return names


def _floats(values, digits=3):
    """Rounded numbers; None where there is none, e.g. a time at which every mite was gone."""
    return [None if pd.isna(value) else round(float(value), digits) for value in values]


def describe_mites(mite_data):
    """One entry per mite with its whole time series, for the mite pages."""
    mites = []
    for mite_id, rows in mite_data.groupby("mite_ID"):
        rows = rows.sort_values("time")
        mites.append(
            {
                "id": str(mite_id),
                "zone_id": int(rows["zone_id"].iloc[0]),
                "group": rows["group"].iloc[0],
                "x": round(float(rows["x"].iloc[0]), 1),
                "y": round(float(rows["y"].iloc[0]), 1),
                "scores": _floats(rows["motion_score"]),
                # the mite's threshold in each recording: its own, or the one of every mite
                "thresholds": _floats(rows["threshold"]),
                "moving": [bool(value) for value in rows["moving"]],
            }
        )
    return sorted(mites, key=lambda mite: int(mite["id"]) if mite["id"].isdigit() else mite["id"])


def _moving_series(rows, times):
    """Fraction of mites moving at each time, or None where there are no mites."""
    if rows.empty:
        return None
    by_time = rows.groupby("time")["moving"].mean()
    return _floats(by_time.reindex(times))


def describe_zones(mite_data, zones, times):
    """Add per-zone results to the zone rectangles, for the plate map and zone pages.

    Zones with no mites are kept (with n_mites 0) so the plate map stays complete.
    """
    mite_data = _observed(mite_data)
    described = []
    for zone in zones:
        rows = mite_data[mite_data["zone_id"] == zone["id"]]
        last = _last_recording(rows) if not rows.empty else rows
        mean_score = rows.groupby("time")["motion_score"].mean().reindex(times) if not rows.empty else None
        described.append(
            {
                **zone,
                "n_mites": int(rows["mite_ID"].nunique()),
                "n_moving_last": int(last["moving"].sum()),
                "moving": _moving_series(rows, times),
                "mean_score": None if mean_score is None else _floats(mean_score),
            }
        )
    return described


def describe_groups(mite_data, times):
    """Fraction of mites moving per group over time, for the overview chart."""
    return [
        {"group": group, "moving": _moving_series(rows, times)}
        for group, rows in sorted(_observed(mite_data).groupby("group"), key=lambda item: item[0])
    ]


def write_outputs(mite_data, annotated_image, out_dir):
    """Write every artefact for one analysis run and describe it in plain data.

    The returned dict contains only filenames and numbers, so it can cross into the
    web layer unchanged.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _check_not_empty(mite_data)

    cv2.imwrite(str(out_dir / DETECTIONS_NAME), annotated_image)

    return {
        "excel": write_excel(mite_data, out_dir),
        "figures": write_figures(mite_data, out_dir),
        "detections": DETECTIONS_NAME,
        "summary": _summary(mite_data),
    }


def describe_outputs(mite_data):
    """What write_outputs() returns, without writing anything: the file names it
    writes, and the summary. For a live run, which writes the files only now and
    then but describes its results after every pool."""
    _check_not_empty(mite_data)
    return {
        "excel": EXCEL_NAME,
        "figures": [name for name, _method in FIGURES],
        "detections": DETECTIONS_NAME,
        "summary": _summary(mite_data),
    }


def _check_not_empty(mite_data):
    if mite_data.empty:
        raise ValueError("No mites were detected, so there is nothing to report.")


def _summary(mite_data):
    mite_data = _observed(mite_data)
    summary = summarise_by_group(mite_data)
    return {
        "n_mites": int(mite_data["mite_ID"].nunique()),
        "n_moving_last": int(_last_recording(mite_data)["moving"].sum()),
        "n_observations": int(len(mite_data)),
        "n_groups": int(mite_data["group"].nunique()),
        "groups": [_without_nan(row) for row in summary.round(3).to_dict(orient="records")],
    }


def _without_nan(row):
    """A NaN, e.g. the SD of a group seen once, as None: JSON cannot hold NaN, so a
    page asking for results with one would get an error instead."""
    return {key: None if isinstance(value, float) and math.isnan(value) else value for key, value in row.items()}


CALIBRATION_EXCEL_NAME = "calibration.xlsx"


def write_calibration_excel(result, out_dir):
    """Write a calibration's summary, the datasets pooled, every labelled (mite,
    recording) observation, the survival curves by the labels and the detector,
    the fraction moving per recording, every mite's death time and, when there
    is one, the ROC curve.
    A calibration with the benchmark has it as a row of the summary, a column of
    the observations and a survival curve."""
    path = Path(out_dir) / CALIBRATION_EXCEL_NAME

    def death_time(name):
        """A caller's death-time error (minutes) and the gap of its survival curve."""
        return {f"death_time_{key}": value for key, value in result["death_time"][name].items()}

    # `window` 0: one threshold (`offset`) for every mite; else each mite's own,
    # `offset` above the moving median of its scores over `window` recordings
    # plus `scale` times their median absolute deviation
    summary = pd.DataFrame(
        [{"calls": "in use", **result["calls"]["current"], **result["current"], **death_time("current")}]
        + ([{"calls": "suggested", **result["calls"]["suggested"], **result["best"], **death_time("suggested")}]
           if result["best"] else [])
    )
    summary["auc"] = [result["auc"]] + ([result["roc_suggested"]["auc"]] if result["best"] else [])
    summary["metric"] = result["metric"]
    summary["metric_params"] = json.dumps(result.get("metric_params") or {})
    if result.get("benchmark"):
        row = {**{key: value for key, value in result["benchmark"].items() if key != "name"}, **death_time("benchmark")}
        row["metric"] = f"benchmark ({result['benchmark']['name']})"
        summary = pd.concat([summary, pd.DataFrame([row])], ignore_index=True)

    observations = pd.DataFrame(result["observations"]).rename(columns={"movement": "your_label"})

    def over_time_rows(level, name, curves):
        return pd.DataFrame(
            {
                "level": level,
                "name": name,
                "time": result["times"],
                "n_labelled": curves["n"],
                "moving_by_labels": curves["truth"],
                "moving_called_in_use": curves["current"],
                **({"moving_called_suggested": curves["suggested"]} if "suggested" in curves else {}),
            }
        )

    over_time = pd.concat(
        [over_time_rows("all", "all", result["moving_over_time"])]
        + [over_time_rows("group", group["group"], group) for group in result["groups"]],
        ignore_index=True,
    )

    def survival_rows(level, name, curves):
        return pd.concat([
            pd.DataFrame(
                {
                    "level": level,
                    "name": name,
                    "curve": {"truth": "labels", "current": "detector_in_use", "suggested": "detector_suggested",
                              "single": "detector_one_threshold", "benchmark": "benchmark"}[source],
                    "n_mites": curve["n_mites"],
                    "n_left_out_never_moving": curve["n_left_out"],
                    "time": result["times"],
                    "survival_percent": curve["alive"],
                    "ci_low": curve["low"],
                    "ci_high": curve["high"],
                }
            )
            for source, curve in curves.items()
        ], ignore_index=True)

    survival = pd.concat(
        [survival_rows("all", "all", result["survival"])]
        + [survival_rows("group", group["group"], group["survival"]) for group in result["groups"]],
        ignore_index=True,
    )

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        pd.DataFrame(result["datasets"]).to_excel(writer, sheet_name="datasets", index=False)
        observations.to_excel(writer, sheet_name="observations", index=False)
        survival.to_excel(writer, sheet_name="survival", index=False)
        over_time.to_excel(writer, sheet_name="moving_over_time", index=False)
        # each mite's death time in minutes, by the labels and by each caller
        pd.DataFrame(result["death_times"]).rename(columns={
            "labels": "death_time_labels", "current": "death_time_in_use", "suggested": "death_time_suggested",
            "single": "death_time_one_threshold", "benchmark": "death_time_benchmark",
        }).to_excel(writer, sheet_name="death_times", index=False)
        if result["windows"]:
            pd.DataFrame(result["windows"]).to_excel(writer, sheet_name="windows", index=False)
        if result["roc"]:
            curve = ("fpr", "tpr", "thresholds")
            pd.DataFrame({key: result["roc"][key] for key in curve}).to_excel(writer, sheet_name="roc", index=False)
    return path.name
