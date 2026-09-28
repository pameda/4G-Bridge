from datetime import datetime, timedelta
from types import SimpleNamespace

from test_smart_query import smart_app

from fourg_bridge.models import TrafficSnapshot
from fourg_bridge.network.traffic import TrafficLedger
from fourg_bridge.storage.auto_query import AutoQueryLedger


def test_unresolved_query_gets_one_new_month_attempt(tmp_path):
    ledger = AutoQueryLedger(tmp_path / "queries.sqlite")
    old = datetime(2026, 9, 29, 12).timestamp()
    new = datetime(2026, 10, 1, 12).timestamp()
    key = "a" * 64
    assert ledger.claim_refresh(key, old, number="10010", command="CXTCYL")
    assert not ledger.claim_refresh(key, old + 86400, number="10010", command="CXTCYL")
    assert ledger.claim_refresh(key, new, number="10010", command="CXTCYL")
    assert not AutoQueryLedger(ledger.path).claim_refresh(key, new + 86400)
    assert not ledger.claim_refresh(key, old)  # Clock reversal cannot grant another attempt.


def test_monthly_views_preserve_history_and_start_zero(tmp_path):
    path = tmp_path / "traffic.sqlite"
    ledger = TrafficLedger(path)
    old = datetime(2026, 9, 30, 23, 59, 40).astimezone()

    def sample(when, rx, tx):
        return TrafficSnapshot("en11", when, rx, tx)

    ledger.record(sample(old, 10, 20))
    ledger.record(sample(old + timedelta(seconds=5), 110, 70))
    new = datetime(2026, 10, 1).astimezone()
    assert ledger.usage(new).month_rx == 0
    ledger.record(sample(new, 120, 75))
    assert ledger.months(new) == (("2026-10", 10, 5), ("2026-09", 100, 50))
    assert TrafficLedger(path).months(new) == ledger.months(new)
    assert ledger.months(datetime(2026, 11, 1).astimezone())[0] == ("2026-11", 0, 0)


def test_manual_plan_refreshes_only_after_calendar_month_changes(tmp_path, monkeypatch):
    app = smart_app(tmp_path, monkeypatch)
    budget = app._auto_data.carrier_budget
    budget.is_manual = lambda: True
    now = datetime.now().astimezone()
    stamp = now
    budget.usage = lambda: SimpleNamespace(timestamp=stamp)
    app._maybe_auto_query(app._snapshot)
    app._runtime.query_carrier.assert_not_called()
    stamp = now.replace(day=1) - timedelta(days=1)
    app._maybe_auto_query(app._snapshot)
    app._runtime.query_carrier.assert_called_once()
    app._maybe_auto_query(app._snapshot)
    assert app._runtime.query_carrier.call_count == 1
