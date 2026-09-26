from datetime import UTC, datetime, timedelta

import pytest

from fourg_bridge.cellular.carrier_query import CarrierUsage, parse_usage
from fourg_bridge.storage.carrier_budget import CarrierBudgetStore


def test_itemized_telecom_general_buckets_exclude_voice_and_promotions():
    body = (
        "[上网流量]\n-国内通用流量\n"
        "1.上月结转/测试套餐，业务类型：手机上网国内流量，总量：10G，剩余量：2G；\n"
        "2.测试套餐，业务类型：手机上网国内流量，总量：50G，剩余量：46G；\n"
        "3.通话，业务类型：天翼国内通话时长，包含量：200分钟，剩余量：100分钟。"
        "回复指令订购短期流量包100GB"
    )
    usage = parse_usage("10001", body, datetime.now(UTC))
    assert usage and usage.total_bytes == 60 * 1024**3
    assert usage.used_bytes == 12 * 1024**3
    assert "结转" in usage.basis
    assert parse_usage("10086", body, datetime.now(UTC)) is None


@pytest.mark.parametrize(
    "used,state",
    [(79, "ready"), (80, "confirmation"), (97, "confirmation"), (98, "locked"), (100, "locked")],
)
def test_exact_thresholds(tmp_path, used, state):
    store = CarrierBudgetStore(tmp_path / "carrier.sqlite")
    store.update_plan(CarrierUsage(100, used, datetime.now(UTC)))
    assert store.status().state == state
    store.approved = True
    assert store.status().state == ("locked" if used >= 98 else "ready")


def test_incremental_both_directions_and_restart_lock(tmp_path):
    path = tmp_path / "carrier.sqlite"
    store = CarrierBudgetStore(path)
    now = datetime.now(UTC)
    store.update_plan(CarrierUsage(1000, 790, now))
    store.observe("en1", "boot", 1000, 2000)
    store.observe("en1", "boot", 1005, 2005)
    assert store.status().state == "confirmation"
    store.approved = True
    assert store.status().state == "ready"
    assert CarrierBudgetStore(path).status().state == "confirmation"
    store.observe("en1", "boot", 1100, 2090)
    assert store.status().state == "locked"
    assert CarrierBudgetStore(path).status().state == "locked"
    store.update_plan(CarrierUsage(2000, 10, now + timedelta(seconds=1)))
    assert store.status().state == "locked"  # Same-month larger total does not bypass latch.


def test_missing_stale_clock_and_new_month(tmp_path):
    store = CarrierBudgetStore(tmp_path / "carrier.sqlite")
    assert store.status().state == "unknown"
    now = datetime(2026, 9, 30, 10, tzinfo=UTC)
    store.update_plan(CarrierUsage(1000, 100, now))
    assert store.status(now + timedelta(hours=7)).state == "stale"
    assert store.status(now - timedelta(seconds=1)).state == "stale"
    store.update_plan(CarrierUsage(1000, 980, now + timedelta(seconds=1)))
    assert store.status(now).state == "locked"
    new = datetime(2026, 10, 1, tzinfo=UTC)
    store.update_plan(CarrierUsage(1000, 1, new))
    assert store.status(new).state == "ready"


def test_old_reply_cannot_rollback_or_reset_counter(tmp_path):
    store = CarrierBudgetStore(tmp_path / "carrier.sqlite")
    now = datetime.now(UTC)
    usage = CarrierUsage(1000, 100, now)
    store.update_plan(usage)
    store.observe("en1", "boot", 100, 100)
    store.observe("en1", "boot", 50, 50)
    store.update_plan(usage)
    assert store.status().used == 200
    store.update_plan(CarrierUsage(1000, 10, now + timedelta(seconds=1)))
    assert store.status(now + timedelta(seconds=2)).used == 200
    assert store.usage().used_bytes == 200
    with pytest.raises(ValueError):
        store.observe("en1", "boot", -1, 0)
