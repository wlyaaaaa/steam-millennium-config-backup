# Steam Millennium 配置备份

此项目保存 Millennium 核心设置、快速 CSS 和插件/主题安装清单，提供可核验快照、独立副本、只读检查及可回滚的配置恢复。它不是 Steam 游戏、账号、全部插件数据或插件程序的完整备份。

## 快速使用

需要 PowerShell 7.2+、Python 3.11+（只用标准库）及 Windows 上已安装的 Steam/Millennium。无需安装 Python 第三方包。现有 `snapshot-millennium-config.ps1` 和注册脚本仍可调用，内部使用新入口；Windows PowerShell 5.1 仅用于启动兼容入口，不再运行备份核心。

```powershell
# 只读；不会创建目录、写日志或触发备份
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Status
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Verify
# 采集；默认源来自 Steam 注册表/常见安装路径
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Snapshot
# 测试仅使用虚构源和目标，不操作真实 Steam 或计划任务
pwsh -NoProfile -File tests/run-snapshot-tests.ps1
```

本机登记文件为 `E:\PCConfig\registries\steam_millennium_backup.json`。只有机器名和仓库位置均匹配时，正常的 Snapshot/Status 与任务管理入口才自动使用它，也可显式传 `-MachineConfig`。其他目录仍独立运行，不会误用 G/H 映射。机器绑定下拒绝更换采集源；实验应使用其他目标目录。登记包含已核验的解释器、源目录与 G 独立副本。

初次接续旧的无清单快照，先复核现有文件，然后用 `-AdoptExisting` 执行一次。旧文件经过内容检查并保存独立历史代后才升级。此选项不能绕过路径、内容或已有清单哈希检查。

## 备份范围与公开边界

| 内容 | 处理方式 |
|---|---|
| `config/config.json` | 严格解析，保存明确支持的核心、通知、插件启用与主题选项字段 |
| `config/quick.css` | 保存 UTF-8 快速 CSS，规范化换行并检查已知敏感模式 |
| `plugins/*/{plugin,metadata,install-state}.json` | 安装清单，仅供核对，不作为程序备份 |
| `themes/*/{metadata,skin,theme,options,waifus}.json` | 主题定义和清单，仅供版本/资源核对 |
| 代理地址、账号、密码、未知核心字段 | 不进入公开投影；覆盖报告列出省略字段名，不输出值 |
| 插件私有设置、缓存、账号/游戏库数据、日志、程序/图片/字体资源 | 不读取或不采集；恢复后需在插件或应用内另行核对 |

JSON 重复键、截断文本、非有限数字、错误类型会拒绝。解码后的凭据字段及已知凭据模式会检查；这是有范围的防误发布措施，不是任意私人内容检测器。新增插件目录会被发现并采集支持的清单；新增未知核心字段明确报告，不静默公开或承诺恢复。公开提交仍需复核实际差异。

## 连续更新、完整性和失败恢复

每一份快照都有 `snapshot-manifest.json`，记录生成代号、时间、软件版本观察、范围和每个文件的字节数/SHA-256。支持目录必须完整可读，启用组件必须存在，采集前后重复核对源。正常卸载在目录完整可读时传播删除；目录缺失、读取失败或枚举期间变化不是有效删除。

工作区内容与**上一份已生成清单**比较，不与不断变化的源比较。故而不需要每次快照后人工提交。真正的手工改动、额外未知文件或 Git 状态命令失败会停止覆盖；README 等非快照源码改动不阻断业务采集。

固定目标锁覆盖手工、计划任务及其他进程。发布先保存全部原件和写入计划，再逐文件替换，最后写清单并回读。中断时 `.millennium-transaction` 保留恢复信息；正式读入口拒绝未完成事务。下次采集可恢复快照事务，也可明确运行：

```powershell
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Recover -DestinationRoot '<受影响目标>'
```

这是**可恢复的多文件事务，不是整个文件系统的原子替换**。断电、磁盘硬件损坏和恶意并发不是由短时测试完全证明的场景。有外来修改与事务冲突时保留现场，不自动抹掉它。

`runtime/snapshots` 默认保留 4 份完整代，可用 `-Keep 2..32` 调整；每文件上限 8 MiB、一次数据上限 64 MiB、最多 4096 文件。无变化仍验证实际内容，不增加重复代，也不使用七天时间门槛。源、目标及运行时的重叠/联接路径被拒绝；运行时只允许目标的 `runtime` 或与源/目标均不重叠的目录。

`runtime/last-run.json` 保存最近尝试结果；`snapshot-state.json` 兼容旧时间入口但已绑定代号和清单哈希。时间、文件复制成功、Git 同步、G 副本、H 冷备和 Steam 中的实际效果分别验收。

## 恢复与回滚

先正常安装 Steam、Millennium 以及所需插件/主题。恢复不下载或运行任何插件，不替换安装元数据、主题程序定义、二进制或资源。目标版本/定义不匹配或主题引用资源缺失时停止，先通过软件本身完成安装或兼容迁移。

```powershell
# 预检只读；即使 Steam 正在运行也不会改变它
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode RestorePlan `
  -DestinationRoot '<含清单的备份>' -TargetRoot '<目标 millennium 目录>'
# 人工退出 Steam，使用预检返回的 plan_sha256；计划发生变化就拒绝
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Restore `
  -DestinationRoot '<含清单的备份>' -TargetRoot '<目标 millennium 目录>' `
  -ExpectedPlan '<plan_sha256>'
# 使用恢复返回的 rollback_id；目标若再次被手工修改则拒绝覆盖
pwsh -NoProfile -File tools/Invoke-MillenniumBackup.ps1 -Mode Rollback `
  -DestinationRoot '<目标 millennium 目录>' -RollbackId '<rollback_id>'
```

恢复合并受支持字段，并保留目标的网络配置与未知字段；可恢复快速 CSS。恢复前原件只保留在目标的 `.millennium-restore-history`，不进入公开仓库/副本。最多保留 4 次已完成、回滚或中止的恢复记录；未完成记录不自动清理。对实际 Steam 安装目录，恢复/回滚要求 Steam 已退出，不自动结束进程；隔离演练目录不受另一安装中正在运行的 Steam 影响。不能从缺失的插件私有数据推导它已恢复，最终主题显示与插件加载仍需 Steam 内实际检查。

## 每周任务与可见管理

```powershell
pwsh -NoProfile -File tools/Manage-MillenniumTask.ps1 -Mode Inspect
pwsh -NoProfile -File tools/Manage-MillenniumTask.ps1 -Mode Install
pwsh -NoProfile -File tools/Show-MillenniumBackupStatus.ps1
```

匹配本机的仓库会自动读取与安装一致的机器配置。任务名 `SteamMillenniumConfigSnapshot` 保持不变：每周日当地时间 19:30，当前交互用户、普通权限、允许错过后补跑，失败间隔 15 分钟重试 3 次，上限 10 分钟，同任务忽略重入。新运行器使用 PowerShell 7。GUI 提供状态刷新、立即采集、启停未来触发及打开 Windows 任务计划程序；关闭窗口不影响已登记任务。禁用任务只停止后续备份，不结束进行中的事务，不影响 Steam。

## 独立副本与开发维护

配置启用的 G 副本写入前核验 PCConfig 的卷身份和登记路径，复制当前快照和已保留历史并逐份验证，不依赖硬链接。G 不可用时保留本地结果，但整次自动任务返回失败，不能冒称完整成功。H 冷备由既有 PCConfig CoreRecovery 按登记集合接续，不新建 H 任务、不解锁或重新锁盘。

核心 Python API/CLI 都不联网；计划任务不自动 Git commit/push。人工维护提交源码/配置时明确检查公开差异，再正常同步。构建工具不应把运行记录、恢复原件和未知私有文件提交到 PUBLIC 仓库。

源码：`tools/millennium_backup.py`；Windows 入口、任务和窗口分别由 `Invoke-MillenniumBackup.ps1`、`Manage-MillenniumTask.ps1`、`Show-MillenniumBackupStatus.ps1` 拥有。PCConfig 只登记机器事实和精确恢复入口，不复制业务实现。测试涵盖连续采集、有效删除、源不完整、内容校验、锁、故障/中断、恢复计划、回滚和副本；隔离测试成功不等于真实 Steam 外观已经验证。

## 本机恢复链

本机 G 热备登记为 `G:\80_Backup\SteamMillennium`，H 冷备登记为 `H:\80_自动备份区\SteamMillennium`。这些是机器事实而非可移植默认目标。

```powershell
# 只同步已经验证的 G 快照到 H，复用现有冷备入口和 H 写入锁
pwsh -NoProfile -File E:\PCConfig\tools\Invoke-CoreRecoveryMaintenance.ps1 `
  -Mode Cold -ColdSetId steam_millennium -Execute -Json
```

H 必须符合 PCConfig 现行卷身份与保护状态合同，且恢复热上下文匹配当前登记。登记调整后可用 `-Mode Hot -ContextOnly -Execute -Json` 只更新恢复元数据，不同步其他模型或数据。普通冷备仍由原有任务负责。`H_media_auto_unlock_contract_mismatch` 等错误必须保留为未完成，不能改保护配置或绕过校验来制造成功。

状态窗口显示本地快照、自动任务和 G 热备状态；H 是独立冷备验收项。核心和回归测试均不联网，不自动 Git 提交、安装插件或停止 Steam。
