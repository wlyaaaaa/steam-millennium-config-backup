"""Classify narrowly scoped file exceptions without hiding ordinary I/O failures."""
from pathlib import Path
import os
import subprocess


def defender_removed(path):
    """Return only an exact-path, successful Defender remediation match."""
    if os.name != "nt":
        return False
    env = os.environ.copy()
    env["BACKUP_WARNING_PATH"] = str(Path(path).absolute())
    script = "$p=$env:BACKUP_WARNING_PATH; $ok=$false; Get-MpThreatDetection -ErrorAction Stop | Where-Object {$_.ActionSuccess -and $_.LastThreatStatusChangeTime -ge (Get-Date).AddDays(-7)} | ForEach-Object {foreach($r in $_.Resources){if(($r -replace '^file:_','') -ieq $p){$ok=$true}}}; if($ok){'matched'}"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                env=env, capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.returncode == 0 and result.stdout.strip() == "matched"
    except (OSError, subprocess.TimeoutExpired):
        return False


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
