import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from test_backup import fixture, put, core
import millennium_backup as m


class WarningTests(unittest.TestCase):
    def test_post_copy_removal_rolls_back_then_updates_unblocked_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source = root / "source"; dest = root / "dest"; target = root / "replica"
            fixture(source); store = m.SnapshotStore(source, dest); store.snapshot(); m.replicate(dest, target)
            old = m.read_bytes(target / "config/quick.css")
            put(source, "config/config.json", core("red")); put(source, "config/quick.css", b"quarantined css"); store.snapshot()
            original = m.atomic_write
            def removed(path, data):
                original(path, data)
                if path == target / "config/quick.css" and data == b"quarantined css":
                    path.rename(root / "removed-after-copy")
            with mock.patch.object(m, "atomic_write", side_effect=removed), \
                 mock.patch.object(m, "defender_removed", side_effect=lambda p: p == target / "config/quick.css"):
                result = m.replicate(dest, target)
            files, _ = m.verify_bundle(target)
            self.assertEqual(files["config/quick.css"], old)
            self.assertEqual(result["file_warnings"][0]["error_code"], 226)
            self.assertEqual(m.parse_json(files["config/config.json"], "test")["general"]["accentColor"], "red")

    def test_missing_replica_needs_same_path_defender_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source = root / "source"; dest = root / "dest"; target = root / "replica"
            fixture(source); m.SnapshotStore(source, dest).snapshot(); m.replicate(dest, target)
            target.joinpath("config/quick.css").rename(root / "quarantine-fixture")
            with mock.patch.object(m, "defender_removed", return_value=False):
                with self.assertRaises(m.BackupError): m.replicate(dest, target)
            with mock.patch.object(m, "defender_removed", side_effect=lambda p: p == target / "config/quick.css"):
                result = m.replicate(dest, target)
            self.assertEqual(result["file_warnings"][0]["reason"], "antivirus_removed")
            self.assertEqual(result["file_warnings"][0]["error_code"], 226)
            self.assertFalse(result["current_data_copied"])

    def test_replica_one_blocked_new_payload_keeps_old_path_and_updates_other_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source = root / "source"; dest = root / "dest"; target = root / "replica"
            fixture(source); store = m.SnapshotStore(source, dest); store.snapshot(); m.replicate(dest, target)
            old = m.read_bytes(target / "config/quick.css")
            put(source, "config/config.json", core("red")); put(source, "config/quick.css", b"blocked new css")
            store.snapshot()
            original = m.atomic_write
            def blocked(path, data):
                if path.is_relative_to(target) and data == b"blocked new css":
                    exc = OSError("synthetic"); exc.winerror = 225; exc.warning_path = path
                    raise exc
                return original(path, data)
            with mock.patch.object(m, "atomic_write", side_effect=blocked): result = m.replicate(dest, target)
            files, manifest = m.verify_bundle(target)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(files["config/quick.css"], old)
            self.assertEqual(m.parse_json(files["config/config.json"], "test")["general"]["accentColor"], "red")
            self.assertEqual(result["generation"], manifest["generation"])
            self.assertNotEqual(result["generation"], result["source_generation"])

    def test_optional_source_warning_retains_verified_generation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source = root / "source"; dest = root / "dest"
            fixture(source); store = m.SnapshotStore(source, dest)
            first = store.snapshot()
            put(source, "config/config.json", core("red"))
            original = m.read_bytes
            for code in (225, 226, None):
                def blocked(path):
                    if path == source / "config/quick.css":
                        exc = FileNotFoundError(2, "synthetic") if code is None else OSError("synthetic")
                        if code is not None: exc.winerror = code
                        raise exc
                    return original(path)
                with mock.patch.object(m, "read_bytes", side_effect=blocked): result = store.snapshot()
                self.assertEqual(result["status"], "complete")
                self.assertFalse(result["current_data_copied"])
                self.assertEqual(result["file_warnings"][0]["relative_path"], "config/quick.css")
                files, manifest = m.verify_bundle(dest)
                self.assertEqual(m.parse_json(files["config/config.json"], "test")["general"]["accentColor"], "red")
                self.assertIn("config/config.json", result["updated_files"])
            source.joinpath("config/config.json").rename(source / "config/missing.json")
            with self.assertRaises(FileNotFoundError): store.snapshot()

    def test_replica_av_reports_unverified_current_data_and_real_error_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source = root / "source"; dest = root / "dest"; target = root / "replica"
            fixture(source); store = m.SnapshotStore(source, dest); store.snapshot()
            m.replicate(dest, target)
            exc = OSError("synthetic"); exc.winerror = 225; exc.warning_path = target / "config/quick.css"
            with mock.patch.object(m, "_replicate", side_effect=exc): result = m.replicate(dest, target)
            self.assertEqual(result["status"], "complete")
            self.assertFalse(result["current_data_copied"])
            with mock.patch.object(m, "_replicate", side_effect=PermissionError("full disk")):
                with self.assertRaises(PermissionError): m.replicate(dest, target)
