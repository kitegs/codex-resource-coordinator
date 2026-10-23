"""Explicit, audited recovery of contained work interrupted by a verified reboot.

Never opens/terminates another job or starts the payload. Missing OS evidence is
blocking, not permission to infer a reboot from a changed clock or missing PID.
"""
import base64
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from .store import CoordinationError, _text
from .windows_job import scope


def machine_fingerprint():
    if os.name != "nt":
        raise CoordinationError("Verified reboot recovery requires Windows")
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        value = winreg.QueryValueEx(key, "MachineGuid")[0]
    if not isinstance(value, str) or not value.strip():
        raise CoordinationError("Machine identity unavailable; retain resources")
    return hashlib.sha256(value.strip().casefold().encode()).hexdigest()


# Fixed read-only query: no peer strings, paths, commands or credentials are
# interpolated. Explicit System32 executable, no profile, no policy bypass.
BOOT_QUERY = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$os = Get-CimInstance Win32_OperatingSystem
$events = @(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Kernel-General';Id=12} -MaxEvents 128 | ForEach-Object {
    [xml]$xml = $_.ToXml()
    $start = @($xml.Event.EventData.Data | Where-Object {$_.Name -eq 'StartTime'})
    if ($start.Count -ne 1) { throw 'Missing structured OS start time' }
    @{start_utc=[string]$start[0].'#text';record_id=$_.RecordId.ToString()}
})
@{machine=$os.CSName;os_boot_utc=$os.LastBootUpTime.ToUniversalTime().ToString('o');events=$events} | ConvertTo-Json -Depth 5 -Compress
"""


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Naive OS timestamp")
        return parsed.timestamp()
    except (TypeError, ValueError, AttributeError) as error:
        raise CoordinationError("Invalid OS reboot timestamp; retain resources") from error


def collect_boot_evidence():
    """CIM boot time plus structured Kernel-General/12 records, not message text."""
    current = scope()
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not executable.is_absolute() or not executable.is_file():
        raise CoordinationError("Windows boot evidence reader unavailable")
    encoded = base64.b64encode(BOOT_QUERY.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run([str(executable), "-NoLogo", "-NoProfile", "-NonInteractive",
                                 "-EncodedCommand", encoded], capture_output=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or len(result.stdout) > 131072:
            raise ValueError("OS evidence query failed")
        raw = json.loads(result.stdout.decode("utf-8-sig"))
        events = [{"start": _stamp(e["start_utc"]), "start_utc": e["start_utc"],
                   "record_id": str(int(e["record_id"]))} for e in raw["events"]]
        if not 1 <= len(events) <= 128 or raw["machine"].casefold() != current["machine"]:
            raise ValueError("OS evidence host mismatch")
        return {"scope": current, "machine_hash": machine_fingerprint(),
                "os_boot": _stamp(raw["os_boot_utc"]), "events": events}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
        raise CoordinationError("Cannot verify Windows boot history; retain resources") from error


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate(store, request, operation, host, evidence):
    saved = json.loads(operation["scope"])
    current = evidence["scope"]
    if saved.get("machine") != current.get("machine"):
        raise CoordinationError("Different machine; retain resources")
    if host is not None and host["machine_hash"] != evidence["machine_hash"]:
        raise CoordinationError("Machine fingerprint differs; retain resources")
    previous, boot = saved.get("boot"), evidence["os_boot"]
    if not _number(previous) or not _number(boot) or not _number(current.get("boot")):
        raise CoordinationError("Invalid boot identity; retain resources")
    if abs(current["boot"] - boot) > 2:
        raise CoordinationError("Clock/OS boot evidence disagrees; retain resources")
    if boot - previous <= 2:
        raise CoordinationError("No strictly later kernel boot; retain resources")
    old_events = [e for e in evidence["events"] if abs(e["start"] - previous) <= 2]
    new_events = [e for e in evidence["events"] if abs(e["start"] - boot) <= 2]
    if len(old_events) != 1 or len(new_events) != 1:
        raise CoordinationError("Both old and current OS boot records are required; retain resources")
    old, new = old_events[0], new_events[0]
    if int(new["record_id"]) <= int(old["record_id"]):
        raise CoordinationError("Boot event ordering is unverifiable; retain resources")
    stamps = [request["created"], operation["created"], operation["updated"]]
    for field in ("monitor", "root"):
        item = json.loads(operation[field]) if operation[field] else None
        if item is not None:
            stamps.append(item.get("created"))
            if store.process_probe(item) != "gone":
                raise CoordinationError("Recorded process alive or unverifiable; retain resources")
    if any(not _number(t) or t < previous - 2 or t >= boot - 2 for t in stamps):
        raise CoordinationError("Operation is not wholly before the verified reboot; retain resources")
    return {"kind": "verified_windows_reboot", "old_boot": old, "current_boot": new,
            "machine_hash": evidence["machine_hash"], "previous_scope": saved,
            "current_scope": current, "legacy_host_binding": host is None,
            "process_identities_verified_gone": True}


def recover_after_reboot(store, request_id, owner, *, confirmed_reboot=False,
                         confirmed_same_machine=False, note="", check_only=False):
    if not check_only:
        if confirmed_reboot is not True or confirmed_same_machine is not True:
            raise CoordinationError("Explicit reboot and same-machine confirmations are required")
        _text(note, "reboot recovery note", 500)
    with store.connection() as db:
        request = dict(store._row(db, request_id))
        store._owned(request, owner)
        row = db.execute("SELECT * FROM managed_operations WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise CoordinationError("Legacy/unmanaged request: use its original reconciliation workflow")
        operation = dict(row)
        if operation["phase"] == "finished" or request["state"] not in ("leased", "running", "suspect"):
            raise CoordinationError("Operation no longer active; nothing released")
        host = db.execute("SELECT * FROM managed_operation_hosts WHERE request_id=?", (request_id,)).fetchone()
    evidence = collect_boot_evidence()
    proof = _validate(store, request, operation, host, evidence)
    if check_only:
        return {"id": request_id, "eligible": True, "check_only": True,
                "resources_released": False, "command_started": False, "proof": proof,
                "requires_explicit_confirmations": True}
    with store.connection(write=True) as db:
        latest_request = store._row(db, request_id)
        store._owned(latest_request, owner)
        latest = db.execute("SELECT * FROM managed_operations WHERE request_id=?", (request_id,)).fetchone()
        if latest is None or dict(latest) != operation or dict(latest_request) != request:
            raise CoordinationError("Operation changed during verification; nothing released")
        current = scope()
        if current != evidence["scope"] or machine_fingerprint() != evidence["machine_hash"]:
            raise CoordinationError("Host scope changed during verification; nothing released")
        _validate(store, latest_request, latest, host, evidence)
        proof.update({"owner": owner, "note": note, "recovered_at": store.clock(),
                      "result": "unknown", "command_restarted": False})
        db.execute("INSERT INTO managed_reboot_recoveries(request_id,evidence,created) VALUES(?,?,?)",
                   (request_id, json.dumps(proof), store.clock()))
        db.execute("UPDATE managed_operations SET phase='finished',result='unknown',error='interrupted_by_verified_reboot',active_processes=0,updated=? WHERE request_id=?",
                   (store.clock(), request_id))
        db.execute("UPDATE requests SET state='failed',result='managed:unknown:verified_reboot',token_hash=NULL,updated=? WHERE id=?",
                   (store.clock(), request_id))
        store._event(db, request_id, "verified_reboot_reconciled_no_process_termination")
        store._event(db, request_id, "failed")
        from .handoff import Handoffs
        handoff = Handoffs(store).enqueue_after_release(db, latest_request)
        return {**store._public(store._row(db, request_id), db), "release_handoff": handoff,
                "resources_released": True, "command_started": False, "command_restarted": False}
