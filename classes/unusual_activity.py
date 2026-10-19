"""What the mites do besides moving their legs: a mite that comes unglued and
walks off (a fly-off), one that turns where it is (a rotator), the recordings of
other mites a fly-off walked through, and how the plate shakes and drifts.

Scoring a recording records, per mite (Analyzer, classes/mite_look.py):

    stray   the most its own shift strayed from the plate's within the recording (px)
    shake   the most its own shift moved from the recording's first frame (px)
    dx, dy  where its image sits against its image in the first recording (px)
    angle, elongation   the long axis of its body (degrees) and how much longer
            it is than the short one
    contrast  how much darker the middle of its image is than its edge (grey levels)

and, per recording, every dark blob the detector finds on the first and the
last frame (MotionAnalysis). From those, UnusualActivity finds:

- a **fly-off**: a mite whose place is empty in ABSENT_RUN recordings in a
  row: no blob there, and its image has faded to less than FADED of its
  contrast in the first recording (the detector alone misses a mite now and
  then). It is left out of the analysis from the start, and followed from
  blob to blob as it walks (its track).
- a **disturbed** recording of another mite: something walked by it. A blob
  that is not a mite in its place and was not there the recording before comes
  within reach of its scored patch; or a fly-off's track passes there in a
  recording in which the fly-off was not seen on its own (it lay against the
  mite, one blob with it), where it was between the recordings it was seen in.
  Its call there is set aside: censored, it counts neither as moving nor as
  still.
- a **rotator**: a mite whose body turned by more than TURN_LIMIT from its
  first recordings, in AWAY_COUNT recordings. It stays in the analysis.
- the plate's **shake** per recording (the median of the mites' shake) and
  the mites that drifted most from their zone across recordings, with the
  fly-offs' paths until they flew off and the way they walked.

Each mite's patch is scored moved back by its own shift (PlateStabilizer, the
shift of its centre); its stray is how far that strayed from the plate's, the
median over the mites.
"""

import numpy as np
import pandas as pd


PRESENT_RADIUS = 6.0  # px: a blob this close to a mite's place is the mite
ABSENT_RUN = 3        # recordings in a row without the mite in its place: it flew off
FADED = 0.5           # of its first contrast: below this, the mite's place is empty
NEW_RADIUS = 3.0      # px: a blob this close to one of the recording before has not moved
MAX_STEP = 200.0      # px a fly-off may walk from one recording to the next and still be followed
TRACK_GAPS = 3        # recordings without it before its track ends
TURN_LIMIT = 30.0     # degrees a mite's body may turn before it counts as a rotator
AWAY_COUNT = 3        # recordings past TURN_LIMIT
ROUND = 1.1           # a body less elongated than this has no orientation
TOP_MOVERS = 10


class UnusualActivity:
    """`mites`: [{id, x, y, zone, activity: [per recording, as above, or None]}]
    for every detection; `blobs`: per recording, [[x, y], ...]; `times`: the
    recordings' times (minutes); `left_out`: the ids already left out (marked
    not a mite), which are still followed if they walk; `reach`: px from a
    mite's centre to the edge of its scored patch."""

    def __init__(self, mites, blobs, times, left_out=(), reach=24.0):
        self.mites = list(mites)
        self.times = [float(t) for t in times]
        self.n = len(self.times)
        self.blobs = [np.asarray(b, dtype=float).reshape(-1, 2) for b in blobs] if len(blobs) == self.n else []
        self.left_out = {str(i) for i in left_out}
        self.reach = float(reach)
        self.centres = np.array([[m["x"], m["y"]] for m in self.mites], dtype=float).reshape(-1, 2)
        self.ids = [str(m["id"]) for m in self.mites]
        self.values = {key: self._series(key) for key in ("stray", "shake", "dx", "dy", "angle", "elongation", "contrast")}
        self.present = self._present()
        self.flown = self._fly_offs()            # mite index -> first recording without it
        self.tracks = self._tracks()             # mite index -> [(recording, x, y)]
        self.disturbed = self._disturbed()       # (mites, recordings) -> "passing" or None
        self.turns = self._turns()               # (mites, recordings) degrees, nan where unknown
        self.rotating = self._rotators()         # mite index -> first recording past TURN_LIMIT

    @classmethod
    def of(cls, analysis, left_out=(), reach=24.0):
        """From a MotionAnalysis: every mite it detected, as recorded on them."""
        zone_of = {}
        for zone in analysis.zone_manager.zones:
            for mite in analysis.zone_mites(zone):
                zone_of[id(mite)] = zone.id
        mites = [{"id": mite.text, "x": (mite.x1 + mite.x2) / 2, "y": (mite.y1 + mite.y2) / 2,
                  "zone": zone_of.get(id(mite)), "activity": list(getattr(mite, "activity", []))}
                 for mite in analysis.mites]
        times = np.array(analysis.recording_times, dtype=float) / 60
        return cls(mites, getattr(analysis, "blobs", []), times, [m.text for m in left_out], reach)

    # --- the measurements as arrays

    def _series(self, key):
        out = np.full((len(self.mites), self.n), np.nan)
        for index, mite in enumerate(self.mites):
            for recording, seen in enumerate(mite["activity"][:self.n]):
                if seen and seen.get(key) is not None:
                    out[index, recording] = seen[key]
        return out

    def _present(self):
        """(mites, recordings): a blob in the mite's place, or its image not
        faded; all True without blobs."""
        present = np.ones((len(self.mites), self.n), dtype=bool)
        if not self.blobs:
            return present
        contrast = self.values["contrast"]
        first = contrast[:, :1] if self.n else contrast
        kept_look = ~(contrast < FADED * first)  # nan (not measured) counts as there
        for recording, blobs in enumerate(self.blobs):
            if not len(blobs):
                present[:, recording] = False
                continue
            distance = np.hypot(*(self.centres[:, None, :] - blobs[None, :, :]).transpose(2, 0, 1))
            present[:, recording] = distance.min(axis=1) <= PRESENT_RADIUS
        return present | kept_look

    # --- fly-offs

    def _fly_offs(self):
        flown = {}
        for index, there in enumerate(self.present):
            run = 0
            for recording, here in enumerate(there):
                run = 0 if here else run + 1
                if run == ABSENT_RUN:
                    flown[index] = recording - ABSENT_RUN + 1
                    break
        return flown

    def _stays(self, recording):
        """Indices of the mites in their place in `recording`, the fly-offs gone."""
        return [m for m in range(len(self.mites)) if not (m in self.flown and recording >= self.flown[m])]

    def _loose(self, recording):
        """The blobs of `recording` that are no mite in its place."""
        blobs = self.blobs[recording]
        stays = self._stays(recording)
        if not len(blobs) or not stays:
            return blobs
        distance = np.hypot(*(blobs[:, None, :] - self.centres[stays][None, :, :]).transpose(2, 0, 1))
        return blobs[distance.min(axis=1) > PRESENT_RADIUS]

    def _tracks(self):
        """Each fly-off from its place, recording by recording, to the loose blob
        nearest where it was last, until it is not seen for TRACK_GAPS recordings.
        Fly-offs leaving together take the nearest blobs first."""
        tracks = {m: [(max(0, start - 1), *self.centres[m])] for m, start in self.flown.items()}
        gaps = {m: 0 for m in self.flown}
        for recording in range(self.n):
            walking = [m for m, start in self.flown.items() if start <= recording and gaps[m] < TRACK_GAPS]
            if not walking:
                continue
            loose = self._loose(recording)
            pairs = sorted((float(np.hypot(*(blob - tracks[m][-1][1:]))), m, b)
                           for m in walking for b, blob in enumerate(loose))
            taken, moved = set(), set()
            for distance, m, b in pairs:
                if distance > MAX_STEP or m in moved or b in taken:
                    continue
                tracks[m].append((recording, float(loose[b][0]), float(loose[b][1])))
                taken.add(b)
                moved.add(m)
            for m in walking:
                gaps[m] = 0 if m in moved else gaps[m] + 1
        return tracks

    # --- recordings disturbed

    def _walking(self, recording):
        """The loose blobs of `recording` that were not in that place the recording before."""
        loose = self._loose(recording)
        if recording == 0 or not len(loose):
            return loose[:0] if recording == 0 else loose
        before = self.blobs[recording - 1]
        if not len(before):
            return loose
        distance = np.hypot(*(loose[:, None, :] - before[None, :, :]).transpose(2, 0, 1))
        return loose[distance.min(axis=1) > NEW_RADIUS]

    def _places(self, m):
        """Where the fly-off `m` was in every recording of its track, those it
        was not seen in put where it was between the ones before and after:
        [(recording, x, y, seen)]."""
        seen = np.array(self.tracks[m], dtype=float)
        between = np.arange(int(seen[0, 0]), int(seen[-1, 0]) + 1)
        found = set(seen[:, 0].astype(int))
        return list(zip(between, np.interp(between, seen[:, 0], seen[:, 1]), np.interp(between, seen[:, 0], seen[:, 2]),
                        (r in found for r in between)))

    def _disturbed(self):
        disturbed = np.full((len(self.mites), self.n), None, dtype=object)
        for recording in range(self.n if self.blobs else 0):
            walking = self._walking(recording)
            if not len(walking):
                continue
            distance = np.hypot(*(self.centres[:, None, :] - walking[None, :, :]).transpose(2, 0, 1)).min(axis=1)
            disturbed[distance <= self.reach, recording] = "passing"
        for m, start in self.flown.items():
            for recording, x, y, seen in self._places(m):
                if recording >= start and not seen:
                    distance = np.hypot(self.centres[:, 0] - x, self.centres[:, 1] - y)
                    disturbed[distance <= self.reach, recording] = "passing"
        for m, start in self.flown.items():
            disturbed[m, :] = None
        for m, mite_id in enumerate(self.ids):
            if mite_id in self.left_out:
                disturbed[m, :] = None
        return disturbed

    # --- rotators

    def _turns(self):
        angle, long = self.values["angle"], self.values["elongation"]
        turns = np.full(angle.shape, np.nan)
        for m in range(len(self.mites)):
            seen = np.flatnonzero(~np.isnan(angle[m]))
            if len(seen) < 3 or np.nanmedian(long[m]) < ROUND:
                continue
            start = np.median(angle[m, seen[:3]])
            turn = np.abs((angle[m] - start + 90) % 180 - 90)
            turns[m] = pd.Series(turn).rolling(5, center=True, min_periods=1).median().to_numpy()
        return turns

    def _rotators(self):
        rotating = {}
        for m in range(len(self.mites)):
            if m in self.flown or self.ids[m] in self.left_out:
                continue
            past = np.nan_to_num(self.turns[m]) > TURN_LIMIT
            if past.sum() >= AWAY_COUNT:
                rotating[m] = int(np.argmax(past))
        return rotating

    # --- for the analysis

    @property
    def fly_off_ids(self):
        return {self.ids[m] for m in self.flown}

    def censor(self, mite_data, changes):
        """The mite score table with the disturbed recordings set aside: censored
        (not moving, counting neither way) and marked `disturbed`, unless the
        call there was set by hand. `changes` (CallCorrections.apply()'s) get
        them under "censored" and "disturbed"."""
        if mite_data.empty or not self.n:
            return mite_data, changes
        times = sorted(mite_data["time"].unique())
        recording = mite_data["time"].map({time: index for index, time in enumerate(times)}).to_numpy()
        index_of = {mite_id: m for m, mite_id in enumerate(self.ids)}
        ids = mite_data["mite_ID"].astype(str).to_numpy()
        hand = mite_data["corrected"].to_numpy(dtype=bool) if "corrected" in mite_data else np.zeros(len(mite_data), bool)
        rows = np.array([index_of.get(i, -1) >= 0 and recording[k] < self.n
                         and self.disturbed[index_of[i], recording[k]] is not None and not hand[k]
                         for k, i in enumerate(ids)], dtype=bool)
        if not rows.any():
            return mite_data, changes
        data = mite_data.copy()
        data["moving"] = data["moving"].to_numpy(dtype=bool) & ~rows
        data["censored"] = (data["censored"].to_numpy(dtype=bool) if "censored" in data else np.zeros(len(data), bool)) | rows
        data["disturbed"] = rows
        changes = dict(changes)
        censored = {key: set(value) for key, value in changes.get("censored", {}).items()}
        disturbed = {}
        for k in np.flatnonzero(rows):
            censored.setdefault(ids[k], set()).add(int(recording[k]))
            disturbed.setdefault(ids[k], set()).add(int(recording[k]))
        changes["censored"] = {key: sorted(value) for key, value in censored.items()}
        changes["disturbed"] = {key: sorted(value) for key, value in disturbed.items()}
        return data, changes

    # --- for the pages

    def _shake(self):
        """Per recording, the median over the mites in their place of how far
        each one's own shift moved from the first frame; None where not measured."""
        out = []
        for recording in range(self.n):
            values = self.values["shake"][self._stays(recording), recording]
            values = values[~np.isnan(values)]
            out.append(round(float(np.median(values)), 4) if len(values) else None)
        return out

    def _movers(self, kept):
        """The TOP_MOVERS mites that drifted furthest from their zone's median
        across recordings (95th percentile over the recordings, so one bad
        registration does not rank a mite), with their displacement and their zone's,
        then every fly-off: its displacement until it flew off (after that its
        image is gone and it says nothing), `flew_off` the recording it left its
        place in and `walk` the way it walked ((dx, dy), one long; None where
        its track has it nowhere else)."""
        dx, dy = self.values["dx"], self.values["dy"]
        zones = {}
        for m in kept:
            zones.setdefault(self.mites[m]["zone"], []).append(m)
        zone_drift = {z: (np.nanmedian(dx[members], axis=0), np.nanmedian(dy[members], axis=0))
                      for z, members in zones.items()}
        ranked = []
        for m in kept:
            zx, zy = zone_drift[self.mites[m]["zone"]]
            away = np.hypot(dx[m] - zx, dy[m] - zy)
            if np.isnan(away).all():
                continue
            ranked.append((float(np.nanpercentile(away, 95)), m))
        rounded = lambda values: [None if np.isnan(v) else round(float(v), 3) for v in values]
        nowhere = [None] * self.n

        def row(m, away, until=None):
            zone = zone_drift.get(self.mites[m]["zone"])
            cut = lambda values: rounded(values[:until]) + [None] * (self.n - until) if until is not None else rounded(values)
            return {"id": self.ids[m], "zone": self.mites[m]["zone"], "x": round(float(self.centres[m][0]), 1),
                    "y": round(float(self.centres[m][1]), 1), "away": away,
                    "dx": cut(dx[m]), "dy": cut(dy[m]),
                    "zone_dx": rounded(zone[0]) if zone else nowhere,
                    "zone_dy": rounded(zone[1]) if zone else nowhere}

        movers = [row(m, round(away, 3)) for away, m in sorted(ranked, reverse=True)[:TOP_MOVERS]]
        for m, start in sorted(self.flown.items(), key=lambda item: item[1]):
            movers.append({**row(m, None, start), "flew_off": int(start), "walk": self._walk(m)})
        return movers

    def _walk(self, m):
        """The way the fly-off `m` walked off: from its place to the first point
        of its track out of it, as (dx, dy) one long; None if it was nowhere else."""
        for _recording, x, y in self.tracks[m][1:]:
            step = np.array([x, y]) - self.centres[m]
            length = float(np.hypot(*step))
            if length > PRESENT_RADIUS:
                return [round(float(v) / length, 4) for v in step]
        return None

    def _rotation(self, m):
        """The long axis of rotator `m`'s body in its first and its last
        AWAY_COUNT recordings it was measured in (degrees, 0 to 180, median of
        each), the turn from the one to the other the short way round (degrees,
        clockwise on the picture positive), the recordings it was first and
        last measured in, and `turns`: per recording, the turn from its first
        recordings the same way, smoothed as _turns() is (None where unknown)."""
        angle = self.values["angle"][m]
        seen = np.flatnonzero(~np.isnan(angle))
        start = float(np.median(angle[seen[:AWAY_COUNT]]))
        signed = (angle - start + 90) % 180 - 90  # signed, round half a circle
        turned = float(np.median(signed[seen[-AWAY_COUNT:]]))
        smooth = pd.Series(signed).rolling(5, center=True, min_periods=1).median().to_numpy()
        return {"angle_first": round(start % 180, 1), "angle_last": round((start + turned) % 180, 1), "turned": round(turned, 1),
                "first_seen": int(seen[0]), "last_seen": int(seen[-1]),
                "turns": [None if np.isnan(v) else round(float(v), 1) for v in smooth]}

    def describe(self):
        """The unusual activity for the result pages."""
        kept = [m for m in range(len(self.mites)) if m not in self.flown and self.ids[m] not in self.left_out]
        steady = [m for m in kept if m not in self.rotating]  # a rotator's drift says nothing
        fly_offs = []
        for m, start in sorted(self.flown.items(), key=lambda item: item[1]):
            track = self.tracks[m]
            # the mites whose recording it disturbed: within reach of where it was then, where it
            # was between two recordings it was seen in if it was not seen (merged with a mite)
            seen = np.array(track, dtype=float)
            near = sorted({self.ids[k] for r, x, y, _ in self._places(m) if r >= start for k in kept
                           if self.disturbed[k, r] is not None
                           and np.hypot(x - self.centres[k][0], y - self.centres[k][1]) <= self.reach + PRESENT_RADIUS},
                          key=lambda mite_id: [int(p) if p.isdigit() else p for p in mite_id.split(".")])
            # the last recording in which it was somewhere else than in the one before
            steps = np.hypot(*np.diff(seen[:, 1:], axis=0).T)
            walked = int(seen[1:][steps > NEW_RADIUS][-1, 0]) if (steps > NEW_RADIUS).any() else int(start)
            fly_offs.append({"id": self.ids[m], "zone": self.mites[m]["zone"], "x": round(float(self.centres[m][0]), 1),
                             "y": round(float(self.centres[m][1]), 1), "from": int(start), "to": int(track[-1][0]),
                             "walked_to": walked,
                             "marked": self.ids[m] in self.left_out,
                             "track": [[int(r), round(x, 1), round(y, 1)] for r, x, y in track], "near": near})
        rotators = [{"id": self.ids[m], "zone": self.mites[m]["zone"], "x": round(float(self.centres[m][0]), 1),
                     "y": round(float(self.centres[m][1]), 1), "from": int(start),
                     "turn": round(float(np.nanmax(self.turns[m])), 1),
                     **self._rotation(m)}
                    for m, start in sorted(self.rotating.items(), key=lambda item: item[1])]
        disturbed = [{"mite": self.ids[m], "recording": int(r), "reason": self.disturbed[m, r],
                      "stray": None if np.isnan(self.values["stray"][m, r]) else round(float(self.values["stray"][m, r]), 3)}
                     for m in kept for r in range(self.n) if self.disturbed[m, r] is not None]
        return {"fly_offs": fly_offs, "rotators": rotators, "disturbed": disturbed, "shake": self._shake(),
                "movers": self._movers(steady), "turn_limit": TURN_LIMIT,
                "measured": bool(self.blobs)}
