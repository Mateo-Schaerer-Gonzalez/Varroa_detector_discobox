"""How many zones each plate is cut into, and the coordinates file of each choice.

A plate is one zone, or two: its upper and its lower half, each with its own half
of the printed-label area. The choice is kept with the recordings, as the
`zones_per_plate` line of their .settings.txt, so every later analysis of them
uses the same zones. A folder without that line has one zone per plate.

Plate labels and negative controls go by zone id, which means another plate in
another layout, so each layout keeps its own: labels.json and controls.json for
one zone per plate, labels_2.json and controls_2.json for two.
"""

from pathlib import Path

from classes.data_loader import DataLoader

APP_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILENAME = ".settings.txt"


class ZoneLayout:
    SETTING = "zones_per_plate"
    DEFAULT = 1
    # zones per plate -> its coordinates file, next to the app
    COORDS_FILES = {1: "coords_pixel.txt", 2: "coords_pixel_2.txt"}

    def __init__(self, zones_per_plate=DEFAULT):
        self.zones_per_plate = self.check(zones_per_plate)

    @classmethod
    def choices(cls):
        return list(cls.COORDS_FILES)

    @classmethod
    def check(cls, value):
        """`value` as a number of zones per plate, or a ValueError naming the choices."""
        choices = " or ".join(str(choice) for choice in cls.COORDS_FILES)
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Zones per plate must be {choices}, not {value!r}.")
        if number != value and str(number) != str(value).strip() or number not in cls.COORDS_FILES:
            raise ValueError(f"Zones per plate must be {choices}, not {value!r}.")
        return number

    @classmethod
    def of_folder(cls, data_dir):
        """The layout saved with the recordings in `data_dir`; one zone per plate
        when none is, or what is saved is not one of the choices."""
        path = Path(data_dir) / SETTINGS_FILENAME
        try:
            return cls(DataLoader._parse_settings_file(path).get(cls.SETTING, cls.DEFAULT) if path.is_file() else cls.DEFAULT)
        except (OSError, ValueError):
            return cls()

    def save(self, data_dir):
        """Keep this layout with the recordings in `data_dir`: the zones_per_plate
        line of their .settings.txt, every other line kept as it is."""
        DataLoader.save_setting(Path(data_dir) / SETTINGS_FILENAME, self.SETTING, self.zones_per_plate)

    @property
    def coords_file(self):
        return APP_DIR / self.COORDS_FILES[self.zones_per_plate]

    def filename(self, name):
        """The file of this layout for what goes by zone id: `name` itself with
        one zone per plate, e.g. labels.json, else labels_2.json."""
        if self.zones_per_plate == self.DEFAULT:
            return name
        path = Path(name)
        return f"{path.stem}_{self.zones_per_plate}{path.suffix}"

    @classmethod
    def filenames(cls, name):
        """`name` in every layout, e.g. to copy a folder's plate labels."""
        return [cls(choice).filename(name) for choice in cls.COORDS_FILES]
