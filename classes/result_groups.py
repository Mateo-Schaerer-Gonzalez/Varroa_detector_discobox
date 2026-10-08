"""The zones of a run's results by group, as the result pages list them.

Works on the results as pipeline describes them for the pages (plain dicts: each
zone with its `id`, `label` and `n_mites`, each mite with its `zone_id`). A zone's
group is its label, or "unlabeled". Only zones with a detected mite count: the
others have nothing to show.
"""

from classes.zones import UNLABELED


def group_order(group):
    """Sort key: named groups alphabetically, whatever their case, "unlabeled" last."""
    return (group == UNLABELED, group.casefold(), group)


class ResultGroups:
    def __init__(self, results):
        self.zones = [zone for zone in results["zones"] if zone["n_mites"]]
        self._censored = results.get("censored", {})
        self._seen = {}  # mite id -> seen(), made once: the survival numbers ask for it many times
        self._mites = {}
        for mite in results["mites"]:
            self._mites.setdefault(mite["zone_id"], []).append(mite)

    @staticmethod
    def group_of(zone):
        return zone["label"] or UNLABELED

    def mites_in(self, zone_ids):
        """The mites of the zones `zone_ids`, zone by zone."""
        return [mite for zone_id in zone_ids for mite in self._mites.get(zone_id, [])]

    def censored(self, mite):
        """Per recording, whether the user marked the mite gone in it, e.g. fallen
        off (classes/call_corrections.py)."""
        gone = set(self._censored.get(mite["id"], []))
        return [recording in gone for recording in range(len(mite["moving"]))]

    def seen(self, mite):
        """The mite's movement per recording, None in those in which it was gone.
        The same list every time: it is not to be changed."""
        seen = self._seen.get(mite["id"])
        if seen is None:
            seen = [None if gone else moving for moving, gone in zip(mite["moving"], self.censored(mite))]
            self._seen[mite["id"]] = seen
        return seen

    def rows(self, zones=None):
        """(group, [zone, ...]) for the zones with mites (or `zones`), in group
        order, each group's zones in their order in the results."""
        by_group = {}
        for zone in self.zones if zones is None else zones:
            by_group.setdefault(self.group_of(zone), []).append(zone)
        return sorted(by_group.items(), key=lambda item: group_order(item[0]))
