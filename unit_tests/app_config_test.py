import classes.app_config as app_config_module
from classes.app_config import AppConfig, get_default_config


class TestYamlCaching:
    def test_repeated_instantiation_reads_each_file_once(self, monkeypatch):
        app_config_module._load_yaml_cached.cache_clear()
        call_count = 0
        real_open = open

        def counting_open(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return real_open(*args, **kwargs)

        monkeypatch.setattr("builtins.open", counting_open)

        AppConfig()
        AppConfig()
        AppConfig()

        assert call_count == 2   # the config file and config.default.yaml (the score's parameters), once each


class TestDefaultConfig:
    def test_returns_same_instance(self):
        assert get_default_config() is get_default_config()

    def test_matches_a_fresh_default_instance(self):
        default = get_default_config()
        fresh = AppConfig()
        assert default.mite == fresh.mite
        assert default.text_zone_style == fresh.text_zone_style


class TestUnknownKeys:
    def test_key_saved_by_another_version_is_left_out(self, tmp_path):
        text = app_config_module.TEMPLATE_CONFIG_PATH.read_text(encoding="utf-8")
        text = text.replace("  stabilize_plate:", "  metric_windows: {topN_variability: {window: 5}}\n  stabilize_plate:", 1)
        path = tmp_path / "config.yaml"
        path.write_text(text, encoding="utf-8")

        config = AppConfig(path)

        assert config.mite == AppConfig(app_config_module.TEMPLATE_CONFIG_PATH).mite
        assert not hasattr(config.mite, "metric_windows")


class TestBlobSettings:
    def test_a_machines_older_detector_settings_give_way_to_the_defaults(self, tmp_path):
        text = app_config_module.TEMPLATE_CONFIG_PATH.read_text(encoding="utf-8")
        text = text.replace("  min_inertia_ratio: 0.087", "  min_inertia_ratio: 0.45", 1)
        text = text.replace("  min_repeatability: 3", "", 1)
        path = tmp_path / "config.yaml"
        path.write_text(text, encoding="utf-8")

        config = AppConfig(path)

        assert config.detector == AppConfig(app_config_module.TEMPLATE_CONFIG_PATH).detector
        assert config.detector.min_inertia_ratio == 0.087 and config.detector.min_repeatability == 3
