from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fourg_bridge.models import AssembledSMS, RelayStatus
from fourg_bridge.sms.inbox import SMSInbox


def message(index=0):
    return AssembledSMS(
        "synthetic-sender",
        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        "仅用于测试 📶\n" + "长短信" * 200,
        (f"fixture-{index}",),
        (("ME", index),),
    )


def test_unicode_full_body_and_private_repr():
    inbox = SMSInbox()
    sms = message()
    inbox.add(sms)
    (row,) = inbox.snapshot()
    assert row.body == sms.body
    assert row.sender == sms.sender
    assert sms.body not in repr(row)
    assert sms.sender not in repr(row)
    assert row.status_label == "已接收 · 未转发"


def test_reread_location_change_does_not_duplicate_or_reset_status():
    inbox = SMSInbox()
    sms = message()
    inbox.add(sms)
    (row,) = inbox.snapshot()
    inbox.set_status(row.message_hash, RelayStatus.SENT)
    inbox.add(replace(sms, locations=(("SM", 99),)))
    assert len(inbox.snapshot()) == 1
    assert inbox.snapshot()[0].status == RelayStatus.SENT
    assert row.status is None  # Published immutable snapshots cannot mutate under UI.


def test_reconnect_retains_but_sim_switch_and_restart_clear():
    inbox = SMSInbox()
    inbox.bind(("device", "sim-a"))
    inbox.add(message())
    inbox.bind(("device", "sim-a"))
    assert len(inbox.snapshot()) == 1
    inbox.bind(("device", "sim-b"))
    assert inbox.snapshot() == ()
    assert SMSInbox().snapshot() == ()


def test_bounded_chronological_order_and_unknown_status_update():
    inbox = SMSInbox(capacity=2)
    for index in (2, 0, 1, 0):
        inbox.add(message(index))
    assert [row.timestamp.second for row in inbox.snapshot()] == [2, 1]
    inbox.set_status("missing", RelayStatus.SENT)
    assert len(inbox.snapshot()) == 2
    with pytest.raises(ValueError):
        SMSInbox(0)


@pytest.mark.parametrize("status", list(RelayStatus))
def test_all_statuses_have_honest_chinese_labels(status):
    inbox = SMSInbox()
    inbox.add(message())
    (row,) = inbox.snapshot()
    inbox.set_status(row.message_hash, status)
    text = inbox.snapshot()[0].status_label
    assert text and "已送达" not in text


def test_concurrent_snapshot_and_ingest():
    inbox = SMSInbox(capacity=10)

    def ingest(index):
        inbox.add(message(index))
        return inbox.snapshot()

    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(ingest, range(80)))
    assert all(len(rows) <= 10 for rows in batches)
    assert [row.timestamp for row in inbox.snapshot()] == [
        message(i).timestamp for i in reversed(range(70, 80))
    ]
