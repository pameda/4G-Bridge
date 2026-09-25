from fourg_bridge.cellular.data_control import ModemAttachControl, NetworkSetupControl
from fourg_bridge.models import ATResponse, DataState, TrafficSnapshot
from fourg_bridge.network.data_session import DataSessionManager
from fourg_bridge.network.ecm import (
    ECMDetector,
    parse_hardware_ports,
    parse_ordered_services,
    parse_service_order,
)
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

MIXED_HARDWARE = """Hardware Port: USB 10/100/1000 LAN
Device: en9
Ethernet Address: 10:20:30:40:50:60

Hardware Port: EG25G-QDC507
Device: en11
Ethernet Address: 11:22:33:44:55:77
"""

MIXED_ORDER = """An asterisk (*) denotes that a network service is disabled.
(1) USB 10/100/1000 LAN
(Hardware Port: USB 10/100/1000 LAN, Device: en9)
(2) EG25G-QDC507 2
(Hardware Port: EG25G-QDC507, Device: en11)
"""


def test_interface_renumbering_parsers() -> None:
    ports = parse_hardware_ports(HARDWARE)
    assert ports[1].device == "en9"
    assert parse_service_order(ORDER) == {"en0": "Wi-Fi", "en9": "Baiwang"}
    assert parse_ordered_services(ORDER) == (("Wi-Fi", "Wi-Fi"), ("Baiwang", "Baiwang QDC507"))


def test_detector_and_network_state(monkeypatch) -> None:
    def command(*arguments, allow_failure=False):
        if "-listallhardwareports" in arguments:
            return HARDWARE
        if "-listnetworkserviceorder" in arguments:
            return ORDER
        if "getifaddr" in arguments:
            return "192.168.225.10\n"
        if "getpacket" in arguments:
            return "router_identifier (ip): 192.168.225.1\n"
        if "route" in arguments[0]:
            return "interface: en0\n"
        return "utun4: flags\n\tinet 198.18.0.1\n"

    monkeypatch.setattr(ECMDetector, "_run", command)
    interface = ECMDetector().discover()
    assert interface is not None and interface.device == "en9"
    assert ECMDetector.ipv4("en9") == "192.168.225.10"
    assert ECMDetector.gateway("en9") == "192.168.225.1"
    assert ECMDetector.default_interface() == "en0"
    assert ECMDetector.has_vpn()


def test_detector_prefers_qdc507_over_generic_usb_ethernet(monkeypatch) -> None:
    def command(*arguments, allow_failure=False):
        if "-listallhardwareports" in arguments:
            return MIXED_HARDWARE
        if "-listnetworkserviceorder" in arguments:
            return MIXED_ORDER
        raise AssertionError(arguments)

    monkeypatch.setattr(ECMDetector, "_run", command)
    interface = ECMDetector().discover()
    assert interface is not None
    assert interface.device == "en11"
    assert interface.service == "EG25G-QDC507 2"


def test_disabled_services_do_not_inherit_previous_adapter() -> None:
    output = (
        "(1) Wi-Fi\n(Hardware Port: Wi-Fi, Device: en0)\n"
        "(*) USB LAN\n(Hardware Port: USB LAN, Device: en9)\n"
        "(*) EG25G-QDC507\n(Hardware Port: EG25G-QDC507, Device: en10)\n"
        "(*) EG25G-QDC507 2\n(Hardware Port: EG25G-QDC507, Device: en11)\n"
        "(2) VPN\n(Hardware Port: VPN, Device: )\n"
    )
    assert parse_service_order(output) == {
        "en0": "Wi-Fi",
        "en9": "USB LAN",
        "en10": "EG25G-QDC507",
        "en11": "EG25G-QDC507 2",
    }
    assert [name for name, _ in parse_ordered_services(output)] == [
        "Wi-Fi",
        "USB LAN",
        "EG25G-QDC507",
        "EG25G-QDC507 2",
        "VPN",
    ]


def test_generic_ethernet_never_selected_as_modem(monkeypatch) -> None:
    monkeypatch.setattr(
        ECMDetector,
        "_run",
        lambda *a, **k: MIXED_HARDWARE.split("Hardware Port: EG25G")[0]
        if "-listallhardwareports" in a
        else MIXED_ORDER,
    )
    assert ECMDetector().discover() is None


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


def test_enable_stops_when_wifi_priority_cannot_be_protected() -> None:
    class UnsafeNetwork(Network):
        def ensure_wifi_precedes(self, service):
            return False

    modem = Modem()
    manager = DataSessionManager("Baiwang", UnsafeNetwork(), modem)
    result = manager.set_enabled(True, user_confirmed=True)
    assert result.current == DataState.OFF
    assert modem.attached


def test_failover_uses_cellular_default_then_restores_wifi():
    calls = []

    class FailoverNetwork(Network):
        def ensure_cellular_precedes(self, service):
            calls.append("cellular-first")
            return True

        def verify_cellular_default(self):
            return True

        def ensure_wifi_precedes(self, service):
            calls.append("wifi-first")
            return True

    manager = DataSessionManager("QDC507", FailoverNetwork(), Modem())
    assert manager.set_enabled(True, True, prefer_cellular=True).current == DataState.ON
    assert manager.force_safe_off().protected
    assert calls == ["cellular-first", "wifi-first"]


def test_failed_priority_restoration_does_not_claim_success():
    class FailedRestore(Network):
        def ensure_wifi_precedes(self, service):
            raise TimeoutError

    manager = DataSessionManager("QDC507", FailedRestore(), Modem())
    manager._cellular_priority = True
    result = manager.force_safe_off()
    assert result.protected and "恢复失败" in result.detail


def test_enable_rolls_back_when_wifi_is_not_default() -> None:
    class WrongDefault(Network):
        def ensure_wifi_precedes(self, service):
            return True

        def verify_wifi_default(self):
            return False

    modem = Modem()
    manager = DataSessionManager("Baiwang", WrongDefault(), modem)
    result = manager.set_enabled(True, user_confirmed=True)
    assert result.current == DataState.OFF
    assert result.protected
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


def test_missing_dhcp_rolls_back_and_does_not_report_on() -> None:
    class NoAddress(Network):
        def wait_ready(self):
            return False

    network = NoAddress()
    result = DataSessionManager("QDC507", network, Modem()).set_enabled(True, True)
    assert result.current == DataState.OFF and result.protected
    assert not network.enabled
    assert "IP" in result.detail


def test_data_exception_rolls_back_and_off_fallback_is_honest() -> None:
    class BrokenNetwork(Network):
        def set_enabled(self, service, enabled):
            raise TimeoutError

    class BrokenModem(Modem):
        def set_attached(self, attached):
            raise TimeoutError

    manager = DataSessionManager("QDC507", BrokenNetwork(), BrokenModem())
    result = manager.set_enabled(True, True)
    assert result.current == DataState.PROTECTION_FAILED
    assert not result.protected


def test_wait_ready_rejects_self_assigned_address(monkeypatch) -> None:
    addresses = iter(("169.254.2.3", "192.168.225.20"))
    monkeypatch.setattr(ECMDetector, "ipv4", lambda _: next(addresses))
    monkeypatch.setattr(ECMDetector, "gateway", lambda _: "192.168.225.1")
    monkeypatch.setattr("fourg_bridge.cellular.data_control.time.sleep", lambda _: None)
    assert NetworkSetupControl("en11").wait_ready()
    assert not NetworkSetupControl().wait_ready()
    assert not NetworkSetupControl("en11").wait_ready(timeout=0)


def test_real_macos_dhcp_gateway_format(monkeypatch) -> None:
    monkeypatch.setattr(
        ECMDetector,
        "_run",
        lambda *a, **kw: (
            "router (ip_mult): {192.168.225.1}\n" if "getpacket" in a else "interface: utun4\n"
        ),
    )
    assert ECMDetector.gateway("en11") == "192.168.225.1"


def test_failed_network_read_is_not_misreported_as_disabled(monkeypatch):
    from types import SimpleNamespace

    import pytest

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(OSError):
        NetworkSetupControl().is_enabled("QDC507")


def test_cellular_priority_only_moves_modem(monkeypatch):
    from types import SimpleNamespace

    names = ["Ethernet", "Wi-Fi", "Thunderbolt", "QDC507", "VPN"]
    calls = []

    def run(args, **kw):
        if "-ordernetworkservices" in args:
            names[:] = args[2:]
            calls.append(tuple(names))
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(
            returncode=0,
            stdout="\n".join(
                f"({i}) {name}\n(Hardware Port: {name}, Device: en{i})"
                for i, name in enumerate(names, 1)
            ),
        )

    monkeypatch.setattr("subprocess.run", run)
    control = NetworkSetupControl("en4")
    assert control.ensure_cellular_precedes("QDC507")
    assert names == ["Ethernet", "QDC507", "Wi-Fi", "Thunderbolt", "VPN"]
    assert control.ensure_wifi_precedes("QDC507")
    assert [name for name in names if name != "QDC507"] == [
        "Ethernet",
        "Wi-Fi",
        "Thunderbolt",
        "VPN",
    ]
    assert len(calls) == 2
    monkeypatch.setattr(ECMDetector, "default_interface", lambda: "en4")
    assert control.verify_cellular_default()
    monkeypatch.setattr(ECMDetector, "default_interface", lambda: "en0")
    assert not control.verify_cellular_default()


def test_attached_modem_is_not_reattached() -> None:
    class AT:
        def transact(self, command, timeout):
            assert command == "AT+CGATT?"
            return ATResponse(("+CGATT: 1",), "OK")

    assert ModemAttachControl(AT()).set_attached(True)


def test_networksetup_and_attach_controls(monkeypatch) -> None:
    class Result:
        returncode = 0
        stderr = ""

        def __init__(self, stdout=""):
            self.stdout = stdout

    calls = []
    reordered = False

    def run(arguments, **kwargs):
        nonlocal reordered
        calls.append(arguments)
        if "-listallnetworkservices" in arguments:
            return Result("An asterisk denotes disabled.\nWi-Fi\n*Baiwang\n")
        if "-listnetworkserviceorder" in arguments:
            if reordered:
                return Result(
                    "(1) VPN\n(Hardware Port: VPN, Device: utun4)\n"
                    "(2) Wi-Fi\n(Hardware Port: Wi-Fi, Device: en0)\n"
                    "(3) Baiwang\n(Hardware Port: Baiwang QDC507, Device: en9)\n"
                )
            return Result(
                "(1) Baiwang\n(Hardware Port: Baiwang QDC507, Device: en9)\n"
                "(2) VPN\n(Hardware Port: VPN, Device: utun4)\n"
                "(3) Wi-Fi\n(Hardware Port: Wi-Fi, Device: en0)\n"
            )
        if "-ordernetworkservices" in arguments:
            reordered = True
        if "-listallhardwareports" in arguments:
            return Result(HARDWARE)
        if "getifaddr" in arguments:
            return Result("192.168.1.2\n")
        if arguments[:4] == ["/sbin/route", "-n", "get", "default"]:
            return Result("interface: en0\n")
        return Result()

    monkeypatch.setattr("subprocess.run", run)
    control = NetworkSetupControl()
    assert control.ensure_wifi_precedes("Baiwang")
    assert control.verify_wifi_default()
    assert [
        "/usr/sbin/networksetup",
        "-ordernetworkservices",
        "VPN",
        "Wi-Fi",
        "Baiwang",
    ] in calls
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
