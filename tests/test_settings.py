import stat

from fourg_bridge.storage.settings import Settings, SettingsStore


def test_atomic_private_settings(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    assert store.load() == Settings()
    store.save(Settings(True, 30))
    assert store.load() == Settings(True, 30)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_invalid_settings_fall_back(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("broken", encoding="utf-8")
    assert SettingsStore(path).load() == Settings()
