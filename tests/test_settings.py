import stat

from fourg_bridge.storage.settings import Settings, SettingsStore, mac_carrier_policy


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
    assert SettingsStore(path).load() == Settings(relay_enabled=False)


def test_appearance_migration_and_validation(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    path.write_text('{"relay_enabled": true}')
    assert store.load() == Settings(True)
    store.save(Settings(True, 30, "dark"))
    assert store.load().appearance == "dark"
    path.write_text('{"appearance": "unknown"}')
    assert store.load().appearance == "system"
    path.write_text("[]")
    assert store.load() == Settings(relay_enabled=False)


def test_default_relay_and_manual_disable_survive_restart(tmp_path):
    path = tmp_path / "settings.json"
    assert SettingsStore(path).load().relay_enabled
    path.write_text('{"appearance": "dark"}')
    assert SettingsStore(path).load().relay_enabled
    SettingsStore(path).save(Settings(relay_enabled=False))
    assert not SettingsStore(path).load().relay_enabled
    SettingsStore(path).save(Settings(relay_enabled=True))
    assert SettingsStore(path).load().relay_enabled


def test_invalid_relay_value_does_not_enable(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"relay_enabled": "false"}')
    assert not SettingsStore(path).load().relay_enabled


def test_mac_uses_carrier_plan_without_granting_data_consent():
    settings = mac_carrier_policy(Settings())
    assert settings.carrier_policy_enabled
    assert not settings.auto_data_enabled
    assert settings.data_limit_bytes == 0  # Never invent a carrier total.


def test_legacy_cap_consent_does_not_expand_to_larger_carrier_plan():
    legacy = Settings(
        relay_enabled=False, appearance="dark", auto_data_enabled=True, data_limit_bytes=100
    )
    migrated = mac_carrier_policy(legacy)
    assert migrated.carrier_policy_enabled and not migrated.auto_data_enabled
    assert not migrated.relay_enabled and migrated.appearance == "dark"
    assert migrated.data_limit_bytes == 100  # Retained for rollback, not actively applied.
    assert mac_carrier_policy(migrated) == migrated


def test_existing_carrier_authorization_survives_mac_ui_upgrade():
    settings = Settings(carrier_policy_enabled=True, auto_data_enabled=True)
    assert mac_carrier_policy(settings) is settings
