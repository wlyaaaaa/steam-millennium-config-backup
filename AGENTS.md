# Steam Millennium backup

This project owns snapshot/restore semantics. PCConfig owns this machine's binding,
Task Scheduler and G/H media identities. Do not duplicate global authorization rules.

- Read-only entry: `tools/Invoke-MillenniumBackup.ps1 -Mode Status` or `-Mode Verify`.
  `RestorePlan` is also zero-write. `Snapshot`, `Recover`, `Restore`, `Rollback`,
  `Replicate`, task Install/Enable/Disable are writes, never checks.
- PowerShell 7.2+ launches the standard-library Python 3.11+ engine. Preserve old
  wrapper names, but do not restore the old time throttle or dirty-workspace bypass.
- `config`, `plugins`, `themes` and `snapshot-manifest.json` are a verified public
  projection. Runtime/transaction/restore preimages are local and ignored.
- Unknown core settings are reported, not published. Plugin-private settings and
  executable assets are not read or backed up. No restore overwrites installation
  metadata, starts/stops Steam, installs components, or runs plugin code.
- Official readers fail during a pending transaction. Use the Recover command,
  under the destination's fixed OS lock, to resolve interruption; never hand-delete
  transaction preimages. Manual conflicts are preserved, not forced away.
- Run `pwsh -File tests/run-snapshot-tests.ps1`. Tests use synthetic temporary roots;
  live source reads, actual task execution, G replica and live Steam UI acceptance
  remain separate checks. Do not restore into live Steam as a test.
- Machine entry is `E:\PCConfig\registries\steam_millennium_backup.json` on the
  registered host. Its absence means a portable local-only invocation; never invent
  a G/H disk identity. Public Git publication is separate from local capture.
