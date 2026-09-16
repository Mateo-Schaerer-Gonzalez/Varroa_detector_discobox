import numpy as np
import pytest

from classes.app_config import TextZoneStyle
from classes.rect import TextZone


class FakeConfig:
    def __init__(self, text_zone_style):
        self.text_zone_style = text_zone_style


class TestInit:
    def test_stores_coords_already_in_order(self):
        z = TextZone(1, 2, 10, 20)
        assert (z.x1, z.y1, z.x2, z.y2) == (1, 2, 10, 20)

    def test_normalizes_reversed_corners(self):
        z = TextZone(10, 20, 1, 2)
        assert (z.x1, z.y1, z.x2, z.y2) == (1, 2, 10, 20)

    def test_default_text(self):
        z = TextZone(0, 0, 1, 1)
        assert z.text == "EMPTY"

    def test_custom_text(self):
        z = TextZone(0, 0, 1, 1, text="hello")
        assert z.text == "hello"

    def test_default_colors_and_style(self):
        z = TextZone(0, 0, 1, 1)
        assert z.color == (255, 0, 0)
        assert z.text_color == (0, 0, 255)
        assert z.thickness == 2
        assert z.font_scale == 1.0
        assert z.text_offset_y == 10

    def test_custom_style(self):
        z = TextZone(0, 0, 1, 1, color=(1, 1, 1), text_color=(2, 2, 2),
                     thickness=5, font_scale=2.0, text_offset_y=20)
        assert z.color == (1, 1, 1)
        assert z.text_color == (2, 2, 2)
        assert z.thickness == 5
        assert z.font_scale == 2.0
        assert z.text_offset_y == 20


class TestFromConfig:
    def test_uses_style_from_config(self):
        style = TextZoneStyle(box_color=(9, 8, 7), text_color=(6, 5, 4),
                               thickness=3, font_scale=1.5, text_offset_y=15)
        config = FakeConfig(text_zone_style=style)
        z = TextZone.from_config(1, 2, 10, 20, config, text="mite_0000")
        assert (z.x1, z.y1, z.x2, z.y2) == (1, 2, 10, 20)
        assert z.text == "mite_0000"
        assert z.color == (9, 8, 7)
        assert z.text_color == (6, 5, 4)
        assert z.thickness == 3
        assert z.font_scale == 1.5
        assert z.text_offset_y == 15

    def test_default_text_is_empty(self):
        style = TextZoneStyle(box_color=(0, 0, 0), text_color=(0, 0, 0),
                               thickness=1, font_scale=1.0, text_offset_y=5)
        config = FakeConfig(text_zone_style=style)
        z = TextZone.from_config(0, 0, 5, 5, config)
        assert z.text == "EMPTY"


class TestDraw:
    def test_draws_rectangle_border(self):
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        z = TextZone(5, 5, 20, 20, color=(255, 255, 255))
        z.draw(image)
        assert tuple(image[5, 5]) == (255, 255, 255)
        assert tuple(image[10, 10]) == (0, 0, 0)

    def test_draws_text_above_box(self):
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        z = TextZone(10, 20, 30, 40, text="A", text_color=(0, 255, 255), text_offset_y=10)
        z.draw(image)
        # The text is drawn in the strip directly above the box's top edge.
        text_strip = image[0:10, 10:30]
        assert np.any(np.all(text_strip == (0, 255, 255), axis=-1))

    def test_draw_respects_thickness_override(self):
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        z = TextZone(5, 5, 30, 30, color=(255, 255, 255))
        z.draw(image, thickness=6)
        # Border is now thick enough to reach a few pixels in from the edge.
        assert tuple(image[8, 15]) == (255, 255, 255)
        # Interior stays untouched.
        assert tuple(image[20, 20]) == (0, 0, 0)


class TestRepr:
    def test_repr_format(self):
        z = TextZone(1, 2, 3, 4, text="mite_0001")
        assert repr(z) == "TextZone(1, 2, 3, 4, text='mite_0001')"

    def test_repr_uses_normalized_coords(self):
        z = TextZone(3, 4, 1, 2, text="x")
        assert repr(z) == "TextZone(1, 2, 3, 4, text='x')"
