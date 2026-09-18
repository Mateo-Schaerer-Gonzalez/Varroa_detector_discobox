from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config


class Mite(TextZone):
    """Mite detection class extending TextZone with domain-specific helpers."""

    id_counter = 0

    def __init__(self, x1, y1, x2, y2, alive=True, config: Optional[AppConfig] = None):
        config = config or get_default_config()
        self.mite_cfg = config.mite
        style = config.text_zone_style

        text = f"{Mite.id_counter}"
        Mite.id_counter += 1

        super().__init__(
            x1, y1, x2, y2,
            text=text,
            color=self.mite_cfg.alive_color if alive else self.mite_cfg.dead_color,
            text_color=self.mite_cfg.alive_color ,
            thickness=style.thickness,
            font_scale=style.font_scale,
            text_offset_y=style.text_offset_y,
        )

        self.radius = self.mite_cfg.radius
        self.motion_threshold = self.mite_cfg.motion_threshold
        self.metric = self.mite_cfg.metric
        self.alive = alive

    @property
    def alive(self):
        return self._alive

    @alive.setter # auto update color when it changes state
    def alive(self, value):
        """Setting alive updates the mite's display color to match its state."""
        self._alive = value
        self.color = self.mite_cfg.alive_color if value else self.mite_cfg.dead_color
        self.text_color = self.color

    def kill(self):
        """Mark the mite as dead, switching its color to the dead-mite color."""
        self.alive = False