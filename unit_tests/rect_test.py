import numpy as np
import pytest

from classes.rect import Rect


class TestInit:
    def test_stores_coords_already_in_order(self):
        r = Rect(1, 2, 10, 20)
        assert (r.x1, r.y1, r.x2, r.y2) == (1, 2, 10, 20)

    def test_normalizes_reversed_x(self):
        r = Rect(10, 2, 1, 20)
        assert (r.x1, r.x2) == (1, 10)

    def test_normalizes_reversed_y(self):
        r = Rect(1, 20, 10, 2)
        assert (r.y1, r.y2) == (2, 20)

    def test_normalizes_fully_reversed_corners(self):
        r = Rect(10, 20, 1, 2)
        assert (r.x1, r.y1, r.x2, r.y2) == (1, 2, 10, 20)

    def test_default_color(self):
        r = Rect(0, 0, 1, 1)
        assert r.color == (0, 255, 0)

    def test_custom_color(self):
        r = Rect(0, 0, 1, 1, color=(255, 0, 0))
        assert r.color == (255, 0, 0)

    def test_zero_area_rect(self):
        r = Rect(5, 5, 5, 5)
        assert (r.x1, r.y1, r.x2, r.y2) == (5, 5, 5, 5)


class TestDraw:
    def test_draws_rectangle_on_image(self):
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        r = Rect(5, 5, 20, 20, color=(255, 255, 255))
        r.draw(image)
        # Border pixels should be colored, interior should remain black
        assert tuple(image[5, 5]) == (255, 255, 255)
        assert tuple(image[10, 10]) == (0, 0, 0)

    def test_draw_respects_thickness(self):
        image = np.zeros((50, 50, 3), dtype=np.uint8)
        r = Rect(5, 5, 20, 20, color=(255, 255, 255))
        r.draw(image, thickness=-1)  # filled
        assert tuple(image[10, 10]) == (255, 255, 255)


class TestContains:
    def test_fully_inside_is_true(self):
        outer = Rect(0, 0, 100, 100)
        inner = Rect(10, 10, 20, 20)
        assert inner in outer

    def test_identical_rects_true(self):
        a = Rect(0, 0, 10, 10)
        b = Rect(0, 0, 10, 10)
        assert a in b

    def test_partially_outside_is_false(self):
        outer = Rect(0, 0, 10, 10)
        other = Rect(5, 5, 15, 15)
        assert other not in outer

    def test_fully_outside_is_false(self):
        outer = Rect(0, 0, 10, 10)
        other = Rect(20, 20, 30, 30)
        assert other not in outer

    def test_touching_edges_counts_as_inside(self):
        outer = Rect(0, 0, 10, 10)
        other = Rect(0, 0, 10, 5)
        assert other in outer


class TestRepr:
    def test_repr_format(self):
        r = Rect(1, 2, 3, 4)
        assert repr(r) == "Rect(1, 2, 3, 4)"

    def test_repr_uses_normalized_coords(self):
        r = Rect(3, 4, 1, 2)
        assert repr(r) == "Rect(1, 2, 3, 4)"


class TestIter:
    def test_unpacking(self):
        r = Rect(1, 2, 3, 4)
        x1, y1, x2, y2 = r
        assert (x1, y1, x2, y2) == (1, 2, 3, 4)

    def test_tuple_conversion(self):
        r = Rect(1, 2, 3, 4)
        assert tuple(r) == (1, 2, 3, 4)


class TestGetROI:
    def test_single_frame_roi(self):
        frame = np.arange(10 * 10 * 3).reshape(10, 10, 3).astype(np.uint8)
        r = Rect(2, 3, 5, 7)
        roi = r.get_ROI(frame)
        assert roi.shape == (4, 3, 3)
        np.testing.assert_array_equal(roi, frame[3:7, 2:5, :])

    def test_batch_frames_roi(self):
        frames = np.arange(4 * 10 * 10 * 3).reshape(4, 10, 10, 3).astype(np.uint8)
        r = Rect(2, 3, 5, 7)
        roi = r.get_ROI(frames)
        assert roi.shape == (4, 4, 3, 3)
        np.testing.assert_array_equal(roi, frames[:, 3:7, 2:5, :])

    def test_invalid_dimensions_raises(self):
        frames = np.zeros((10, 10))  # 2D, unsupported
        r = Rect(0, 0, 5, 5)
        with pytest.raises(ValueError):
            r.get_ROI(frames)

    def test_five_dim_raises(self):
        frames = np.zeros((2, 2, 10, 10, 3))
        r = Rect(0, 0, 5, 5)
        with pytest.raises(ValueError):
            r.get_ROI(frames)
