import classes.app_config as app_config_module
from classes.app_config import AppConfig, get_default_config


class TestYamlCaching:
    def test_repeated_instantiation_reads_file_once(self, monkeypatch):
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

        assert call_count == 1


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
