import numpy as np
import pytest

from classes.app_config import TextZoneStyle
from classes.mite import Mite
from classes.zones import Zone, ZoneManager


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


    def test_mite_inside_zone(self):
        z = Zone(0, 0, 10, 10, type="brood")
        mite = Mite(1, 1, 2, 2)

        assert mite in z

    def test_mite_outside_zone(self):
        z = Zone(0, 0, 10, 10, type="brood")
        mite = Mite(11, 11, 12, 12)

        assert mite not in z


class TestRepr:
    def test_repr_uses_generated_text(self):
        z = Zone(1, 2, 3, 4, type="brood")
        assert repr(z) == "TextZone(1, 2, 3, 4, text='brood_zone')"


class TestZoneManagerExclusionAndValidZones:
    def test_exclusion_zones_matches_excluded_types(self):
        label = Zone(0, 0, 10, 10, type="label")
        mite = Zone(0, 0, 10, 10, type="mite")
        manager = ZoneManager([label, mite], excluded_types=["label"])

        assert manager.exclusion_zones == [label]
        assert manager.valid_zones == [mite]

    def test_excluded_types_are_case_insensitive(self):
        label = Zone(0, 0, 10, 10, type="label")
        manager = ZoneManager([label], excluded_types=["LABEL"])

        assert manager.exclusion_zones == [label]

    def test_no_excluded_types_means_all_zones_are_valid(self):
        a = Zone(0, 0, 10, 10, type="brood")
        b = Zone(0, 0, 10, 10, type="entrance")
        manager = ZoneManager([a, b], excluded_types=[])

        assert manager.exclusion_zones == []
        assert manager.valid_zones == [a, b]


class TestZoneManagerIsExcluded:
    def test_point_inside_exclusion_zone_is_excluded(self):
        label = Zone(0, 0, 10, 10, type="label")
        manager = ZoneManager([label], excluded_types=["label"])

        assert manager.is_excluded(5, 5) is True

    def test_point_outside_exclusion_zones_is_not_excluded(self):
        label = Zone(0, 0, 10, 10, type="label")
        manager = ZoneManager([label], excluded_types=["label"])

        assert manager.is_excluded(50, 50) is False

    def test_point_inside_a_non_excluded_zone_is_not_excluded(self):
        mite_zone = Zone(0, 0, 10, 10, type="mite")
        manager = ZoneManager([mite_zone], excluded_types=[])

        assert manager.is_excluded(5, 5) is False


class TestZoneManagerMaskImageToValidRois:
    def test_keeps_only_valid_zone_pixels(self):
        label = Zone(0, 0, 5, 10, type="label")
        mite_zone = Zone(5, 0, 10, 10, type="mite")
        manager = ZoneManager([label, mite_zone], excluded_types=["label"])
        image = np.full((10, 10), 7, dtype=np.uint8)

        masked = manager.mask_image_to_valid_rois(image, fill_color=255)

        assert (masked[:, :5] == 255).all()
        assert (masked[:, 5:] == 7).all()


class TestZoneManagerRemoveMites:
    def test_rejected_mites_leave_their_zones(self):
        left = Zone(0, 0, 100, 100, type="brood")
        right = Zone(200, 0, 300, 100, type="brood")
        manager = ZoneManager([left, right])
        keep, drop, other = Mite(10, 10, 20, 20), Mite(30, 30, 40, 40), Mite(210, 10, 220, 20)
        manager.assign_mites([keep, drop, other])

        remaining = manager.remove_mites([drop])

        assert remaining == [keep, other]
        assert left.mites == [keep]
        assert right.mites == [other]


class TestZoneManagerAssignMites:
    def test_mite_inside_a_zone_is_assigned_and_returned(self):
        zone = Zone(0, 0, 100, 100, type="brood")
        manager = ZoneManager([zone])
        mite = Mite(10, 10, 20, 20)

        assigned = manager.assign_mites([mite])

        assert assigned == [mite]
        assert zone.mites == [mite]

    def test_mite_outside_all_zones_is_dropped(self):
        zone = Zone(0, 0, 10, 10, type="brood")
        manager = ZoneManager([zone])
        mite = Mite(50, 50, 60, 60)

        assigned = manager.assign_mites([mite])

        assert assigned == []
        assert zone.mites == []

    def test_mite_assigned_to_first_matching_zone_only(self):
        first = Zone(0, 0, 100, 100, type="brood")
        second = Zone(0, 0, 100, 100, type="entrance")
        manager = ZoneManager([first, second])
        mite = Mite(10, 10, 20, 20)

        manager.assign_mites([mite])

        assert first.mites == [mite]
        assert second.mites == []

    def test_multiple_mites_are_each_assigned_independently(self):
        zone = Zone(0, 0, 100, 100, type="brood")
        manager = ZoneManager([zone])
        first_mite = Mite(1, 1, 2, 2)
        second_mite = Mite(3, 3, 4, 4)

        assigned = manager.assign_mites([first_mite, second_mite])

        assert assigned == [first_mite, second_mite]
        assert zone.mites == [first_mite, second_mite]




class TestZoneManagerTextZoneFor:
    def test_picks_the_label_area_beside_the_plate(self):
        plate = Zone(100, 0, 200, 50, type="mite")
        own_label = Zone(60, 0, 98, 50, type="label")
        next_plates_label = Zone(215, 0, 260, 50, type="label")
        manager = ZoneManager([plate, own_label, next_plates_label], excluded_types=["label"])

        assert manager.text_zone_for(plate) is own_label

    def test_ignores_label_areas_in_other_rows(self):
        plate = Zone(100, 0, 200, 50, type="mite")
        row_below = Zone(60, 60, 98, 110, type="label")
        manager = ZoneManager([plate, row_below], excluded_types=["label"])

        assert manager.text_zone_for(plate) is None

    def test_none_without_label_areas(self):
        plate = Zone(100, 0, 200, 50, type="mite")
        manager = ZoneManager([plate], excluded_types=["label"])

        assert manager.text_zone_for(plate) is None
