"""Deterministic isolated tests: no live Steam, Task Scheduler, network or Git writes."""
import copy
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import millennium_backup as m


def core(color='lime'):
    return {'general': {'accentColor': color}, 'plugins': {'enabledPlugins': ['sample']},
            'themes': {'activeTheme': 'Test', 'conditions': {}, 'themeColors': {}},
            'network': {'proxy': '', 'proxyUsername': '', 'proxyPassword': ''}}


def put(root, rel, value):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(m.encoded(value) if isinstance(value, dict) else value)


def fixture(root):
    put(root, 'config/config.json', core())
    put(root, 'config/quick.css', b'body { color: lime; }\n')
    put(root, 'plugins/sample/plugin.json', {'name': 'sample', 'version': '1.0'})
    put(root, 'plugins/sample/metadata.json', {'commit': 'a' * 40})
    put(root, 'themes/Test/skin.json', {'name': 'Test', 'version': '1.0'})
    put(root, 'themes/Test/metadata.json', {'commit': 'b' * 40})


def file_view(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class BackupTests(unittest.TestCase):
    def setUp(self):
        steam_check = mock.patch.object(m, "assert_steam_stopped")
        steam_check.start()
        self.addCleanup(steam_check.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='millennium-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.dest = self.root / 'destination'
        fixture(self.source)
        self.store = m.SnapshotStore(self.source, self.dest)

    def snap(self, **kwargs):
        return self.store.snapshot(**kwargs)

    def test_first_snapshot_and_exclusions(self):
        put(self.source, 'plugins/sample/private-config.json', {'token': 'never copy'})
        put(self.source, 'id_cache.json', {'id': 'never copy'})
        put(self.source, 'themes/Test/resource.css', b'resource')
        self.assertEqual(self.snap()['status'], 'complete')
        files, manifest = m.verify_bundle(self.dest)
        self.assertEqual(len(files), 6)
        self.assertFalse((self.dest / 'id_cache.json').exists())
        self.assertEqual(manifest['schema'], m.SCHEMA)

    def test_successive_updates_without_git_commit(self):
        self.snap()
        put(self.source, 'config/config.json', core('red'))
        self.assertEqual(self.snap()['status'], 'complete')
        put(self.source, 'config/config.json', core('blue'))
        self.assertEqual(self.snap()['status'], 'complete')
        self.assertEqual(json.loads((self.dest / 'config/config.json').read_bytes())['general']['accentColor'], 'blue')

    def test_nochange_verifies_instead_of_throttling(self):
        first = self.snap()
        second = self.snap()
        self.assertEqual(second['status'], 'unchanged')
        self.assertEqual(first['generation'], second['generation'])

    def test_manual_edit_blocks_even_if_source_changed(self):
        self.snap()
        put(self.dest, 'config/config.json', core('manual'))
        put(self.source, 'config/config.json', core('updated'))
        with self.assertRaisesRegex(m.BackupError, 'snapshot_hash_mismatch'):
            self.snap()
        self.assertEqual(json.loads((self.dest / 'config/config.json').read_bytes())['general']['accentColor'], 'manual')

    def test_unrelated_document_does_not_block(self):
        self.snap()
        put(self.dest, 'README.md', b'Uncommitted documentation\n')
        put(self.source, 'config/config.json', core('new'))
        self.snap()
        self.assertEqual((self.dest / 'README.md').read_bytes(), b'Uncommitted documentation\n')

    def test_unknown_file_in_managed_directory_preserved(self):
        self.snap()
        put(self.dest, 'themes/Test/personal-note.txt', b'keep')
        with self.assertRaisesRegex(m.BackupError, 'non_allowlisted_path'):
            self.snap()
        self.assertEqual((self.dest / 'themes/Test/personal-note.txt').read_bytes(), b'keep')

    def test_partial_source_never_deletes_backup(self):
        self.snap()
        previous = m.managed_files(self.dest)
        os.rename(self.source / 'plugins', self.source / 'plugins-offline')
        with self.assertRaisesRegex(m.BackupError, 'source_incomplete'):
            self.snap()
        self.assertEqual(previous, m.managed_files(self.dest))

    def test_valid_uninstall_propagates(self):
        self.snap()
        c = core()
        c['plugins']['enabledPlugins'] = []
        put(self.source, 'config/config.json', c)
        import shutil
        shutil.rmtree(self.source / 'plugins/sample')
        self.snap()
        self.assertFalse((self.dest / 'plugins/sample/plugin.json').exists())
        m.verify_bundle(self.dest)

    def test_missing_enabled_plugin_blocks(self):
        (self.source / 'plugins/sample/plugin.json').unlink()
        with self.assertRaisesRegex(m.BackupError, 'incomplete_installed_component'):
            self.snap()
        self.assertFalse(self.dest.exists())

    def test_missing_active_theme_blocks(self):
        c = core()
        c['themes']['activeTheme'] = 'Absent'
        put(self.source, 'config/config.json', c)
        with self.assertRaisesRegex(m.BackupError, 'active_theme_missing'):
            self.snap()
        self.assertFalse(self.dest.exists())

    def test_path_alias_and_runtime_boundaries(self):
        for dest, runtime in ((self.source, None), (self.source / 'backup', None),
                              (self.root, None), (self.dest, self.source),
                              (self.dest, self.dest / 'config'), (self.dest, self.root)):
            with self.subTest(destination=dest, runtime=runtime):
                with self.assertRaises(m.BackupError):
                    m.SnapshotStore(self.source, dest, runtime)
        self.assertFalse(self.dest.exists())

    def test_link_component_rejected(self):
        link = self.root / 'alias'
        try:
            link.symlink_to(self.source, target_is_directory=True)
        except OSError:
            self.skipTest('Symbolic links unavailable in this execution identity')
        with self.assertRaisesRegex(m.BackupError, 'linked_path'):
            m.SnapshotStore(link, self.dest)

    def test_runtime_other_pair_rejected(self):
        self.snap()
        alternate = self.root / 'other-source'
        fixture(alternate)
        with self.assertRaisesRegex(m.BackupError, 'runtime_bound_to_other_pair'):
            m.SnapshotStore(alternate, self.dest).snapshot()

    def test_invalid_json_duplicate_keys_and_nonfinite(self):
        for b in (b'{"themes":', b'{"themes":{},"themes":{}}', b'{"value":NaN}'):
            with self.subTest(data=b):
                with self.assertRaises(m.BackupError):
                    m.parse_json(b, 'fixture')

    def test_escaped_secret_never_published(self):
        c = core()
        c['network']['proxyPassword'] = 'private-password'
        c['network']['proxyUsername'] = 'private-user'
        c['network']['proxy'] = 'https://private:password@proxy'
        data = m.encoded(c).replace(b'proxyPassword', b'proxy\\u0050assword')
        put(self.source, 'config/config.json', data)
        self.snap()
        public = (self.dest / 'config/config.json').read_bytes()
        self.assertNotIn(b'private', public)
        self.assertIn('network.proxyPassword', self.store.status()['omitted_core_fields'])

    def test_unknown_core_fields_reported_not_published(self):
        c = core()
        c['futurePrivateSection'] = {'access_token': 'do-not-copy'}
        c['general']['newPrivateSetting'] = 'do-not-copy'
        put(self.source, 'config/config.json', c)
        self.snap()
        data = (self.dest / 'config/config.json').read_bytes()
        self.assertNotIn(b'do-not-copy', data)
        self.assertIn('futurePrivateSection', self.store.status()['omitted_core_fields'])

    def test_plugin_secret_blocks(self):
        put(self.source, 'plugins/sample/metadata.json', {'access_token': 'private-token'})
        with self.assertRaisesRegex(m.BackupError, 'sensitive_field'):
            self.snap()
        self.assertFalse(self.dest.exists())

    def test_css_sensitive_value_blocks(self):
        put(self.source, 'config/quick.css', b'/* https://user:password@example.invalid */')
        with self.assertRaises(m.BackupError):
            self.snap()

    def test_git_error_fails_closed(self):
        self.snap()
        (self.dest / '.git').mkdir()
        with mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 128, b'', b'failure')):
            with self.assertRaisesRegex(m.BackupError, 'git_status_failed'):
                self.snap()
        self.assertEqual(self.store.status()['last_run']['status'], 'failed')

    def test_status_has_zero_writes(self):
        self.snap()
        before = file_view(self.root)
        self.assertEqual(self.store.status()['status'], 'healthy')
        self.assertEqual(before, file_view(self.root))

    def test_status_missing_destination_does_not_create_it(self):
        self.assertEqual(self.store.status()['status'], 'needs_attention')
        self.assertFalse(self.dest.exists())

    def test_legacy_requires_adoption_and_preserves_previous(self):
        fixture(self.dest)
        with self.assertRaisesRegex(m.BackupError, 'explicit_adoption'):
            self.snap()
        put(self.source, 'config/config.json', core('new'))
        self.snap(adopt_existing=True)
        bundles = list((self.store.runtime / 'snapshots').iterdir())
        self.assertEqual(len(bundles), 2)
        old_values = [json.loads(m.verify_bundle(p)[0]['config/config.json'])['general']['accentColor'] for p in bundles]
        self.assertIn('lime', old_values)
        self.assertIn('new', old_values)

    def test_transaction_exception_rolls_back_all(self):
        self.snap()
        before = m.managed_files(self.dest)
        manifest = (self.dest / m.MANIFEST).read_bytes()
        put(self.source, 'config/config.json', core('new'))
        put(self.source, 'config/quick.css', b'new-css')
        def fail(index):
            if index == 0:
                raise OSError('injected')
        with self.assertRaises(OSError):
            self.snap(fault=fail)
        self.assertEqual(before, m.verify_bundle(self.dest)[0])
        self.assertEqual(manifest, (self.dest / m.MANIFEST).read_bytes())
        self.assertFalse((self.dest / m.JOURNAL).exists())

    def test_process_interruption_recoverable(self):
        self.snap()
        before = m.managed_files(self.dest)
        put(self.source, 'config/config.json', core('new'))
        class Crash(BaseException):
            pass
        def crash(index):
            raise Crash()
        with self.assertRaises(Crash):
            self.snap(fault=crash)
        self.assertEqual(self.store.status()['status'], 'needs_attention')
        with m.writer_lock(self.dest):
            self.assertEqual(m.recover_transaction(self.dest), 'rolled_back')
        self.assertEqual(before, m.verify_bundle(self.dest)[0])

    def test_crash_then_manual_change_not_overwritten(self):
        self.snap()
        put(self.source, 'config/config.json', core('new'))
        def crash(index):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.snap(fault=crash)
        put(self.dest, 'config/config.json', core('manual-after-crash'))
        with m.writer_lock(self.dest):
            with self.assertRaisesRegex(m.BackupError, 'recovery_conflict'):
                m.recover_transaction(self.dest)
        self.assertEqual(json.loads((self.dest / 'config/config.json').read_bytes())['general']['accentColor'], 'manual-after-crash')

    def test_lock_uses_destination_not_runtime(self):
        with m.writer_lock(self.dest):
            with self.assertRaisesRegex(m.BackupError, 'writer_busy'):
                with m.writer_lock(self.dest):
                    pass

    def test_manifest_tamper_and_path_traversal(self):
        self.snap()
        doc = json.loads((self.dest / m.MANIFEST).read_bytes())
        doc['files'][0]['path'] = '../outside.json'
        put(self.dest, m.MANIFEST, doc)
        with self.assertRaises(m.BackupError):
            m.verify_bundle(self.dest)

    def test_duplicate_manifest_paths(self):
        self.snap()
        doc = json.loads((self.dest / m.MANIFEST).read_bytes())
        doc['files'].append(doc['files'][0])
        put(self.dest, m.MANIFEST, doc)
        with self.assertRaisesRegex(m.BackupError, 'duplicate_manifest_path'):
            m.verify_bundle(self.dest)

    def test_replica_is_independent_and_deletions_follow(self):
        self.snap()
        replica = self.root / 'replica'
        m.replicate(self.dest, replica)
        self.assertEqual(m.verify_bundle(replica)[0], m.verify_bundle(self.dest)[0])
        self.assertNotEqual(os.stat(replica / 'config/config.json').st_ino, os.stat(self.dest / 'config/config.json').st_ino)
        c = core('new')
        c['plugins']['enabledPlugins'] = []
        put(self.source, 'config/config.json', c)
        import shutil
        shutil.rmtree(self.source / 'plugins/sample')
        self.snap()
        m.replicate(self.dest, replica)
        self.assertFalse((replica / 'plugins/sample/plugin.json').exists())

    def test_replica_refuses_unowned_data(self):
        self.snap()
        replica = self.root / 'replica'
        fixture(replica)
        with self.assertRaisesRegex(m.BackupError, 'unowned_replica'):
            m.replicate(self.dest, replica)

    def test_restore_and_rollback_preserve_network_and_metadata(self):
        self.snap()
        target = self.root / 'restore-target'
        fixture(target)
        c = core('old-target')
        c['network']['proxyPassword'] = 'target-private-password'
        c['futureSection'] = {'keep': True}
        put(target, 'config/config.json', c)
        put(target, 'config/quick.css', b'old-target-css')
        before = {p: b for p, b in file_view(target).items()}
        plan, _ = m.restore_plan(self.dest, target)
        self.assertEqual(plan['status'], 'ready')
        with mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')):
            result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        changed = json.loads((target / 'config/config.json').read_bytes())
        self.assertEqual(changed['general']['accentColor'], 'lime')
        self.assertEqual(changed['network']['proxyPassword'], 'target-private-password')
        self.assertTrue(changed['futureSection']['keep'])
        self.assertEqual((target / 'plugins/sample/metadata.json').read_bytes(), before['plugins/sample/metadata.json'])
        m.rollback_restore(target, result['rollback_id'])
        for rel, data in before.items():
            self.assertEqual((target / rel).read_bytes(), data)

    def test_restore_missing_or_mismatching_resources_blocks(self):
        self.snap()
        target = self.root / 'target'
        fixture(target)
        put(target, 'themes/Test/metadata.json', {'commit': 'c' * 40})
        plan, _ = m.restore_plan(self.dest, target)
        self.assertEqual(plan['status'], 'blocked')
        self.assertTrue(any('version_mismatch' in x for x in plan['blockers']))

    def test_stale_restore_plan_rejected(self):
        self.snap()
        target = self.root / 'target'
        fixture(target)
        plan, _ = m.restore_plan(self.dest, target)
        put(target, 'config/config.json', core('newer'))
        with self.assertRaisesRegex(m.BackupError, 'restore_plan_changed'):
            m.restore(self.dest, target, expected_plan=plan['plan_sha256'])

    def test_restore_rollback_conflict_preserved(self):
        self.snap()
        target = self.root / 'target'
        fixture(target)
        plan, _ = m.restore_plan(self.dest, target)
        with mock.patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')):
            result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        put(target, 'config/config.json', core('post-restore-manual'))
        with self.assertRaisesRegex(m.BackupError, 'rollback_target_changed'):
            m.rollback_restore(target, result['rollback_id'])

    def test_retention_bounded(self):
        for n in range(7):
            put(self.source, 'config/config.json', core(str(n)))
            self.snap(keep=3)
        self.assertLessEqual(len(list((self.store.runtime / 'snapshots').iterdir())), 4)
        m.verify_bundle(self.dest)

    def test_fresh_cli_process(self):
        command = [sys.executable, '-I', '-B', str(Path(m.__file__)), 'snapshot', '--source', str(self.source), '--destination', str(self.dest)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run(command[:4] + ['verify', '--destination', str(self.dest)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'verified')



    def test_missing_theme_resource_blocks_restore(self):
        put(self.source, 'themes/Test/skin.json', {'name': 'Test', 'Patches': [{'src': 'missing.css'}]})
        self.snap()
        target = self.root / 'target'; fixture(target)
        put(target, 'themes/Test/skin.json', {'name': 'Test', 'Patches': [{'src': 'missing.css'}]})
        plan, _ = m.restore_plan(self.dest, target)
        self.assertEqual(plan['status'], 'blocked')
        self.assertTrue(any(x.startswith('missing_theme_resource:') for x in plan['blockers']))

    def test_replica_includes_verified_history(self):
        first = self.snap()['generation']
        put(self.source, 'config/config.json', core('blue'))
        self.snap()
        target = self.root / 'replica'
        result = m.replicate(self.dest, target)
        self.assertEqual(result['retained_generations'], 2)
        self.assertTrue((target / 'history' / first / m.MANIFEST).is_file())

    def test_nonpublic_core_cannot_be_smuggled_with_new_manifest(self):
        self.snap()
        files, _ = m.verify_bundle(self.dest)
        value = m.parse_json(files['config/config.json'], 'core')
        value['unknown'] = {'hello':'world'}
        files['config/config.json'] = m.encoded(value)
        for name, data in files.items(): put(self.dest, name, data)
        put(self.dest, m.MANIFEST, m.make_manifest(files))
        with self.assertRaisesRegex(m.BackupError, 'nonpublic'):
            m.verify_bundle(self.dest)

    def test_committed_restore_crash_finalizes_rollback_record(self):
        self.snap()
        target = self.root / 'target'; fixture(target)
        put(target, 'config/config.json', core('blue'))
        plan, _ = m.restore_plan(self.dest, target)
        original = m.finalize_restore_record
        with mock.patch.object(m, 'finalize_restore_record', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        self.assertEqual(m.recover_transaction(target), 'finalized')
        history = list((target / '.millennium-restore-history').iterdir())[0]
        self.assertEqual(m.rollback_restore(target, history.name)['status'], 'rolled_back')


    def test_membership_change_during_read_is_rejected(self):
        original=m.source_membership
        calls=0
        def changed(root):
            nonlocal calls
            calls+=1
            if calls==2: put(root,'plugins/new/plugin.json',{'name':'new'})
            return original(root)
        with mock.patch.object(m,'source_membership',side_effect=changed):
            with self.assertRaisesRegex(m.BackupError,'source_changed'):
                m.read_source(self.source)
        self.assertFalse(self.dest.exists())

    def test_empty_preparation_recovery(self):
        self.dest.mkdir();(self.dest/m.JOURNAL).mkdir()
        with m.writer_lock(self.dest):
            self.assertEqual(m.recover_transaction(self.dest),'discarded_empty_preparation')

    def test_status_wrong_runtime_identity(self):
        self.snap()
        binding=self.dest/'runtime/binding.json'
        value=m.parse_json(binding.read_bytes(),'binding');value['source']='wrong'
        binding.write_bytes(m.encoded(value))
        before=file_view(self.dest)
        self.assertEqual(self.store.status()['reason'],'runtime_binding_mismatch')
        self.assertEqual(before,file_view(self.dest))

    def test_status_wrong_generation_receipt(self):
        self.snap()
        p=self.dest/'runtime/snapshot-state.json';v=m.parse_json(p.read_bytes(),'state')
        v['generation']=m.generation_id();p.write_bytes(m.encoded(v))
        self.assertEqual(self.store.status()['reason'],'state_manifest_mismatch')

    def test_failed_restore_marks_preimage_aborted(self):
        self.snap();target=self.root/'target';fixture(target)
        put(target,'config/config.json',core('blue'));before=(target/'config/config.json').read_bytes()
        plan,_=m.restore_plan(self.dest,target)
        def fault(_):raise OSError('fixture')
        with self.assertRaises(OSError):m.restore(self.dest,target,expected_plan=plan['plan_sha256'],fault=fault)
        record=next((target/'.millennium-restore-history').glob('*/rollback.json'))
        self.assertEqual(m.parse_json(record.read_bytes(),'record')['status'],'aborted')
        self.assertEqual((target/'config/config.json').read_bytes(),before)

    def test_cold_replica_preserves_bounded_history(self):
        first=self.snap()['generation'];put(self.source,'config/config.json',core('blue'));self.snap()
        hot=self.root/'G';cold=self.root/'H';m.replicate(self.dest,hot);result=m.replicate(hot,cold)
        self.assertEqual(result['retained_generations'],2)
        self.assertTrue((cold/'history'/first/m.MANIFEST).is_file())
        self.assertEqual(m.verify_bundle(hot),m.verify_bundle(cold))

    def test_custom_runtime_history_replicates(self):
        runtime=self.root/'separate-runtime';store=m.SnapshotStore(self.source,self.dest,runtime)
        store.snapshot();put(self.source,'config/config.json',core('blue'));store.snapshot()
        result=m.replicate(self.dest,self.root/'G',runtime)
        self.assertEqual(result['retained_generations'],2)

    def test_real_cli_restore_round_trip_without_live_steam_changes(self):
        self.snap();target=self.root/'scratch-target';fixture(target)
        put(target,'config/config.json',core('blue'));before=(target/'config/config.json').read_bytes()
        def cli(*args):
            p=subprocess.run([sys.executable,'-I','-B',str(Path(m.__file__)),*args],capture_output=True,timeout=20)
            self.assertEqual(p.returncode,0,p.stdout)
            return json.loads(p.stdout)
        plan=cli('restore-plan','--destination',str(self.dest),'--target',str(target))
        restored=cli('restore','--destination',str(self.dest),'--target',str(target),'--expected-plan',plan['plan_sha256'])
        self.assertEqual(m.parse_json((target/'config/config.json').read_bytes(),'core')['general']['accentColor'],'lime')
        cli('rollback','--destination',str(target),'--rollback-id',restored['rollback_id'])
        self.assertEqual((target/'config/config.json').read_bytes(),before)

    def test_enabled_component_missing_from_bundle_blocks_restore(self):
        self.snap();files,manifest=m.verify_bundle(self.dest)
        for p in list(files):
            if p.startswith('plugins/sample/'):(self.dest/p).unlink();del files[p]
        put(self.dest,m.MANIFEST,m.make_manifest(files));target=self.root/'target';fixture(target)
        self.assertEqual(m.restore_plan(self.dest,target)[0]['status'],'blocked')

    def test_retry_after_preimage_interruption_returns_rollback_id(self):
        self.snap()
        target = self.root / 'target'; fixture(target)
        put(target, 'config/config.json', core('old-target'))
        before = (target / 'config/config.json').read_bytes()
        plan, _ = m.restore_plan(self.dest, target)
        original = m.atomic_json
        def interrupt(path, value):
            if path.name == 'rollback.json' and value.get('status') == 'prepared':
                raise KeyboardInterrupt('interrupted before record publication')
            return original(path, value)
        with mock.patch.object(m, 'atomic_json', side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        incomplete = next((target / '.millennium-restore-history').iterdir())
        preserved = file_view(incomplete)
        self.assertEqual((target / 'config/config.json').read_bytes(), before)
        result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        self.assertEqual(result['status'], 'complete')
        self.assertIn('restore_history_needs_attention', result['warnings'])
        self.assertEqual(file_view(incomplete), preserved)
        self.assertEqual(m.rollback_restore(target, result['rollback_id'])['status'], 'rolled_back')
        self.assertEqual((target / 'config/config.json').read_bytes(), before)

    def test_restore_preserves_malformed_and_unfinished_history(self):
        self.snap(); target = self.root / 'target'; fixture(target)
        history = target / '.millennium-restore-history'
        inputs = [b'{', b'[]', b'{}']
        for state in ('prepared', 'future-state'):
            identifier = m.generation_id()
            inputs.append((identifier, m.encoded({'schema':'millennium.restore-rollback.v2',
                'id':identifier, 'target':m.norm(target), 'status':state})))
        preserved = {}
        for value in inputs:
            identifier, data = value if isinstance(value, tuple) else (m.generation_id(), value)
            put(history / identifier, 'rollback.json', data)
            preserved[identifier] = data
        plan, _ = m.restore_plan(self.dest, target)
        result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['history_cleanup']['issues']), len(inputs))
        for identifier, data in preserved.items():
            self.assertEqual((history / identifier / 'rollback.json').read_bytes(), data)
        self.assertEqual(m.rollback_restore(target, result['rollback_id'])['status'], 'rolled_back')

    def test_history_cleanup_failure_does_not_fail_successful_restore(self):
        self.snap(); target = self.root / 'target'; fixture(target)
        for n in range(4):
            put(target, 'config/config.json', core(str(n)))
            plan, _ = m.restore_plan(self.dest, target)
            m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        original = m.remove_owned_tree
        def denied(path):
            if path.parent.name == '.millennium-restore-history':
                raise PermissionError('fixture cleanup denied')
            return original(path)
        put(target, 'config/config.json', core('final-preimage'))
        before = (target / 'config/config.json').read_bytes()
        plan, _ = m.restore_plan(self.dest, target)
        with mock.patch.object(m, 'remove_owned_tree', side_effect=denied):
            result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['history_cleanup']['status'], 'needs_attention')
        self.assertIn('restore_history_needs_attention', result['warnings'])
        m.rollback_restore(target, result['rollback_id'])
        self.assertEqual((target / 'config/config.json').read_bytes(), before)

    def test_restore_history_enumeration_failure_is_a_warning(self):
        self.snap(); target = self.root / 'target'; fixture(target)
        plan, _ = m.restore_plan(self.dest, target)
        original = Path.iterdir
        def denied(path):
            if path == target / '.millennium-restore-history':
                raise PermissionError('fixture enumeration denied')
            return original(path)
        with mock.patch.object(Path, 'iterdir', denied):
            result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['history_cleanup']['status'], 'needs_attention')
        self.assertEqual(m.rollback_restore(target, result['rollback_id'])['status'], 'rolled_back')

    def test_restore_retention_always_pins_new_current(self):
        self.snap(); target = self.root / 'target'; fixture(target)
        history = target / '.millennium-restore-history'
        for n in range(6):
            if history.exists():
                for item in history.iterdir():
                    os.utime(item, (2000000000 + n, 2000000000 + n))
            put(target, 'config/config.json', core(str(n)))
            plan, _ = m.restore_plan(self.dest, target)
            result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
            self.assertTrue((history / result['rollback_id'] / 'rollback.json').is_file())
            self.assertLessEqual(len(list(history.iterdir())), 4)
        self.assertEqual(m.rollback_restore(target, result['rollback_id'])['status'], 'rolled_back')

    def test_terminal_restore_record_is_not_rewritten_after_commit(self):
        self.snap(); target = self.root / 'target'; fixture(target)
        plan, _ = m.restore_plan(self.dest, target)
        original = m.atomic_json
        counts = {}
        def count_terminal(path, value):
            if path.name == 'rollback.json' and value.get('status') in ('complete', 'rolled_back'):
                key = value['status']
                counts[key] = counts.get(key, 0) + 1
                if counts[key] > 1:
                    raise OSError('duplicate post-commit record write')
            return original(path, value)
        with mock.patch.object(m, 'atomic_json', side_effect=count_terminal):
            result = m.restore(self.dest, target, expected_plan=plan['plan_sha256'])
            m.rollback_restore(target, result['rollback_id'])
        self.assertEqual(counts, {'complete':1, 'rolled_back':1})

if __name__ == '__main__':
    unittest.main(verbosity=2)
