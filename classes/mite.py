from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config


class Mite(TextZone):
    """Mite detection class extending TextZone with domain-specific helpers."""

    id_counter = 0

    def __init__(self, x1, y1, x2, y2, alive=True, config: Optional[AppConfig] = None):
        config = config or get_default_config()
        mite_cfg = config.mite
        style = config.text_zone_style

        color = mite_cfg.alive_color if alive else mite_cfg.dead_color
        text = f"mite_{Mite.id_counter:04d}"
        Mite.id_counter += 1

        super().__init__(
            x1, y1, x2, y2,
            text=text,
            color=color,
            text_color=color,
            thickness=style.thickness,
            font_scale=style.font_scale,
            text_offset_y=style.text_offset_y,
        )

        self.alive = alive
        self.radius = mite_cfg.radius
        self.motion_threshold = mite_cfg.motion_threshold
        self.metric = mite_cfg.metric
