import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from fourg_bridge.cellular.carrier_query import CarrierUsage
from fourg_bridge.windows.diagnostics import diagnostic
from fourg_bridge.windows.notifications import NetworkNotifications
from fourg_bridge.windows.platform import Adapter, Inventory
from fourg_bridge.windows.probe import ProbeRunner, _smoke_worker, probe_self_test
from fourg_bridge.windows.runtime import Runtime

MODEM = Adapter(
    "00000000-0000-4000-8000-000000000001",
    11,
    "Test modem",
    r"USB\VID_2C7C&PID_0125\TEST",
    False,
    True,
    False,
    False,
)


class ReliabilityTests(unittest.TestCase):
    def test_notification_burst_is_coalesced(self):
        wake = Mock()
        listener = NetworkNotifications(wake)
        with patch(
            "fourg_bridge.windows.notifications.time.monotonic", side_effect=(0, 0.1, 0.2, 0.3, 0.6)
        ):
            for _ in range(4):
                listener.signal()
            self.assertEqual(wake.call_count, 2)
            listener.close()
            listener.signal()
            self.assertEqual(wake.call_count, 2)

    @patch("fourg_bridge.windows.notifications.dll", side_effect=OSError)
    def test_registration_failure_keeps_polling_available(self, load):
        listener = NetworkNotifications(lambda: None)
        self.assertFalse(listener.start())
        listener.close()

    def test_probe_reaps_stuck_worker(self):
        self.assertTrue(probe_self_test())

    def test_probe_cancellation_and_single_flight(self):
        runner = ProbeRunner()
        self.assertEqual(runner.run((), lambda: True).state, "cancelled")
        runner._lock.acquire()
        try:
            self.assertEqual(runner.run((), lambda: False).state, "error")
        finally:
            runner._lock.release()
        started = time.monotonic()
        result = runner.run(
            ((0, ""),), lambda: time.monotonic() - started > 0.2, worker=_smoke_worker
        )
        self.assertEqual(result.state, "cancelled")
        self.assertLess(time.monotonic() - started, 2.2)

    def test_diagnostics_are_fixed_chinese_not_raw_errors(self):
        self.assertEqual(diagnostic("untrusted private content").code, "probe_error")
        self.assertIn("管理员", diagnostic("permission").action)
        self.assertIn("80%", diagnostic("confirmation").title)

    @patch("fourg_bridge.windows.runtime.native.is_admin", return_value=True)
    @patch("fourg_bridge.windows.runtime.native.interface_counters", return_value=(0, 0))
    @patch("fourg_bridge.windows.runtime.platform.change_adapter")
    def test_quota_cutoff_during_enable_never_becomes_on(self, change, counters, admin):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory))
            runtime._adapter = MODEM
            runtime.sim_verified = runtime.registered = True
            runtime.metric = Mock()
            runtime.budget.update_plan(CarrierUsage(1000, 790, datetime.now().astimezone()))
            actual = replace(
                MODEM, enabled=True, connected=True, ipv4="192.0.2.2", gateway="192.0.2.1"
            )
            control_available = []

            def inventory():
                # Assert another thread can meter while the slow system call runs.
                def sample():
                    with runtime._control_lock:
                        runtime.budget.observe(MODEM.guid, "", 5, 5)
                        control_available.append(True)

                thread = threading.Thread(target=sample)
                thread.start()
                thread.join(0.5)
                return Inventory((actual,))

            with patch("fourg_bridge.windows.runtime.platform.inventory", side_effect=inventory):
                self.assertFalse(runtime._change(True))
            self.assertTrue(control_available)
            self.assertFalse(runtime.data_on)
            self.assertEqual(runtime.budget.status().state, "confirmation")
            self.assertFalse(change.call_args.args[1])

    def test_off_cancels_enable_without_waiting_for_command_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory))
            runtime.preferences.auto_takeover = True
            runtime.command("off")
            self.assertTrue(runtime._cancel_enable.is_set())
            self.assertFalse(runtime.preferences.auto_takeover)
            epoch = runtime._network_epoch
            runtime._network_changed()
            self.assertGreater(runtime._network_epoch, epoch)
            self.assertTrue(runtime._refresh.is_set())
