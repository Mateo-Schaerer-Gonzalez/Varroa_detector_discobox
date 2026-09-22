from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config


class Mite(TextZone):
    """Mite detection class extending TextZone with domain-specific helpers."""

    id_counter = 0

    @classmethod
    def reset_ids(cls):
        """Restart mite numbering at 0.

        `id_counter` is shared by every Mite ever created, so a long-lived process
        (the web server) must reset it before each analysis or ids keep climbing.
        """
        cls.id_counter = 0

    def __init__(self, x1, y1, x2, y2, alive=True, config: Optional[AppConfig] = None):
        config = config or get_default_config()
        self.mite_cfg = config.mite
        style = config.text_zone_style

        text = f"{Mite.id_counter}"
        Mite.id_counter += 1

        super().__init__(
            x1, y1, x2, y2,
            text=text,
            thickness=style.thickness,
            font_scale=style.font_scale,
            text_offset_y=style.text_offset_y,
        )

        self.radius = self.mite_cfg.radius
        self.motion_threshold = self.mite_cfg.motion_threshold
        self.metric = self.mite_cfg.metric
        self.motion_scores = []
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

    def record_motion(self, score):
        """Append a per-recording motion score; alive reflects this latest recording only."""
        self.motion_scores.append(score)
        self.alive = score >= self.motion_threshold

    @property
    def moving(self):
        """Per recording: did the mite move above the threshold in that recording?"""
        return [score >= self.motion_threshold for score in self.motion_scores]

    @property
    def survival(self):
        """Per recording: was the mite still alive at that point in the session?

        A mite that sits still for one recording and moves again later was resting,
        not dead, so it counts as alive up to and including its last movement and
        dead from then on. Once dead it stays dead, which makes survival curves
        built from this never go back up.
        """
        survival = []
        moved_later = False
        for moved in reversed(self.moving):
            moved_later = moved_later or moved
            survival.append(moved_later)
        return survival[::-1]