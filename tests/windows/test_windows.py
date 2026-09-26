"""Portable regression suite; unittest runs on clean Windows without pip installs."""

import ctypes
import importlib.util
import json
import socket
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from fourg_bridge.cellular.carrier_query import CarrierUsage, parse_usage, query_pdu
from fourg_bridge.network.failover import Action
from fourg_bridge.storage.carrier_budget import CarrierBudgetStore
from fourg_bridge.support.presentation import usage_style
from fourg_bridge.windows.app_traffic import Aggregator, DataStats, OwnerRow, TcpRow
from fourg_bridge.windows.metric import MetricLease
from fourg_bridge.windows.native import DCB, IfRow, SerialPort
from fourg_bridge.windows.platform import (
    Adapter,
    Inventory,
    PlatformError,
    adapter_metric,
    change_adapter,
    compatible,
    parse_inventory,
    run_ps,
    wifi_probe,
)
from fourg_bridge.windows.policy import ControllerPolicy
from fourg_bridge.windows.probe import BoundHTTPS, online
from fourg_bridge.windows.runtime import QueryRequest, Runtime
from fourg_bridge.windows.settings import Preferences

GUID = "00000000-0000-4000-8000-000000000001"
PNP = r"USB\VID_2C7C&PID_0125\TEST_DEVICE"
MODEM = Adapter(GUID, 11, "Test modem", PNP, False, True, False, False)
WIFI = Adapter(
    "00000000-0000-4000-8000-000000000002",
    2,
    "Wi-Fi",
    "PCI\\TEST",
    True,
    True,
    True,
    True,
    "192.0.2.2",
    "192.0.2.1",
    True,
)


class UsagePresentationTests(unittest.TestCase):
    def test_warning_boundaries(self):
        for fraction, color, stage in (
            (0, "blue", 0),
            (0.59999, "blue", 0),
            (0.6, "orange", 0),
            (0.74999, "orange", 0),
            (0.75, "red", 0),
            (0.79999, "red", 0),
            (0.8, "red", 1),
            (0.97999, "red", 1),
            (0.98, "red", 2),
            (1.02, "red", 2),
        ):
            with self.subTest(fraction=fraction):
                visual = usage_style(fraction)
                self.assertEqual((visual.color, visual.stage), (color, stage))

    def test_no_rounding_across_protection_boundaries(self):
        self.assertEqual(usage_style(0.79999).percent, "79.9%")
        self.assertEqual(usage_style(0.97999).percent, "97.9%")
        self.assertEqual(usage_style(1.02).percent, "102.0%")

    def test_unknown_is_not_zero_or_authorization(self):
        for fraction in (None, float("nan"), float("inf"), -0.1):
            visual = usage_style(fraction)
            self.assertEqual(visual.percent, "—")
            self.assertIsNone(visual.stage)

    @unittest.skipUnless(importlib.util.find_spec("_tkinter"), "Tk is verified by Windows CI")
    def test_render_does_not_touch_runtime_or_budget(self):
        from fourg_bridge.windows.ui import Window

        window = object.__new__(Window)
        window.runtime = Mock()
        window.ring = Mock()
        window.style = Mock()
        window.palette = dict.fromkeys(
            ("blue", "orange", "red", "secondary", "bg", "track", "card", "muted"), "#123456"
        )
        window.labels = {key: Mock() for key in ("percent", "usage_band")}
        window.stage_cards = [Mock() for _ in range(3)]
        for fraction in (None, 0, 0.75, 0.8, 0.98, 1.1):
            window.render_usage(fraction)
        self.assertEqual(window.runtime.mock_calls, [])
        window.labels["percent"].set.assert_called_with("110.0%  套餐估算已用")


class PlatformTests(unittest.TestCase):
    def test_exact_identity(self):
        for value in (PNP, r"USB\VID_2CA3&PID_4006&MI_02\TEST", "VID_2c7c&PID_0125"):
            self.assertTrue(compatible(value))
        for value in ("Baiwang", "EC25", "VID_2C7C&PID_01250", "VID_9999&PID_0125"):
            self.assertFalse(compatible(value))

    def test_dynamic_interface(self):
        record = {
            "guid": GUID,
            "index": 99,
            "name": "renamed",
            "pnp": PNP,
            "enabled": True,
            "connected": True,
            "ipv4": "192.0.2.3",
        }
        snap = parse_inventory({"adapters": [record], "ports": None, "present": True})
        self.assertEqual(snap.modem().index, 99)
        self.assertTrue(snap.modem().usable)

    def test_malformed_and_multiple(self):
        self.assertIsNone(parse_inventory({"adapters": [{"guid": "bad"}]}).modem())
        self.assertIsNone(Inventory((MODEM, replace(MODEM, guid=WIFI.guid))).modem())

    def test_apipa_not_ready(self):
        self.assertFalse(replace(MODEM, connected=True, ipv4="169.254.1.1").usable)
        self.assertFalse(replace(MODEM, connected=True, ipv4="bad").usable)

    def test_ports_validated(self):
        snap = parse_inventory(
            {
                "ports": [
                    {"port": "COM8", "pnp": PNP},
                    {"port": "COM8;bad", "pnp": PNP},
                    {"port": "COM1", "pnp": "OTHER"},
                ]
            }
        )
        self.assertEqual([p.name for p in snap.ports], ["COM8"])

    def test_no_command_injection(self):
        for function in (change_adapter, adapter_metric):
            with self.assertRaises(ValueError):
                function("';evil;#", True)
        with self.assertRaises(ValueError):
            SerialPort("COM1;evil")

    @patch("fourg_bridge.windows.platform.run_ps")
    def test_mutation_is_scoped(self, runner):
        change_adapter(GUID, False)
        script = runner.call_args.args[0]
        self.assertIn(GUID, script)
        self.assertIn("PNPDeviceID", script)
        self.assertIn("Disable-NetAdapter", script)
        self.assertNotIn("Set-Dns", script)
        self.assertNotIn("Remove-NetRoute", script)

    def test_wifi_disconnected_no_probe(self):
        with patch("fourg_bridge.windows.platform.subprocess.run") as runner:
            self.assertFalse(wifi_probe(replace(WIFI, connected=False)))
            runner.assert_not_called()

    def test_non_windows_fails_without_execution(self):
        with (
            patch("fourg_bridge.windows.platform.sys.platform", "darwin"),
            self.assertRaises(PlatformError),
        ):
            run_ps("anything")

    def test_native_abi(self):
        self.assertEqual(ctypes.sizeof(DCB), 28)
        self.assertEqual(ctypes.sizeof(IfRow), 1352)
        self.assertEqual(IfRow.rx.offset, 1208)
        self.assertEqual(ctypes.sizeof(TcpRow), 20)
        self.assertEqual(ctypes.sizeof(OwnerRow), 24)
        self.assertEqual(ctypes.sizeof(DataStats), 96)


class PolicyTests(unittest.TestCase):
    def decide(self, policy, snap, **kw):
        return policy.decide(
            snap, authorized=True, budget="ready", data_on=False, wifi_online=False, **kw
        ).action

    def test_physical_disconnect_immediate(self):
        self.assertEqual(self.decide(ControllerPolicy(), Inventory((MODEM,))), Action.ENABLE)

    def test_connected_failure_requires_three(self):
        policy = ControllerPolicy()
        snap = Inventory((MODEM, WIFI))
        self.assertEqual(
            [self.decide(policy, snap) for _ in range(3)], [Action.HOLD, Action.HOLD, Action.ENABLE]
        )

    def test_wifi_return_closes_owned_data(self):
        policy = ControllerPolicy()
        policy.failover.completed(Action.ENABLE, True)
        results = [
            policy.decide(
                Inventory((MODEM, WIFI)),
                authorized=True,
                budget="ready",
                data_on=True,
                wifi_online=True,
            ).action
            for _ in range(2)
        ]
        self.assertEqual(results, [Action.HOLD, Action.DISABLE])

    def test_no_spending_without_authority(self):
        result = ControllerPolicy().decide(
            Inventory((MODEM,)), authorized=False, budget="ready", data_on=False, wifi_online=False
        )
        self.assertEqual(result.action, Action.HOLD)

    def test_all_guard_failures_stop(self):
        for state in ("unknown", "stale", "confirmation", "locked"):
            result = ControllerPolicy().decide(
                Inventory((MODEM,)), authorized=True, budget=state, data_on=True, wifi_online=False
            )
            self.assertEqual(result.action, Action.DISABLE)

    def test_other_physical_default_prevents_takeover(self):
        ethernet = replace(WIFI, wifi=False)
        self.assertEqual(self.decide(ControllerPolicy(), Inventory((MODEM, ethernet))), Action.HOLD)

    def test_vpn_not_removed_or_blocked(self):
        vpn = replace(WIFI, physical=False, wifi=False)
        self.assertEqual(self.decide(ControllerPolicy(), Inventory((MODEM, vpn))), Action.ENABLE)

    def test_failure_does_not_reenable_loop(self):
        policy = ControllerPolicy()
        policy.failover.completed(Action.ENABLE, False)
        self.assertEqual(self.decide(policy, Inventory((MODEM,))), Action.HOLD)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_preferences_do_not_restore_data_on(self):
        file = self.path / "settings.json"
        file.write_text(
            '{"auto_takeover": true, "data_on": true, "approved": true}', encoding="utf-8"
        )
        prefs = Preferences.load(file)
        self.assertTrue(prefs.auto_takeover)
        prefs.save(file)
        self.assertNotIn("data_on", file.read_text())
        self.assertNotIn("approved", file.read_text())

    def test_invalid_preferences_fail_closed(self):
        file = self.path / "settings.json"
        for value in ("bad", "[]", '{"auto_takeover": "true"}'):
            file.write_text(value, encoding="utf-8")
            self.assertFalse(Preferences.load(file).auto_takeover)

    def test_percentage_guard_and_restart(self):
        file = self.path / "carrier.sqlite"
        store = CarrierBudgetStore(file)
        now = datetime.now().astimezone()
        store.update_plan(CarrierUsage(10000, 7900, now))
        self.assertEqual(store.status().state, "ready")
        store.observe(GUID, "boot", 0, 0)
        store.observe(GUID, "boot", 100, 0)
        self.assertEqual(store.status().state, "confirmation")
        store.approved = True
        self.assertEqual(store.status().state, "ready")
        self.assertEqual(CarrierBudgetStore(file).status().state, "confirmation")
        store.observe(GUID, "boot", 1900, 0)
        self.assertEqual(CarrierBudgetStore(file).status().state, "locked")

    def test_stale_and_counter_reset(self):
        store = CarrierBudgetStore(self.path / "carrier.sqlite")
        now = datetime.now().astimezone()
        store.update_plan(CarrierUsage(10000, 0, now))
        store.observe(GUID, "boot", 100, 100)
        store.observe(GUID, "boot", 5, 7)
        self.assertEqual(store.status().used, 12)
        self.assertEqual(store.status(now + timedelta(hours=7)).state, "stale")

    @patch(
        "fourg_bridge.windows.metric.adapter_metric", return_value={"metric": 25, "automatic": True}
    )
    def test_metric_lease_survives_restart(self, metric):
        file = self.path / "lease.json"
        MetricLease(file).acquire(GUID)
        self.assertTrue(file.exists())
        MetricLease(file).restore(GUID)
        metric.assert_called_with(GUID, 25, True)
        self.assertFalse(file.exists())

    @patch(
        "fourg_bridge.windows.metric.adapter_metric",
        return_value={"metric": 25, "automatic": False},
    )
    def test_metric_no_overwrite_different_device(self, metric):
        lease = MetricLease(self.path / "lease.json")
        lease.acquire(GUID)
        with self.assertRaises(PlatformError):
            lease.acquire(WIFI.guid)

    def test_query_is_restricted(self):
        with self.assertRaises(ValueError):
            query_pdu("not-a-carrier", "108")
        with self.assertRaises(ValueError):
            query_pdu("10001", "108\rAT")
        self.assertIsNone(
            parse_usage("not-a-carrier", "总量1GB已用0GB", datetime.now().astimezone())
        )

    def test_query_expiry_and_sim_change(self):
        request = QueryRequest("10001", "108", "synthetic-hash", 100)
        self.assertTrue(request.valid("synthetic-hash", 110))
        self.assertFalse(request.valid("other-sim", 110))
        self.assertFalse(request.valid("synthetic-hash", 161))

    def test_unready_sim_rejects_query(self):
        with self.assertRaises(PlatformError):
            Runtime(self.path).query("10001", "108")

    def test_duplicate_query_rejected(self):
        runtime = Runtime(self.path)
        runtime.sim_verified, runtime._sim_key = True, "synthetic-hash"
        runtime.query("10001", "108")
        with self.assertRaises(PlatformError):
            runtime.query("10001", "108")
        self.assertEqual(runtime.sms_commands.qsize(), 1)

    def test_sleep_revokes_consent(self):
        runtime = Runtime(self.path)
        runtime.budget.approved = True
        runtime.command("sleep")
        self.assertFalse(runtime.budget.approved)
        self.assertTrue(runtime._suspended.is_set())

    @patch("fourg_bridge.windows.runtime.platform.inventory", side_effect=OSError)
    @patch("fourg_bridge.windows.runtime.platform.change_adapter")
    @patch("fourg_bridge.windows.runtime.native.is_admin", return_value=True)
    @patch("fourg_bridge.windows.runtime.native.interface_counters", return_value=(0, 0))
    @patch("fourg_bridge.windows.runtime.MetricLease")
    def test_enable_exception_attempts_rollback(self, lease, counters, admin, change, scan):
        runtime = Runtime(self.path)
        runtime._adapter, runtime.sim_verified = MODEM, True
        runtime.budget.update_plan(CarrierUsage(10000, 0, datetime.now().astimezone()))
        self.assertFalse(runtime._change(True))
        self.assertEqual([call.args[1] for call in change.call_args_list], [True, False])
        self.assertTrue(runtime.protection_failed)

    def test_runtime_no_threads_or_actions_on_construct(self):
        runtime = Runtime(self.path)
        self.assertFalse(runtime.data_on)
        self.assertFalse(runtime._net_thread.is_alive())
        self.assertFalse(runtime._sms_thread.is_alive())

    @patch("fourg_bridge.windows.runtime.native.is_admin", return_value=False)
    def test_unprivileged_auto_rejected(self, admin):
        runtime = Runtime(self.path)
        with self.assertRaises(PlatformError):
            runtime.authorize_auto(True)
        self.assertFalse(runtime.preferences.auto_takeover)

    @patch("fourg_bridge.windows.runtime.platform.change_adapter")
    @patch("fourg_bridge.windows.runtime.native.is_admin", return_value=True)
    def test_locked_enable_never_touches_network(self, admin, change):
        runtime = Runtime(self.path)
        runtime._adapter = MODEM
        self.assertFalse(runtime._change(True))
        change.assert_not_called()

    def test_shutdown_missing_device(self):
        runtime = Runtime(self.path)
        self.assertTrue(runtime.shutdown())
        self.assertTrue(runtime._stop.is_set())

    def test_unknown_commands_rejected(self):
        with self.assertRaises(ValueError):
            Runtime(self.path).command("arbitrary command")

    def test_no_sms_body_stored(self):
        runtime = Runtime(self.path)
        runtime.budget.update_plan(CarrierUsage(10000, 100, datetime.now().astimezone()))
        self.assertNotIn("sender", json.dumps(runtime.preferences.__dict__))
        self.assertEqual(
            set(p.name for p in self.path.iterdir()), {"carrier.sqlite", "traffic.sqlite"}
        )


class TrafficTests(unittest.TestCase):
    def test_baseline_rate_and_reset(self):
        tracker = Aggregator()
        self.assertEqual(tracker.sample([(b"a", "App", 100, 100)], 1)[0].total, 0)
        row = tracker.sample([(b"a", "App", 140, 120)], 3)[0]
        self.assertEqual((row.download, row.upload, row.total), (20, 10, 60))
        self.assertEqual(tracker.sample([(b"a", "App", 0, 0)], 4)[0].download, 0)

    def test_pause_not_billed(self):
        tracker = Aggregator()
        tracker.sample([(b"a", "App", 100, 100)], 1)
        self.assertEqual(tracker.sample([(b"a", "App", 1000, 1000)], 20)[0].total, 0)

    def test_closed_and_reused_connections_not_inflated(self):
        tracker = Aggregator()
        tracker.sample([(b"a", "App", 100, 100)], 1)
        tracker.sample([], 2)
        self.assertEqual(tracker.sample([(b"a", "App", 1000, 1000)], 3)[0].total, 0)


class ProbeTests(unittest.TestCase):
    @patch(
        "fourg_bridge.windows.probe.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))],
    )
    @patch("fourg_bridge.windows.probe.socket.socket")
    def test_interface_is_bound_before_connect(self, factory, resolve):
        conn = BoundHTTPS("example.invalid", 12, "192.0.2.2")
        with patch.object(conn.tls_context, "wrap_socket"):
            conn.connect()
        raw = factory.return_value
        raw.setsockopt.assert_called_with(socket.IPPROTO_IP, 31, socket.htonl(12))
        raw.bind.assert_called_with(("192.0.2.2", 0))
        names = [call[0] for call in raw.method_calls]
        self.assertLess(names.index("setsockopt"), names.index("connect"))

    @patch("fourg_bridge.windows.probe.BoundHTTPS")
    def test_captive_portal_not_success(self, factory):
        response = factory.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = b"Login to Wi-Fi"
        self.assertFalse(online(1, "192.0.2.2"))


if __name__ == "__main__":
    unittest.main()
