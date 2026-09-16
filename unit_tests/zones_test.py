import pytest

from classes.app_config import TextZoneStyle
from classes.mite import Mite
from classes.zones import Zone


class FakeConfig:
    def __init__(self, zone_styles):
        self.zone_styles = zone_styles


class TestInit:
    def test_stores_coords_already_in_order(self):
        z = Zone(1, 2, 10, 20, type="entrance")
        assert (z.x1, z.y1, z.x2, z.y2) == (1, 2, 10, 20)

    def test_normalizes_reversed_corners(self):
        z = Zone(10, 20, 1, 2, type="entrance")
        assert (z.x1, z.y1, z.x2, z.y2) == (1, 2, 10, 20)

    def test_stores_type(self):
        z = Zone(0, 0, 1, 1, type="brood")
        assert z.type == "brood"

    def test_text_is_derived_from_type(self):
        z = Zone(0, 0, 1, 1, type="brood")
        assert z.text == "brood_zone"

    def test_starts_with_no_mites(self):
        z = Zone(0, 0, 1, 1, type="brood")
        assert z.mites == []

    def test_inherits_default_text_zone_style(self):
        z = Zone(0, 0, 1, 1, type="brood")
        assert z.color == (255, 0, 0)
        assert z.text_color == (0, 0, 255)
        assert z.thickness == 2
        assert z.font_scale == 1.0
        assert z.text_offset_y == 10


class TestFromConfig:
    def test_uses_matching_zone_style(self):
        style = TextZoneStyle(box_color=(9, 8, 7), text_color=(6, 5, 4),
                               thickness=3, font_scale=1.5, text_offset_y=15)
        config = FakeConfig(zone_styles={"mite_zone": style})
        z = Zone(0, 0, 10, 10, type="mite", config=config)
        assert z.color == (9, 8, 7)
        assert z.text_color == (6, 5, 4)
        assert z.thickness == 3
        assert z.font_scale == 1.5
        assert z.text_offset_y == 15

    def test_falls_back_to_default_style_when_type_has_no_entry(self):
        style = TextZoneStyle(box_color=(9, 8, 7), text_color=(6, 5, 4),
                               thickness=3, font_scale=1.5, text_offset_y=15)
        config = FakeConfig(zone_styles={"mite_zone": style})
        z = Zone(0, 0, 10, 10, type="brood", config=config)
        assert z.color == (255, 0, 0)
        assert z.text_color == (0, 0, 255)
        assert z.thickness == 2
        assert z.font_scale == 1.0
        assert z.text_offset_y == 10


class TestAddMite:
    def test_adds_single_mite(self):
        z = Zone(0, 0, 10, 10, type="brood")
        mite = object()
        z.add_mite(mite)
        assert z.mites == [mite]

    def test_adds_multiple_mites_in_order(self):
        z = Zone(0, 0, 10, 10, type="brood")
        first, second, third = object(), object(), object()
        z.add_mite(first)
        z.add_mite(second)
        z.add_mite(third)
        assert z.mites == [first, second, third]

    def test_separate_zones_have_independent_mite_lists(self):
        a = Zone(0, 0, 10, 10, type="brood")
        b = Zone(0, 0, 10, 10, type="entrance")
        a.add_mite(object())
        assert a.mites != b.mites
        assert b.mites == []


    def mite_inside_zone(self):
        z = Zone(0, 0, 10, 10, type="brood")
        mite = Mite(1, 1, 2, 2)
       
        assert mite in z == True

    def mite_outside_zone(self):
        z = Zone(0, 0, 10, 10, type="brood")
        mite = Mite(11, 11, 12, 12)
       
        assert mite in z == False


class TestRepr:
    def test_repr_uses_generated_text(self):
        z = Zone(1, 2, 3, 4, type="brood")
        assert repr(z) == "TextZone(1, 2, 3, 4, text='brood_zone')"


