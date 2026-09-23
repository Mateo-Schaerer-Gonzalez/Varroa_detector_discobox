"""Turns the mite score table into files on disk (one Excel workbook and the figures)
and into plain data the web page can browse zone by zone and mite by mite.

Runs head-less (the Agg backend) so it behaves the same from the CLI and the server.
"""

import json

import matplotlib

matplotlib.use("Agg")  # must be set before pyplot is imported anywhere

import matplotlib.pyplot as plt
import pandas as pd
import cv2
from pathlib import Path

from classes.plotter import Plotter

EXCEL_NAME = "results.xlsx"
DETECTIONS_NAME = "detections.jpg"


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
    """Write the long-form measurements, the per-group summary and movement over time."""
    path = Path(out_dir) / EXCEL_NAME
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        mite_data.to_excel(writer, sheet_name="measurements", index=False)
        summarise_by_group(mite_data).to_excel(writer, sheet_name="group_summary", index=False)
        moving_table(mite_data).to_excel(writer, sheet_name="moving", index=False)
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
    plotter = Plotter(mite_data)
    figures = {name: getattr(plotter, method)() for name, method in FIGURES}

    names = []
    for name, figure in figures.items():
        figure.savefig(Path(out_dir) / name, dpi=110)
        plt.close(figure)  # free the figure; the server never shows it
        names.append(name)
    return names


def _floats(values, digits=3):
    return [round(float(value), digits) for value in values]


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
        for group, rows in sorted(mite_data.groupby("group"), key=lambda item: item[0])
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
    summary = summarise_by_group(mite_data)
    return {
        "n_mites": int(mite_data["mite_ID"].nunique()),
        "n_moving_last": int(_last_recording(mite_data)["moving"].sum()),
        "n_observations": int(len(mite_data)),
        "n_groups": int(mite_data["group"].nunique()),
        "groups": summary.round(3).to_dict(orient="records"),
    }


CALIBRATION_EXCEL_NAME = "calibration.xlsx"


def write_calibration_excel(result, out_dir):
    """Write a calibration's summary, the datasets pooled, every labelled (mite,
    recording) observation, the fraction moving per recording and, when there is
    one, the ROC curve."""
    path = Path(out_dir) / CALIBRATION_EXCEL_NAME

    summary = pd.DataFrame(
        [{"threshold": "in use", **result["current"]}]
        + ([{"threshold": "suggested", **result["best"]}] if result["best"] else [])
    )
    summary["auc"] = result["auc"]
    summary["metric"] = result["metric"]
    summary["metric_params"] = json.dumps(result.get("metric_params") or {})

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

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        pd.DataFrame(result["datasets"]).to_excel(writer, sheet_name="datasets", index=False)
        observations.to_excel(writer, sheet_name="observations", index=False)
        over_time.to_excel(writer, sheet_name="moving_over_time", index=False)
        if result["roc"]:
            pd.DataFrame(result["roc"]).to_excel(writer, sheet_name="roc", index=False)
    return path.name
