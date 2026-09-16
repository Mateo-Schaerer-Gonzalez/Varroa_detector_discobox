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
