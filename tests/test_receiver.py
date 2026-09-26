from fourg_bridge.models import ATResponse
from fourg_bridge.sms.receiver import CleanupResult, SMSReceiver


class Transport:
    def __init__(self):
        self.commands = []
        self.fail_delete = False

    def transact(self, command, timeout=5):
        self.commands.append(command)
        if command == "AT+CMGL=4":
            return ATResponse(("+CMGL: 3,0,,25", "001122AABB", "noise"), "OK")
        if command.startswith("AT+CMGD") and self.fail_delete:
            return ATResponse((), "ERROR")
        return ATResponse((), "OK")


def test_poll_all_stores_and_parse() -> None:
    transport = Transport()
    receiver = SMSReceiver(transport)
    parts = receiver.poll()
    assert [(part.storage, part.index) for part in parts] == [("ME", 3), ("SM", 3)]
    assert transport.commands[0] == "AT+CMGF=0"


def test_delete_stops_on_failure() -> None:
    transport = Transport()
    receiver = SMSReceiver(transport)
    assert receiver.delete_verified(()) == CleanupResult.BLOCKED
    assert transport.commands == []
