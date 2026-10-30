"""Mites that appear on the plates after the first recording.

A live run adds them by hand (pipeline/live/add_mites.py): the plates are lit,
the mites not followed yet detected, and the user keeps those that are mites.
A folder of frames, whose mites were put on while it was being recorded, has
them found on the first frame of each recording (NewMites): mites are put on a
plate several at once, debris and a mite that walked from its place turn up
one by one, so a zone's new detections are taken only when at least `least` of
them appear in one recording.
"""

from classes.scoring.motion_analysis import DETECTION_LOCK

# Pixels round a known mite's box in which a detection is that mite.
REACH = 4


def unknown(detected, known, zone_manager, reach=REACH):
    """[(mite, zone)]: the mites of `detected` (Mites, as Analyzer.detect() gives
    them) in a zone and not within `reach` of one of the boxes `known` ((x1,
    y1, x2, y2) each), in the order detected."""
    found = []
    for mite in detected:
        x, y = mite.home
        if any(x1 - reach <= x <= x2 + reach and y1 - reach <= y <= y2 + reach for x1, y1, x2, y2 in known):
            continue
        zone = zone_manager.zone_of(mite)
        if zone is not None:
            found.append((mite, zone))
    return found


class NewMites:
    """The mites that appear in the recordings after the first, found on each
    one's first frame given in turn (search())."""

    def __init__(self, zone_manager, analyzer, known, least):
        """`known`: the boxes of the mites found on the first frame; `least`:
        the fewest new detections in a zone in one recording to take them."""
        self.zone_manager = zone_manager
        self.analyzer = analyzer
        self.known = [tuple(box) for box in known]
        self.least = least
        self.found = []  # (recording, box) of every mite taken, in order

    def search(self, recording, image):
        """The boxes of the mites that appear on `image`, the first frame of
        recording `recording`: the zones' new detections, those of a zone with
        fewer than `least` left out. They are known from then on."""
        masked = self.zone_manager.mask_image_to_valid_rois(image)
        with DETECTION_LOCK:  # a Mite counts the ids on
            detected = self.analyzer.detect(masked)
        new = unknown(detected, self.known, self.zone_manager)
        per_zone = {}
        for mite, zone in new:
            per_zone.setdefault(zone.id, []).append(mite)
        taken = [tuple(mite) for mite, zone in new if len(per_zone[zone.id]) >= self.least]
        self.known.extend(taken)
        self.found.extend((recording, box) for box in taken)
        return taken
