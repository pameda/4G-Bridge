import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from fourg_bridge.cellular.carrier_query import CarrierUsage
from fourg_bridge.imessage.runner import AppleScriptRunner
from fourg_bridge.models import ATResponse, CleanupProof, RelayStatus
from fourg_bridge.sms.receiver import CleanupResult, SMSReceiver
from fourg_bridge.storage.database import RelayDatabase
from fourg_bridge.storage.identity import IdentityStore
from fourg_bridge.storage.scoped_budget import ScopedCarrierBudget


class Device:
    def __init__(self):
        self.iccid = "8" * 20
        self.imei = "9" * 15
        self.slots = {1: "AABB", 2: "CCDD"}
        self.commands = []
        self.fail = ""

    def transaction(self):
        return nullcontext()

    def transact(self, command, timeout=5):
        self.commands.append(command)
        if command == self.fail:
            return ATResponse((), "ERROR")
        if command == "AT+CPIN?":
            return ATResponse(("+CPIN: READY",), "OK")
        if command == "AT+QCCID":
            return ATResponse((f"+QCCID: {self.iccid}",), "OK")
        if command == "AT+GSN":
            return ATResponse((self.imei,), "OK")
        if command == "AT+CMGL=4":
            return ATResponse(
                tuple(
                    item
                    for index, pdu in self.slots.items()
                    for item in (f"+CMGL: {index},0,,2", pdu)
                ),
                "OK",
            )
        if command.startswith("AT+CMGD="):
            self.slots.pop(int(command.split("=")[1]), None)
        return ATResponse((), "OK")


def proof(receiver, index=1, pdu="AABB"):
    return CleanupProof(
        "ME", index, hashlib.sha256(bytes.fromhex(pdu)).hexdigest(), receiver.read_identity()
    )


@pytest.mark.parametrize("change", ["slot", "sim", "device", "unknown"])
def test_cleanup_never_deletes_reassigned_content(tmp_path, change):
    device = Device()
    receiver = SMSReceiver(device, identity=IdentityStore(tmp_path))
    expected = proof(receiver)
    if change == "slot":
        device.slots[1] = "DDFF"
    elif change == "sim":
        device.iccid = "7" * 20
    elif change == "device":
        device.imei = "6" * 15
    else:
        device.fail = "AT+QCCID"
    assert receiver.delete_verified((expected,)) == CleanupResult.BLOCKED
    assert not any(command.startswith("AT+CMGD") for command in device.commands)


def test_partial_cleanup_retries_verify_remaining_slots(tmp_path):
    device = Device()
    receiver = SMSReceiver(device, identity=IdentityStore(tmp_path))
    proofs = (proof(receiver), proof(receiver, 2, "CCDD"))
    device.fail = "AT+CMGD=2"
    assert receiver.delete_verified(proofs) == CleanupResult.PENDING
    assert 1 not in device.slots
    device.fail = ""
    assert receiver.delete_verified(proofs) == CleanupResult.DELETED
    assert not device.slots


@pytest.mark.parametrize("command", ['AT+CPMS="ME"', "AT+CMGL=4", "AT+CMGD=1"])
def test_at_failure_does_not_claim_cleanup_success(tmp_path, command):
    device = Device()
    receiver = SMSReceiver(device, identity=IdentityStore(tmp_path))
    proofs = (proof(receiver),)
    device.fail = command
    assert receiver.delete_verified(proofs) == CleanupResult.PENDING
    assert 1 in device.slots


def test_scoped_budget_rejects_legacy_and_wrong_sim(tmp_path):
    budget = ScopedCarrierBudget(tmp_path)
    assert budget.status().state == "unknown"
    budget.bind("8" * 20)
    key = budget.key
    now = datetime.now(UTC)
    budget.update_plan(CarrierUsage(1000, 200, now), sim_key="wrong")
    budget.update_plan(CarrierUsage(1000, 200, now - timedelta(hours=1)), sim_key=key)
    assert budget.status().state == "unknown"
    budget.update_plan(CarrierUsage(1000, 200, now), sim_key=key)
    assert budget.status().state == "ready"
    budget.approved = True
    budget.bind("7" * 20)
    assert budget.status().state == "unknown" and not budget.approved
    budget.bind("8" * 20)
    assert budget.status().used == 200 and not budget.approved
    budget.bind(None)
    assert budget.usage() is None
    assert budget.status().state == "unknown"


def test_identity_is_stable_private_and_local(tmp_path):
    first = IdentityStore(tmp_path / "a")
    key = first.sim("8" * 20)
    assert IdentityStore(tmp_path / "a").sim("8" * 20) == key
    assert IdentityStore(tmp_path / "b").sim("8" * 20) != key
    assert first.sim("bad") is None and first.device_sim("8" * 20, "bad") is None
    assert b"88888888" not in (tmp_path / "a/identity.key").read_bytes()


def test_future_database_is_untouched_and_paused(tmp_path):
    path = tmp_path / "relay.sqlite"
    database = RelayDatabase(path)
    database.create_pending("hash", "service", "stamp", ())
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA user_version=999")
    before = path.read_bytes()
    reopened = RelayDatabase(path)
    assert reopened.blocked and path.read_bytes() == before
    with pytest.raises(sqlite3.DatabaseError):
        reopened.create_pending("new", "service", "stamp", ())
    assert reopened.due() == ()


def test_old_database_migrates_without_resend_or_unverified_delete(tmp_path):
    path = tmp_path / "relay.sqlite"
    database = RelayDatabase(path)
    database.create_pending("hash", "service", "stamp", (("ME", 1),))
    database.transition("hash", RelayStatus.CLEANUP_PENDING)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE relay DROP COLUMN cleanup_json")
        db.execute("PRAGMA user_version=1")
    reopened = RelayDatabase(path)
    assert not reopened.blocked
    assert reopened.get("hash").status == RelayStatus.CLEANUP_BLOCKED
    assert list(tmp_path.glob("backups/relay-*/relay.sqlite"))


def test_relay_body_only_in_stdin(tmp_path):
    script = Path("src/fourg_bridge/imessage/resources/relay.applescript")
    body = '中文🙂 "\\\n' * 100
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "ACCEPTED"
        assert AppleScriptRunner(script).run("test@example.invalid", body).accepted
    assert "test@example.invalid" not in str(run.call_args.args)
    assert body not in str(run.call_args.args)
    assert json.loads(run.call_args.kwargs["input"])["body"] == body


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Foundation only")
def test_actual_applescript_stdin_and_private_process_arguments():
    resource = Path("src/fourg_bridge/imessage/resources/relay.applescript")
    source = resource.read_text().split('    tell application id "com.apple.MobileSMS"')[0]
    source += "    delay 0.3\n    return messageText\nend run\n"
    body = '合成隐私检查🙂\n引号"与\\反斜杠'
    target = "synthetic@example.invalid"
    with subprocess.Popen(
        ["/usr/bin/osascript", "-e", source, "send"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"target": target, "body": body}))
        process.stdin.close()
        arguments = subprocess.run(
            ["/bin/ps", "-ww", "-p", str(process.pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert target not in arguments and body not in arguments
        assert process.stdout.read().strip() == body
        assert process.wait(timeout=5) == 0
    # Compile the entire real script, stopping before the Messages tell block executes.
    result = subprocess.run(
        ["/usr/bin/osascript", str(resource), "invalid-operation"],
        input="{}",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0 and "41000" in result.stderr


def test_receiver_poll_binds_proofs_and_rejects_identity_change(tmp_path):
    from fourg_bridge.models import AssembledSMS

    device = Device()
    receiver = SMSReceiver(device, identity=IdentityStore(tmp_path))
    assert receiver.poll()
    message = AssembledSMS("service", datetime.now(UTC), "synthetic", ("AABB",), (("ME", 1),))
    assert receiver.proofs(message)[0].identity == receiver.identity
    with patch.object(receiver, "read_identity", side_effect=("before", "after")):
        assert receiver.poll() == ()
    assert receiver.proofs(message) == ()


def test_legacy_budget_backup_does_not_import_allowance(tmp_path):
    from fourg_bridge.storage.carrier_budget import CarrierBudgetStore

    legacy = CarrierBudgetStore(tmp_path / "carrier-budget.sqlite")
    legacy.update_plan(CarrierUsage(1000, 100, datetime.now(UTC)))
    scoped = ScopedCarrierBudget(tmp_path)
    scoped.bind("8" * 20)
    assert scoped.status().state == "unknown"
    assert list(tmp_path.glob("backups/carrier-budget-*/*.sqlite"))
