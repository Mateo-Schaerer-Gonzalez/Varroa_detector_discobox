from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config


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
