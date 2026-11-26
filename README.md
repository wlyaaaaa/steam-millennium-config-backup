# Steam Millennium 配置备份

- **这是什么：** 保存 Steam 皮肤工具 Millennium 的核心设置、快捷样式，以及插件和主题清单；不包含游戏、账号和插件程序本身。
- **我怎么用：** 每周自动备份已于 2026 年 11 月 23 日停用。想核对现在有哪些变化，可以在实况看当前设置与旧快照的比较。
- **我还能看什么：** [停用前保存的衣橱清单](docs/wardrobe.md)和[历史换装记录](docs/wardrobe-history.md)。

换电脑时，按各自的入口安装 Steam、Millennium、插件和主题。停用时已清理备份盘上的副本，换机流程不恢复原备份任务。工具仍可核对明确指定的已有快照，恢复前先走只读预检。

`config`、`plugins`、`themes` 和 `snapshot-manifest.json` 是受版本管理的公开投影。完整快照使用被忽略的 `runtime/snapshots`，不会随 Git 发布。

整理已保存的快照时，先运行以下只读核验，只提交已核验的投影，运行记录和恢复原件保留在本机。

```powershell
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Status
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Verify
git status --short
git diff HEAD -- config plugins themes snapshot-manifest.json
```

`Status` 仍会显示原机器任务和副本的结果，停用后的任务缺失不会改变本地旧快照的内容。可选源文件读不全时，`changes` 为 `null`，`file_warnings` 说明原因。未通过核验就保留现场，不发布。

实况页通过 `docs/live.contract.json` 读取现有小输出。`Snapshot` 完成后顺带更新被忽略的
`runtime/live.json`；`Status`、`Verify` 仍然零写入。需要单独刷新测量时运行
`pwsh -File tools/Invoke-MillenniumBackup.ps1 -Mode Live`，只写测量，不备份或恢复 Steam。
机器上的共享采样已经接入比较读数，沿用显示采样并缓存 240 秒。取数时刻说明最近何时核对当前设置，保存日期仍取上一次成功备份；过期读数按源时刻标旧。
按需整理历史、公开清单和自有代码规模：`python tools/millennium_backup.py live --source <Millennium目录> --destination <备份目录> --runtime <原runtime目录> --live-output runtime/live.json --static-output docs/live.snapshot.json`。
静态内容未变时不改文件和取数时间；生成的清单文档、第三方组件及运行文件不计自有代码规模。
本机回归：`pwsh -File tests/run-snapshot-tests.ps1`；测试只使用临时合成目录，不恢复到正在用的 Steam。
