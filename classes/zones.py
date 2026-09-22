from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config
import cv2
import numpy as np
import pandas as pd
from pathlib import Path

class Zone(TextZone):
    def __init__(self, x1, y1, x2, y2, type, config: Optional[AppConfig] = None):
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
        self.mites = []  # List to hold Mite instances within this zone


    

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



class ZoneManager:
    def __init__(self, zones, excluded_types=None):
        self.zones = zones
        # Types of zones where mites should be eliminated / ignored
        self.excluded_types = set(zone_type.lower() for zone_type in excluded_types or [])


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
                for time, motion_score in zip(times, mite.motion_scores):
                    rows.append(
                        {
                            "mite_ID": mite_id,
                            "time": time,
                            "motion_score": motion_score,
                            "Zone assigned": zone.type,
                        }
                    )

        return pd.DataFrame(
            rows,
            columns=["mite_ID", "time", "motion_score", "Zone assigned"],
        )
        

    