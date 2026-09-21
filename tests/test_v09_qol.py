from pathlib import Path

from src import config
from src.storage import LocalDiskBallotStore


def _isolated_config(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")


def test_theme_and_ui_state_persist(monkeypatch, tmp_path):
    _isolated_config(monkeypatch, tmp_path)

    config.set_theme_preference("dark")
    config.set_ui_state(
        recent_search="nuclear",
        recent_format="LD",
        recent_winner="AFF",
        recent_sort="resolution",
        window_geometry=[10, 20, 1100, 760],
        window_maximized=True,
    )

    assert config.get_theme_preference() == "dark"
    state = config.get_ui_state()
    assert state["recent_search"] == "nuclear"
    assert state["recent_format"] == "LD"
    assert state["recent_winner"] == "AFF"
    assert state["recent_sort"] == "resolution"
    assert state["window_geometry"] == [10, 20, 1100, 760]
    assert state["window_maximized"] is True


def test_onboarding_flag_persists(monkeypatch, tmp_path):
    _isolated_config(monkeypatch, tmp_path)
    assert config.is_onboarding_complete() is False
    config.set_onboarding_complete(True)
    assert config.is_onboarding_complete() is True


def test_round_display_name_and_pin_are_exposed_in_history(tmp_path):
    store = LocalDiskBallotStore(tmp_path / "Ballots")
    round_id = "123456.092026.topic.alice"
    store.save_metadata(
        round_id,
        {
            "date": "2026-09-20",
            "format": "LD",
            "resolution": "Test resolution",
            "aff": "Alice",
            "neg": "Bob",
            "display_name": "Practice vs Bob",
            "pinned": True,
        },
    )

    item = store.list_rounds()[0]
    assert item["display_name"] == "Practice vs Bob"
    assert item["pinned"] is True
