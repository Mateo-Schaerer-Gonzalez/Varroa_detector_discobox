"""The poke test: mites poked by hand between two recordings, to see which answer.

A mite that moves when poked is alive up to that poke; one that does not is dead
from it on. That gives the poked mites a survival curve of their own, which the
test report draws with the detector's laid over it, by which a mite dies at the
recording after its last movement (classes/survival.py).

A round is every mite poked at one moment, after the recording `after` (counted
from 0; -1 before the first). Deaths and pokes are counted in recordings: a poke
after recording k is at k + 1, the number of recordings before it, as a death is
the number of recordings up to the mite's last movement
(calibration.death_recording()).

PokeTest holds the rounds, by mite id, and reads and writes them by mite
position, as the ground truth is saved, so they survive a change of detector
settings that renumbers the mites. PokeSurvival draws the two curves.
"""

import numpy as np

from classes.survival import SurvivalAnalysis, kaplan_meier

MOVED = "moved"      # the mite moved when poked: alive up to then
UNMOVED = "unmoved"  # it did not: dead from then on
POKE_STATES = (MOVED, UNMOVED)


class PokeTest:
    def __init__(self, mites, n_recordings, saved=None, tolerance=10.0):
        """`mites`: [{id, zone_id, x, y}, ...]; `saved`: the rounds by position,
        as saved() gives them. A saved poke belongs to the nearest mite within
        `tolerance` pixels; those away from every mite, e.g. of detections
        since marked not a mite, are kept as they are."""
        self.mites = list(mites)
        self.n = n_recordings
        self.rounds = []  # [{after, states: {mite id: state}, others: saved pokes of no mite here}], by `after`
        for saved_round in (saved or {}).get("rounds", []):
            after = min(max(int(saved_round.get("after", n_recordings - 1)), -1), n_recordings - 1)
            if self._find(after) is None:
                states, others = self._match(saved_round.get("mites", []), tolerance)
                self.rounds.append({"after": after, "states": states, "others": others})
        self.rounds.sort(key=lambda poke_round: poke_round["after"])

    def _match(self, entries, tolerance):
        """({mite id: state}, the entries of no mite): each entry to the closest
        mite within `tolerance` pixels, a mite and an entry used once."""
        entries = [entry for entry in entries if entry.get("state") in POKE_STATES]
        pairs = sorted(
            (float(np.hypot(mite["x"] - entry["x"], mite["y"] - entry["y"])), mite["id"], index)
            for mite in self.mites for index, entry in enumerate(entries))
        states, used = {}, set()
        for distance, mite_id, index in pairs:
            if distance <= tolerance and mite_id not in states and index not in used:
                states[mite_id] = entries[index]["state"]
                used.add(index)
        return states, [entry for index, entry in enumerate(entries) if index not in used]

    def _find(self, after):
        return next((poke_round for poke_round in self.rounds if poke_round["after"] == after), None)

    def _round(self, after):
        poke_round = self._find(int(after))
        if poke_round is None:
            raise ValueError(f"No poke round after recording {int(after) + 1}.")
        return poke_round

    # --- changes

    def add(self, after):
        """A new round, poked after the recording `after` (-1: before the first)."""
        after = int(after)
        if not -1 <= after < self.n:
            raise ValueError(f"No recording {after + 1} in this dataset.")
        if self._find(after) is not None:
            raise ValueError("There is already a poke round there.")
        self.rounds.append({"after": after, "states": {}, "others": []})
        self.rounds.sort(key=lambda poke_round: poke_round["after"])

    def remove(self, after):
        self.rounds.remove(self._round(after))

    def set(self, after, mite_id, state):
        """What one mite did in the round after `after`: MOVED, UNMOVED, or None for not poked."""
        self._check(state)
        if all(mite["id"] != mite_id for mite in self.mites):
            raise ValueError(f"No mite {mite_id} in this dataset.")
        states = self._round(after)["states"]
        if state is None:
            states.pop(mite_id, None)
        else:
            states[mite_id] = state

    def fill(self, after, state, zone_id=None):
        """Give `state` to the mites of a zone (of every zone without one) not
        poked yet in the round after `after`; None takes their pokes back instead."""
        self._check(state)
        states = self._round(after)["states"]
        for mite in self.mites:
            if zone_id is not None and mite["zone_id"] != zone_id:
                continue
            if state is None:
                states.pop(mite["id"], None)
            else:
                states.setdefault(mite["id"], state)

    @staticmethod
    def _check(state):
        if state not in (*POKE_STATES, None):
            raise ValueError(f"Unknown poke result {state!r}.")

    # --- what they say

    def pokes(self, mite_id):
        """[(after, state)] of one mite, in order: the rounds it was poked in."""
        return [(poke_round["after"], poke_round["states"][mite_id])
                for poke_round in self.rounds if mite_id in poke_round["states"]]

    def bounds(self, mite_id):
        """(alive until, dead from), in recordings: the mite was alive through
        the recordings before the last poke it answered, and is dead from the
        first poke it did not answer on. Each None without such a poke."""
        pokes = self.pokes(mite_id)
        answered = [after + 1 for after, state in pokes if state == MOVED]
        unanswered = [after + 1 for after, state in pokes if state == UNMOVED]
        return (max(answered) if answered else None, min(unanswered) if unanswered else None)

    # --- saving, and for the page

    def saved(self):
        """The rounds by mite position, as they are saved next to the recordings."""
        where = {mite["id"]: mite for mite in self.mites}
        return {"rounds": [
            {"after": poke_round["after"],
             "mites": [{"x": where[mite_id]["x"], "y": where[mite_id]["y"], "state": state}
                       for mite_id, state in poke_round["states"].items()] + poke_round["others"]}
            for poke_round in self.rounds]}

    def view(self):
        """What the poke-test page shows: the mites that can be poked, and each
        round with what its mites did and how many did what ("unset": not poked)."""
        rounds = []
        for poke_round in self.rounds:
            states = poke_round["states"]
            counts = {state: sum(1 for value in states.values() if value == state) for state in POKE_STATES}
            rounds.append({"after": poke_round["after"], "states": dict(states),
                           "counts": {**counts, "unset": len(self.mites) - len(states)}})
        return {"mites": [mite["id"] for mite in self.mites], "n_recordings": self.n, "rounds": rounds}


class PokeSurvival:
    def __init__(self, poke, times, moving, others=None):
        """`poke`: a PokeTest; `times`: its recordings' times in minutes;
        `moving`: mite id -> the detector's call in each recording; `others`:
        {name: mite id -> a call in each recording} of other sources of calls,
        e.g. the outline change between recordings (classes/outline_change.py)."""
        self.poke = poke
        self.times = list(times)
        self.moving = moving
        self.others = others or {}

    def mites(self):
        """One row per mite poked at least once: {n_recordings (of its dataset),
        death (the detector's, in recordings: the one after its last movement, 0
        for a mite it never saw moving), alive_until, dead_from (what the pokes
        say, see PokeTest.bounds())}, and with `others`, "others": {name: the
        death by those calls, as the detector's}."""
        rows = []
        for mite in self.poke.mites:
            if self.poke.pokes(mite["id"]):
                alive_until, dead_from = self.poke.bounds(mite["id"])
                rows.append({"n_recordings": len(self.times),
                             "death": SurvivalAnalysis.last_movement(self.moving[mite["id"]]) + 1,
                             "alive_until": alive_until, "dead_from": dead_from,
                             **({"others": {name: SurvivalAnalysis.last_movement(calls[mite["id"]]) + 1
                                            for name, calls in self.others.items()}} if self.others else {})})
        return rows

    @staticmethod
    def curves(mites, times):
        """The Kaplan-Meier survival of the poked mites (`mites`: the rows of
        mites(), of one dataset or of several pooled) by the pokes and by the
        detector, on the same mites, over the recordings' `times`:

            times        `times`, with one more at the end when mites were poked after
                         the last recording: where those that did not answer are dead
            final_poke   whether there is that one more
            poke         {alive, low, high (percent at each time, see kaplan_meier()), n_mites, n_dead}:
                         a mite dies at the first poke it did not answer, so in the
                         recording after it; one that answered every poke is censored
                         at its last one, where it still counts among the living
            detector     the same by its calls: a mite dies at the recording after its
                         last movement, one never seen moving at the first, and one
                         moving in its last recording is censored there. None past the
                         last recording, where the detector saw nothing
            others       {name: the same by each other source of calls of the rows}
            n_left_out   the mites that answered a poke after not answering an earlier
                         one: the pokes cannot both be right, so they are in neither curve

        None without poked mites."""
        if not mites:
            return None
        poked = [mite for mite in mites
                 if mite["alive_until"] is None or mite["dead_from"] is None or mite["alive_until"] <= mite["dead_from"]]
        n = len(times)
        final_poke = any(n in (mite["dead_from"], mite["alive_until"]) for mite in poked)
        grid = list(times) + ([times[-1] + (times[-1] - times[-2] if n > 1 else 1.0)] if final_poke else [])

        def by_poke(mite):
            if mite["dead_from"] is not None:
                return grid[mite["dead_from"]], True
            return grid[mite["alive_until"]], False

        def by_calls(mite, death):
            if death < mite["n_recordings"]:
                return grid[death], True
            return grid[mite["n_recordings"] - 1], False

        def curve(survivals, until):
            described = kaplan_meier(survivals, grid)
            return {**{key: values[:until] + [None] * (len(grid) - until) for key, values in described.items()},
                    "n_mites": len(survivals), "n_dead": sum(1 for _time, dead in survivals if dead)}

        return {
            "times": grid,
            "final_poke": final_poke,
            "poke": curve([by_poke(mite) for mite in poked], len(grid)),
            "detector": curve([by_calls(mite, mite["death"]) for mite in poked], n),
            "others": {name: curve([by_calls(mite, mite["others"][name]) for mite in poked], n)
                       for name in (poked[0].get("others") or {} if poked else {})},
            "n_left_out": len(mites) - len(poked),
        }
