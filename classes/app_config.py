from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@lru_cache(maxsize=None)
def _load_yaml_cached(config_path: Path) -> dict:
    """Read and parse a YAML file, caching the result per path so repeated
    AppConfig() instantiations don't hit the filesystem again."""
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _tuplify(data: dict) -> dict:
    """Convert list values (e.g. YAML color arrays) into tuples."""
    return {key: tuple(value) if isinstance(value, list) else value for key, value in data.items()}


@dataclass
class RectStyle:
    color: tuple
    thickness: int


@dataclass
class TextZoneStyle:
    box_color: tuple
    text_color: tuple
    thickness: int
    font_scale: float
    text_offset_y: int


@dataclass
class MiteConfig:
    radius: int
    motion_threshold: float
    metric: str
    alive_color: tuple
    dead_color: tuple


@dataclass
class DetectorConfig:
    min_threshold: float
    max_threshold: float
    threshold_step: float
    filter_by_color: bool
    blob_color: int
    filter_by_area: bool
    min_area: float
    max_area: float
    filter_by_circularity: bool
    min_circularity: float
    filter_by_convexity: bool
    min_convexity: float
    filter_by_inertia: bool
    min_inertia_ratio: float


class AppConfig:
    """Loads configuration and exposes strongly-typed style/domain sections."""

    def __init__(self, config_path: Optional[str | Path] = None):
        self.config_path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
        self._raw_config = _load_yaml_cached(self.config_path)

        visual_styles = self._raw_config.get("visual_styles", {})
        self.rect_style = RectStyle(**_tuplify(visual_styles.get("rect", {})))
        self.text_zone_style = TextZoneStyle(**_tuplify(visual_styles.get("text_zone", {})))
        self.mite = MiteConfig(**_tuplify(self._raw_config.get("mite", {})))
        self.detector = DetectorConfig(**self._raw_config.get("detector", {}))
        self.zone_styles = {
            name: TextZoneStyle(**_tuplify(style))
            for name, style in visual_styles.get("Zones", {}).items()
        }

    def get(self, section: str, default: Optional[Any] = None):
        """Retrieve raw parameters for any given configuration section."""
        return self._raw_config.get(section, default)


_default_config: Optional["AppConfig"] = None


def get_default_config() -> "AppConfig":
    """Return the shared AppConfig loaded from the default config.yaml.

    Lazily built once and reused by every caller (e.g. every Mite) that
    doesn't supply its own config, so the default file is only ever
    read/parsed a single time.
    """
    global _default_config
    if _default_config is None:
        _default_config = AppConfig()
    return _default_config
