from fourg_bridge.cellular.data_control import ModemAttachControl, NetworkSetupControl
from fourg_bridge.models import ATResponse, DataState, TrafficSnapshot
from fourg_bridge.network.data_session import DataSessionManager
from fourg_bridge.network.ecm import ECMDetector, parse_hardware_ports, parse_service_order
from fourg_bridge.network.traffic import TrafficLedger, TrafficMonitor, parse_netstat_counters

HARDWARE = """Hardware Port: Wi-Fi
Device: en0
Ethernet Address: aa:bb:cc:dd:ee:ff

Hardware Port: Baiwang QDC507
Device: en9
Ethernet Address: 11:22:33:44:55:66
"""

ORDER = """An asterisk (*) denotes that a network service is disabled.
(1) Wi-Fi
(Hardware Port: Wi-Fi, Device: en0)
(2) Baiwang
(Hardware Port: Baiwang QDC507, Device: en9)
"""


def test_interface_renumbering_parsers() -> None:
    ports = parse_hardware_ports(HARDWARE)
    assert ports[1].device == "en9"
    assert parse_service_order(ORDER) == {"en0": "Wi-Fi", "en9": "Baiwang"}


def test_detector_and_network_state(monkeypatch) -> None:
    def command(*arguments, allow_failure=False):
        if "-listallhardwareports" in arguments:
            return HARDWARE
        if "-listnetworkserviceorder" in arguments:
            return ORDER
        if "getifaddr" in arguments:
            return "192.168.225.10\n"
        if "route" in arguments[0]:
            return "interface: en0\n"
        return "utun4: flags\n\tinet 198.18.0.1\n"

    monkeypatch.setattr(ECMDetector, "_run", command)
    interface = ECMDetector().discover()
    assert interface is not None and interface.device == "en9"
    assert ECMDetector.ipv4("en9") == "192.168.225.10"
    assert ECMDetector.default_interface() == "en0"
    assert ECMDetector.has_vpn()


class Network:
    def __init__(self, works=True):
        self.enabled = True
        self.works = works

    def set_enabled(self, service, enabled):
        if self.works:
            self.enabled = enabled
        return self.works

    def is_enabled(self, service):
        return self.enabled


class Modem:
    def __init__(self, works=True):
        self.works = works
        self.attached = True

    def set_attached(self, attached):
        self.attached = attached
        return self.works


def test_data_defaults_off_and_needs_confirmation() -> None:
    manager = DataSessionManager("Baiwang", Network(), Modem())
    assert manager.state == DataState.OFF
    assert manager.set_enabled(True).current == DataState.OFF
    assert manager.set_enabled(True, user_confirmed=True).current == DataState.ON
    assert manager.force_safe_off().current == DataState.OFF


def test_disable_falls_back_to_detach() -> None:
    modem = Modem()
    manager = DataSessionManager("Baiwang", Network(False), modem)
    result = manager.force_safe_off()
    assert result.current == DataState.OFF
    assert not modem.attached


def test_counter_parser_and_reset(monkeypatch) -> None:
    first = (
        "Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
        "en7 1500 <Link#1> aa 1 0 100 1 0 200 0\n"
    )
    second = first.replace("100", "160").replace("200", "260")
    assert parse_netstat_counters(first, "en7") == (100, 200)
    outputs = iter((first, second))

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result(next(outputs)))
    monitor = TrafficMonitor()
    monitor.sample("en7")
    snapshot = monitor.sample("en7")
    assert snapshot.session_rx_bytes == 60
    assert snapshot.session_tx_bytes == 60
    monitor.reset_session()


def test_networksetup_and_attach_controls(monkeypatch) -> None:
    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout=""):
            self.stdout = stdout

    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        if "-listallnetworkservices" in arguments:
            return Result("An asterisk denotes disabled.\nWi-Fi\n*Baiwang\n")
        return Result()

    monkeypatch.setattr("subprocess.run", run)
    control = NetworkSetupControl()
    assert control.set_enabled("Baiwang", False)
    assert not control.is_enabled("Baiwang")

    class AT:
        def transact(self, command, timeout):
            calls.append(command)
            return ATResponse((), "OK")

    assert ModemAttachControl(AT()).set_attached(False)
    assert "AT+CGATT=0" in calls


def test_traffic_ledger_daily_monthly_and_counter_reset(tmp_path) -> None:
    from datetime import datetime

    ledger = TrafficLedger(tmp_path / "traffic.sqlite")
    when = datetime.fromisoformat("2026-09-25T12:00:00+08:00")
    ledger.record(TrafficSnapshot("en9", when, 100, 200))
    usage = ledger.record(TrafficSnapshot("en9", when, 160, 240))
    assert (usage.today_rx, usage.today_tx) == (60, 40)
    assert (usage.month_rx, usage.month_tx) == (60, 40)
    reset = ledger.record(TrafficSnapshot("en9", when, 10, 20))
    assert reset == usage
