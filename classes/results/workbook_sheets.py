"""Sheets of a run's workbook beyond the tables of reporting.py: one per group,
and the settings the results were made with (pipeline/run_settings.py).
"""

import json
import re

import pandas as pd

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
