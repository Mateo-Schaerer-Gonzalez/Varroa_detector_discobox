import re
import shutil
from dataclasses import dataclass, field, fields
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

# config.yaml is this machine's own and not in git, so an update never changes
# the metric saved from the calibration page. A new copy of the app makes it
# from config.default.yaml, which is in git.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
TEMPLATE_CONFIG_PATH = DEFAULT_CONFIG_PATH.with_name("config.default.yaml")


def _config_file(config_path: Optional[str | Path] = None) -> Path:
    """The config file to read or write: `config_path`, or config.yaml, made
    from config.default.yaml if there is none yet."""
    if config_path is not None:
        return Path(config_path)
    if not DEFAULT_CONFIG_PATH.exists():
        shutil.copyfile(TEMPLATE_CONFIG_PATH, DEFAULT_CONFIG_PATH)
    return DEFAULT_CONFIG_PATH


@lru_cache(maxsize=None)
def _load_yaml_cached(config_path: Path) -> dict:
    """Read and parse a YAML file, caching the result per path so repeated
    AppConfig() instantiations don't hit the filesystem again."""
    with open(config_path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _tuplify(data: dict) -> dict:
    """Convert list values (e.g. YAML color arrays) into tuples."""
    return {key: tuple(value) if isinstance(value, list) else value for key, value in data.items()}


def _known(section, data: dict) -> dict:
    """The entries of `data` that `section` (a dataclass) has a field for.

    config.yaml is this machine's own, so it can hold a key saved by another
    version of the app; such a key is left out instead of stopping the app.
    """
    names = {f.name for f in fields(section)}
    return {key: value for key, value in data.items() if key in names}


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
    metric: str
    moving_color: tuple
    still_color: tuple
    # metric name -> its parameters, e.g. {"topN_variability": {"n": 10}}; a metric
    # or parameter left out uses the default in its Analyzer function.
    metric_params: dict = field(default_factory=dict)
    # metric name -> its movement threshold, on that metric's scale, e.g.
    # {"topN_variability": 14.17}.
    metric_thresholds: dict = field(default_factory=dict)
    # The threshold of a metric missing from metric_thresholds (older config files).
    # After loading it is the threshold of `metric`.
    motion_threshold: Optional[float] = None
    # Take a shaking plate out of the frames before scoring (see
    # classes/plate_stabilizer.py). It works with every metric.
    stabilize_plate: bool = False
    # Put the scores of a finished run on one scale for every mite (see
    # classes/score_normalizer.py): scaled to the run's typical brightness, and
    # each mite's own floor moved to the common one.
    normalize_brightness: bool = False
    normalize_floor: bool = False

    def __post_init__(self):
        self._fallback_threshold = self.motion_threshold
        self.motion_threshold = self.threshold_for(self.metric)

    def params_for(self, metric):
        return dict((self.metric_params or {}).get(metric) or {})

    def threshold_for(self, metric):
        """The movement threshold saved for `metric`."""
        value = (self.metric_thresholds or {}).get(metric, self._fallback_threshold)
        if value is None:
            raise ValueError(f"No threshold for metric {metric!r}: add it to mite.metric_thresholds in config.yaml.")
        return float(value)


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


@dataclass
class LabelReaderConfig:
    # A config.yaml made before the names were read has no label_reader section.
    enabled: bool = False
    model: str = "gemini-flash-lite-latest"


class AppConfig:
    """Loads configuration and exposes strongly-typed style/domain sections."""

    def __init__(self, config_path: Optional[str | Path] = None):
        self.config_path = _config_file(config_path)
        self._raw_config = _load_yaml_cached(self.config_path)

        visual_styles = self._raw_config.get("visual_styles", {})
        self.rect_style = RectStyle(**_known(RectStyle, _tuplify(visual_styles.get("rect", {}))))
        self.text_zone_style = TextZoneStyle(**_known(TextZoneStyle, _tuplify(visual_styles.get("text_zone", {}))))
        self.mite = MiteConfig(**_known(MiteConfig, _tuplify(self._raw_config.get("mite", {}))))
        self.detector = DetectorConfig(**_known(DetectorConfig, self._raw_config.get("detector", {})))
        self.label_reader = LabelReaderConfig(**_known(LabelReaderConfig, self._raw_config.get("label_reader") or {}))
        self.zone_styles = {
            name: TextZoneStyle(**_known(TextZoneStyle, _tuplify(style)))
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
    """Write a new threshold for the metric in use into `mite.metric_thresholds`
    of the config file and reload it.

    Only that one line is rewritten, so the comments and layout of the file are
    kept. Every AppConfig built afterwards, including the shared default one,
    sees the new value.
    """
    path = _config_file(config_path)
    text = path.read_text(encoding="utf-8")

    value = round(float(value), 3)
    metric = (yaml.safe_load(text) or {}).get("mite", {}).get("metric")
    if not metric:
        raise ValueError(f"No mite.metric line found in {path}")
    path.write_text(_set_metric_entry(text, "metric_thresholds", metric, value, path), encoding="utf-8")
    _forget_loaded_config()
    return value


def _forget_loaded_config():
    """Make every AppConfig built from now on read the file again."""
    global _default_config
    _load_yaml_cached.cache_clear()
    _default_config = None


_METRIC_LINE = re.compile(r"^([ \t]+)metric:[ \t]*(\"[^\"]*\"|'[^']*'|[^\s#]+)", re.MULTILINE)


def _set_metric_entry(text, key, metric, value, path):
    """Set `mite.<key>[metric] = value`, keeping the entries of the other metrics.

    `mite.<key>` is one flow-style line, e.g. `metric_thresholds: {variability: 15.6}`,
    added under `metric:` if the file has none yet.
    """
    mite = (yaml.safe_load(text) or {}).get("mite", {})
    entries = dict(mite.get(key) or {})
    entries[metric] = value
    flow = yaml.safe_dump(entries, default_flow_style=True, sort_keys=False, width=10_000).strip()

    line = re.compile(rf"^[ \t]+{key}:[ \t]*(\{{.*\}}|[^\s#]*)", re.MULTILINE)
    match = line.search(text)
    if match:
        return text[:match.start(1)] + flow + text[match.end(1):]
    match = _METRIC_LINE.search(text)
    if not match:
        raise ValueError(f"No mite.metric line found in {path}")
    end = text.find("\n", match.end())
    end = len(text) if end < 0 else end
    return text[:end] + f"\n{match.group(1)}{key}: {flow}" + text[end:]


def save_movement_score(metric: str, params: dict, threshold: float,
                        config_path: Optional[str | Path] = None, stabilize_plate: Optional[bool] = None,
                        normalize_brightness: Optional[bool] = None, normalize_floor: Optional[bool] = None) -> dict:
    """Write the movement score (metric and its parameters) and the threshold that
    goes with it into the config file, and reload it.

    They are saved together because a threshold only means something on the scale
    of one metric. The parameters and thresholds of the other metrics are kept, so
    switching `metric` back later picks up that metric's own threshold. Only the
    lines concerned are rewritten, so comments and layout survive. With
    `stabilize_plate`, `mite.stabilize_plate` is set too: the threshold was
    chosen on scores cut with or without it. Likewise `normalize_brightness` and
    `normalize_floor`, the normalisations the scores went through.
    """
    path = _config_file(config_path)
    text = path.read_text(encoding="utf-8")
    threshold = round(float(threshold), 3)

    match = _METRIC_LINE.search(text)
    if not match:
        raise ValueError(f"No mite.metric line found in {path}")
    text = text[:match.start(2)] + f'"{metric}"' + text[match.end(2):]
    text = _set_metric_entry(text, "metric_params", metric, dict(params), path)
    text = _set_metric_entry(text, "metric_thresholds", metric, threshold, path)
    flags = {"stabilize_plate": stabilize_plate, "normalize_brightness": normalize_brightness,
             "normalize_floor": normalize_floor}
    flags = {key: bool(value) for key, value in flags.items() if value is not None}
    for key, value in flags.items():
        text = _set_flag(text, key, value, path)

    path.write_text(text, encoding="utf-8")
    _forget_loaded_config()
    return {"metric": metric, "params": dict(params), "threshold": threshold, **flags}


def _set_flag(text, key, value, path):
    """Set `mite.<key>` to true or false, added under `metric:` if the file has none yet."""
    flag = "true" if value else "false"
    match = re.search(rf"^[ \t]+{key}:[ \t]*([^\s#]*)", text, re.MULTILINE)
    if match:
        return text[:match.start(1)] + flag + text[match.end(1):]
    match = _METRIC_LINE.search(text)
    if not match:
        raise ValueError(f"No mite.metric line found in {path}")
    end = text.find("\n", match.end())
    end = len(text) if end < 0 else end
    return text[:end] + f"\n{match.group(1)}{key}: {flag}" + text[end:]


_LABEL_READER_SECTION = re.compile(r"^label_reader:[ \t]*(?:#.*)?$", re.MULTILINE)
# The section's own `enabled:` line: only indented or empty lines lie between.
_LABEL_READER_ENABLED = re.compile(
    r"^label_reader:[ \t]*(?:#.*)?\n(?:[ \t]+.*\n|[ \t]*\n)*?[ \t]+enabled:[ \t]*([^\s#]*)", re.MULTILINE)


def save_label_reading(enabled: bool, config_path: Optional[str | Path] = None) -> bool:
    """Write whether the names written beside the plates are read
    (`label_reader.enabled`) into the config file and reload it. Only that line
    is rewritten; a file made before the names were read gets the section."""
    path = _config_file(config_path)
    text = path.read_text(encoding="utf-8")
    flag = "true" if enabled else "false"

    match = _LABEL_READER_ENABLED.search(text)
    section = _LABEL_READER_SECTION.search(text)
    if match:
        text = text[:match.start(1)] + flag + text[match.end(1):]
    elif section:
        text = text[:section.end()] + f"\n  enabled: {flag}" + text[section.end():]
    else:
        text = text.rstrip("\n") + f"\n\nlabel_reader:\n  enabled: {flag}\n"
    path.write_text(text, encoding="utf-8")
    _forget_loaded_config()
    return bool(enabled)
