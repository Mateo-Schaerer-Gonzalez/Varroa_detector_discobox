"""How far a test run has got, as the bar over the live result pages shows it.

The whole run is one bar, filled as far as the run has got, with a tick for each
recording: analysed, captured and being analysed, being recorded, or still to
come. A run going on until every mite is dead has no set length: its bar shows
the share of the mites alive instead, and it has no ticks.
"""

MAX_MARKS = 150  # more ticks than this cannot be told apart


class RunProgress:
    def __init__(self, status):
        """`status`: the live run's status (pipeline.live_status) without this."""
        self.status = status

    def describe(self):
        """{fraction (0-1), alive_bar (the bar shows the mites alive), marks
        ([{at (0-1 along the bar), state}]), left_seconds}."""
        s = self.status
        line = s.get("timeline")
        alive_bar = bool(s.get("open_ended"))
        alive = s.get("alive")
        if alive_bar:
            fraction = alive["alive"] / alive["mites"] if alive and alive["mites"] else 1
        else:
            fraction = min(1, line["elapsed"] / line["length"]) if line and line["length"] > 0 else 0
        return {
            "fraction": fraction,
            "alive_bar": alive_bar,
            "marks": [] if alive_bar else self.marks(line),
            "left_seconds": line["length"] - line["elapsed"] if line else 0,
        }

    def marks(self, line):
        # none before the run has a length, or when there are too many to tell apart
        if not line or line["length"] <= 0 or len(line["starts"]) > MAX_MARKS:
            return []
        return [{"at": start / line["length"], "state": self.mark_state(i)} for i, start in enumerate(line["starts"])]

    def mark_state(self, index):
        s = self.status
        if index < s["analysed"]:
            return "analysed"
        if index < s["completed"]:
            return "captured"
        if index == s["completed"] and s.get("recording_name"):
            return "capturing"
        return "planned"
