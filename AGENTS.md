# Steam Millennium backup

This project owns snapshot/restore semantics. PCConfig owns this machine's
source binding and Windows system backup. Do not duplicate global authorization rules.

- Read-only entry: `tools/Invoke-MillenniumBackup.ps1 -Mode Status` or `-Mode Verify`.
  `RestorePlan` is also zero-write. `Snapshot`, `Recover`, `Restore`, `Rollback`,
  `Replicate` and `Live` (measurement output only) are writes, never checks.
- PowerShell 7.2+ launches the standard-library Python 3.11+ engine. Do not restore
  the old time throttle or dirty-workspace bypass.
- The former weekly task is retired. The current Windows system backup covers the installed configuration.
- `config`, `plugins`, `themes` and `snapshot-manifest.json` are a verified public
  projection. Runtime/transaction/restore preimages are local and ignored.
- Unknown core settings are reported, not published. Plugin-private settings and
  executable assets are not read or backed up. No restore overwrites installation
  metadata, starts/stops Steam, installs components, or runs plugin code.
- Official readers fail during a pending transaction. Use the Recover command,
  under the destination's fixed OS lock, to resolve interruption; never hand-delete
  transaction preimages. Manual conflicts are preserved, not forced away.
- Run `pwsh -File tests/run-snapshot-tests.ps1`. Tests use synthetic temporary roots;
  live source reads and live Steam UI acceptance remain separate checks. Do not
  restore into live Steam as a test.
- Machine entry is `E:\PCConfig\registries\steam_millennium_backup.json` on the
  registered host. Its absence means a portable local-only invocation. Public Git publication is separate from local capture.
- A snapshot saves supported core settings and quick CSS for restoration; plugin
  and theme manifests are inventory only. Keep the user's existing choice that
  source deletions propagate only after a complete, readable source scan.
- Taking a snapshot does not commit or push to Git. Replicate takes an explicit target.
