import src.config as config


def test_gui_defaults_round_trip(tmp_path, monkeypatch):
    config_dir = tmp_path / ".judgeai"
    config_file = config_dir / "config.json"
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)

    assert config.get_gui_defaults()["default_runs"] == 3
    config.set_gui_defaults(5, ["lay", "circuit"])
    assert config.get_gui_defaults() == {
        "default_runs": 5,
        "default_paradigms": ["lay", "circuit"],
    }


def test_model_preference_round_trip(tmp_path, monkeypatch):
    config_dir = tmp_path / ".judgeai"
    config_file = config_dir / "config.json"
    monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config, "CONFIG_FILE", config_file)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    config.set_model_preference("openai", "example-model")
    assert config.get_model_preference("openai") == "example-model"
    config.set_model_preference("openai", "")
    assert config.get_model_preference("openai") is None
