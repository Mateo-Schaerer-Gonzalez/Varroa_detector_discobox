from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config


class Mite(TextZone):
    """Mite detection class extending TextZone with domain-specific helpers.

    The camera only sees movement, so a mite records one motion score per
    recording and whether that score reaches the threshold (`moving`). It makes
    no claim about the mite being alive or dead.
    """

    id_counter = 0

    @classmethod
    def reset_ids(cls):
        """Restart mite numbering at 0.

        `id_counter` is shared by every Mite ever created, so a long-lived process
        (the web server) must reset it before each analysis or ids keep climbing.
        """
        cls.id_counter = 0

    def __init__(self, x1, y1, x2, y2, config: Optional[AppConfig] = None):
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
        self.metric_params = self.mite_cfg.params_for(self.metric)
        self.motion_scores = []
        self._show_moving(False)

    def _show_moving(self, moving):
        """Draw the mite in the moving or the still color."""
        self.color = self.mite_cfg.moving_color if moving else self.mite_cfg.still_color
        self.text_color = self.color

    def record_motion(self, score):
        """Append a per-recording motion score. The drawing color follows the
        latest recording: moving or still."""
        self.motion_scores.append(score)
        self._show_moving(score >= self.motion_threshold)

    @property
    def moving(self):
        """Per recording: did the mite move above the threshold in that recording?"""
        return [score >= self.motion_threshold for score in self.motion_scores]
