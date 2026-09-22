import pytest

from classes.app_config import AppConfig, MiteConfig, TextZoneStyle, get_default_config
from classes.mite import Mite


class FakeConfig:
    def __init__(self, mite, text_zone_style):
        self.mite = mite
        self.text_zone_style = text_zone_style


@pytest.fixture(autouse=True)
def reset_id_counter():
    Mite.id_counter = 0
    yield
    Mite.id_counter = 0


@pytest.fixture
def custom_config():
    return FakeConfig(
        mite=MiteConfig(radius=99, motion_threshold=1.23, metric="mean_diff",
                         alive_color=(1, 2, 3), dead_color=(7, 8, 9)),
        text_zone_style=TextZoneStyle(
            box_color=(11, 12, 13),
            text_color=(14, 15, 16),
            thickness=9,
            font_scale=2.5,
            text_offset_y=42,
        ),
    )


@pytest.fixture
def use_custom_config(custom_config):
    """A custom config to pass explicitly into Mite(..., config=...)."""
    return custom_config


class TestInit:
    def test_stores_coords(self):
        m = Mite(1, 2, 10, 20)
        assert (m.x1, m.y1, m.x2, m.y2) == (1, 2, 10, 20)

    def test_normalizes_reversed_coords(self):
        m = Mite(10, 20, 1, 2)
        assert (m.x1, m.y1, m.x2, m.y2) == (1, 2, 10, 20)

    def test_alive_by_default(self):
        m = Mite(0, 0, 10, 10)
        assert m.alive is True

    def test_defaults_come_from_yaml(self):
        config = AppConfig()
        m = Mite(0, 0, 10, 10)
        assert m.radius == config.mite.radius
        assert m.motion_threshold == config.mite.motion_threshold
        assert m.metric == config.mite.metric
        assert m.color == config.mite.alive_color
        assert m.text_color == config.mite.alive_color
        assert m.thickness == config.text_zone_style.thickness
        assert m.font_scale == config.text_zone_style.font_scale
        assert m.text_offset_y == config.text_zone_style.text_offset_y

    def test_custom_config_overrides_yaml(self, use_custom_config):
        m = Mite(0, 0, 10, 10, config=use_custom_config)
        assert m.radius == 99
        assert m.motion_threshold == 1.23
        assert m.metric == "mean_diff"
        assert m.color == (1, 2, 3)
        assert m.text_color == (1, 2, 3)
        assert m.thickness == 9
        assert m.font_scale == 2.5
        assert m.text_offset_y == 42

    def test_no_config_uses_shared_default_instance(self):
        """Mites without an explicit config all share one AppConfig instance
        instead of each parsing config.yaml on their own."""
        Mite(0, 0, 10, 10)
        Mite(0, 0, 10, 10)
        assert get_default_config() is get_default_config()


class TestIdCounter:
    def test_first_mite_id_is_zero(self):
        m = Mite(0, 0, 10, 10)
        assert m.text == "0"

    def test_ids_increment_across_instances(self):
        first = Mite(0, 0, 10, 10)
        second = Mite(0, 0, 10, 10)
        third = Mite(0, 0, 10, 10)
        assert (first.text, second.text, third.text) == (
            "0",
            "1",
            "2",
        )

    def test_ids_are_unique_even_with_custom_config(self, use_custom_config):
        first = Mite(0, 0, 10, 10, config=use_custom_config)
        second = Mite(0, 0, 10, 10, config=use_custom_config)
        assert first.text != second.text


class TestSurvival:
    """custom_config has motion_threshold 1.23."""

    def record(self, config, scores):
        mite = Mite(0, 0, 10, 10, config=config)
        for score in scores:
            mite.record_motion(score)
        return mite

    def test_moving_compares_each_score_to_the_threshold(self, custom_config):
        mite = self.record(custom_config, [5, 0.1, 1.23])
        assert mite.moving == [True, False, True]

    def test_resting_mite_that_moves_again_stays_alive(self, custom_config):
        mite = self.record(custom_config, [5, 0.1, 0.1, 5])
        assert mite.survival == [True, True, True, True]

    def test_dead_from_the_recording_after_its_last_movement(self, custom_config):
        mite = self.record(custom_config, [5, 5, 0.1, 0.1])
        assert mite.survival == [True, True, False, False]

    def test_mite_that_never_moves_is_dead_throughout(self, custom_config):
        mite = self.record(custom_config, [0.1, 0.1])
        assert mite.survival == [False, False]

    def test_no_recordings_means_no_survival_data(self, custom_config):
        assert self.record(custom_config, []).survival == []
