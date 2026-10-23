"""The poke test: mites poked by hand between two recordings. One that moves is
alive up to then, one that does not is dead from then on (classes/ground_truth/poke_test.py).
The rounds are saved by mite position next to the recordings, like the ground
truth, and every change at once: the file is small. The test report draws the
survival they show with the detector's laid over it.
"""

from pathlib import Path

from classes.ground_truth.poke_test import PokeSurvival, PokeTest
from classes.storage.files import read_json, write_json
from pipeline import ground_truth, paths, refusals
from pipeline.calibration import report_rows, session_file, truth_entry


def load_poke_test(data_dir):
    """The poke test saved for a recording folder: {rounds: [{after, mites: [{x,
    y, state}]}]}, as PokeTest.saved() gives it; {} without one."""
    return read_json(Path(data_dir) / paths.POKE_FILENAME, {})


def _poke_of(source):
    """The poke test of a calibration session or a saved dataset (`source` has
    its data_dir, mites and times), by mite id. Detections marked not a mite in
    the ground truth have no part in it."""
    truth = source["truth"] if "truth" in source else truth_entry.saved_truth(source)
    mites = [mite for mite, _states in ground_truth.mite_states(source, truth)]
    return PokeTest(mites, len(source["times"]), load_poke_test(source["data_dir"]))


def poke_view(out_dir):
    """The poke test of a calibration session as saved now (PokeTest.view())."""
    return _poke_of(session_file.read_calibration_session(out_dir)).view()


def edit_poke(out_dir, action, after, mite=None, zone=None, state=None):
    """A change on the poke-test page, saved at once: "add" a round poked after
    the recording `after` (-1: before the first) or "remove" it; "set" what a
    `mite` did in it to `state` ("moved", "unmoved" or None for not poked); or
    "fill" the mites of a `zone` (of every zone without one) not poked yet in it
    with `state`, None taking their pokes back. Returns the view with it."""
    stored = session_file.read_calibration_session(out_dir)
    recordings_dir = refusals.recordings_dir(stored, "the poke test cannot be saved with them")
    poke = _poke_of(stored)
    if action == "add":
        poke.add(after)
    elif action == "remove":
        poke.remove(after)
    elif action == "set":
        poke.set(after, str(mite), state)
    elif action == "fill":
        poke.fill(after, state, None if zone is None else int(zone))
    else:
        raise ValueError(f"Unknown change {action!r}.")
    write_json(recordings_dir / paths.POKE_FILENAME, poke.saved())
    return poke.view()


def poked_mites(dataset, scores, threshold, outline=None):
    """The poked mites of a dataset with the detector's death of each at
    `threshold` (PokeSurvival.mites()) and, with `outline` (mite id to the
    outline change's calls, see OutlineChange.calls()), the outline change's;
    [] without a poke test."""
    poke = _poke_of(dataset)
    if not poke.rounds:
        return []
    moving = {mite["id"]: [score >= threshold for score in scores[mite["id"]]] for mite in poke.mites}
    others = {} if outline is None else {"outline": {mite["id"]: outline[mite["id"]] for mite in poke.mites}}
    return PokeSurvival(poke, dataset["times"], moving, others).mites()


def poke_survival(mites, times):
    """The survival of the poked mites of the pooled datasets by the pokes and by
    the detector, for the test report (PokeSurvival.curves()); None without any."""
    curves = PokeSurvival.curves(mites, times)
    if curves:
        for curve in [curves["poke"], curves["detector"], *curves["others"].values()]:
            curve.update({key: report_rows.rounded(curve[key], 2) for key in ("alive", "low", "high")})
    return curves
