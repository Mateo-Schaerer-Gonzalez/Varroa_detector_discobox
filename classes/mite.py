from typing import Optional

from classes.rect import TextZone
from classes.app_config import AppConfig, get_default_config
from classes.mite_threshold import MiteThreshold


class Mite(TextZone):
    """Mite detection class extending TextZone with domain-specific helpers.

    The camera only sees movement, so a mite records one motion score per
    recording and whether that score reaches the threshold (`moving`). It makes
    no claim about the mite being alive or dead.

    The threshold is config.yaml's: the same for every mite, or, with a window,
    the mite's own, an offset above the moving median of its scores (see
    MiteThreshold). The median moves with every recording added, so `moving`
    and `thresholds` are worked out from all the scores so far.
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
        self.threshold = MiteThreshold.from_config(self.mite_cfg)
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
        self._show_moving(self.moving[-1])

    @property
    def thresholds(self):
        """Per recording: the threshold the mite's score is compared with."""
        return self.threshold.thresholds(self.motion_scores)

    @property
    def moving(self):
        """Per recording: did the mite's score reach its threshold in that recording?"""
        return self.threshold.moving(self.motion_scores)
