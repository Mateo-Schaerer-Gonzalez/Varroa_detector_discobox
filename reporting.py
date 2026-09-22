"""Turns the mite score table into files on disk (one Excel workbook and the figures)
and into plain data the web page can browse zone by zone and mite by mite.

Runs head-less (the Agg backend) so it behaves the same from the CLI and the server.
"""

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
    """One row per user-defined group: how many mites, how many survived, and their
    score statistics."""
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
    alive_at_end = _last_recording(mite_data).groupby("group")["alive"].sum()
    summary.insert(1, "n_alive_at_end", alive_at_end.reindex(summary.index, fill_value=0).astype(int))
    summary.insert(2, "survival_at_end", summary["n_alive_at_end"] / summary["n_mites"])
    return summary.reset_index().sort_values("group")


def survival_table(mite_data):
    """Long-form survival: per group and per zone, how many mites are alive at each
    recording. One row per (level, name, time)."""
    tables = []
    for level, key in [("group", "group"), ("zone", "zone_id")]:
        table = (
            mite_data.groupby([key, "time"])
            .agg(n_mites=("mite_ID", "nunique"), n_alive=("alive", "sum"))
            .reset_index()
            .rename(columns={key: "name"})
        )
        table.insert(0, "level", level)
        tables.append(table)

    survival = pd.concat(tables, ignore_index=True)
    survival["n_alive"] = survival["n_alive"].astype(int)
    survival["fraction_alive"] = survival["n_alive"] / survival["n_mites"]
    return survival


def write_excel(mite_data, out_dir):
    """Write the long-form measurements, the per-group summary and survival."""
    path = Path(out_dir) / EXCEL_NAME
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        mite_data.to_excel(writer, sheet_name="measurements", index=False)
        summarise_by_group(mite_data).to_excel(writer, sheet_name="group_summary", index=False)
        survival_table(mite_data).to_excel(writer, sheet_name="survival", index=False)
    return path.name


def write_figures(mite_data, out_dir):
    """Save every figure as a PNG and return their filenames, most useful first."""
    plotter = Plotter(mite_data)
    figures = {
        "survival_by_group.png": plotter.plot_survival_by_group(),
        "distribution_by_group.png": plotter.plot_distribution_by_group(),
        "score_over_time.png": plotter.plot_score_over_time(),
        "score_distribution.png": plotter.plot_score_distribution(),
    }

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
        dead_rows = rows[~rows["alive"]]
        mites.append(
            {
                "id": str(mite_id),
                "zone_id": int(rows["zone_id"].iloc[0]),
                "group": rows["group"].iloc[0],
                "x": round(float(rows["x"].iloc[0]), 1),
                "y": round(float(rows["y"].iloc[0]), 1),
                "scores": _floats(rows["motion_score"]),
                "moving": [bool(value) for value in rows["moving"]],
                "alive": [bool(value) for value in rows["alive"]],
                # first recording at which the mite counts as dead, or None
                "died_at": None if dead_rows.empty else round(float(dead_rows["time"].iloc[0]), 2),
            }
        )
    return sorted(mites, key=lambda mite: int(mite["id"]) if mite["id"].isdigit() else mite["id"])


def _survival_series(rows, times):
    """Fraction alive at each time, or None where there are no mites."""
    if rows.empty:
        return None
    by_time = rows.groupby("time")["alive"].mean()
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
                "n_alive_at_end": int(last["alive"].sum()),
                "survival": _survival_series(rows, times),
                "mean_score": None if mean_score is None else _floats(mean_score),
            }
        )
    return described


def describe_groups(mite_data, times):
    """Survival curve per group, for the overview chart."""
    return [
        {"group": group, "survival": _survival_series(rows, times)}
        for group, rows in sorted(mite_data.groupby("group"), key=lambda item: item[0])
    ]


def write_outputs(mite_data, annotated_image, out_dir):
    """Write every artefact for one analysis run and describe it in plain data.

    The returned dict contains only filenames and numbers, so it can cross into the
    web layer unchanged.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if mite_data.empty:
        raise ValueError("No mites were detected, so there is nothing to report.")

    cv2.imwrite(str(out_dir / DETECTIONS_NAME), annotated_image)

    summary = summarise_by_group(mite_data)
    return {
        "excel": write_excel(mite_data, out_dir),
        "figures": write_figures(mite_data, out_dir),
        "detections": DETECTIONS_NAME,
        "summary": {
            "n_mites": int(mite_data["mite_ID"].nunique()),
            "n_alive_at_end": int(_last_recording(mite_data)["alive"].sum()),
            "n_observations": int(len(mite_data)),
            "n_groups": int(mite_data["group"].nunique()),
            "groups": summary.round(3).to_dict(orient="records"),
        },
    }


CALIBRATION_EXCEL_NAME = "calibration.xlsx"


def write_calibration_excel(result, out_dir):
    """Write a calibration's summary, every labelled (mite, recording) observation,
    the survival curves and, when there is one, the ROC curve."""
    path = Path(out_dir) / CALIBRATION_EXCEL_NAME

    summary = pd.DataFrame(
        [{"threshold": "in use", **result["current"]}]
        + ([{"threshold": "suggested", **result["best"]}] if result["best"] else [])
    )
    summary["auc"] = result["auc"]
    summary["metric"] = result["metric"]

    observations = pd.DataFrame(result["observations"]).rename(
        columns={"score": "score_from_here_on", "recording_score": "score_this_recording"}
    )

    def survival_rows(level, name, curves):
        return pd.DataFrame(
            {
                "level": level,
                "name": name,
                "time": result["times"],
                "n_labelled": curves["n"],
                "alive_ground_truth": curves["truth"],
                "alive_called_in_use": curves["current"],
                **({"alive_called_suggested": curves["suggested"]} if "suggested" in curves else {}),
            }
        )

    survival = pd.concat(
        [survival_rows("all", "all", result["survival"])]
        + [survival_rows("group", group["group"], group) for group in result["group_survival"]],
        ignore_index=True,
    )

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        observations.to_excel(writer, sheet_name="observations", index=False)
        survival.to_excel(writer, sheet_name="survival", index=False)
        if result["roc"]:
            pd.DataFrame(result["roc"]).to_excel(writer, sheet_name="roc", index=False)
    return path.name
