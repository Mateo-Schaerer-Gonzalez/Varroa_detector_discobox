"""Where on the plate the detector's calls go wrong, for the test report's map.

Works on the report's observations: one per (mite, recording) labelled moving or
still, with its "outcome" at the threshold in use (e.g. "moving_called_still").
Each mite is one dot: right in every recording, or coloured by its more frequent
error. The map shows one dataset at a time, with every recording or one alone.
"""

# A mite's kind on the map, by the outcome it had most.
CORRECT, MISSED_MOVING, MISSED_STILL = "correct", "missed-positive", "missed-negative"


class ErrorMap:
    def __init__(self, observations):
        self.observations = observations

    def describe(self):
        """dataset id -> {"all": selection, "recordings": {recording: selection}},
        each selection as select() describes it."""
        by_dataset = {}
        for row in self.observations:
            by_dataset.setdefault(row["dataset"], []).append(row)
        described = {}
        for dataset, rows in by_dataset.items():
            by_recording = {}
            for row in rows:
                by_recording.setdefault(row["recording"], []).append(row)
            described[dataset] = {
                "all": self.select(rows),
                "recordings": {recording: self.select(by_recording[recording]) for recording in sorted(by_recording)},
            }
        return described

    @staticmethod
    def select(rows):
        """The mites of `rows`, in their order, each {mite_id, zone_id, x, y,
        dataset_name, kind, n (its recordings), moving_missed and still_missed
        (the recordings it was called wrong in: {time, recording_name}), open (the
        recording to open it in: its first error, else its first recording)}, and
        how many mites are of each kind."""
        by_mite = {}
        for row in rows:
            by_mite.setdefault(row["mite_id"], []).append(row)
        mites = []
        counts = dict.fromkeys((CORRECT, MISSED_MOVING, MISSED_STILL), 0)
        for mite_rows in by_mite.values():
            first = mite_rows[0]
            moving_missed = [row for row in mite_rows if row["outcome"] == "moving_called_still"]
            still_missed = [row for row in mite_rows if row["outcome"] == "still_called_moving"]
            kind = (CORRECT if not moving_missed and not still_missed
                    else MISSED_MOVING if len(moving_missed) >= len(still_missed) else MISSED_STILL)
            counts[kind] += 1
            opened = (moving_missed + still_missed + [first])[0]
            mites.append({
                "mite_id": first["mite_id"],
                "zone_id": first["zone_id"],
                "x": first["x"],
                "y": first["y"],
                "dataset_name": first["dataset_name"],
                "kind": kind,
                "n": len(mite_rows),
                "moving_missed": [ErrorMap._when(row) for row in moving_missed],
                "still_missed": [ErrorMap._when(row) for row in still_missed],
                "open": {"dataset": opened["dataset"], "zone_id": opened["zone_id"], "mite_id": opened["mite_id"],
                         "recording": opened["recording"]},
            })
        return {"mites": mites, "counts": counts}

    @staticmethod
    def _when(row):
        return {"time": row["time"], "recording_name": row["recording_name"]}
