"""How far a test run has got, as the panel over the live result pages shows it:
a circle per zone, filled by the share of its mites that are dead, and the time
to the next recording.

The mites of a zone that count are those in the study (seen moving at least
once, classes/survival.py). A zone is done once each of them is dead, or no
longer known of (marked gone from a recording on); a zone with none in the study
yet does not count. The run is over once every zone that counts is done, and at
least one does: the live run then stops (pipeline.py). Every mite counting as
dead, in the study or not (one never seen moving is dead once still for the
death time from its start), is no longer followed from the next recording on.
"""

from classes.result_groups import ResultGroups
from classes.survival import SurvivalAnalysis


class ZoneProgress:
    def __init__(self, results, death_minutes):
        """`results` as pipeline describes them for the pages."""
        self.analysis = SurvivalAnalysis(results["times"], death_minutes)
        self.groups = ResultGroups(results)
        self.last = len(results["times"]) - 1

    def zones(self):
        """[{id, label, mites, dead, gone, fraction, done, counts}] for the zones
        with mites, in the order of the results: of its `mites` in the study,
        how many are `dead` and how many `gone`; `fraction` dead (0-1); `counts`:
        it has mites in the study, so it holds the run up until `done`."""
        described = []
        for zone in self.groups.zones:
            study = SurvivalAnalysis.study([self.groups.seen(mite) for mite in self.groups.mites_in([zone["id"]])])
            dead = sum(1 for moving in study if self.analysis.counts_dead(moving))
            gone = sum(1 for moving in study if SurvivalAnalysis.followed(moving) < self.last)
            described.append({
                "id": zone["id"], "label": zone.get("label"), "mites": len(study), "dead": dead, "gone": gone,
                "fraction": dead / len(study) if study else 0.0,
                "done": bool(study) and dead + gone == len(study), "counts": bool(study),
            })
        return described

    def all_done(self, zones=None):
        """Every zone that counts is done, and one does at least."""
        counting = [zone for zone in (self.zones() if zones is None else zones) if zone["counts"]]
        return bool(counting) and all(zone["done"] for zone in counting)

    def dead_ids(self):
        """The ids of the mites that count as dead in the last recording; none
        without a time to count one as dead."""
        if not self.analysis.death_minutes:
            return []
        mites = self.groups.mites_in([zone["id"] for zone in self.groups.zones])
        return [mite["id"] for mite in mites if self.analysis.counts_dead(self.groups.seen(mite))]


class RunProgress:
    def __init__(self, status, zones=()):
        """`status`: the live run's status (pipeline.live_status) without this;
        `zones`: ZoneProgress.zones() of its latest results."""
        self.status = status
        self.zones = list(zones)

    def describe(self):
        """{zones (ZoneProgress.zones()), next_seconds (until the next recording
        starts, None when none is to come)}."""
        return {"zones": self.zones, "next_seconds": self.next_seconds(self.status.get("timeline"))}

    def next_seconds(self, line):
        """Seconds until the next recording starts. A pause pushes the starts
        back as long as it holds the run, so meanwhile this stands still."""
        if not line or self.status.get("state") not in ("running", "paused"):
            return None
        ahead = [start - line["elapsed"] for start in line["starts"] if start > line["elapsed"]]
        return min(ahead) if ahead else None
