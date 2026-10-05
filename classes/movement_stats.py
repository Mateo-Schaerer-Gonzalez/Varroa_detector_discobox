"""Numbers about how the mites move, for the result pages.

Works on the results as pipeline describes them for the pages: each mite with
one motion score and one moving/still call per recording (`scores`, `moving`).

MovementStats holds the arithmetic; MovementReport adds its numbers to the
results: per mite, per zone, and per group in the order the pages list them.
"""

from classes.result_groups import ResultGroups
from classes.survival import SurvivalAnalysis


class MovementStats:
    @staticmethod
    def moving_count(moving):
        """In how many recordings a mite moved."""
        return sum(1 for value in moving if value)

    @staticmethod
    def mean(values):
        return sum(values) / len(values) if values else None

    @staticmethod
    def rest_periods(moving, times):
        """A mite's rests in minutes: the time from a recording in which it moved,
        through at least one in which it was still, to the next one in which it
        moved. Moving in two recordings in a row is no rest. Stillness before the
        first or after the last movement is left out, as its length is not known,
        and so is a stretch with a recording in which the mite was gone (None):
        it may have moved then."""
        rests = []
        last = -1
        unseen = False
        for recording, value in enumerate(moving):
            if value is None:
                unseen = True
            if not value:
                continue
            if last >= 0 and recording - last > 1 and not unseen:
                rests.append(times[recording] - times[last])
            last = recording
            unseen = False
        return rests

    @staticmethod
    def quantile(sorted_values, q):
        """The value at fraction `q` of sorted values, between neighbours."""
        i = (len(sorted_values) - 1) * q
        lo = int(i)
        hi = min(lo + 1, len(sorted_values) - 1)
        return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (i - lo)

    @classmethod
    def quartiles(cls, values):
        """(q1, median, q3) of a non-empty list of numbers."""
        ordered = sorted(values)
        return tuple(cls.quantile(ordered, q) for q in (0.25, 0.5, 0.75))

    @classmethod
    def box_stats(cls, values):
        """Quartiles and Tukey whiskers: the furthest values within 1.5 box lengths."""
        ordered = sorted(values)
        q1, median, q3 = cls.quartiles(ordered)
        reach = 1.5 * (q3 - q1)
        return {
            "q1": q1, "median": median, "q3": q3,
            "lo": next(v for v in ordered if v >= q1 - reach),
            "hi": next(v for v in reversed(ordered) if v <= q3 + reach),
        }


class MovementReport:
    def __init__(self, results):
        self.results = results
        self.times = results["times"]
        self.groups = ResultGroups(results)
        self.survival = SurvivalAnalysis(self.times)

    def describe(self):
        """The results' mites and zones with their numbers added, and the groups:

            mites        + n_moving, mean_score, max_score, last_movement (time, or None),
                           corrected (per recording: the call is the user's, not the
                           detector's; see classes/call_corrections.py), censored (per
                           recording: the user marked the mite gone) and gone_from (the
                           recording from which it is gone for good, or None)
            zones        + n_moving (mites moving per recording), n_seen (mites there
                           per recording, not gone), n_moving_observations,
                           n_never_moved, overall_mean_score and rests (see zone_rests());
                           None for a zone without mites
            group_rows   [{group, zones (ids), n_mites, moving_scores}] for the groups
                         with mites, named ones alphabetically, "unlabeled" last
        """
        return {
            "mites": [{**mite, **self.mite_stats(mite)} for mite in self.results["mites"]],
            "zones": [{**zone, **self.zone_stats(zone)} for zone in self.results["zones"]],
            "group_rows": [self.group_row(group, zones) for group, zones in self.groups.rows()],
        }

    def mite_stats(self, mite):
        corrected = set(self.results.get("corrections", {}).get(mite["id"], []))
        scores = self.seen_scores(mite)
        return {
            "corrected": [recording in corrected for recording in range(len(mite["moving"]))],
            "censored": self.groups.censored(mite),
            "gone_from": self.results.get("gone_from", {}).get(mite["id"]),
            "n_moving": MovementStats.moving_count(mite["moving"]),
            "mean_score": MovementStats.mean(scores),
            "max_score": max(scores, default=None),
            "last_movement": self.survival.last_movement_time(mite["moving"]),
        }

    def seen_scores(self, mite):
        """The mite's scores in the recordings in which it was there."""
        return [score for score, gone in zip(mite["scores"], self.groups.censored(mite)) if not gone]

    def zone_stats(self, zone):
        mites = self.groups.mites_in([zone["id"]])
        if not mites:
            return {"n_moving": None, "n_seen": None, "n_moving_observations": None, "n_never_moved": None,
                    "overall_mean_score": None, "rests": None}
        censored = [self.groups.censored(mite) for mite in mites]
        return {
            "n_moving": [sum(1 for mite in mites if mite["moving"][recording]) for recording in range(len(self.times))],
            "n_seen": [sum(1 for gone in censored if not gone[recording]) for recording in range(len(self.times))],
            "n_moving_observations": sum(MovementStats.moving_count(mite["moving"]) for mite in mites),
            "n_never_moved": sum(1 for mite in mites if not any(mite["moving"])),
            "overall_mean_score": MovementStats.mean([score for mite in mites for score in self.seen_scores(mite)]),
            "rests": self.zone_rests(mites),
        }

    def zone_rests(self, mites):
        """Every rest of the zone's mites (see MovementStats.rest_periods), pooled:
        {values, n_mites (those with a rest), q1, median, q3, shortest, longest},
        or None when no mite was seen still between two movements."""
        per_mite = [rests for rests in (MovementStats.rest_periods(self.groups.seen(mite), self.times) for mite in mites) if rests]
        values = [rest for rests in per_mite for rest in rests]
        if not values:
            return None
        q1, median, q3 = MovementStats.quartiles(values)
        return {"values": values, "n_mites": len(per_mite), "q1": q1, "median": median, "q3": q3,
                "shortest": min(values), "longest": max(values)}

    def group_row(self, group, zones):
        """A group with its zones, and the box of its mites' scores in the
        recordings in which they moved: how strongly they move when they do,
        untouched by how often they sit still. {n, n_mites, q1, median, q3, lo, hi},
        or None when none of its mites was seen moving."""
        mites = self.groups.mites_in([zone["id"] for zone in zones])
        moving = [(mite["id"], score) for mite in mites
                  for score, value in zip(mite["scores"], mite["moving"]) if value]
        box = None
        if moving:
            box = {"n": len(moving), "n_mites": len({mite_id for mite_id, _score in moving}),
                   **MovementStats.box_stats([score for _mite_id, score in moving])}
        return {"group": group, "zones": [zone["id"] for zone in zones], "n_mites": len(mites), "moving_scores": box}
