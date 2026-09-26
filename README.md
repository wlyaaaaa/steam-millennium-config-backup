# Steam Millennium 配置备份

- **这是什么：**保存 Millennium 的核心设置、快捷样式和插件、主题清单；不包含游戏、账号或插件程序。
- **我怎么用：**运行 `pwsh -File tools/Invoke-MillenniumBackup.ps1 -Mode Snapshot` 采集；已登记机器也可用每周任务。
- **怎么知道正常：**运行 `pwsh -File tools/Show-MillenniumBackupStatus.ps1` 看最近一次结果；`-Mode Verify` 可核对备份内容。
- **坏了怎么提醒我：**没有自动提醒；状态窗口能显示失败，发现问题直接跟 AI 说。
- **让 AI 做什么：**让 AI 查看状态、核对备份范围，或先做只读的恢复预检；实际恢复前确认目标。

需要迁移到新电脑时，先安装 Steam、Millennium 和所需插件、主题，再让 AI 按恢复预检结果处理。
