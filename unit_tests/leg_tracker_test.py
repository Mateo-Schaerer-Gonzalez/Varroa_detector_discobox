import numpy as np
import pytest

from classes.leg_tracker import LegTracker, synthetic_mite


def _frames(legs_per_frame, **kwargs):
    """Frames of a mite whose legs are given per frame, without noise, and where each leg ends."""
    made = [synthetic_mite(legs, noise=0, **kwargs) for legs in legs_per_frame]
    return np.stack([frame for frame, _tips in made]), [tips for _frame, tips in made]


class TestDetect:
    def test_a_mite_without_legs_has_none(self):
        frame, _tips = synthetic_mite([], noise=0)
        assert len(LegTracker().detect(frame)) == 0

    def test_an_empty_patch_has_none(self):
        found = LegTracker().detect(np.full((46, 46), 110, dtype=np.float32))
        assert len(found) == 0

    def test_a_black_patch_has_none(self):
        assert len(LegTracker().detect(np.zeros((46, 46), dtype=np.float32))) == 0

    def test_it_finds_each_leg(self):
        frame, tips = synthetic_mite([(150, 3), (200, 3), (250, 3)], noise=0)
        found = LegTracker().detect(frame)
        assert len(found) == 3
        # each is on its leg: between the body and the leg's end
        for tip in tips:
            assert np.linalg.norm(found.xy - tip, axis=1).min() < 3

    def test_the_body_is_where_the_mite_is(self):
        frame, _tips = synthetic_mite([(180, 3)], noise=0, shift=(2.0, -1.5), turn=20)
        found = LegTracker().detect(frame)
        assert found.centre == pytest.approx([46 / 2 + 2.0, 46 / 2 - 1.5], abs=0.3)
        # the oval is drawn upright and turned by 20 degrees: its long axis is at 110
        assert np.degrees(found.axis) == pytest.approx(110, abs=5)

    def test_a_longer_leg_is_longer(self):
        short = LegTracker().detect(synthetic_mite([(180, 2)], noise=0)[0])
        long = LegTracker().detect(synthetic_mite([(180, 4)], noise=0)[0])
        assert long.length[0] > short.length[0] + 1


class TestTrack:
    def test_a_leg_that_stays_is_one_track_that_does_not_move(self):
        frames, _tips = _frames([[(180, 3)]] * 10)
        tracks = LegTracker().track(frames)
        assert len(tracks) == 1
        assert tracks.seen.all()
        assert LegTracker.movement(tracks, 10)[0] == pytest.approx(0, abs=1e-6)

    def test_a_leg_that_swings_moves_by_about_as_much(self):
        angles = [170, 175, 180, 185, 190, 185, 180, 175, 170, 175]
        frames, tips = _frames([[(angle, 3)] for angle in angles])
        tracks = LegTracker().track(frames)
        assert len(tracks) == 1
        tips = np.array(tips)[:, 0]
        true = 2 * np.sqrt(((tips - tips.mean(axis=0)) ** 2).sum(axis=1).mean())
        # the leg's place is nearer the body than its end, so it moves less than the end: more than a third of it
        assert 0.35 * true < LegTracker.movement(tracks, 10)[0] <= true

    def test_a_leg_that_swings_further_moves_more(self):
        near, _tips = _frames([[(180 + turn, 3)] for turn in (-2, 2) * 5])
        far, _tips = _frames([[(180 + turn, 3)] for turn in (-4, 4) * 5])
        assert LegTracker.movement(LegTracker().track(far), 10)[0] > 1.5 * LegTracker.movement(LegTracker().track(near), 10)[0]

    def test_a_mite_moved_as_a_whole_keeps_its_legs_in_place(self):
        shifts = [(0, 0), (0.4, 0.1), (-0.3, 0.2), (0.2, -0.4), (0, 0.3), (-0.4, -0.2)]
        made = [synthetic_mite([(180, 3), (240, 3)], noise=0, shift=shift) for shift in shifts]
        tracks = LegTracker().track(np.stack([frame for frame, _tips in made]))
        assert len(tracks) == 2
        # not 0: a leg as thin as a pixel looks a little different wherever it falls on the pixels
        assert LegTracker.movement(tracks, len(shifts))[0] < 0.25

    def test_a_leg_that_jumps_further_than_the_link_is_two_legs(self):
        """What the tracker cannot do: 8 degrees either way is 2.4 pixels at the leg's end."""
        frames, _tips = _frames([[(180 + turn, 3)] for turn in (-8, 8) * 5])
        tracks = LegTracker().track(frames)
        assert len(tracks) == 2
        assert LegTracker.movement(tracks, 10)[0] == pytest.approx(0, abs=1e-6)

    def test_two_legs_keep_their_names(self):
        frames, _tips = _frames([[(160 + turn, 3), (230 - turn, 3)] for turn in (0, 3, 6, 3, 0, -3, -6, -3, 0, 3)])
        tracks = LegTracker().track(frames)
        assert len(tracks) == 2
        assert tracks.seen.all()
        # each stays on its side of the other
        assert (tracks.xy[0, :, 1] < tracks.xy[1, :, 1]).all() or (tracks.xy[0, :, 1] > tracks.xy[1, :, 1]).all()

    def test_a_leg_seen_too_seldom_is_not_one(self):
        frames, _tips = _frames([[(180, 3)]] * 2 + [[]] * 8)
        assert len(LegTracker(at_least=5).track(frames)) == 0

    def test_a_leg_that_comes_back_is_the_same_leg(self):
        frames, _tips = _frames([[(180, 3)]] * 5 + [[]] * 3 + [[(180, 3)]] * 5)
        tracks = LegTracker().track(frames)
        assert len(tracks) == 1
        assert tracks.seen[0].tolist() == [True] * 5 + [False] * 3 + [True] * 5
        assert tracks.count.tolist() == [1] * 5 + [0] * 3 + [1] * 5

    def test_a_leg_gone_for_too_long_is_a_new_one(self):
        frames, _tips = _frames([[(180, 3)]] * 5 + [[]] * 6 + [[(180, 3)]] * 5)
        assert len(LegTracker(patience=3).track(frames)) == 2

    def test_no_frames_with_legs_is_no_track(self):
        frames, _tips = _frames([[]] * 10)
        tracks = LegTracker().track(frames)
        assert len(tracks) == 0
        assert LegTracker.movement(tracks, 10).tolist() == [0.0]
        assert LegTracker.places(tracks, 10).shape == (0, 1, 2)


class TestByRecording:
    def test_movement_is_per_recording(self):
        still = [[(180, 3)]] * 10
        swinging = [[(180 + turn, 3)] for turn in (-4, 4) * 5]
        frames, _tips = _frames(still + swinging)
        movement = LegTracker.movement(LegTracker().track(frames), 10)
        assert movement.shape == (2,)
        assert movement[0] == pytest.approx(0, abs=1e-6)
        assert movement[1] > 0.3

    def test_a_leg_seen_in_too_few_frames_of_a_recording_does_not_count_there(self):
        frames, _tips = _frames([[(180, 3)]] * 10 + [[(175, 3)], [(185, 3)]] + [[]] * 8)
        tracks = LegTracker().track(frames)
        assert np.isnan(LegTracker.swings(tracks, 10)[0, 1])
        assert LegTracker.movement(tracks, 10)[1] == 0

    def test_places_are_the_mean_of_the_frames(self):
        frames, _tips = _frames([[(180, 3)]] * 10 + [[(186, 3)]] * 10)
        tracks = LegTracker().track(frames)
        places = LegTracker.places(tracks, 10)
        assert places.shape == (1, 2, 2)
        assert places[0, 0] == pytest.approx(tracks.xy[0, :10].mean(axis=0))
        assert np.linalg.norm(places[0, 1] - places[0, 0]) > 0.3

    def test_frames_cuts_the_tracks(self):
        frames, _tips = _frames([[(180, 3)]] * 20)
        part = LegTracker().track(frames).frames(10, 20)
        assert part.xy.shape == (1, 10, 2) and part.count.shape == (10,)
