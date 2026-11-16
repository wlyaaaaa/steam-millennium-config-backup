# Steam Millennium 配置备份

- **这是什么：** 备份 Steam 皮肤工具 Millennium 的核心设置、快捷样式，以及插件和主题清单；不包含游戏、账号和插件程序本身。
- **我怎么用：** 每周一 10:30（北京时间）自动备份，平时不用管；想马上备份一次，跟 AI 说一声。重装任务保持现有 UTC 02:30 触发时刻，不随电脑本地时区改动。
- **怎么知道正常：** 请 AI 看最近一次备份的结果，也可以让它核对备份内容。
- **坏了怎么提醒我：** 没有自动提醒，出问题直接跟 AI 说。
- **让 AI 做什么：** 查看备份状态、核对备份内容；恢复前先让它做一次只读预检，确认要恢复到哪里。

换电脑时，先装好 Steam、Millennium 和需要的插件、主题，再让 AI 按预检结果恢复设置。

实况页通过 `docs/live.contract.json` 读取现有小输出。`Snapshot` 完成后顺带更新被忽略的
`runtime/live.json`；`Status`、`Verify` 仍然零写入。需要单独刷新测量时运行
`pwsh -File tools/Invoke-MillenniumBackup.ps1 -Mode Live`，只写测量，不备份或恢复 Steam。
现有每周任务不足以保持五分钟读数新鲜，共享采样流程还需接上此入口；过期读数按源时刻标旧。
按需整理历史、公开清单和自有代码规模：`python tools/millennium_backup.py live --source <Millennium目录> --destination <备份目录> --runtime <原runtime目录> --live-output runtime/live.json --static-output docs/live.snapshot.json`。
静态内容未变时不改文件和取数时间；生成的清单文档、第三方组件及运行文件不计自有代码规模。
本机回归：`pwsh -File tests/run-snapshot-tests.ps1`；测试只使用临时合成目录，不恢复到正在用的 Steam。
