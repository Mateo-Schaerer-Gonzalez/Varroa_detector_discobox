from typing import Optional

from classes.plate.rect import TextZone
from classes.app_config import AppConfig, get_default_config


class Mite(TextZone):
    """Mite detection class extending TextZone with domain-specific helpers.

    The camera only sees movement, so a mite records one motion score per
    recording and whether that score reaches the threshold (`moving`). It makes
    no claim about the mite being alive or dead.

    Its box (x1, y1, x2, y2) is where it was found: what it is known by (labels,
    ground truth, corrections) and where it is drawn. A live run follows each
    mite from recording to recording; where it was scored in each is the
    analysis's to know (MotionAnalysis.boxes_of). A recording in which it was not followed, before
    it was added (`start`) or once it counted as dead (`stopped`), has None for
    its score, and for everything else recorded with it.
    """

    # A mite is numbered as it is detected; once it is in a zone its id becomes
    # "<zone id>.<number in the zone>" (ZoneManager.number_mites()).
    id_counter = 0

    @staticmethod
    def id_order(mite_id):
        """A key that sorts mite ids by zone, then by number: "2.10" after "2.9".
        An id of another form comes after those, by its text."""
        parts = str(mite_id).split(".")
        if all(part.isdigit() for part in parts):
            return (0, [int(part) for part in parts], "")
        return (1, [], str(mite_id))

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
        # Per recording: the mean pixel value of the patch that was scored, for
        # classes/scoring/score_normalizer.py; None where it was not measured.
        self.brightness = []
        # Per recording: how its patch followed the plate and how it looks
        # (classes/scoring/unusual_activity.py), a dict, or None where not measured.
        self.activity = []
        self.start = 0       # the first recording it is followed in: a mite added during a live run starts later
        self.stopped = None  # the recording from which it is no longer followed, once it counted as dead
        self._show_moving(False)

    def _show_moving(self, moving):
        """Draw the mite in the moving or the still color."""
        self.color = self.mite_cfg.moving_color if moving else self.mite_cfg.still_color
        self.text_color = self.color

    def record_motion(self, score, brightness=None, activity=None):
        """Append a per-recording motion score, with the `brightness` of the patch
        it was scored on and its `activity` there (see classes/scoring/unusual_activity.py).
        The drawing color follows the latest recording: moving or still."""
        self.motion_scores.append(score)
        self.brightness.append(brightness)
        self.activity.append(activity)
        self._show_moving(score >= self.motion_threshold)

    def record_absence(self):
        """A recording in which the mite was not followed: nothing recorded."""
        self.motion_scores.append(None)
        self.brightness.append(None)
        self.activity.append(None)

    def followed_in(self, recording):
        """Whether the mite is followed (scored, and its surroundings saved) in recording `recording`."""
        return self.start <= recording and (self.stopped is None or recording < self.stopped)

    @property
    def home(self):
        """(x, y): the centre of its box, where it was found."""
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    @property
    def moving(self):
        """Per recording: did the mite move above the threshold in that
        recording? None where it was not followed."""
        return [None if score is None else score >= self.motion_threshold for score in self.motion_scores]
