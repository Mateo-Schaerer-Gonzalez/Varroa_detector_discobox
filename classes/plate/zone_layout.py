"""The zone mask a recording's plates are cut into (classes/plate/zone_masks.py).

The choice is kept with the recordings, as the `zone_mask` line of their
.settings.txt, so every later analysis of them uses the same zones. A folder
without that line uses the default mask, one zone per plate; one with the
`zones_per_plate` line of earlier versions (1 or 2) the built-in mask of that
name; one whose mask was deleted since, the default mask.

Plate labels and negative controls go by zone id, which means another plate in
another mask, so each mask keeps its own: labels.json and controls.json for the
default mask, labels_<mask>.json and controls_<mask>.json for the others
(labels_2.json for two zones per plate, as before).
"""

from pathlib import Path

from classes.plate import zone_masks
from classes.storage import settings_file


class ZoneLayout:
    SETTING = "zone_mask"
    # the line of earlier versions: 1 or 2 zones per plate, now the masks of those names
    OLD_SETTING = "zones_per_plate"
    DEFAULT = zone_masks.DEFAULT

    def __init__(self, mask=DEFAULT):
        self.mask = zone_masks.check(mask)

    @classmethod
    def choices(cls):
        """Every mask, as the pages offer them: [{name, title}]."""
        return [{"name": name, "title": zone_masks.title(name)} for name in zone_masks.names()]

    @classmethod
    def of_folder(cls, data_dir):
        """The mask saved with the recordings in `data_dir`; the default one when
        none is, or the one saved is no longer there."""
        try:
            saved = settings_file.of_folder(data_dir)
            return cls(saved.get(cls.SETTING, saved.get(cls.OLD_SETTING, cls.DEFAULT)))
        except (OSError, ValueError):
            return cls()

    def save(self, data_dir):
        """Keep this mask with the recordings in `data_dir`: the zone_mask line of
        their .settings.txt, every other line kept as it is."""
        settings_file.remove(data_dir, self.OLD_SETTING)
        settings_file.save(data_dir, self.SETTING, self.mask)

    @property
    def coords_file(self):
        return zone_masks.coords_file(self.mask)

    @property
    def title(self):
        return zone_masks.title(self.mask)

    def filename(self, name):
        """The file of this mask for what goes by zone id: `name` itself for the
        default mask, e.g. labels.json, else e.g. labels_2.json."""
        if self.mask == self.DEFAULT:
            return name
        path = Path(name)
        return f"{path.stem}_{self.mask}{path.suffix}"

    @classmethod
    def filenames(cls, name):
        """`name` in every mask, e.g. to copy a folder's plate labels."""
        return [cls(mask).filename(name) for mask in zone_masks.names()]
