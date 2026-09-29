"""Alive or dead: whether each mite is alive in each recording, when it died, and
whether the mites of one group died faster than those of the negative control.

A mite's movement per recording (one moving/still call each, from the analysis)
is all this goes by. A mite counts as alive in every recording up to the last
one in which it moved. With a death time (`death_minutes`, from the test-run
settings or the results page), it counts as dead from then on only once it has
been seen still for that long after it (or from the start, if it never moved);
until then it may yet move, so it counts as alive.

SurvivalAnalysis applies that rule; SurvivalReport describes it for the result
pages: the mites alive over time per group and per zone, and every group, its
zones pooled, tested against the negative controls.
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


class SurvivalAnalysis:
    def __init__(self, times, death_minutes=0):
        """`times`: the recordings' times in minutes, in order."""
        self.times = list(times)
        self.death_minutes = death_minutes or 0

    @staticmethod
    def last_movement(moving):
        """The last recording in which a mite moved; -1 when it never did."""
        return max((index for index, value in enumerate(moving) if value), default=-1)

    def last_movement_time(self, moving):
        """The time of the last recording in which a mite moved; None when it never did."""
        last = self.last_movement(moving)
        return None if last < 0 else self.times[last]

    def is_alive(self, moving, recording):
        """Whether a mite that moved as `moving` (one bool per recording) counts
        as alive in recording `recording`."""
        last = self.last_movement(moving)
        if recording <= last:
            return True
        still_for = self.times[-1] - self.times[max(last, 0)]
        return still_for < self.death_minutes

    def alive_count(self, movings, recording):
        return sum(1 for moving in movings if self.is_alive(moving, recording))

    def alive_percent(self, movings):
        """The share of the mites alive in each recording, in percent; None
        throughout without mites."""
        if not movings:
            return [None] * len(self.times)
        return [100 * self.alive_count(movings, recording) / len(movings) for recording in range(len(self.times))]

    def alive_ci(self, movings, confidence=0.95):
        """The confidence interval of alive_percent() in each recording, in percent,
        as {low, high}. With the mites censored only at the end, alive_percent()
        is the Kaplan-Meier estimate; the interval is scipy's, by Greenwood's
        formula on the log-log scale, which keeps it within 0-100%. Where all
        or none of the mites are alive it is undefined, and taken as the estimate
        itself. None throughout without mites."""
        if not movings:
            return {"low": [None] * len(self.times), "high": [None] * len(self.times)}
        curve = stats.ecdf(self.censored([self.survival(moving) for moving in movings])).sf
        with warnings.catch_warnings():
            # Where it is undefined, scipy warns and gives NaN.
            warnings.simplefilter("ignore", RuntimeWarning)
            interval = curve.confidence_interval(confidence, method="log-log")
        estimate = curve.evaluate(self.times)
        low = interval.low.evaluate(self.times)
        high = interval.high.evaluate(self.times)
        low = np.where(np.isnan(low), estimate, low)
        high = np.where(np.isnan(high), estimate, high)
        return {"low": [100 * float(value) for value in low], "high": [100 * float(value) for value in high]}

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
        longer counts as alive. One alive in the last recording is censored there:
        all that is known is that it lived at least that long."""
        for recording, time in enumerate(self.times):
            if not self.is_alive(moving, recording):
                return time, True
        return self.times[-1], False

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
        return [mite["moving"] for mite in self.groups.mites_in(zone_ids)]

    def describe(self):
        """Plain data for the result pages:

            death_minutes   the time a mite must be still to count as dead
            groups          [{group, alive, alive_ci}]: each group's mites alive (%) per
                            recording, with its 95% confidence interval (see alive_ci())
            zones           {zone id: {alive, alive_ci, n_alive}}: the same per zone, and how many
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
            }
        groups = []
        for group, group_zones in self.groups.rows():
            movings = self.movings([zone["id"] for zone in group_zones])
            groups.append({"group": group, "alive": analysis.alive_percent(movings), "alive_ci": analysis.alive_ci(movings)})
        return {
            "death_minutes": analysis.death_minutes,
            "groups": groups,
            "zones": zones,
            "log_rank": self.log_rank(),
        }

    def log_rank(self):
        """Every group, its zones pooled, against the zones ticked as negative
        controls, pooled:

            controls          the zones ticked
            control_zones     those of them with mites
            control_groups    their groups
            n_control_mites, n_control_dead, control_lt50
            rows              [{group, zones, n_mites, lt50, observed, expected, chi2, p}]:
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
