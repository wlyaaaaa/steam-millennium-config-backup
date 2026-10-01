"""Classify narrowly scoped file exceptions without hiding ordinary I/O failures."""
from pathlib import Path
import os
import subprocess
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar

_attempt_started = ContextVar("replica_defender_since_utc", default=None)


@contextmanager
def defender_attempt():
    token = _attempt_started.set(time.time())
    try:
        yield
    finally:
        _attempt_started.reset(token)


def defender_removed(path):
    """Only this replica attempt's exact-path successful quarantine/removal counts."""
    since = _attempt_started.get()
    if since is None:
        return False
    return removal_record_matches(path, since, defender_records(path, since))


def removal_record_matches(path, since, records):
    expected = os.path.normcase(str(Path(path).absolute()))
    now = time.time()
    for row in records:
        try:
            exact = os.path.normcase(str(Path(row["path"]).absolute())) == expected
            current = since <= float(row["observed_unix"]) <= now
            removed = row["status"] in (3, 4)
        except (KeyError, ValueError, TypeError):
            continue
        if exact and current and removed and row.get("success") is True:
            return True
    return False


def defender_records(path, since):
    if os.name != "nt":
        return []
    env = os.environ.copy()
    env["BACKUP_WARNING_PATH"] = str(Path(path).absolute())
    env["BACKUP_WARNING_SINCE"] = str(since)
    script = "$p=$env:BACKUP_WARNING_PATH; $since=[double]::Parse($env:BACKUP_WARNING_SINCE,[cultureinfo]::InvariantCulture); $rows=@(); Get-MpThreatDetection -ErrorAction Stop | Where-Object {$_.ActionSuccess -and $_.ThreatStatusID -in @(3,4)} | ForEach-Object {$d=$_; $observed=([DateTimeOffset]$d.LastThreatStatusChangeTime).ToUnixTimeMilliseconds()/1000.0; if($observed -ge $since){foreach($r in $d.Resources){if(($r -replace '^file:_','') -ieq $p){$rows+=@{path=$p;success=$true;status=[int]$d.ThreatStatusID;observed_unix=$observed}}}}}; ConvertTo-Json -InputObject $rows -Compress"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                env=env, capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def file_warning(exc, relative_path, stage, *, enumerated=False):
    code = getattr(exc, "winerror", None)
    if code is None:
        value = getattr(exc, "hresult", None)
        if value is not None and (value & 0xFFFF0000) == 0x80070000:
            code = value & 0xFFFF
    if code in (225, 226):
        reason = "antivirus_blocked" if code == 225 else "antivirus_removed"
    elif enumerated and isinstance(exc, FileNotFoundError):
        code, reason = getattr(exc, "errno", 2), "source_disappeared"
    else:
        return None
    return {"relative_path": str(relative_path).replace("\\", "/"),
            "reason": reason, "error_code": code, "stage": stage}
