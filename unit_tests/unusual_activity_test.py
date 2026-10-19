import cv2
import numpy as np
import pandas as pd

from classes.mite_look import MiteLook
from classes.unusual_activity import ABSENT_RUN, TURN_LIMIT, UnusualActivity

TIMES = [10.0 * i for i in range(12)]
# Three mites in a row, 60 px apart, and one further off in another zone.
PLACES = {"1.1": (100, 100, 1), "1.2": (160, 100, 1), "1.3": (220, 100, 1), "2.1": (400, 300, 2)}


def seen(contrast=40.0, **values):
    return {"stray": 0.03, "shake": 0.05, "dx": 0.0, "dy": 0.0, "angle": 45.0, "elongation": 1.5, "contrast": contrast, **values}


def mites(change=None):
    """Every mite there and still in every recording; `change(id, recording)`
    returns what to put in place of a mite's activity there."""
    out = []
    for mite_id, (x, y, zone) in PLACES.items():
        activity = [(change(mite_id, r) if change else None) or seen() for r in range(len(TIMES))]
        out.append({"id": mite_id, "x": x, "y": y, "zone": zone, "activity": activity})
    return out


def blobs(extra=None, gone=()):
    """Per recording, a blob on every mite in its place, those in `gone`
    (id -> first recording without it) left out, and `extra(recording)`."""
    out = []
    for r in range(len(TIMES)):
        here = [[x + 0.4, y - 0.3] for mite_id, (x, y, _zone) in PLACES.items() if not (mite_id in gone and r >= gone[mite_id])]
        out.append(here + list(extra(r) if extra else []))
    return out


def walker(r):
    """The mite 1.1 walking off from recording 4: 40 px right per recording, 12 px below the row."""
    return [[100 + 40 * (r - 3), 112]] if r >= 4 else []


def fly_off_activity(mite_id, r):
    return seen(contrast=2.0) if mite_id == "1.1" and r >= 4 else None


class TestFlyOffs:
    def test_a_mite_that_walks_off_is_a_fly_off_with_its_track(self):
        activity = UnusualActivity(mites(fly_off_activity), blobs(walker, {"1.1": 4}), TIMES, reach=26)
        assert activity.fly_off_ids == {"1.1"}
        described = activity.describe()["fly_offs"][0]
        assert described["from"] == 4
        assert [point[1] for point in described["track"][1:4]] == [140, 180, 220]

    def test_the_mites_it_walks_by_have_those_recordings_set_aside(self):
        activity = UnusualActivity(mites(fly_off_activity), blobs(walker, {"1.1": 4}), TIMES, reach=26)
        set_aside = {(row["mite"], row["recording"]) for row in activity.describe()["disturbed"]}
        # within 26 px: of 1.2 at recordings 4 and 5 (23 px off), of 1.3 at 6 (12 px off)
        assert set_aside == {("1.2", 4), ("1.2", 5), ("1.3", 6)}
        assert activity.describe()["fly_offs"][0]["near"] == ["1.2", "1.3"]

    def test_a_mite_the_detector_misses_but_still_there_is_no_fly_off(self):
        # no blob on 1.2 for 5 recordings, but its image has not faded
        activity = UnusualActivity(mites(), blobs(gone={"1.2": 3}), TIMES)
        assert activity.fly_off_ids == set()

    def test_a_short_absence_is_no_fly_off(self):
        short = [b if not 3 <= r < 3 + ABSENT_RUN - 1 else b[1:] for r, b in enumerate(blobs())]
        faded = mites(lambda mite_id, r: seen(contrast=1.0) if mite_id == "1.1" and 3 <= r < 3 + ABSENT_RUN - 1 else None)
        assert UnusualActivity(faded, short, TIMES).fly_off_ids == set()

    def test_a_fly_off_drifts_until_it_flew_off_then_walks_out(self):
        drifting = lambda mite_id, r: fly_off_activity(mite_id, r) or seen(dx=0.1 * r)
        activity = UnusualActivity(mites(drifting), blobs(walker, {"1.1": 4}), TIMES, reach=26)
        movers = activity.describe()["movers"]
        flown = [m for m in movers if m.get("flew_off") is not None]
        assert [m["id"] for m in flown] == ["1.1"] and movers[-1] is flown[0] and len(movers) == len(PLACES)
        assert flown[0]["flew_off"] == 4 and flown[0]["dx"][:4] == [0.0, 0.1, 0.2, 0.3] and flown[0]["dx"][4:] == [None] * 8
        assert flown[0]["walk"] == [round(40 / np.hypot(40, 12), 4), round(12 / np.hypot(40, 12), 4)]

    def test_without_blobs_nothing_flies_off(self):
        activity = UnusualActivity(mites(fly_off_activity), [], TIMES)
        assert activity.fly_off_ids == set() and not activity.describe()["measured"]


class TestDisturbed:
    def test_a_resting_blob_beside_a_mite_disturbs_nothing(self):
        # something lies 15 px from 1.2 in every recording: it does not move
        activity = UnusualActivity(mites(), blobs(lambda r: [[175, 100]]), TIMES, reach=22)
        assert activity.describe()["disturbed"] == []

    def test_a_patch_pulled_along_without_a_walker_counts(self):
        pulled = mites(lambda mite_id, r: seen(stray=1.2) if (mite_id, r) == ("2.1", 7) else None)
        assert UnusualActivity(pulled, blobs(), TIMES).describe()["disturbed"] == []

    def test_a_fly_off_lying_against_a_mite_disturbs_it_where_the_track_passes(self):
        # at recording 6 the walker lies against 1.3: one blob with it, not seen on its own
        merged = lambda r: [] if r == 6 else walker(r)
        activity = UnusualActivity(mites(fly_off_activity), blobs(merged, {"1.1": 4}), TIMES, reach=26)
        assert ("1.3", 6) in {(row["mite"], row["recording"]) for row in activity.describe()["disturbed"]}

    def test_censor_sets_the_recordings_aside_unless_set_by_hand(self):
        # something walks by 2.1 at recordings 2 and 7: there, and 20 px off
        passing = lambda r: [[420, 300]] if r in (2, 7) else []
        activity = UnusualActivity(mites(), blobs(passing), TIMES, reach=22)
        rows = [{"mite_ID": mite_id, "time": t, "moving": True, "corrected": mite_id == "2.1" and t == TIMES[7]}
                for mite_id in PLACES for t in TIMES]
        data, changes = activity.censor(pd.DataFrame(rows), {"censored": {"1.1": [0]}})
        aside = data[data["disturbed"]]
        assert list(zip(aside["mite_ID"], aside["time"])) == [("2.1", TIMES[2])]
        assert not aside["moving"].any() and aside["censored"].all()
        assert changes["censored"] == {"1.1": [0], "2.1": [2]} and changes["disturbed"] == {"2.1": [2]}


class TestRotators:
    def test_a_mite_that_turns_is_a_rotator_and_stays_in(self):
        turning = mites(lambda mite_id, r: seen(angle=45.0 + 70 * min(1, max(0, r - 3) / 3)) if mite_id == "1.3" else None)
        activity = UnusualActivity(turning, blobs(), TIMES)
        rotators = activity.describe()["rotators"]
        assert [r["id"] for r in rotators] == ["1.3"] and rotators[0]["turn"] > TURN_LIMIT
        assert activity.fly_off_ids == set()
        assert rotators[0]["angle_first"] == 45.0 and rotators[0]["angle_last"] == 115.0 and rotators[0]["turned"] == 70.0
        assert (rotators[0]["first_seen"], rotators[0]["last_seen"]) == (0, len(TIMES) - 1)

    def test_the_last_axis_is_taken_round_half_a_circle(self):
        # from 170 degrees on to 10 degrees past 180: 20 degrees on, not 160 back
        turning = mites(lambda mite_id, r: seen(angle=(170.0 + 40 * min(1, max(0, r - 3) / 3)) % 180) if mite_id == "1.3" else None)
        rotators = UnusualActivity(turning, blobs(), TIMES).describe()["rotators"]
        assert rotators[0]["angle_first"] == 170.0 and rotators[0]["angle_last"] == 30.0 and rotators[0]["turned"] == 40.0

    def test_a_mite_turning_anticlockwise_turns_below_zero(self):
        turning = mites(lambda mite_id, r: seen(angle=100.0 - 50 * min(1, max(0, r - 3) / 3)) if mite_id == "1.3" else None)
        rotators = UnusualActivity(turning, blobs(), TIMES).describe()["rotators"]
        assert rotators[0]["turned"] == -50.0

    def test_the_turn_wraps_round_half_a_circle(self):
        # 175 degrees and 5 degrees are the same axis, 10 degrees apart
        wobbling = mites(lambda mite_id, r: seen(angle=175.0 if r % 2 else 5.0) if mite_id == "1.3" else None)
        assert UnusualActivity(wobbling, blobs(), TIMES).describe()["rotators"] == []

    def test_a_round_mite_has_no_orientation(self):
        round_turning = mites(lambda mite_id, r: seen(angle=10.0 * r, elongation=1.02) if mite_id == "1.3" else None)
        assert UnusualActivity(round_turning, blobs(), TIMES).describe()["rotators"] == []


class TestPlateShake:
    def test_the_shake_is_the_median_of_the_mites_in_place(self):
        shaking = mites(lambda mite_id, r: seen(shake=0.1 * r + (5.0 if mite_id == "2.1" else 0.0)))
        shake = UnusualActivity(shaking, blobs(), TIMES).describe()["shake"]
        assert shake == [round(0.1 * r, 4) for r in range(len(TIMES))]

    def test_the_movers_are_ranked_by_their_drift_from_their_zone(self):
        drifting = mites(lambda mite_id, r: seen(dx=0.2 * r) if mite_id == "1.2" else seen(dx=0.05 * r))
        movers = UnusualActivity(drifting, blobs(), TIMES).describe()["movers"]
        assert movers[0]["id"] == "1.2" and len(movers) == len(PLACES)
        assert movers[0]["dx"][-1] == round(0.2 * (len(TIMES) - 1), 3)


class TestMiteLook:
    def frames(self, angle, dx=0.0):
        image = np.full((40, 40), 200, np.float32)
        cv2.ellipse(image, (20, 20), (8, 4), angle, 0, 360, 60, -1)
        image = cv2.warpAffine(cv2.GaussianBlur(image, (0, 0), 1.0), np.float32([[1, 0, dx], [0, 1, 0]]), (40, 40),
                               borderMode=cv2.BORDER_REFLECT101)
        return np.stack([image] * 3)[..., None].repeat(3, axis=-1)

    def test_it_finds_where_the_mite_sits_and_which_way_it_points(self):
        class Mite:
            pass

        mite, box, still = Mite(), (12, 12, 28, 28), np.zeros((3, 2))
        first = MiteLook.observe(self.frames(30), box, still, mite)
        later = MiteLook.observe(self.frames(30, dx=0.6), box, still, mite)
        turned = MiteLook.observe(self.frames(110), box, still, mite)
        assert first["dx"] == 0 and abs(later["dx"] - 0.6) < 0.08
        assert abs(first["angle"] - 30) < 5 and abs(turned["angle"] - 110) < 5 and first["elongation"] > 1.5
        assert first["contrast"] > 100
