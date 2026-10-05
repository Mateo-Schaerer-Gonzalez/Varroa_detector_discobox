"""Alive or dead: whether each mite is alive in each recording, when it died, and
whether the mites of one group died faster than those of the negative control.

A mite's movement per recording (one moving/still call each, from the analysis)
is all this goes by. A mite counts as alive in every recording up to the last
one in which it moved. With a death time (`death_minutes`, from the test-run
settings or the results page), it counts as dead from then on only once it has
been seen still for that long after it (or from the start, if it never moved);
until then it may yet move, so it counts as alive.

Only the mites seen moving at least once are in the study: one never seen
moving may have been dead from the start, or no live mite at all, so it is left
out of every survival number (SurvivalAnalysis.in_study).

A mite the user marked gone in a recording, e.g. fallen off the plate
(classes/call_corrections.py), has None there instead of a call. It is followed
up to the last recording in which it was there (SurvivalAnalysis.followed): one
gone from a recording on, and not dead by then, is right-censored at the
recording before, known only to have lived that long. A recording in which it
was gone in between says nothing: the mite did not move in it, as far as is known.

SurvivalAnalysis applies that rule; SurvivalReport describes it for the result
pages: the survival rate over time per group and per zone, each mite's lifeline,
and every group, its zones pooled, tested against the negative controls.
"""

import warnings
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

from classes.result_groups import ResultGroups


@dataclass(frozen=True)
class LogRank:
    """A log-rank test: the deaths among the tested mites, how many there would
    have been had they died like the controls, chi-squared and its p value (None
    when no death could have gone either way)."""

    observed: int
    expected: float
    chi2: float | None
    p: float | None


def kaplan_meier(survivals, times, confidence=0.95):
    """The Kaplan-Meier curve of `survivals` ((time, dead) pairs, see
    SurvivalAnalysis.survival()) at `times`, in percent, with its confidence
    interval: scipy's, by Greenwood's formula on the log-log scale, which keeps it
    within 0-100%. Where the interval is undefined (all or none alive) it is the
    estimate itself. {alive, low, high}, each None throughout without survivals."""
    if not survivals:
        return {"alive": [None] * len(times), "low": [None] * len(times), "high": [None] * len(times)}
    curve = stats.ecdf(SurvivalAnalysis.censored(survivals)).sf
    with warnings.catch_warnings():
        # Where it is undefined, scipy warns and gives NaN.
        warnings.simplefilter("ignore", RuntimeWarning)
        interval = curve.confidence_interval(confidence, method="log-log")
    estimate = curve.evaluate(times)
    low = interval.low.evaluate(times)
    high = interval.high.evaluate(times)
    low = np.where(np.isnan(low), estimate, low)
    high = np.where(np.isnan(high), estimate, high)

    def percent(values):
        return [None if np.isnan(value) else 100 * float(value) for value in values]

    return {"alive": percent(estimate), "low": percent(low), "high": percent(high)}


class SurvivalAnalysis:
    def __init__(self, times, death_minutes=0):
        """`times`: the recordings' times in minutes, in order."""
        self.times = list(times)
        self.death_minutes = death_minutes or 0

    @staticmethod
    def in_study(moving):
        """Whether a mite counts in the survival numbers: only once it has been
        seen moving, so it is known to have been alive."""
        return any(moving)

    @classmethod
    def study(cls, movings):
        """The mites of `movings` in the study, see in_study()."""
        return [moving for moving in movings if cls.in_study(moving)]

    @staticmethod
    def last_movement(moving):
        """The last recording in which a mite moved; -1 when it never did."""
        return max((index for index, value in enumerate(moving) if value), default=-1)

    def last_movement_time(self, moving):
        """The time of the last recording in which a mite moved; None when it never did."""
        last = self.last_movement(moving)
        return None if last < 0 else self.times[last]

    @staticmethod
    def followed(moving):
        """The last recording in which a mite was there (not None): the end of
        its follow-up, the last recording unless it is gone by then; -1 when it
        never was there."""
        return max((index for index, value in enumerate(moving) if value is not None), default=-1)

    def is_alive(self, moving, recording):
        """Whether a mite that moved as `moving` (one call per recording, None
        where it was gone) counts as alive in recording `recording`; not after
        the end of its follow-up, where nothing is known of it."""
        last = self.last_movement(moving)
        if recording <= last:
            return True
        end = self.followed(moving)
        if recording > end:
            return False
        still_for = self.times[end] - self.times[max(last, 0)]
        return still_for < self.death_minutes

    def alive_count(self, movings, recording):
        return sum(1 for moving in movings if self.is_alive(moving, recording))

    def alive_percent(self, movings):
        """The share of the mites alive in each recording, in percent; None
        throughout without mites. With a mite gone before the last recording it
        is the Kaplan-Meier estimate, which takes that mite out of the count
        from then on instead of counting it as dead."""
        if not movings:
            return [None] * len(self.times)
        if any(self.followed(moving) < len(self.times) - 1 for moving in movings):
            return kaplan_meier([self.survival(moving) for moving in movings], self.times)["alive"]
        return [100 * self.alive_count(movings, recording) / len(movings) for recording in range(len(self.times))]

    def alive_ci(self, movings, confidence=0.95):
        """The confidence interval of alive_percent() in each recording, in percent,
        as {low, high}. With the mites censored only at the end, alive_percent()
        is the Kaplan-Meier estimate; the interval is scipy's, by Greenwood's
        formula on the log-log scale (see kaplan_meier()). None throughout
        without mites."""
        curve = kaplan_meier([self.survival(moving) for moving in movings], self.times, confidence)
        return {"low": curve["low"], "high": curve["high"]}

    def lt50(self, movings):
        """LT50, the time by which half the mites are dead: the first recording in
        which at most 50% of them are alive, the median of the Kaplan-Meier curve.
        Its 95% confidence interval runs from the first recording in which the low
        bound of alive_ci() is at most 50% to the first in which the high bound
        is. As {estimate, low, high}, in minutes from the first recording; each
        None when it is not reached by the last recording."""
        def first_at_most_half(percents):
            for time, percent in zip(self.times, percents):
                if percent is not None and percent <= 50:
                    return time
            return None

        ci = self.alive_ci(movings)
        return {
            "estimate": first_at_most_half(self.alive_percent(movings)),
            "low": first_at_most_half(ci["low"]),
            "high": first_at_most_half(ci["high"]),
        }

    def survival(self, moving):
        """(time, dead): when a mite died, at the first recording in which it no
        longer counts as alive. One alive at the end of its follow-up (the last
        recording, or the last before it was gone) is censored there: all that
        is known is that it lived at least that long."""
        end = self.followed(moving)
        for recording, time in enumerate(self.times[:end + 1]):
            if not self.is_alive(moving, recording):
                return time, True
        return self.times[max(end, 0)], False

    def dead_count(self, movings):
        return sum(1 for moving in movings if self.survival(moving)[1])

    def log_rank(self, movings, controls):
        """The log-rank test of the survival() of the mites `movings` against that
        of `controls`, its statistic squared is chi-squared with one
        degree of freedom. The observed and expected deaths are those among
        `movings`, see expected_deaths()."""
        tested = [self.survival(moving) for moving in movings]
        control = [self.survival(moving) for moving in controls]
        observed = sum(1 for _time, dead in tested if dead)
        expected = self.expected_deaths(tested, control)

        # No death that could have gone either way: scipy divides by a variance of 0.
        with np.errstate(divide="ignore", invalid="ignore"):
            test = stats.logrank(self.censored(tested), self.censored(control))
        if not np.isfinite(test.statistic):
            return LogRank(observed, expected, None, None)
        return LogRank(observed, expected, float(test.statistic) ** 2, float(test.pvalue))

    @staticmethod
    def expected_deaths(tested, controls):
        """How many of the `tested` would have died had they died like the
        `controls` (both survival()s): at every time a mite died, the deaths then,
        shared out among the mites still at risk in proportion to the tested."""
        everyone = tested + controls
        death_times = set()
        for time, dead in everyone:
            if dead:
                death_times.add(time)

        expected = 0.0
        for death_time in death_times:
            deaths = 0  # deaths at this time
            at_risk = 0  # mites at risk at this time: not dead or censored before it
            tested_at_risk = 0  # the same among the tested
            for time, dead in everyone:
                if dead and time == death_time:
                    deaths += 1
                if time >= death_time:
                    at_risk += 1
            for time, _dead in tested:
                if time >= death_time:
                    tested_at_risk += 1
            expected += deaths * tested_at_risk / at_risk
        return expected

    @staticmethod
    def censored(survivals):
        """survival()s as scipy takes them: the mites alive at the end are
        right-censored, known only to have lived at least that long."""
        uncensored = []  # the time each dead mite died
        right = []  # the last recording's time, for each mite still alive then
        for time, dead in survivals:
            if dead:
                uncensored.append(time)
            else:
                right.append(time)
        return stats.CensoredData(uncensored=uncensored, right=right)


class SurvivalReport:
    def __init__(self, results, death_minutes=0, controls=()):
        """`results` as pipeline describes them for the pages; `controls` the ids
        of the zones ticked as negative controls."""
        self.analysis = SurvivalAnalysis(results["times"], death_minutes)
        self.groups = ResultGroups(results)
        self.controls = sorted(set(controls))

    def movings(self, zone_ids):
        """The movement of the mites of the zones `zone_ids` in the study."""
        return SurvivalAnalysis.study(self.all_movings(zone_ids))

    def all_movings(self, zone_ids):
        return [self.groups.seen(mite) for mite in self.groups.mites_in(zone_ids)]

    def describe(self):
        """Plain data for the result pages:

            death_minutes   the time a mite must be still to count as dead
            groups          [{group, alive, alive_ci, n_mites, n_left_out}]: each group's
                            survival rate (%) per recording, with its 95% confidence
                            interval (see alive_ci()), of its n_mites in the study;
                            n_left_out were never seen moving
            zones           {zone id: {alive, alive_ci, n_alive, n_mites, n_left_out}}: the
                            same per zone, and how many are alive
            mites           {mite id: {in_study, time, dead, lost}}: each mite's lifeline,
                            see lifeline()
            n_left_out      the mites never seen moving, left out
            log_rank        the groups against the negative controls, see log_rank()
        """
        analysis = self.analysis
        zones = {}
        for zone in self.groups.zones:
            movings = self.movings([zone["id"]])
            zones[zone["id"]] = {
                "alive": analysis.alive_percent(movings),
                "alive_ci": analysis.alive_ci(movings),
                "n_alive": [analysis.alive_count(movings, recording) for recording in range(len(analysis.times))],
                **self.counts([zone["id"]]),
            }
        groups = []
        for group, group_zones in self.groups.rows():
            zone_ids = [zone["id"] for zone in group_zones]
            movings = self.movings(zone_ids)
            groups.append({"group": group, "alive": analysis.alive_percent(movings), "alive_ci": analysis.alive_ci(movings),
                           **self.counts(zone_ids)})
        mites = self.groups.mites_in([zone["id"] for zone in self.groups.zones])
        return {
            "death_minutes": analysis.death_minutes,
            "groups": groups,
            "zones": zones,
            "mites": {mite["id"]: self.lifeline(self.groups.seen(mite)) for mite in mites},
            "n_left_out": sum(1 for mite in mites if not SurvivalAnalysis.in_study(self.groups.seen(mite))),
            "log_rank": self.log_rank(),
        }

    def counts(self, zone_ids):
        """{n_mites, n_left_out}: the mites of the zones in the study, and those not."""
        n_all = len(self.all_movings(zone_ids))
        n_mites = len(self.movings(zone_ids))
        return {"n_mites": n_mites, "n_left_out": n_all - n_mites}

    def lifeline(self, moving):
        """{in_study, time, dead, lost}: when a mite in the study died, or the
        time of the last recording of its follow-up when it is still alive then
        (right-censored, dead False): the last recording, or with `lost` the last
        before the mite was gone. time and dead None for a mite left out."""
        if not SurvivalAnalysis.in_study(moving):
            return {"in_study": False, "time": None, "dead": None, "lost": False}
        time, dead = self.analysis.survival(moving)
        lost = not dead and SurvivalAnalysis.followed(moving) < len(moving) - 1
        return {"in_study": True, "time": time, "dead": dead, "lost": lost}

    def log_rank(self):
        """Every group, its zones pooled, against the zones ticked as negative
        controls, pooled:

            controls          the zones ticked
            control_zones     those of them with mites
            control_groups    their groups
            n_control_mites, n_control_dead, control_lt50
                              of the control mites in the study
            rows             [{group, zones, n_mites, lt50, observed, expected, chi2, p}]:
                                one per group of the zones not ticked; none
                                without control mites
        LT50s as SurvivalAnalysis.lt50() gives them.
        """
        ticked = set(self.controls)
        control_zones = [zone for zone in self.groups.zones if zone["id"] in ticked]
        control_movings = self.movings([zone["id"] for zone in control_zones])
        rows = []
        if control_movings:
            tested = [zone for zone in self.groups.zones if zone["id"] not in ticked]
            for group, group_zones in self.groups.rows(tested):
                zone_ids = [zone["id"] for zone in group_zones]
                movings = self.movings(zone_ids)
                rows.append({"group": group, "zones": zone_ids, "n_mites": len(movings),
                             "lt50": self.analysis.lt50(movings),
                             **asdict(self.analysis.log_rank(movings, control_movings))})
        return {
            "controls": self.controls,
            "control_zones": [zone["id"] for zone in control_zones],
            "control_groups": list(dict.fromkeys(ResultGroups.group_of(zone) for zone in control_zones)),
            "n_control_mites": len(control_movings),
            "n_control_dead": self.analysis.dead_count(control_movings),
            "control_lt50": self.analysis.lt50(control_movings) if control_movings else None,
            "rows": rows,
        }
