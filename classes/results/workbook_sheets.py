"""Sheets of a run's workbook beyond the tables of reporting.py: one per group,
the settings the results were made with (pipeline/run_settings.py), and the
percent of each group alive by recording under the group summary.
"""

import json
import re

import pandas as pd

from classes.results.survival import Calls, SurvivalAnalysis

SETTINGS_SHEET = "settings"
GROUP_PREFIX = "group "
_SHEET_NAME_LENGTH = 31  # Excel's limit
_NOT_IN_SHEET_NAMES = re.compile(r"[\[\]:*?/\\]")
_CELL_LENGTH = 32767  # Excel's limit on the text of a cell


def group_sheet_names(groups, taken=()):
    """{group: its sheet's name}: "group <name>", without the characters Excel
    refuses, cut to its length and made unique against each other and `taken`."""
    names, used = {}, {name.lower() for name in taken}
    for group in groups:
        base = (GROUP_PREFIX + _NOT_IN_SHEET_NAMES.sub("_", str(group)))[:_SHEET_NAME_LENGTH]
        name, number = base, 2
        while name.lower() in used:
            suffix = f" ({number})"
            name, number = base[:_SHEET_NAME_LENGTH - len(suffix)] + suffix, number + 1
        used.add(name.lower())
        names[group] = name
    return names


def group_tables(last_moved, scores):
    """{group: its table}: one row per mite of the group, with its zone, when it
    last moved and its score in every recording. `last_moved` and `scores` are
    reporting.last_moved_table() and reporting.scores_table()."""
    table = scores.merge(last_moved[["mite_ID", "last_moved_min"]], on="mite_ID", how="left")
    table.insert(2, "last_moved_min", table.pop("last_moved_min"))
    return {group: rows.drop(columns="group").reset_index(drop=True)
            for group, rows in sorted(table.groupby("group", sort=False), key=lambda item: str(item[0]))}


def alive_table(mite_data, death_minutes=0, starts=None):
    """The percent of each group's mites alive in every recording, as the result
    pages' survival chart shows it (classes/results/survival.py): one row per
    recording, its time and a column per group. Mites never seen moving are left
    out; one marked gone is censored. `starts`: {mite id: the recording a live
    run added it in}, for those added after the first."""
    times = sorted(mite_data["time"].unique())
    analysis = SurvivalAnalysis(times, death_minutes)
    starts = starts or {}
    table = pd.DataFrame({"time": times})
    for group, rows in sorted(mite_data.groupby("group"), key=lambda item: str(item[0])):
        movings = []
        for mite_id, mite in rows.groupby("mite_ID"):
            mite = mite.sort_values("time")
            gone = mite["censored"].to_numpy(dtype=bool) if "censored" in mite else [False] * len(mite)
            calls = [None if out else bool(moving) for moving, out in zip(mite["moving"], gone)]
            movings.append(Calls(calls, starts.get(str(mite_id), 0)))
        table[group] = analysis.alive_percent(SurvivalAnalysis.study(movings))
    return table


def alive_title(death_minutes):
    """The line above alive_table() in the workbook: the death rule it was made with."""
    rule = (f"dead once still for {death_minutes} min after its last movement" if death_minutes
            else "dead from the recording after its last movement")
    return f"Percent alive by recording (time in minutes; a mite counts as {rule}; mites never seen moving left out)"


def _rows(value, path):
    """(path, value) of every value in `value`, nested dicts and lists of dicts
    opened; a list of plain values is one cell, as JSON."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _rows(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list) and value and all(isinstance(item, (dict, list)) for item in value):
        for index, item in enumerate(value):
            yield from _rows(item, f"{path}.{index}")
    elif isinstance(value, (dict, list)):
        text = json.dumps(value)
        yield path, text if len(text) <= _CELL_LENGTH else "too long for a cell: see run_settings.json"
    else:
        yield path, value


def settings_table(settings):
    """`settings` (run_settings.describe()) as rows: its section, the parameter
    (the path to it, dotted) and its value."""
    rows = [(path.split(".", 1)[0], path.split(".", 1)[1] if "." in path else "", value)
            for path, value in _rows(settings, "")]
    return pd.DataFrame(rows, columns=["section", "parameter", "value"])
