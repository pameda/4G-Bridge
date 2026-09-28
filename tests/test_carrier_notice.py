"""Fictional usage notices only; no subscriber SMS or identifiers."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest
from test_auto_query import snapshot

from fourg_bridge.app.runtime import ModemRuntime
from fourg_bridge.cellular.carrier_query import parse_allowance, parse_unicom_notice, parse_usage
from fourg_bridge.models import AssembledSMS, RegistrationState
from fourg_bridge.sms.inbox import SMSInbox
from fourg_bridge.storage.carrier_budget import CarrierBudgetStore
from fourg_bridge.storage.identity import IdentityStore

STAMP = datetime(2026, 8, 18, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
BODY = (
    "【流量提醒】尊敬的用户，截至08月17日24时，您当月共享国内通用流量"
    "已用12.345GB，剩余87.655GB；请关注使用情况。【中国联通】"
)


def test_notice_derives_total_without_losing_decimal_precision():
    usage = parse_usage("10010", BODY, STAMP)
    assert usage and usage.total_bytes == 100 * 1024**3
    assert usage.used_bytes == int(Decimal("12.345") * 1024**3)
    assert usage.timestamp == STAMP  # Receipt is not the billing cutoff.
    assert usage.basis == "联通共享通用 · 截至08-18 00:00"
    allowance = parse_allowance("10010", BODY, STAMP)
    assert allowance.remaining_bytes == usage.total_bytes - usage.used_bytes


@pytest.mark.parametrize(
    "body,stamp,sender",
    [
        (BODY, STAMP, "10001"),
        (BODY, STAMP, "1060010010"),
        (BODY, STAMP.replace(tzinfo=None), "10010"),
        (BODY.replace("12.345", "-1"), STAMP, "10010"),
        (BODY.replace("共享国内通用", "定向"), STAMP, "10010"),
        (BODY.replace("24时", "25时"), STAMP, "10010"),
        (BODY.replace("08月17日", "08月19日"), STAMP, "10010"),
        (BODY.replace("08月17日", "08月15日"), STAMP, "10010"),
        (BODY.replace("08月17日", "07月31日"), STAMP, "10010"),
        (BODY.replace("08月17日", "02月30日"), STAMP, "10010"),
        (BODY.replace("【中国联通】", ""), STAMP, "10010"),
        (BODY.replace("【流量提醒】", ""), STAMP, "10010"),
        (BODY.replace("；", "，另有定向流量3GB；"), STAMP, "10010"),
        (BODY.replace("；", "，总量200GB；"), STAMP, "10010"),
        (BODY.replace("12.345GB，剩余87.655GB", "0GB，剩余0GB"), STAMP, "10010"),
        (BODY + BODY, STAMP, "10010"),
    ],
)
def test_ambiguous_old_or_noncarrier_notices_rejected(body, stamp, sender):
    assert parse_unicom_notice(sender, body, stamp) is None


def test_mixed_units_and_nonshared_scope():
    body = BODY.replace("共享", "").replace("12.345GB", "512MB").replace("87.655GB", "1.5GB")
    usage = parse_unicom_notice("10010", body, STAMP)
    assert usage.total_bytes == 2 * 1024**3
    assert "共享" not in usage.basis


def runtime_notice(tmp_path, monkeypatch):
    runtime = ModemRuntime.__new__(ModemRuntime)
    runtime.inbox = SMSInbox()
    current = replace(snapshot(), operator="中国联通")
    key = IdentityStore(tmp_path).sim(current.iccid)
    runtime._database = SimpleNamespace(path=tmp_path / "relay.sqlite", get=lambda _: None)
    runtime._receiver = SimpleNamespace(poll=lambda: (object(),), identity="device", sim_key=key)
    runtime._sms_identity = ("device", key)
    runtime._controller = SimpleNamespace(snapshot=Mock(return_value=current))
    runtime.carrier_usage = None
    runtime._carrier_requested_at = None  # No query was sent.
    now = datetime.now().astimezone()
    # Same-day synthetic cutoff handles any wall clock, including month boundaries.
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    body = BODY.replace("08月17日24时", f"{local:%m月%d日%H}时")
    message = AssembledSMS("10010", now, body, (), ())
    runtime._assembler = SimpleNamespace(add=lambda _: message)
    monkeypatch.setattr("fourg_bridge.app.runtime.decode_pdu", lambda raw: raw)
    return runtime, message


def test_unsolicited_notice_updates_with_relay_off_and_no_sms_send(tmp_path, monkeypatch):
    runtime, message = runtime_notice(tmp_path, monkeypatch)
    runtime.poll_sms(relay_enabled=False)
    assert runtime.carrier_usage.total_bytes == 100 * 1024**3
    assert runtime.carrier_sim_key == runtime._receiver.sim_key
    assert runtime.inbox.snapshot()[0].body == message.body
    assert not runtime.carrier_pending
    assert runtime._accept_carrier_notice(message) is False
    runtime._controller.snapshot.assert_called_once()


@pytest.mark.parametrize("failure", ["sim", "carrier", "roaming", "timeout", "old", "future"])
def test_notice_requires_fresh_current_home_sim(tmp_path, monkeypatch, failure):
    runtime, message = runtime_notice(tmp_path, monkeypatch)
    if failure == "sim":
        runtime._receiver.sim_key = "different"
    elif failure == "carrier":
        runtime._controller.snapshot.return_value = snapshot()
    elif failure == "roaming":
        runtime._controller.snapshot.return_value = replace(
            runtime._controller.snapshot.return_value,
            registration=RegistrationState.REGISTERED_ROAMING,
        )
    elif failure == "timeout":
        runtime._controller.snapshot.side_effect = TimeoutError
    else:
        message = replace(
            message, timestamp=message.timestamp + timedelta(hours=-7 if failure == "old" else 1)
        )
    assert not runtime._accept_carrier_notice(message)
    assert runtime.carrier_usage is None


def test_notice_store_preserves_cutoff_restart_and_newer_balance(tmp_path):
    path = tmp_path / "budget.sqlite"
    usage = parse_unicom_notice("10010", BODY, STAMP)
    store = CarrierBudgetStore(path)
    store.update_plan(usage)
    restored = CarrierBudgetStore(path)
    assert "截至08-18 00:00" in restored.usage().basis
    assert "估算" in restored.usage().basis
    assert restored.status(STAMP + timedelta(hours=7)).state == "stale"
    restored.update_plan(replace(usage, timestamp=STAMP - timedelta(hours=1), used_bytes=0))
    assert restored.usage().used_bytes == usage.used_bytes
    with closing(sqlite3.connect(path)) as db:
        assert BODY not in str(db.execute("SELECT * FROM plan").fetchall())


def test_notice_never_clears_98_percent_lock(tmp_path):
    usage = parse_unicom_notice("10010", BODY, STAMP)
    store = CarrierBudgetStore(tmp_path / "budget.sqlite")
    store.update_plan(replace(usage, used_bytes=99 * 1024**3))
    store.update_plan(
        replace(
            usage,
            total_bytes=200 * 1024**3,
            timestamp=STAMP + timedelta(hours=1),
            reported_at=usage.reported_at + timedelta(hours=1),
        )
    )
    assert store.status(STAMP + timedelta(hours=1)).state == "locked"
    assert store.usage().used_bytes == 99 * 1024**3


def test_late_receipt_with_old_cutoff_does_not_override_newer_report(tmp_path):
    usage = parse_unicom_notice("10010", BODY, STAMP)
    store = CarrierBudgetStore(tmp_path / "budget.sqlite")
    store.update_plan(usage)
    store.update_plan(
        replace(usage, total_bytes=200 * 1024**3, timestamp=STAMP + timedelta(hours=1))
    )
    assert store.usage().total_bytes == usage.total_bytes
    assert store.usage().timestamp == STAMP


def test_verified_notice_can_replace_manual_estimate(tmp_path):
    usage = parse_unicom_notice("10010", BODY, STAMP)
    store = CarrierBudgetStore(tmp_path / "budget.sqlite")
    store.update_plan(
        replace(usage, timestamp=STAMP - timedelta(hours=1), total_bytes=80 * 1024**3),
        manual=True,
    )
    store.update_plan(usage)
    assert not store.is_manual()
    assert store.usage().total_bytes == usage.total_bytes
