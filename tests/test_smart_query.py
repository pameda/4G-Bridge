"""Synthetic carriers and quantities only; never submit a real SMS."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_auto_query import fake_app, snapshot

from fourg_bridge.cellular.carrier_query import parse_allowance, parse_usage
from fourg_bridge.cellular.operator_profile import operator_profile
from fourg_bridge.models import RegistrationState
from fourg_bridge.storage.auto_query import AutoQueryLedger
from fourg_bridge.storage.settings import Settings, SettingsStore


@pytest.mark.parametrize(
    "operator,number,command",
    [
        ("中国电信", "10001", "108"),
        ("CHN-CT", "10001", "108"),
        ("46011", "10001", "108"),
        ("中国联通", "10010", "CXTCYL"),
        ("CHN-UNICOM", "10010", "CXTCYL"),
        ("46001", "10010", "CXTCYL"),
        ("中国移动", "10086", "CXLL"),
        ("CMCC", "10086", "CXLL"),
        ("46000", "10086", "CXLL"),
    ],
)
def test_profile_recognizes_three_carriers(operator, number, command):
    result = operator_profile(replace(snapshot(), operator=operator))
    assert result and (result.number, result.command) == (number, command)


@pytest.mark.parametrize(
    "changes",
    [
        {"operator": "unknown"},
        {"operator": "CMCC foreign"},
        {"operator": "310260"},
        {"iccid": None},
        {"descriptor": None},
        {"registration": RegistrationState.REGISTERED_ROAMING},
    ],
)
def test_profile_never_guesses(changes):
    assert operator_profile(replace(snapshot(), **changes)) is None


@pytest.mark.parametrize(
    "sender,body,used",
    [
        ("10086", "国内通用流量共100GB，已用20GB，剩余80GB", 20),
        ("10010", "流量总量100GB，剩余流量80GB", 20),
        ("10010", "套餐内流量共100G，已使用20G", 20),
        ("10001", "总流量100GB，已使用0GB", 0),
    ],
)
def test_complete_general_plan_parsed(sender, body, used):
    now = datetime.now(UTC)
    usage = parse_usage(sender, body, now)
    remaining = parse_allowance(sender, body, now)
    assert usage and usage.total_bytes == 100 * 1024**3
    assert usage.used_bytes == used * 1024**3
    assert remaining and remaining.remaining_bytes == (100 - used) * 1024**3


@pytest.mark.parametrize(
    "body",
    [
        "流量总量100GB，剩余120GB",
        "总流量100GB，已用20GB，剩余90GB",
        "国内通用流量共100GB，剩余80GB，定向流量剩余10GB",
        "流量共100GB，剩余20GB，剩余30GB",
        "剩余流量80GB",
        "总量100GB，剩余80GB",
    ],
)
def test_incomplete_ambiguous_plan_never_grants_data(body):
    assert parse_usage("10086", body, datetime.now(UTC)) is None


def test_refresh_reservation_survives_restart_and_only_reply_unlocks(tmp_path):
    path = tmp_path / "queries.sqlite"
    ledger = AutoQueryLedger(path)
    key = "a" * 64
    assert ledger.claim_refresh(key, 100000)
    assert not AutoQueryLedger(path).claim_refresh(key, 200000)
    ledger.complete_refresh(key, 99999)  # stale message must not acknowledge a query
    assert not ledger.claim_refresh(key, 200000)
    ledger.complete_refresh(key, 100010)
    assert not ledger.claim_refresh(key, 100020)
    assert not ledger.claim_refresh(key, 50000)  # clock rollback
    assert ledger.claim_refresh(key, 118001)


def test_refresh_global_limit_and_new_sim(tmp_path):
    ledger = AutoQueryLedger(tmp_path / "queries.sqlite")
    for i in range(8):
        assert ledger.claim_refresh(f"{i:064x}", 100000)
    assert not ledger.claim_refresh("f" * 64, 100001)
    assert ledger.claim_refresh("f" * 64, 200000)


def test_concurrent_refresh_and_v1_migration(tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import closing

    path = tmp_path / "queries.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE current_sim (id INTEGER PRIMARY KEY, key TEXT)")
        db.execute("CREATE TABLE attempts (key TEXT NOT NULL, stamp REAL NOT NULL)")
        db.execute("INSERT INTO attempts VALUES(?,?)", ("a" * 64, 100000))
        db.execute("PRAGMA user_version=1")
    ledger = AutoQueryLedger(path)
    assert not ledger.claim_refresh("a" * 64, 100001)
    with ThreadPoolExecutor(4) as pool:
        assert sum(pool.map(lambda _: ledger.claim_refresh("b" * 64, 100001), range(12))) == 1


@pytest.mark.parametrize("used,wifi,expected", [(20, False, 1), (20, True, 0), (98, False, 0)])
def test_valid_reply_releases_wifi_failover_gate(tmp_path, monkeypatch, used, wifi, expected):
    from test_auto_data import OneTick

    from fourg_bridge.app.auto_data import AutoDataMonitor
    from fourg_bridge.models import DataState
    from fourg_bridge.network.failover import Action

    app = smart_app(tmp_path, monkeypatch)
    app._settings = replace(app._settings, carrier_policy_enabled=True)
    app._data_epoch = 0
    app.current_snapshot = lambda: replace(snapshot(), data_state=DataState.OFF, interface="en11")
    app.auto_data_request = Mock()
    monkeypatch.setattr(
        "fourg_bridge.app.auto_data.subprocess.run", lambda *a, **kw: SimpleNamespace(stdout="boot")
    )
    worker = AutoDataMonitor(app, None)
    worker.stop = OneTick()
    worker.carrier_budget.bind("8" * 20)
    usage = parse_usage("10001", f"总流量100GB，已用{used}GB", datetime.now(UTC))
    assert usage
    worker.carrier_budget.update_plan(usage, sim_key=worker.carrier_budget.key)
    monkeypatch.setattr(
        "fourg_bridge.app.auto_data.WiFiProbe",
        lambda: SimpleNamespace(
            interface=lambda: "en0",
            disconnected=lambda _: not wifi,
            online=lambda _: wifi,
        ),
    )
    monkeypatch.setattr("fourg_bridge.app.auto_data.ECMDetector.has_vpn", lambda: False)
    monkeypatch.setattr("fourg_bridge.app.auto_data.ECMDetector.default_interface", lambda: "en0")
    worker._probe()
    assert app.auto_data_request.call_count == expected
    if expected:
        app.auto_data_request.assert_called_once_with(Action.ENABLE, 0)


def test_new_mode_never_silently_migrates_legacy_consent(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(auto_query_enabled=True, auto_query_operator="CHN-CT"))
    assert not store.load().auto_query_detect_carrier
    store.save(Settings(auto_query_enabled=True, auto_query_detect_carrier=True))
    assert store.load().auto_query_enabled
    assert store.load().auto_query_detect_carrier


def smart_app(tmp_path, monkeypatch):
    app = fake_app(tmp_path, monkeypatch)
    app._settings = replace(app._settings, auto_query_detect_carrier=True, auto_data_enabled=True)
    app._auto_data.carrier_budget.usage = lambda: None
    app._auto_data.carrier_budget.status = lambda: SimpleNamespace(state="unknown")
    return app


def test_sim_change_selects_new_operator_not_saved_telecom(tmp_path, monkeypatch):
    app = smart_app(tmp_path, monkeypatch)
    app._snapshot = replace(snapshot(), operator="中国联通")
    app._maybe_auto_query(app._snapshot)
    app._runtime.query_carrier.assert_called_once()
    assert app._runtime.query_carrier.call_args.args == ("10010", "CXTCYL")
    assert app._runtime.query_carrier.call_args.kwargs["operator"] == "中国联通"
    app._maybe_auto_query(app._snapshot)
    assert app._runtime.query_carrier.call_count == 1
    app._auto_data.carrier_budget.key = "b" * 64
    app._snapshot = replace(snapshot(), operator="中国移动")
    app._maybe_auto_query(app._snapshot)
    assert app._runtime.query_carrier.call_args.args == ("10086", "CXLL")


def test_refresh_before_six_hour_expiry(tmp_path, monkeypatch):
    app = smart_app(tmp_path, monkeypatch)
    app._auto_data.carrier_budget.status = lambda: SimpleNamespace(state="ready")
    app._auto_data.carrier_budget.usage = lambda: SimpleNamespace(timestamp=datetime.now(UTC))
    app._maybe_auto_query(snapshot())
    app._runtime.query_carrier.assert_not_called()
    app._auto_data.carrier_budget.usage = lambda: SimpleNamespace(
        timestamp=datetime.now(UTC) - timedelta(hours=5, minutes=1)
    )
    app._maybe_auto_query(snapshot())
    app._runtime.query_carrier.assert_called_once()


def test_smart_query_does_not_enable_data_directly_or_override_manual_disable(
    tmp_path, monkeypatch
):
    app = smart_app(tmp_path, monkeypatch)
    app._settings = replace(app._settings, auto_data_enabled=False)
    app._start_data_change = Mock()
    app._maybe_auto_query(snapshot())
    app._start_data_change.assert_not_called()
    assert not app._settings.auto_data_enabled


@pytest.mark.parametrize("kind", ["old_sim", "unsolicited", "wrong_sender"])
def test_reply_cannot_cross_sim_or_query_boundary(tmp_path, monkeypatch, kind):
    from fourg_bridge.app.runtime import ModemRuntime
    from fourg_bridge.models import AssembledSMS
    from fourg_bridge.sms.inbox import SMSInbox

    now = datetime.now(UTC)
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime.inbox = SMSInbox()
    runtime._database = SimpleNamespace(get=lambda key: None)
    runtime._receiver = SimpleNamespace(poll=lambda: (object(),), identity="test", sim_key="new")
    runtime._sms_identity = ("test", "new")
    runtime._carrier_requested_at = None if kind == "unsolicited" else now
    runtime._carrier_query_sim = "old" if kind == "old_sim" else "new"
    runtime._carrier_number = "10001"
    runtime.carrier_usage = None
    message = AssembledSMS(
        "10010" if kind == "wrong_sender" else "10001",
        now,
        "总流量100GB，已使用20GB，剩余流量80GB",
        (),
        (),
    )
    runtime._assembler = SimpleNamespace(add=lambda _: message)
    monkeypatch.setattr("fourg_bridge.app.runtime.decode_pdu", lambda raw: raw)
    runtime.poll_sms(relay_enabled=False)
    assert runtime.carrier_usage is None


def test_pending_reply_restores_without_another_send(tmp_path):
    from fourg_bridge.app.runtime import ModemRuntime

    ledger = AutoQueryLedger(tmp_path / "queries.sqlite")
    key = "a" * 64
    assert ledger.claim_refresh(key, 100000, number="10010", command="CXTCYL")
    assert ledger.pending_refresh(key, 100030) == ("10010", 100000)
    assert ledger.pending_refresh(key, 99999) is None
    assert ledger.pending_refresh(key, 130000) is None
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime._carrier_requested_at = None
    runtime.restore_carrier_query(key, *ledger.pending_refresh(key, 100030))
    assert runtime._carrier_query_sim == key and runtime._carrier_number == "10010"
    assert runtime._carrier_requested_at.timestamp() == 100000
    assert runtime.carrier_pending
    runtime.restore_carrier_query(key, "10001", 100030)
    assert runtime._carrier_number == "10010"
    ledger.record_manual(key, 100100, "10010", "CXTCYL")
    assert ledger.pending_refresh(key, 100110) == ("10010", 100100)
    ledger.complete_refresh(key, 100105)
    assert ledger.pending_refresh(key, 100110) is None


def test_v2_pending_without_destination_is_not_guessed(tmp_path):
    import sqlite3
    from contextlib import closing

    path = tmp_path / "queries.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE current_sim (id INTEGER PRIMARY KEY, key TEXT)")
        db.execute("CREATE TABLE attempts (key TEXT NOT NULL, stamp REAL NOT NULL)")
        db.execute("CREATE TABLE refresh (key TEXT PRIMARY KEY, stamp REAL, resolved INTEGER)")
        db.execute("INSERT INTO refresh VALUES(?,?,0)", ("a" * 64, 100000))
        db.execute("PRAGMA user_version=2")
    ledger = AutoQueryLedger(path)
    assert ledger.pending_refresh("a" * 64, 100010) is None
    assert not ledger.claim_refresh("a" * 64, 200000)


def test_app_redirect_has_explicit_safe_status_and_no_invented_balance():
    from fourg_bridge.cellular.carrier_query import query_response_issue

    body = "请打开运营商APP查询流量：https://example.invalid/synthetic-token"
    assert "只返回 App" in query_response_issue(body)
    assert "synthetic-token" not in query_response_issue(body)
    assert parse_usage("10010", body, datetime.now(UTC)) is None
    assert parse_allowance("10010", body, datetime.now(UTC)) is None
    assert "未包含" in query_response_issue("服务暂不可用")
