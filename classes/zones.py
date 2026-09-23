from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config
import cv2
import numpy as np
import pandas as pd
from pathlib import Path

UNLABELED = "unlabeled"

# One row per (mite, recording). `moving`: the score of that recording reaches the
# threshold. x, y is the mite's centre in image pixels.
MITE_SCORE_COLUMNS = [
    "mite_ID", "time", "motion_score", "moving",
    "zone_id", "group", "zone_type", "x", "y",
]


class Zone(TextZone):
    def __init__(self, x1, y1, x2, y2, type, id=None, label=None, config: Optional[AppConfig] = None):
        config = config or get_default_config()
        text = f"{type}_zone"
        style = config.zone_styles.get(text)

        style_kwargs = {}
        if style is not None:
            style_kwargs = dict(
                color=style.box_color,
                text_color=style.text_color,
                thickness=style.thickness,
                font_scale=style.font_scale,
                text_offset_y=style.text_offset_y,
            )

        super().__init__(x1, y1, x2, y2, text=text, **style_kwargs)
        self.type = type
        self.id = id
        self.mites = []  # List to hold Mite instances within this zone
        self.label = label

    @property
    def label(self):
        """The user-supplied group name for this zone (e.g. a venom extract)."""
        return self._label

    @label.setter
    def label(self, value):
        """Setting a label also changes the text drawn above the zone."""
        self._label = value or None
        self.text = self._label if self._label else f"{self.type}_zone"

    @property
    def group(self):
        """The name this zone's mites are grouped under when summarising."""
        return self._label or UNLABELED

    def add_mite(self, mite):
        """Add a Mite instance to the zone"""
        self.mites.append(mite)

    def draw_mask(self, image, fill_color=255):
        """Paints over this zone with fill_color to neutralize blobs."""
        cv2.rectangle(
            image,
            (int(self.x1), int(self.y1)),
            (int(self.x2), int(self.y2)),
            fill_color,
            -1
        )

    def draw(self, image):
        """Draws the zone rectangle and label on the image."""
        super().draw(image)

        # also draw mites within this zone
        for mite in self.mites:
            mite.draw(image)


def sort_reading_order(zones):
    """Order zones left-to-right, top-to-bottom, the way you would read the plate.

    Zones in the same physical row have slightly different y1 values, so rows are
    grouped by proximity rather than by an exact coordinate match.
    """
    if not zones:
        return []

    row_tolerance = float(np.median([zone.y2 - zone.y1 for zone in zones])) / 2
    by_height = sorted(zones, key=lambda zone: zone.y1)

    rows = [[by_height[0]]]
    for zone in by_height[1:]:
        if zone.y1 - rows[-1][0].y1 > row_tolerance:
            rows.append([zone])
        else:
            rows[-1].append(zone)

    return [zone for row in rows for zone in sorted(row, key=lambda zone: zone.x1)]


class ZoneManager:
    def __init__(self, zones, excluded_types=None):
        self.zones = zones
        # Types of zones where mites should be eliminated / ignored
        self.excluded_types = set(zone_type.lower() for zone_type in excluded_types or [])

        # Number the zones the user labels, in reading order, so that an id always
        # points at the same physical plate.
        for index, zone in enumerate(sort_reading_order(self.valid_zones)):
            zone.id = index

    @classmethod
    def from_coords_file(cls, filepath: str | Path, zone_types: dict[str, str],  excluded_types=None) -> "ZoneManager":
        """Factory method: parses a coordinate file and returns a ready-to-use ZoneManager."""
        mapping = zone_types
        path = Path(filepath)

        if not path.is_file():
            raise FileNotFoundError(f"Zone coordinates file not found: {path}")

        zones = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                type_id, x1, y1, x2, y2 = line.split()
                zone_type = mapping.get(type_id, type_id)

                zones.append(
                    Zone(
                        int(float(x1)),
                        int(float(y1)),
                        int(float(x2)),
                        int(float(y2)),
                        type=zone_type,
                    )
                )

        return cls(zones=zones, excluded_types=excluded_types)

    def add_zone(self, zone):
        self.zones.append(zone)

    @property
    def exclusion_zones(self):
        """Returns only the zones meant for elimination."""
        return [zone for zone in self.zones if zone.type in self.excluded_types]

    @property
    def valid_zones(self):
        """Returns only the zones meant to be kept (i.e. not excluded)."""
        return [zone for zone in self.zones if zone.type not in self.excluded_types]

    @property
    def labelled_zones(self):
        """Valid zones in reading order: the ones the user assigns group names to."""
        return sort_reading_order(self.valid_zones)

    def text_zone_for(self, zone):
        """The printed-label area that belongs to a plate, or None.

        On the discobox each plate's label area sits beside it in the same row, so
        this is the exclusion zone that shares most of the plate's height and whose
        nearest edge is closest to the plate.
        """
        best, best_gap = None, None
        for candidate in self.exclusion_zones:
            overlap = min(zone.y2, candidate.y2) - max(zone.y1, candidate.y1)
            shorter = min(zone.y2 - zone.y1, candidate.y2 - candidate.y1)
            if shorter <= 0 or overlap < shorter / 2:
                continue  # not in the same row
            gap = max(candidate.x1 - zone.x2, zone.x1 - candidate.x2, 0)
            if best_gap is None or gap < best_gap:
                best, best_gap = candidate, gap
        return best

    def apply_labels(self, labels):
        """Assign user-supplied group names to zones, keyed by zone id.

        Keys may be ints or strings, since JSON object keys arrive as strings.
        """
        if not labels:
            return
        by_id = {str(key): value for key, value in labels.items()}
        for zone in self.valid_zones:
            if str(zone.id) in by_id:
                zone.label = by_id[str(zone.id)]

    def is_excluded(self, px, py):
        """Returns True if (px, py) falls inside any exclusion zone."""
        return any(zone.contains_point(px, py) for zone in self.exclusion_zones)

    def mask_image_to_valid_rois(self, image, fill_color: int = 255):
        """
        Creates a clean canvas with `fill_color` and only pastes
        the image pixels from valid zones.
        """
        # 1. Blank canvas (neutral background)
        output_img = np.full_like(image, fill_value=fill_color)

        # 2. Copy only valid regions
        for z in self.valid_zones:
            x1, y1 = max(0, int(z.x1)), max(0, int(z.y1))
            x2, y2 = min(image.shape[1], int(z.x2)), min(image.shape[0], int(z.y2))

            output_img[y1:y2, x1:x2] = image[y1:y2, x1:x2]

        return output_img

    def draw(self, image):
        """Draws all zones on the image."""
        for zone in self.zones:
            zone.draw(image)

        return image


    def assign_mites(self, mites):
        """Assigns mites to their respective zones.

        Returns the list of mites that successfully landed inside a valid zone.
        """
        assigned_mites = []

        for mite in mites:
            for zone in self.zones:
                if mite in zone:
                    zone.add_mite(mite)
                    assigned_mites.append(mite)
                    break  # Stop checking once the first matching zone claims it

        return assigned_mites


    def remove_mites(self, rejected):
        """Drop detections that are not mites from their zones.

        `rejected` is a collection of Mite instances. Returns the mites that remain.
        """
        rejected = set(map(id, rejected))
        remaining = []
        for zone in self.zones:
            zone.mites = [mite for mite in zone.mites if id(mite) not in rejected]
            remaining.extend(zone.mites)
        return remaining

    def get_mite_scores(self, times):
        """Return a long-form timeseries of mite motion scores.

        `times` holds one timestamp per recording burst and is shared by
        every mite (e.g. `burst_minutes` in main.py). Each mite's
        `motion_scores` list must line up with `times` one-to-one, so the
        result has one row per (mite, time) pair.
        """
        rows = []
        for zone in self.zones:
            for mite in zone.mites:
                mite_id = mite.text
                x = (mite.x1 + mite.x2) / 2
                y = (mite.y1 + mite.y2) / 2
                for time, motion_score, moving in zip(times, mite.motion_scores, mite.moving):
                    rows.append(
                        {
                            "mite_ID": mite_id,
                            "time": time,
                            "motion_score": motion_score,
                            "moving": moving,
                            "zone_id": zone.id,
                            "group": zone.group,
                            "zone_type": zone.type,
                            "x": x,
                            "y": y,
                        }
                    )

        return pd.DataFrame(rows, columns=MITE_SCORE_COLUMNS)
