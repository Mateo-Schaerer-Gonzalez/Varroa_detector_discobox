import re
from dataclasses import dataclass, field
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
    moving_color: tuple
    still_color: tuple
    # metric name -> its parameters, e.g. {"topN_variability": {"n": 10}}; a metric
    # or parameter left out uses the default in its Analyzer function.
    metric_params: dict = field(default_factory=dict)

    def params_for(self, metric):
        return dict((self.metric_params or {}).get(metric) or {})


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



def save_motion_threshold(value: float, config_path: Optional[str | Path] = None) -> float:
    """Write a new `mite.motion_threshold` into the config file and reload it.

    Only that one line is rewritten, so the comments and layout of the file are
    kept. Every AppConfig built afterwards, including the shared default one,
    sees the new value.
    """
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    text = path.read_text(encoding="utf-8")

    value = round(float(value), 3)
    path.write_text(_set_threshold_line(text, value, path), encoding="utf-8")
    _forget_loaded_config()
    return value


def _forget_loaded_config():
    """Make every AppConfig built from now on read the file again."""
    global _default_config
    _load_yaml_cached.cache_clear()
    _default_config = None


def _set_threshold_line(text, value, path):
    pattern = re.compile(r"^(\s+motion_threshold:\s*)[-+0-9.eE]+", re.MULTILINE)
    if not pattern.search(text):
        raise ValueError(f"No mite.motion_threshold line found in {path}")
    return pattern.sub(lambda match: f"{match.group(1)}{value}", text, count=1)


def save_movement_score(metric: str, params: dict, threshold: float,
                        config_path: Optional[str | Path] = None) -> dict:
    """Write the movement score (metric and its parameters) and the threshold that
    goes with it into the config file, and reload it.

    They are saved together because a threshold only means something on the scale
    of one metric. The parameters of the other metrics are kept. Only the three
    lines concerned are rewritten, so comments and layout survive; the parameters
    are one flow-style line, `metric_params: {topN_variability: {n: 10}}`, added
    under `metric:` if the file has none yet.
    """
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    text = path.read_text(encoding="utf-8")
    threshold = round(float(threshold), 3)
    text = _set_threshold_line(text, threshold, path)

    metric_line = re.compile(r"^([ \t]+)metric:[ \t]*(\"[^\"]*\"|'[^']*'|[^\s#]+)", re.MULTILINE)
    match = metric_line.search(text)
    if not match:
        raise ValueError(f"No mite.metric line found in {path}")
    text = text[:match.start(2)] + f'"{metric}"' + text[match.end(2):]

    mite = (yaml.safe_load(text) or {}).get("mite", {})
    all_params = dict(mite.get("metric_params") or {})
    all_params[metric] = dict(params)
    flow = yaml.safe_dump(all_params, default_flow_style=True, sort_keys=False, width=10_000).strip()

    params_line = re.compile(r"^[ \t]+metric_params:[ \t]*(\{.*\}|[^\s#]*)", re.MULTILINE)
    match = params_line.search(text)
    if match:
        text = text[:match.start(1)] + flow + text[match.end(1):]
    else:
        match = metric_line.search(text)
        end = text.find("\n", match.end())
        end = len(text) if end < 0 else end
        text = text[:end] + f"\n{match.group(1)}metric_params: {flow}" + text[end:]

    path.write_text(text, encoding="utf-8")
    _forget_loaded_config()
    return {"metric": metric, "params": dict(params), "threshold": threshold}
