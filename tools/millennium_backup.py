"""Millennium configuration snapshots, verified replicas and reversible restores.

Python 3.11+ standard library only. Public bundles contain configuration/metadata,
not executable assets or plugin-private data. No command downloads or runs plugins.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import uuid
from typing import Any, Callable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_file_warnings import file_warning, defender_removed

VERSION = "2.0.1"
SCHEMA = "millennium.snapshot.v2"
MANIFEST = "snapshot-manifest.json"
MANAGED = ("config", "plugins", "themes")
LOCK = ".millennium-backup.lock"
JOURNAL = ".millennium-transaction"
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 4096
PLUGIN_FILES = ("plugin.json", "metadata.json", "install-state.json")
THEME_FILES = ("metadata.json", "skin.json", "theme.json", "options.json", "waifus.json")
IDENTIFIER = re.compile(r"[\w][\w .()-]{0,127}\Z", re.UNICODE)
GENERATION = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}\Z")
SENSITIVE_KEY = re.compile(r"(?:password|passwd|secret|token|apikey|authorization|cookie|proxyauth|proxyusername|steamid64)$", re.I)
SENSITIVE_TEXT = re.compile(r"7656119\d{10}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}|https?://[^\s/@:]+:[^\s/@]+@", re.I)
# Deliberately small schema: new core fields are reported, not silently published.
CORE_FIELDS = {
    "general": {"accentColor": str, "checkForMillenniumUpdates": bool,
        "checkForPluginAndThemeUpdates": bool, "injectCSS": bool, "injectJavascript": bool,
        "millenniumUpdateChannel": str, "onMillenniumUpdate": int,
        "shouldShowThemePluginUpdateNotifications": bool},
    "misc": {"hasShownWelcomeModal": bool},
    "network": {"proxy": str, "proxyPassword": str, "proxyUsername": str},
    "notifications": {"showNotifications": bool, "showPluginNotifications": bool, "showUpdateNotifications": bool},
    "plugins": {"enabledPlugins": list},
    "themes": {"activeTheme": str, "allowedScripts": bool, "allowedStyles": bool,
        "conditions": dict, "themeColors": dict},
}
COVERAGE = {
    "restorable": ["supported core settings", "quick.css"],
    "inventory_only": ["plugin manifests", "theme definitions", "installation metadata"],
    "excluded": ["plugin-private settings", "account caches", "game-library caches", "logs", "executables", "plugin/theme program and media assets"],
    "unknown": ["plugin-private settings are not inspected; recheck in each plugin"],
}


class BackupError(RuntimeError):
    """A bounded, content-free diagnostic suitable for receipts."""


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def generation_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BackupError("duplicate_json_key")
        result[key] = value
    return result


def parse_json(data: bytes, label: str) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs_no_duplicates,
                          parse_constant=lambda _: (_ for _ in ()).throw(BackupError("nonfinite_json")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BackupError(f"invalid_utf8_json:{label}") from exc


def no_links(path: Path) -> Path:
    """Reject reparse/symlink components, including junction aliases and leaf links."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        try:
            s = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(s.st_mode) or getattr(s, "st_file_attributes", 0) & 0x400:
            raise BackupError("linked_path_not_supported")
    return path


def norm(path: Path) -> str:
    return os.path.normcase(str(no_links(path))).casefold()


def overlap(a: Path, b: Path) -> bool:
    a_s, b_s = norm(a).rstrip("\\/"), norm(b).rstrip("\\/")
    return a_s == b_s or a_s.startswith(b_s + os.sep) or b_s.startswith(a_s + os.sep)


def safe_rel(value: str, *, manifest: bool = False) -> str:
    if not isinstance(value, str) or "\\" in value or ":" in value or "\x00" in value:
        raise BackupError("invalid_relative_path")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or str(p) != value:
        raise BackupError("invalid_relative_path")
    if any(part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))} for part in p.parts):
        raise BackupError("reserved_windows_path")
    if manifest and value == MANIFEST:
        return value
    if len(p.parts) == 2 and p.parts[0] == "config" and p.name in ("config.json", "quick.css"):
        return value
    if len(p.parts) == 3 and IDENTIFIER.fullmatch(p.parts[1]) and not p.parts[1].endswith((" ", ".")):
        if p.parts[0] == "plugins" and p.name in PLUGIN_FILES:
            return value
        if p.parts[0] == "themes" and p.name in THEME_FILES:
            return value
    raise BackupError("non_allowlisted_path")


def path_for(root: Path, relative: str, *, manifest: bool = False) -> Path:
    return no_links(root / safe_rel(relative, manifest=manifest))


def read_bytes(path: Path) -> bytes:
    path = no_links(path)
    try:
        return _read_bytes_checked(path)
    except OSError as exc:
        exc.warning_path = path
        raise


def _read_bytes_checked(path: Path) -> bytes:
    with path.open("rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size > MAX_FILE:
            raise BackupError("file_size_limit")
        data = f.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise BackupError("file_size_limit")
    return data


def atomic_write(path: Path, data: bytes) -> None:
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    except OSError as exc:
        exc.warning_path = path
        raise
    finally:
        if temp.exists():
            temp.unlink()


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, encoded(value))


def remove_owned_tree(path: Path) -> None:
    # Never traverse a reparse point introduced into our scratch/history.
    if not path.exists():
        return
    no_links(path)
    for parent, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            no_links(Path(parent) / name)
    shutil.rmtree(path)


@contextlib.contextmanager
def writer_lock(root: Path):
    root = no_links(root)
    root.mkdir(parents=True, exist_ok=True)
    handle = no_links(root / LOCK).open("a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BackupError("writer_busy") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BackupError("writer_busy") from exc
        yield
    finally:
        handle.close()  # OS releases the lock after crashes too. Never unlink the inode.


def check_sensitive(value: Any, label: str = "config", depth: int = 0) -> None:
    if depth > 64:
        raise BackupError("json_depth_limit")
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if SENSITIVE_KEY.search(normalized) and item not in (None, "", False, [], {}):
                raise BackupError(f"sensitive_field:{label}")
            check_sensitive(item, label, depth + 1)
    elif isinstance(value, list):
        for item in value:
            check_sensitive(item, label, depth + 1)
    elif isinstance(value, str) and SENSITIVE_TEXT.search(value):
        raise BackupError(f"sensitive_value:{label}")


def project_core(value: Any) -> tuple[dict, list[str]]:
    if not isinstance(value, dict) or not isinstance(value.get("themes"), dict) or not isinstance(value.get("plugins"), dict):
        raise BackupError("unsupported_core_layout")
    result: dict[str, Any] = {}
    omitted: list[str] = []
    for section, contents in value.items():
        if section not in CORE_FIELDS:
            omitted.append(section)
            continue
        if not isinstance(contents, dict):
            raise BackupError("invalid_core_section_type")
        result[section] = {}
        for key, item in contents.items():
            expected = CORE_FIELDS[section].get(key)
            if expected is None:
                omitted.append(section + "." + key)
                continue
            if type(item) is not expected:
                raise BackupError(f"invalid_core_type:{section}.{key}")
            if section == "network" and item:
                # Public projection must not carry a proxy endpoint/account/credential.
                omitted.append(section + "." + key)
                continue
            check_sensitive({key: item}, "core")
            result[section][key] = item
    enabled = result.get("plugins", {}).get("enabledPlugins")
    active = result.get("themes", {}).get("activeTheme")
    if not isinstance(enabled, list) or any(not isinstance(x, str) or not IDENTIFIER.fullmatch(x) for x in enabled):
        raise BackupError("invalid_enabled_plugins")
    if not isinstance(active, str) or (active and not IDENTIFIER.fullmatch(active)):
        raise BackupError("invalid_active_theme")
    for kind in ("conditions", "themeColors"):
        groups = result.get("themes", {}).get(kind, {})
        for theme, settings in groups.items():
            if not IDENTIFIER.fullmatch(theme) or not isinstance(settings, dict):
                raise BackupError("invalid_theme_settings")
            if any(not isinstance(v, (str, bool, int, float)) for v in settings.values()):
                raise BackupError("unsupported_theme_setting_type")
    return result, sorted(omitted)


def validate_payload(relative: str, data: bytes, *, core_projection: bool = True) -> bytes:
    safe_rel(relative)
    if relative.endswith(".json"):
        value = parse_json(data, relative)
        if not isinstance(value, dict) and not (relative.startswith("themes/") and relative.endswith(("/options.json", "/waifus.json")) and isinstance(value, list)):
            raise BackupError(f"json_object_required:{relative}")
        if relative == "config/config.json" and core_projection:
            value, _ = project_core(value)
        check_sensitive(value, relative)
        return encoded(value)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise BackupError("invalid_css_utf8") from exc
    check_sensitive(text, relative)
    return text.replace("\r\n", "\n").encode("utf-8")


def source_membership(source: Path) -> list[str]:
    members = []
    for group in MANAGED:
        folder = no_links(source / group)
        if not folder.is_dir():
            raise BackupError(f"source_incomplete:{group}")
        if group == "config":
            members.extend(f"config/{name}" for name in ("config.json", "quick.css") if (folder/name).exists())
        else:
            allowed = PLUGIN_FILES if group == "plugins" else THEME_FILES
            for component in folder.iterdir():
                no_links(component)
                if component.is_dir():
                    members.append(group+"/"+component.name+"/")
                    members.extend(f"{group}/{component.name}/{name}" for name in allowed if (component/name).exists())
    return sorted(members)


def read_source(source: Path, *, fallback=None, file_warnings=None) -> tuple[dict[str, bytes], dict]:
    fallback = fallback or {}
    file_warnings = file_warnings if file_warnings is not None else []
    source = no_links(source)
    for directory in MANAGED:
        if not no_links(source / directory).is_dir():
            raise BackupError(f"source_incomplete:{directory}")
    initial_membership = source_membership(source)
    paths = ["config/config.json"]
    if (source / "config/quick.css").exists():
        paths.append("config/quick.css")
    names: dict[str, list[str]] = {}
    for directory, allowed, required in (("plugins", PLUGIN_FILES, "plugin.json"), ("themes", THEME_FILES, "skin.json")):
        names[directory] = []
        for item in sorted((source / directory).iterdir()):
            no_links(item)
            if not item.is_dir():
                continue
            if not IDENTIFIER.fullmatch(item.name) or item.name.endswith((" ", ".")):
                raise BackupError("unsupported_install_directory_name")
            if not (item / required).is_file():
                raise BackupError(f"incomplete_installed_component:{directory}/{item.name}")
            names[directory].append(item.name)
            for filename in allowed:
                relative = f"{directory}/{item.name}/{filename}"
                if (source / relative).exists():
                    paths.append(relative)
    if len(paths) > MAX_FILES:
        raise BackupError("file_count_limit")
    def read_enumerated(rel):
        try:
            return read_bytes(path_for(source, rel))
        except OSError as exc:
            exc.warning_path = source / rel
            exc.enumerated_optional = rel != "config/config.json" and not rel.endswith(("/plugin.json", "/skin.json"))
            warning = file_warning(exc, rel, "source_read", enumerated=exc.enumerated_optional)
            if warning is None or not source.is_dir() or any(not (source / group).is_dir() for group in MANAGED):
                raise
            if rel not in fallback and not exc.enumerated_optional:
                raise
            if warning not in file_warnings:
                file_warnings.append(warning)
            return fallback.get(rel)
    raw = {rel: data for rel in paths if (data := read_enumerated(rel)) is not None}
    if sum(map(len, raw.values())) > MAX_TOTAL:
        raise BackupError("snapshot_size_limit")
    core, omitted = project_core(parse_json(raw["config/config.json"], "core"))
    enabled = core["plugins"]["enabledPlugins"]
    if any(name not in names["plugins"] for name in enabled):
        raise BackupError("enabled_plugin_missing")
    active = core["themes"]["activeTheme"]
    if active and active.lower() != "default" and active not in names["themes"]:
        raise BackupError("active_theme_missing")
    projected = {rel: validate_payload(rel, data) for rel, data in raw.items()}
    # Read again after validation: source mutation or incomplete enumeration is not deletion.
    raw_check: dict[str, bytes] = {}
    for rel in paths:
        data = read_enumerated(rel)
        if data is not None:
            raw_check[rel] = data
    skipped = {w["relative_path"] for w in file_warnings}
    for rel in skipped:
        if rel in raw_check:
            raw[rel] = raw_check[rel]
        else:
            raw.pop(rel, None)
    if raw != raw_check or [p for p in source_membership(source) if p not in skipped] != [p for p in initial_membership if p not in skipped]:
        raise BackupError("source_changed_during_read")
    core, omitted = project_core(parse_json(raw["config/config.json"], "core"))
    projected = {rel: validate_payload(rel, data) for rel, data in raw.items()}
    return projected, {"layout": names, "omitted_core_fields": omitted,
                       "raw_fingerprint": digest(encoded({p: digest(b) for p, b in raw.items()}))}


def managed_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for directory in MANAGED:
        parent = no_links(root / directory)
        if not parent.exists():
            continue
        if not parent.is_dir():
            raise BackupError("managed_directory_not_directory")
        for current, dirs, leaves in os.walk(parent, followlinks=False):
            for name in dirs + leaves:
                no_links(Path(current) / name)
            for name in leaves:
                relative = (Path(current) / name).relative_to(root).as_posix()
                safe_rel(relative)
                files[relative] = read_bytes(root / relative)
                if len(files) > MAX_FILES:
                    raise BackupError("file_count_limit")
    return files


def make_manifest(files: dict[str, bytes], *, generation: str | None = None,
                  versions: dict | None = None, coverage: dict | None = None) -> dict:
    return {"schema": SCHEMA, "tool_version": VERSION,
            "generation": generation or generation_id(), "created_utc": utc(),
            "versions": versions or {}, "coverage": coverage or copy.deepcopy(COVERAGE),
            "files": [{"path": p, "bytes": len(b), "sha256": digest(b),
                       "role": "settings" if p.startswith("config/") else "inventory_only"}
                      for p, b in sorted(files.items())]}


def verify_bundle(root: Path, *, allow_pending: bool = False) -> tuple[dict[str, bytes], dict]:
    root = no_links(root)
    if not allow_pending and (root / JOURNAL).exists():
        raise BackupError("pending_transaction")
    manifest_data = read_bytes(root / MANIFEST)
    manifest = parse_json(manifest_data, MANIFEST)
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA or not GENERATION.fullmatch(str(manifest.get("generation", ""))):
        raise BackupError("unsupported_snapshot_manifest")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise BackupError("invalid_manifest_files")
    files = managed_files(root)
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise BackupError("invalid_manifest_entry")
        p = safe_rel(entry.get("path"))
        if p.casefold() in seen:
            raise BackupError("duplicate_manifest_path")
        seen.add(p.casefold())
        data = files.get(p)
        if data is None and defender_removed(root / p):
            exc = FileNotFoundError(2, "antivirus_removed", str(root / p))
            exc.winerror = 226
            exc.warning_path = root / p
            raise exc
        if data is None or entry.get("bytes") != len(data) or entry.get("sha256") != digest(data):
            raise BackupError(f"snapshot_hash_mismatch:{p}")
        projected = validate_payload(p, data)
        if p == "config/config.json" and parse_json(projected, p) != parse_json(data, p):
            raise BackupError("bundle_contains_nonpublic_core_fields")
    check_sensitive(manifest, "manifest")
    if len(files) != len(entries) or "config/config.json" not in files:
        raise BackupError("snapshot_file_set_mismatch")
    # Detect publication crossing a read. Official readers never accept a mixed bundle.
    if read_bytes(root / MANIFEST) != manifest_data or (not allow_pending and (root / JOURNAL).exists()):
        raise BackupError("snapshot_changed_during_read")
    return files, manifest


def write_bundle(root: Path, files: dict[str, bytes], manifest: dict) -> None:
    if root.exists():
        raise BackupError("bundle_destination_exists")
    staging = no_links(root.with_name(".building-" + root.name))
    if staging.exists():
        # No final bundle was published; bounded scratch may be discarded only after
        # its owner marker and target are proven. Unmarked directories stay untouched.
        marker = parse_json(read_bytes(staging / "building.json"), "building")
        if marker != {"schema": "millennium.building.v1", "destination": norm(root)}:
            raise BackupError("unowned_bundle_staging")
        remove_owned_tree(staging)
    staging.mkdir(parents=True)
    atomic_json(staging / "building.json", {"schema": "millennium.building.v1", "destination": norm(root)})
    try:
        for directory in MANAGED:
            (staging / directory).mkdir()
        for p, b in files.items():
            atomic_write(path_for(staging, p), b)
        atomic_json(staging / MANIFEST, manifest)
        verify_bundle(staging)
        os.replace(staging, root)
        (root / "building.json").unlink()
    except Exception:
        remove_owned_tree(staging)
        raise


def git_health(root: Path) -> None:
    if not (root / ".git").exists():
        return
    try:
        result = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                                capture_output=True, timeout=30,
                                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
                                creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError("git_status_unavailable") from exc
    if result.returncode:
        raise BackupError("git_status_failed")


def current_hash(path: Path) -> str | None:
    return digest(read_bytes(path)) if path.exists() else None


def finalize_restore_record(root: Path, journal: dict) -> None:
    identifier = journal.get("restore_record")
    if identifier is None:
        return
    if journal.get("purpose") != "restore" or not GENERATION.fullmatch(str(identifier)):
        raise BackupError("invalid_restore_transaction_record")
    state = journal.get("final_restore_status")
    if state not in ("complete", "rolled_back", "aborted"):
        raise BackupError("invalid_restore_final_status")
    path = no_links(root / ".millennium-restore-history" / identifier / "rollback.json")
    record = parse_json(read_bytes(path), "rollback")
    if record.get("schema") != "millennium.restore-rollback.v2" or record.get("target") != norm(root):
        raise BackupError("restore_record_binding_mismatch")
    record["status"] = state
    atomic_json(path, record)


def recover_transaction(root: Path, *, rollback_committed: bool = False) -> str:
    journal_root = no_links(root / JOURNAL)
    if not journal_root.exists():
        return "not_needed"
    if not (journal_root / "journal.json").exists() and not list(journal_root.iterdir()):
        journal_root.rmdir()
        return "discarded_empty_preparation"
    journal = parse_json(read_bytes(journal_root / "journal.json"), "transaction")
    if journal.get("schema") != "millennium.transaction.v1" or journal.get("target") != norm(root):
        raise BackupError("transaction_binding_mismatch")
    if journal.get("purpose") == "restore":
        assert_steam_stopped(root)
    if journal.get("status") == "preparing":
        if any(current_hash(path_for(root, e["path"], manifest=True)) != e["before"] for e in journal["entries"]):
            raise BackupError("preparing_transaction_target_changed")
        if journal.get("purpose") == "restore":
            journal["final_restore_status"] = "complete" if journal.get("final_restore_status") == "rolled_back" else "aborted"
            finalize_restore_record(root, journal)
        remove_owned_tree(journal_root)
        return "discarded_preparation"
    if journal.get("status") == "committed" and not rollback_committed:
        for entry in journal["entries"]:
            if current_hash(path_for(root, entry["path"], manifest=True)) != entry["after"]:
                raise BackupError("committed_transaction_changed")
        finalize_restore_record(root, journal)
        remove_owned_tree(journal_root)
        return "finalized"
    # First check ALL paths; never clobber edits made after the interrupted operation.
    for entry in journal["entries"]:
        p = safe_rel(entry["path"], manifest=True)
        live = path_for(root, p, manifest=True)
        current = current_hash(live)
        removed_by_antivirus = current is None and defender_removed(live)
        if current not in (entry["before"], entry["after"]) and not removed_by_antivirus:
            raise BackupError(f"transaction_recovery_conflict:{p}")
        if entry["before"] is not None and current_hash(path_for(journal_root / "before", p, manifest=True)) != entry["before"]:
            raise BackupError("transaction_preimage_corrupt")
    for entry in reversed(journal["entries"]):
        p = entry["path"]
        target = path_for(root, p, manifest=True)
        if entry["before"] is None:
            if target.exists():
                target.unlink()
        else:
            atomic_write(target, read_bytes(path_for(journal_root / "before", p, manifest=True)))
    if journal.get("purpose") == "restore":
        journal["final_restore_status"] = "complete" if journal.get("final_restore_status") == "rolled_back" else "aborted"
        finalize_restore_record(root, journal)
    remove_owned_tree(journal_root)
    return "rolled_back"


def transact(root: Path, writes: dict[str, bytes | None], *, before: dict[str, str | None],
             fault: Callable[[int], None] | None = None, purpose: str = "snapshot",
             restore_record: str | None = None, final_restore_status: str = "complete") -> None:
    """Recoverable multi-file publication, not a claim of filesystem-wide atomicity.

    Call while holding writer_lock(root). Every preimage is durable before changes.
    The callback is an in-process fault-injection seam, never exposed by the CLI.
    """
    if (root / JOURNAL).exists():
        raise BackupError("pending_transaction")
    if set(before) != set(writes):
        raise BackupError("transaction_precondition_missing")
    for p, expected in before.items():
        if current_hash(path_for(root, p, manifest=True)) != expected:
            raise BackupError("destination_changed_before_write")
    journal_root = root / JOURNAL
    journal_root.mkdir()
    entries = [{"path": p, "before": before[p], "after": digest(b) if b is not None else None}
               for p, b in writes.items()]
    journal = {"schema": "millennium.transaction.v1", "target": norm(root), "purpose": purpose,
               "status": "preparing", "entries": entries,
               "restore_record": restore_record, "final_restore_status": final_restore_status}
    atomic_json(journal_root / "journal.json", journal)
    try:
        for p, b in writes.items():
            old = path_for(root, p, manifest=True)
            if before[p] is not None:
                atomic_write(path_for(journal_root / "before", p, manifest=True), read_bytes(old))
            if b is not None:
                atomic_write(path_for(journal_root / "after", p, manifest=True), b)
        journal["status"] = "prepared"
        atomic_json(journal_root / "journal.json", journal)
    except Exception:
        remove_owned_tree(journal_root)  # No target mutation has begun.
        raise
    try:
        for index, entry in enumerate(entries):
            p = entry["path"]
            target = path_for(root, p, manifest=True)
            if current_hash(target) != entry["before"]:
                raise BackupError("destination_changed_during_write")
            if entry["after"] is None:
                if target.exists():
                    target.unlink()
            else:
                atomic_write(target, read_bytes(path_for(journal_root / "after", p, manifest=True)))
            if fault:
                fault(index)
        for entry in entries:
            target = path_for(root, entry["path"], manifest=True)
            observed = current_hash(target)
            if observed is None and entry["after"] is not None and defender_removed(target):
                exc = FileNotFoundError(2, "antivirus_removed", str(target))
                exc.winerror = 226
                exc.warning_path = target
                raise exc
            if observed != entry["after"]:
                raise BackupError("publication_readback_failed")
        journal["status"] = "committed"
        atomic_json(journal_root / "journal.json", journal)
    except Exception:
        recover_transaction(root, rollback_committed=True)
        raise
    finalize_restore_record(root, journal)
    remove_owned_tree(journal_root)


def publish(root: Path, files: dict[str, bytes], manifest: dict,
            before_files: dict[str, bytes], *, fault=None) -> None:
    writes: dict[str, bytes | None] = {p: files.get(p) for p in sorted(set(files) | set(before_files))
                                     if files.get(p) != before_files.get(p)}
    writes[MANIFEST] = encoded(manifest)  # Completion marker always last.
    before = {p: digest(before_files[p]) if p in before_files else None for p in writes if p != MANIFEST}
    before[MANIFEST] = current_hash(root / MANIFEST)
    transact(root, writes, before=before, fault=fault)
    verify_bundle(root)


class SnapshotStore:
    def __init__(self, source: Path, destination: Path, runtime: Path | None = None):
        self.source, self.destination = no_links(source), no_links(destination)
        self.runtime = no_links(runtime or self.destination / "runtime")
        if overlap(self.source, self.destination) or overlap(self.source, self.runtime):
            raise BackupError("source_destination_runtime_overlap")
        # Runtime may be exactly destination/runtime; otherwise it must be disjoint.
        if overlap(self.destination, self.runtime) and norm(self.runtime) != norm(self.destination / "runtime"):
            raise BackupError("unsafe_runtime_location")
        if self.destination == self.destination.parent or self.runtime == self.runtime.parent:
            raise BackupError("volume_root_not_allowed")

    def receipt(self, status: str, **extra) -> dict:
        value = {"schema": "millennium.run.v2", "status": status, "attempt_utc": utc(),
                 "source": str(self.source), "destination": str(self.destination), **extra}
        atomic_json(self.runtime / "last-run.json", value)
        return value

    def snapshot(self, *, adopt_existing: bool = False, keep: int = 4, versions: dict | None = None,
                 fault=None) -> dict:
        return self._snapshot(adopt_existing=adopt_existing, keep=keep, versions=versions, fault=fault)

    def _snapshot(self, *, adopt_existing=False, keep=4, versions=None, fault=None):
        if not 2 <= keep <= 32:
            raise BackupError("retention_must_be_between_2_and_32")
        # Check source BEFORE creating destination/lock/runtime: missing is not empty.
        fallback = {}
        if (self.destination / MANIFEST).is_file() and not (self.destination / JOURNAL).exists():
            try:
                fallback = verify_bundle(self.destination)[0]
            except BackupError:
                pass  # The locked destination validation below still rejects corruption.
        file_warnings = []
        try:
            files, observation = read_source(self.source, fallback=fallback, file_warnings=file_warnings)
        except Exception as exc:
            binding_path = self.runtime / "binding.json"
            if binding_path.exists():
                identity = parse_json(read_bytes(binding_path), "binding")
                if identity.get("source") == norm(self.source) and identity.get("destination") == norm(self.destination):
                    self.receipt("failed", reason=str(exc) if isinstance(exc, BackupError) else type(exc).__name__)
            raise
        with writer_lock(self.destination):
            self.runtime.mkdir(parents=True, exist_ok=True)
            binding = self.runtime / "binding.json"
            identity = {"schema": "millennium.binding.v1", "source": norm(self.source), "destination": norm(self.destination)}
            if binding.exists() and parse_json(read_bytes(binding), "binding") != identity:
                raise BackupError("runtime_bound_to_other_pair")
            atomic_json(binding, identity)
            try:
                recovered = recover_transaction(self.destination)
                git_health(self.destination)
                previous = managed_files(self.destination)
                if (self.destination / MANIFEST).exists():
                    verified, previous_manifest = verify_bundle(self.destination)
                    if verified != previous:
                        raise BackupError("destination_changed_during_read")
                elif previous:
                    if not adopt_existing:
                        raise BackupError("legacy_snapshot_requires_explicit_adoption")
                    for p, b in previous.items():
                        projected = validate_payload(p, b)
                        if p == "config/config.json" and parse_json(projected, p) != parse_json(b, p):
                            raise BackupError("legacy_contains_nonpublic_core_fields")
                    previous_manifest = make_manifest(previous, coverage={**COVERAGE, "legacy_adopted": True})
                    old_bundle = self.runtime / "snapshots" / previous_manifest["generation"]
                    write_bundle(old_bundle, previous, previous_manifest)
                    publish(self.destination, previous, previous_manifest, previous)
                else:
                    previous_manifest = None
                if previous_manifest:
                    old_bundle = self.runtime / "snapshots" / previous_manifest["generation"]
                    if not old_bundle.exists():
                        write_bundle(old_bundle, previous, previous_manifest)
                files_check, check = read_source(self.source, fallback=fallback, file_warnings=file_warnings)
                if files_check != files or check != observation:
                    raise BackupError("source_changed_during_collection")
                # No clock throttle. Even no-change verifies actual files and source.
                if (previous_manifest and files == previous and previous_manifest.get("versions", {}) == (versions or {})
                        and previous_manifest.get("coverage", {}).get("omitted_core_fields", []) == observation["omitted_core_fields"]):
                    bundle = self.runtime / "snapshots" / previous_manifest["generation"]
                    if not bundle.exists():
                        write_bundle(bundle, previous, previous_manifest)
                    else:
                        verify_bundle(bundle)
                    manifest = previous_manifest
                    outcome = "unchanged"
                else:
                    coverage = {**copy.deepcopy(COVERAGE), "omitted_core_fields": observation["omitted_core_fields"]}
                    manifest = make_manifest(files, versions=versions, coverage=coverage)
                    bundle = self.runtime / "snapshots" / manifest["generation"]
                    write_bundle(bundle, files, manifest)
                    publish(self.destination, files, manifest, previous, fault=fault)
                    outcome = "complete"
                pointer = {"schema": "millennium.current.v2", "generation": manifest["generation"],
                           "manifest_sha256": digest(read_bytes(bundle / MANIFEST)), "verified_utc": utc()}
                atomic_json(self.runtime / "current.json", pointer)
                # Compatibility projection for old human/owner references, now hash-bound.
                atomic_json(self.runtime / "snapshot-state.json", {"schema": "millennium.snapshot-state.v2",
                    "lastSnapshotUtc": pointer["verified_utc"], "sourceRoot": str(self.source),
                    "destinationRoot": str(self.destination), "copiedFiles": len(files),
                    "generation": manifest["generation"], "manifest_sha256": pointer["manifest_sha256"]})
                self.prune(keep, manifest["generation"])
                skipped = {w["relative_path"] for w in file_warnings}
                return self.receipt("complete" if file_warnings else outcome,
                                    generation=manifest["generation"], verified_files=len(files),
                                    recovered=recovered, omitted_core_fields=observation["omitted_core_fields"],
                                    file_warnings=file_warnings, current_data_copied=not bool(file_warnings),
                                    updated_files=[p for p in files if p not in skipped],
                                    verification_scope="current_files_with_previous_same_path_fallback" if file_warnings else "complete_current_generation")
            except Exception as exc:
                self.receipt("failed", reason=str(exc) if isinstance(exc, BackupError) else type(exc).__name__)
                raise

    def prune(self, keep: int, current: str) -> None:
        history = self.runtime / "snapshots"
        items = sorted((p for p in history.iterdir() if GENERATION.fullmatch(p.name) and p.is_dir()),
                       key=lambda p: p.stat().st_mtime_ns, reverse=True) if history.exists() else []
        survivors = {current} | {p.name for p in [x for x in items if x.name != current][:keep - 1]}
        for item in items:
            if item.name not in survivors:
                verify_bundle(item)
                remove_owned_tree(item)

    def status(self) -> dict:
        # Strict zero-write: not even mkdir/lock/receipt updates.
        value = {"schema": "millennium.status.v2", "write_mode": "zero_write", "status": "healthy"}
        try:
            files, manifest = verify_bundle(self.destination)
            source_files, observation = read_source(self.source)
            changes = [{"path": p, "change": "added" if p not in files else "deleted" if p not in source_files else "modified"}
                       for p in sorted(set(files) | set(source_files)) if files.get(p) != source_files.get(p)]
            value.update(generation=manifest["generation"], verified_files=len(files), changes=changes,
                         coverage=manifest["coverage"], omitted_core_fields=observation["omitted_core_fields"])
            if changes:
                value["status"] = "source_changed"
        except (BackupError, OSError) as exc:
            value.update(status="needs_attention", reason=str(exc) if isinstance(exc, BackupError) else type(exc).__name__)
        binding_path = self.runtime / "binding.json"
        if binding_path.exists():
            binding = parse_json(read_bytes(binding_path), "binding")
            if binding.get("source") != norm(self.source) or binding.get("destination") != norm(self.destination):
                value.update(status="needs_attention", reason="runtime_binding_mismatch")
                return value
        if (self.runtime / "last-run.json").exists():
            value["last_run"] = parse_json(read_bytes(self.runtime / "last-run.json"), "last-run")
            if value["last_run"].get("status") == "failed":
                value["status"] = "needs_attention"
        state_path = self.runtime / "snapshot-state.json"
        if state_path.exists():
            state = parse_json(read_bytes(state_path), "snapshot-state")
            if state.get("schema") == "millennium.snapshot-state.v2" and (state.get("generation") != value.get("generation") or state.get("manifest_sha256") != current_hash(self.destination / MANIFEST)):
                value.update(status="needs_attention", reason="state_manifest_mismatch")
            last = dt.datetime.fromisoformat(state["lastSnapshotUtc"].replace("Z", "+00:00"))
            age = (dt.datetime.now(dt.timezone.utc) - last).total_seconds() / 3600
            value["last_success_utc"] = state["lastSnapshotUtc"]
            value["age_hours"] = round(age, 2)
            if age < -1 or age > 216:
                value["status"] = "needs_attention"
                value["freshness"] = "clock_anomaly" if age < -1 else "stale"
        if (self.runtime / "replica-last.json").exists():
            value["replica"] = parse_json(read_bytes(self.runtime / "replica-last.json"), "replica")
        return value


def replicate(bundle_root: Path, target: Path, runtime: Path | None = None) -> dict:
    try:
        return _replicate(bundle_root, target, runtime)
    except OSError as exc:
        path = getattr(exc, "warning_path", None)
        if path is None:
            raise
        root = target if Path(path).is_relative_to(target) else bundle_root
        if not Path(path).is_relative_to(root):
            raise
        warning = file_warning(exc, Path(path).relative_to(root), "replica_copy")
        if warning is None:
            raise
        # Transactions retain durable preimages; never label blocked bytes verified.
        result = {"schema": "millennium.replica.v2", "status": "complete", "file_warnings": [warning],
                  "current_data_copied": False, "verification_scope": "retained_recoverable_state",
                  "destination": str(target), "retry_required": True}
        atomic_json(target / "replica-receipt.json", result)
        return result


def _replicate(bundle_root: Path, target: Path, runtime: Path | None = None) -> dict:
    """Export the verified public bundle; never copy arbitrary runtime/private files."""
    bundle_root, target = no_links(bundle_root), no_links(target)
    if overlap(bundle_root, target) or target == target.parent:
        raise BackupError("unsafe_replica_target")
    files, manifest = verify_bundle(bundle_root)
    source_generation = manifest["generation"]
    file_warnings = []
    with writer_lock(target):
        recover_transaction(target)
        existing = managed_files(target)
        if (target / MANIFEST).exists():
            verify_bundle(target)
        elif existing:
            raise BackupError("unowned_replica_destination")
        source_runtime = no_links(runtime or bundle_root / "runtime")
        if runtime is not None:
            binding = parse_json(read_bytes(source_runtime / "binding.json"), "binding")
            if binding.get("destination") != norm(bundle_root):
                raise BackupError("replica_runtime_binding_mismatch")
        source_history = no_links(source_runtime / "snapshots")
        if runtime is None and (bundle_root / "replica-receipt.json").is_file():
            receipt = parse_json(read_bytes(bundle_root / "replica-receipt.json"), "replica")
            if receipt.get("schema") != "millennium.replica.v2" or receipt.get("status") != "complete" or receipt.get("generation") != manifest["generation"] or receipt.get("manifest_sha256") != current_hash(bundle_root / MANIFEST):
                raise BackupError("source_replica_receipt_mismatch")
            source_history = no_links(bundle_root / "history")
        wanted = {manifest["generation"]: (files, manifest)}
        if source_history.exists():
            candidates = sorted((x for x in source_history.iterdir() if GENERATION.fullmatch(x.name) and x.is_dir()),
                                key=lambda p: p.stat().st_mtime_ns, reverse=True)[:32]
            for item in candidates:
                saved = verify_bundle(item)
                if saved[1]["generation"] != item.name:
                    raise BackupError("history_generation_mismatch")
                wanted[item.name] = saved
        history = no_links(target / "history")
        for name, (history_files, history_manifest) in wanted.items():
            saved = history / name
            if saved.exists():
                saved_files, saved_manifest = verify_bundle(saved)
                if saved_files != history_files or saved_manifest != history_manifest:
                    raise BackupError("replica_history_conflict")
            else:
                try:
                    write_bundle(saved, history_files, history_manifest)
                except OSError as exc:
                    warning = _replica_warning(exc, target, "history_copy")
                    if warning is None:
                        raise
                    file_warnings.append(warning)
                    # An interrupted historical bundle is not advertised as verified.
        for attempt in range(len(files) + 1):
            try:
                publish(target, files, manifest, existing)
                break
            except OSError as exc:
                warning = _replica_warning(exc, target, "current_copy")
                if warning is None:
                    raise
                rel = warning["relative_path"]
                if rel not in files or any(w["relative_path"] == rel and w["stage"] == "current_copy" for w in file_warnings):
                    raise  # A blocked rollback/preimage is not safe to skip.
                if rel not in existing and rel == "config/config.json":
                    raise  # No valid core projection can be fabricated on first capture.
                file_warnings.append(warning)
                files = dict(files)
                if rel in existing:
                    files[rel] = existing[rel]
                else:
                    files.pop(rel, None)
                manifest = make_manifest(files, versions=manifest.get("versions"), coverage=manifest.get("coverage"))
        else:
            raise BackupError("replica_retry_limit")
        verified_files, verified_manifest = verify_bundle(target)
        if verified_files != files or verified_manifest != manifest:
            raise BackupError("replica_projection_readback_failed")
        for item in history.iterdir():
            if GENERATION.fullmatch(item.name) and item.name not in wanted:
                verify_bundle(item)
                remove_owned_tree(item)
        receipt = {"schema": "millennium.replica.v2", "status": "complete", "completed_utc": utc(),
                   "generation": manifest["generation"], "verified_files": len(files), "retained_generations": len(wanted),
                   "manifest_sha256": digest(read_bytes(target / MANIFEST)), "destination": str(target),
                   "source_generation": source_generation, "file_warnings": file_warnings,
                   "current_data_copied": not bool(file_warnings),
                   "verification_scope": "current_files_with_previous_same_path_fallback" if file_warnings else "complete_current_generation"}
        atomic_json(target / "replica-receipt.json", receipt)
        return receipt


def _replica_warning(exc, target, stage):
    path = getattr(exc, "warning_path", None)
    if path is None or not Path(path).is_relative_to(target):
        return None
    parts = Path(path).relative_to(target).parts
    # Staging/transaction prefixes are implementation details, not payload paths.
    index = next((i for i, part in enumerate(parts) if part in MANAGED), None)
    if index is None:
        return None
    return file_warning(exc, Path(*parts[index:]).as_posix(), stage)


def assert_steam_stopped(target: Path | None = None) -> None:
    if target is not None and not no_links(target.parent / "steam.exe").is_file():
        return
    if os.name != "nt":
        return
    try:
        result = subprocess.run(["tasklist.exe", "/FI", "IMAGENAME eq steam.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, timeout=15, creationflags=0x08000000)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError("steam_process_status_unknown") from exc
    if result.returncode or b'"steam.exe"' in result.stdout.lower():
        raise BackupError("steam_must_be_closed_or_status_unknown")


def resource_references(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() == "src":
                candidates = [item] if isinstance(item, str) else item if isinstance(item, list) else []
                result.extend(x for x in candidates if isinstance(x, str))
            else:
                result.extend(resource_references(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(resource_references(item))
    return result


def deep_merge(base: dict, overlay: dict) -> dict:
    result = copy.deepcopy(base)
    for k, v in overlay.items():
        result[k] = deep_merge(result[k], v) if isinstance(v, dict) and isinstance(result.get(k), dict) else copy.deepcopy(v)
    return result


def restore_plan(bundle: Path, target: Path) -> tuple[dict, dict[str, bytes]]:
    bundle, target = no_links(bundle), no_links(target)
    if overlap(bundle, target):
        raise BackupError("restore_roots_overlap")
    files, manifest = verify_bundle(bundle)
    if (target / JOURNAL).exists():
        raise BackupError("pending_transaction")
    core, omitted = project_core(parse_json(files["config/config.json"], "core"))
    current = parse_json(read_bytes(path_for(target, "config/config.json")), "target-core")
    if not isinstance(current, dict):
        raise BackupError("target_config_object_required")
    project_core(current)  # Detect incompatible known target types before merging.
    blockers, warnings = [], []
    # Require every enabled component and the active theme to have the same captured
    # manifest/definition bytes. This is a narrow compatibility proof, not UI proof.
    checks = [("plugins", p, PLUGIN_FILES) for p in core["plugins"]["enabledPlugins"]]
    active = core["themes"]["activeTheme"]
    theme_names = set(core["themes"].get("conditions", {})) | set(core["themes"].get("themeColors", {}))
    if active and active.lower() != "default":
        theme_names.add(active)
    checks.extend(("themes", name, THEME_FILES) for name in sorted(theme_names))
    for group, name, filenames in checks:
        required = f"{group}/{name}/" + ("plugin.json" if group == "plugins" else "skin.json")
        if required not in files:
            blockers.append("missing_snapshot_component:" + required)
        for filename in filenames:
            rel = f"{group}/{name}/{filename}"
            if filename == "install-state.json":
                continue
            if rel in files:
                live = path_for(target, rel)
                if not live.is_file():
                    blockers.append("missing_component_file:" + rel)
                elif validate_payload(rel, read_bytes(live)) != validate_payload(rel, files[rel]):
                    blockers.append("component_version_mismatch:" + rel)
        if group == "themes":
            skin_rel = f"themes/{name}/skin.json"
            if skin_rel in files:
                for ref in resource_references(parse_json(files[skin_rel], skin_rel)):
                    # Resource paths are never copied or executed; check bounded local
                    # existence. Absolute/escaping/remote references need manual review.
                    rel = PurePosixPath(ref.replace("\\", "/"))
                    if rel.is_absolute() or ".." in rel.parts or ":" in ref:
                        blockers.append("unsupported_resource_reference:" + name)
                    elif not no_links(target / group / name / Path(str(rel))).is_file():
                        blockers.append("missing_theme_resource:" + name + "/" + str(rel))
    # Network is deliberately not restored from the public projection (including empty
    # values); preserve target proxy/credentials. Unknown target fields survive merging.
    core.pop("network", None)
    writes = {"config/config.json": encoded(deep_merge(current, core))}
    if "config/quick.css" in files:
        writes["config/quick.css"] = files["config/quick.css"]
    warnings += ["plugin_private_settings_not_restored", "component_program_assets_must_be_installed", "steam_ui_acceptance_separate"]
    if omitted:
        warnings.append("unsupported_core_fields_omitted")
    plan = {"schema": "millennium.restore-plan.v2", "write_mode": "zero_write", "status": "blocked" if blockers else "ready",
            "generation": manifest["generation"], "target": str(target), "blockers": sorted(set(blockers)), "warnings": warnings,
            "files": [{"path": p, "before": current_hash(path_for(target, p)), "after": digest(b)} for p, b in writes.items()],
            "inventory_files_written": False}
    plan["plan_sha256"] = digest(encoded(plan))
    return plan, writes


def prune_restore_history(target: Path, current: str) -> dict:
    """Best-effort retention after a committed restore; never hide its rollback ID.

    Incomplete/unreadable records are preserved for inspection. The new restore is
    pinned even when an older directory has a newer timestamp. Caller holds lock.
    """
    result = {"status": "complete", "pruned_records": 0, "issues": []}
    try:
        history = no_links(target / ".millennium-restore-history")
        completed = []
        for item in history.iterdir():
            if not GENERATION.fullmatch(item.name):
                continue
            try:
                no_links(item)
                candidate = parse_json(read_bytes(item / "rollback.json"), "rollback")
                if (not isinstance(candidate, dict) or
                        candidate.get("schema") != "millennium.restore-rollback.v2" or
                        candidate.get("id") != item.name or candidate.get("target") != norm(target)):
                    raise BackupError("invalid_restore_history_record")
                if candidate.get("status") not in ("complete", "rolled_back", "aborted"):
                    raise BackupError("incomplete_restore_history_record")
                if item.name != current:
                    completed.append((item.stat().st_mtime_ns, item.name, item))
            except (BackupError, OSError) as exc:
                result["issues"].append({"record": item.name,
                    "reason": str(exc) if isinstance(exc, BackupError) else type(exc).__name__})
        # Four completed records in total: current plus three predecessors.
        for _, name, item in sorted(completed, reverse=True)[3:]:
            try:
                remove_owned_tree(item)
                result["pruned_records"] += 1
            except (BackupError, OSError) as exc:
                result["issues"].append({"record": name, "reason": "cleanup_" + type(exc).__name__})
    except (BackupError, OSError) as exc:
        result["issues"].append({"record": None, "reason": "enumeration_" + type(exc).__name__})
    if result["issues"]:
        result["status"] = "needs_attention"
    return result


def restore(bundle: Path, target: Path, *, expected_plan: str, fault=None) -> dict:
    target = no_links(target)
    with writer_lock(target):
        plan, writes = restore_plan(bundle, target)
        if plan["status"] != "ready":
            raise BackupError("restore_preflight_blocked")
        if plan["plan_sha256"] != expected_plan:
            raise BackupError("restore_plan_changed")
        # The wrapper checks live Steam processes; engine also checks on Windows.
        assert_steam_stopped(target)
        identifier = generation_id()
        archive = target / ".millennium-restore-history" / identifier
        old = {p: read_bytes(path_for(target, p)) for p in writes if path_for(target, p).exists()}
        archive.mkdir(parents=True)
        for p, data in old.items():
            atomic_write(path_for(archive, p), data)
        record = {"schema": "millennium.restore-rollback.v2", "id": identifier, "target": norm(target),
                  "files": plan["files"], "created_utc": utc(), "status": "prepared"}
        atomic_json(archive / "rollback.json", record)
        transact(target, writes, before={e["path"]: e["before"] for e in plan["files"]}, fault=fault, purpose="restore", restore_record=identifier)
        # transact has already durably finalized the rollback record.
        retention = prune_restore_history(target, identifier)
        warnings = list(plan["warnings"])
        if retention["status"] != "complete":
            warnings.append("restore_history_needs_attention")
        return {"schema": "millennium.restore.v2", "status": "complete", "rollback_id": identifier,
                "verified_files": len(writes), "ui_acceptance": "not_performed",
                "warnings": warnings, "history_cleanup": retention}


def rollback_restore(target: Path, identifier: str) -> dict:
    if not GENERATION.fullmatch(identifier):
        raise BackupError("invalid_rollback_id")
    target = no_links(target)
    with writer_lock(target):
        assert_steam_stopped(target)
        if (target / JOURNAL).exists():
            raise BackupError("recover_pending_transaction_first")
        archive = no_links(target / ".millennium-restore-history" / identifier)
        record = parse_json(read_bytes(archive / "rollback.json"), "rollback")
        if record.get("schema") != "millennium.restore-rollback.v2" or record.get("target") != norm(target) or record.get("status") != "complete":
            raise BackupError("rollback_binding_or_state_invalid")
        writes = {}
        for entry in record["files"]:
            p = safe_rel(entry["path"])
            if not p.startswith("config/"):
                raise BackupError("rollback_path_not_settings")
            if current_hash(path_for(target, p)) != entry["after"]:
                raise BackupError("rollback_target_changed")
            b = read_bytes(path_for(archive, p)) if entry["before"] is not None else None
            if (digest(b) if b is not None else None) != entry["before"]:
                raise BackupError("rollback_preimage_corrupt")
            writes[p] = b
        transact(target, writes, before={e["path"]: e["after"] for e in record["files"]}, purpose="restore", restore_record=identifier, final_restore_status="rolled_back")
        # transact owns the durable terminal record; do not rewrite it afterward.
        return {"schema": "millennium.restore.v2", "status": "rolled_back", "rollback_id": identifier, "verified_files": len(writes)}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["snapshot", "status", "verify", "replicate", "restore-plan", "restore", "rollback", "recover"])
    p.add_argument("--source", type=Path)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--runtime", type=Path)
    p.add_argument("--target", type=Path)
    p.add_argument("--adopt-existing", action="store_true")
    p.add_argument("--keep", type=int, default=4)
    p.add_argument("--versions-json", default="{}")
    p.add_argument("--expected-plan", default="")
    p.add_argument("--rollback-id", default="")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.action in ("snapshot", "status"):
            if args.source is None:
                raise BackupError("source_required")
            store = SnapshotStore(args.source, args.destination, args.runtime)
            result = store.snapshot(adopt_existing=args.adopt_existing, keep=args.keep,
                                    versions=parse_json(args.versions_json.encode(), "versions")) if args.action == "snapshot" else store.status()
        elif args.action == "verify":
            files, manifest = verify_bundle(args.destination)
            result = {"status": "verified", "schema": "millennium.verify.v2", "write_mode": "zero_write",
                      "generation": manifest["generation"], "verified_files": len(files), "coverage": manifest["coverage"]}
        elif args.action == "recover":
            with writer_lock(args.destination):
                result = {"status": recover_transaction(args.destination)}
        elif args.action == "rollback":
            result = rollback_restore(args.destination, args.rollback_id)
        else:
            if args.target is None:
                raise BackupError("target_required")
            if args.action == "replicate":
                result = replicate(args.destination, args.target, args.runtime)
            elif args.action == "restore-plan":
                result, _ = restore_plan(args.destination, args.target)
            else:
                result = restore(args.destination, args.target, expected_plan=args.expected_plan)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 2 if result.get("status") in ("blocked", "needs_attention") else 0
    except Exception as exc:
        print(json.dumps({"schema": "millennium.error.v2", "status": "failed",
                          "reason": str(exc) if isinstance(exc, BackupError) else type(exc).__name__}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
