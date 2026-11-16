# Steam Millennium 配置备份

- **这是什么：** 备份 Steam 皮肤工具 Millennium 的核心设置、快捷样式，以及插件和主题清单；不包含游戏、账号和插件程序本身。
- **我怎么用：** 每周一 10:30（北京时间）自动备份，平时不用管；想马上备份一次，跟 AI 说一声。重装任务保持现有 UTC 02:30 触发时刻，不随电脑本地时区改动。
- **怎么知道正常：** 请 AI 看最近一次备份的结果，也可以让它核对备份内容。
- **坏了怎么提醒我：** 没有自动提醒，出问题直接跟 AI 说。
- **让 AI 做什么：** 查看备份状态、核对备份内容；恢复前先让它做一次只读预检，确认要恢复到哪里。

换电脑时，先装好 Steam、Millennium 和需要的插件、主题，再让 AI 按预检结果恢复设置。

每周任务只负责本地快照和登记的 G 副本，不自动提交或推送 Git。`config`、`plugins`、
`themes` 和 `snapshot-manifest.json` 是受版本管理的公开投影；时间、代号或 Steam 版本变化
也会产生待提交差异，不代表备份失败。保留的完整快照仍在被忽略的 `runtime/snapshots` 中。

每周公开发布由维护本项目的 AI 负责：查看本周结果或维护仓库时，先运行以下只读核验，
再复核这四处的实际差异，只提交已核验的投影并正常推送；不要把运行记录或恢复原件加入 Git。

```powershell
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Status
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Verify
git status --short
git diff HEAD -- config plugins themes snapshot-manifest.json
```

`Status` 的本地、任务、G 和 H 结果分别看；可选源文件读不全时，`changes` 为 `null`，
`file_warnings` 说明原因，不把它算成删除。未通过核验就保留现场，不发布。
没有 AI 接手时不会自动发布或提醒；待发布内容一直能在上面两条 Git 命令里看到，
采集失败则看 `Status`、`runtime/last-run.json` 和 `runtime/machine-run.json`。

实况页通过 `docs/live.contract.json` 读取现有小输出。`Snapshot` 完成后顺带更新被忽略的
`runtime/live.json`；`Status`、`Verify` 仍然零写入。需要单独刷新测量时运行
`pwsh -File tools/Invoke-MillenniumBackup.ps1 -Mode Live`，只写测量，不备份或恢复 Steam。
现有每周任务不足以保持五分钟读数新鲜，共享采样流程还需接上此入口；过期读数按源时刻标旧。
按需整理历史、公开清单和自有代码规模：`python tools/millennium_backup.py live --source <Millennium目录> --destination <备份目录> --runtime <原runtime目录> --live-output runtime/live.json --static-output docs/live.snapshot.json`。
静态内容未变时不改文件和取数时间；生成的清单文档、第三方组件及运行文件不计自有代码规模。
本机回归：`pwsh -File tests/run-snapshot-tests.ps1`；测试只使用临时合成目录，不恢复到正在用的 Steam。
