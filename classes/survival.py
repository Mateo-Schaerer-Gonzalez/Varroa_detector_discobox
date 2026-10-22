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

A mite a live run added later (classes/follow_up.py) has None in the
recordings before it, and its own clock: its follow-up starts at the recording
it was added in (`Calls.start`), and the time it lived is counted from there.
The survival curves, their counts of mites alive, the LT50s and the log-rank
tests are all on that clock: time since each mite's follow-up started, which
for the mites found at the start is the run's own. So is each mite's lifeline:
every mite runs on its own timer.

SurvivalAnalysis applies that rule; SurvivalReport describes it for the result
pages: the survival rate over time per group and per zone, each mite's lifeline,
and every group, its zones pooled, tested against the negative controls.
"""

import warnings
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

from classes.result_groups import Calls, ResultGroups  # noqa: F401  (Calls: a mite's calls with its start)


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
        return [None if value != value else 100 * value for value in values.tolist()]  # NaN is not itself

    return {"alive": percent(estimate), "low": percent(low), "high": percent(high)}


def start_of(moving):
    return getattr(moving, "start", 0)


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
        for index in range(len(moving) - 1, -1, -1):
            if moving[index]:
                return index
        return -1

    def last_movement_time(self, moving):
        """The time of the last recording in which a mite moved; None when it never did."""
        last = self.last_movement(moving)
        return None if last < 0 else self.times[last]

    @staticmethod
    def followed(moving):
        """The last recording in which a mite was there (not None): the end of
        its follow-up, the last recording unless it is gone by then; -1 when it
        never was there."""
        for index in range(len(moving) - 1, -1, -1):
            if moving[index] is not None:
                return index
        return -1

    def alive_until(self, moving):
        """The last recording in which a mite that moved as `moving` (one call
        per recording, None where it was gone) counts as alive; -1 when it does
        in none. That is its last movement, or the end of its follow-up when it
        has not been still for the death time by then: whether it counts as
        alive after its last movement is the same for every recording up to
        there, so one pass over its calls tells them all."""
        last = self.last_movement(moving)
        end = self.followed(moving)
        if end > last and self.times[end] - self.times[max(last, start_of(moving))] < self.death_minutes:
            return end
        return last

    def is_alive(self, moving, recording):
        """Whether the mite counts as alive in recording `recording`; not after
        the end of its follow-up, where nothing is known of it."""
        return start_of(moving) <= recording <= self.alive_until(moving)

    def alive_count(self, movings, recording):
        return sum(1 for moving in movings if self.is_alive(moving, recording))

    def alive_counts(self, movings):
        """alive_count() in every recording, each mite's calls read once."""
        counts = [0] * len(self.times)
        for moving in movings:
            for recording in range(start_of(moving), self.alive_until(moving) + 1):
                counts[recording] += 1
        return counts

    def alive_numbers(self, movings, at=None):
        """How many of the mites are alive at each recording's time on the clock
        of survival(), as alive_percent() counts them: alive_counts() when every
        mite was there from the first recording, but a mite added later counts
        from its own start, as if it had been there from the first. `at`: other
        times on that clock to count them at (own_clock())."""
        survivals = [self.survival(moving) for moving in movings]
        return [sum(1 for time, dead in survivals if (time > when if dead else time >= when))
                for when in (self.times if at is None else at)]

    def own_clock(self, start):
        """The times of the recordings from `start` on, on the clock of
        survival() with `start` as its 0: where a zone whose mites were all
        added at `start` has its survival read."""
        return [self.times[recording] - self.times[start] + self.times[0] for recording in range(start, len(self.times))]

    def alive_percent(self, movings, at=None):
        """The share of the mites alive in each recording, in percent; None
        throughout without mites. With a mite gone before the last recording it
        is the Kaplan-Meier estimate, which takes that mite out of the count
        from then on instead of counting it as dead. `at`: other times to read
        it at, on the clock of survival() (own_clock())."""
        times = self.times if at is None else at
        if not movings:
            return [None] * len(times)
        if at is not None or any(self.followed(moving) < len(self.times) - 1 or start_of(moving) for moving in movings):
            return kaplan_meier([self.survival(moving) for moving in movings], times)["alive"]
        return [100 * count / len(movings) for count in self.alive_counts(movings)]

    def alive_ci(self, movings, confidence=0.95, at=None):
        """The confidence interval of alive_percent() in each recording (or at
        `at`), in percent, as {low, high}. With the mites censored only at the
        end, alive_percent() is the Kaplan-Meier estimate; the interval is
        scipy's, by Greenwood's formula on the log-log scale (see
        kaplan_meier()). None throughout without mites."""
        curve = kaplan_meier([self.survival(moving) for moving in movings], self.times if at is None else at, confidence)
        return {"low": curve["low"], "high": curve["high"]}

    def lt50(self, movings):
        """LT50, the time by which half the mites are dead: the first recording in
        which at most 50% of them are alive, the median of the Kaplan-Meier curve.
        Its 95% confidence interval runs from the first recording in which the low
        bound of alive_ci() is at most 50% to the first in which the high bound
        is. As {estimate, low, high}, in minutes from the first recording (from
        its own start for a mite added later, see survival()); each None when it
        is not reached by the last recording."""
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
        is known is that it lived at least that long. A mite added later
        counts its time from the recording it was added in, as if that were the first."""
        recording, dead = self.end_of_life(moving)
        zero = self.times[start_of(moving)] - self.times[0] if self.times else 0  # 0 but for a mite added later
        return self.times[recording] - zero, dead

    def end_of_life(self, moving):
        """(recording, dead): the recording survival() puts the mite's death or
        censoring at."""
        end = self.followed(moving)
        until = self.alive_until(moving)
        if until < end:
            return until + 1, True
        return max(end, 0), False

    def counts_dead(self, moving):
        """Whether a mite followed to the last recording counts as dead there:
        once it does, it stays so whatever comes, unless a call is changed."""
        end = self.followed(moving)
        return end == len(moving) - 1 and self.alive_until(moving) < end

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
                            same per zone, and how many are alive (alive_numbers()); a
                            zone whose mites were all added later is on its own clock:
                            "start", the recording its first ones were added in, those
                            numbers from there on only, read at own_clock(start), and
                            "group_alive", its group's survival rate read there too
            mites           {mite id: {in_study, time, dead, lost[, added, at]}}: each
                            mite's lifeline, see lifeline()
            n_left_out      the mites never seen moving, left out
            log_rank        the groups against the negative controls, see log_rank()
        """
        analysis = self.analysis
        group_of = {zone["id"]: [z["id"] for z in group_zones] for _group, group_zones in self.groups.rows() for zone in group_zones}
        zones = {}
        for zone in self.groups.zones:
            movings = self.movings([zone["id"]])
            start = self.groups.zone_start(zone["id"])
            at = analysis.own_clock(start) if start else None
            zones[zone["id"]] = {
                "alive": analysis.alive_percent(movings, at),
                "alive_ci": analysis.alive_ci(movings, at=at),
                "n_alive": analysis.alive_numbers(movings, at),
                **self.counts([zone["id"]]),
                **({"start": start, "group_alive": analysis.alive_percent(self.movings(group_of[zone["id"]]), at)} if start else {}),
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
        before the mite was gone. time and dead None for a mite left out.
        Each mite is on its own clock, as the survival curves are: `time` is
        from the start of its follow-up. A mite a live run added later also has
        `added`, the run's time of the recording it was added in, and `at`, the
        run's time of `time`."""
        if not SurvivalAnalysis.in_study(moving):
            return {"in_study": False, "time": None, "dead": None, "lost": False}
        time, dead = self.analysis.survival(moving)
        lost = not dead and SurvivalAnalysis.followed(moving) < len(moving) - 1
        start = start_of(moving)
        if not start:
            return {"in_study": True, "time": time, "dead": dead, "lost": lost}
        times = self.analysis.times
        return {"in_study": True, "time": round(time, 2), "dead": dead, "lost": lost,
                "added": times[start], "at": times[self.analysis.end_of_life(moving)[0]]}

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
