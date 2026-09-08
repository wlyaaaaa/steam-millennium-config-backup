# Steam Millennium 配置备份

本仓库是 **Steam + [Millennium](https://github.com/SteamClientHomebrew/Millennium) 库管理器** 的配置快照备份，用于在重装系统、迁移设备或误操作后快速恢复个性化设置。

> 备份来源：`C:\Program Files (x86)\Steam\millennium`
> 配置以所选 Git 提交或本地快照为准。`runtime/snapshot-state.json` 记录最近一次本机采集时间和文件数；它不会自动提交或推送 Git，也不能证明后来安装的插件仍与备份相同。

---

## 备份范围

本仓库**只包含用户配置文件**（JSON / CSS），不含任何二进制（DLL / EXE）、插件主题源码、缓存或日志。

| 目录 | 内容 | 说明 |
|------|------|------|
| `config/` | `config.json`、`quick.css` | Millennium 核心设置 + 全局自定义 CSS |
| `plugins/` | 各插件的 `plugin.json` / `metadata.json` / `install-state.json` | 记录已安装插件及其版本/提交号 |
| `themes/` | 各主题的 `metadata.json` / `skin.json` / `theme.json` / `options.json` / `waifus.json` | 记录已安装主题及其个性化选项 |

注意：`plugins/` 只备份插件清单、元数据和安装状态。插件自己的运行时设置、缓存、账号相关状态或插件私有 `config.json` 不在当前白名单内；恢复后需要在插件内重新检查这些设置。

### 为隐私而**刻意排除**的文件

| 文件 | 排除原因 |
|------|----------|
| `id_cache.json` | 含真实 **SteamID64**，不可公开 |
| `cache.json` | HLTB 游戏时长缓存，会暴露个人游戏库 |
| `lib/`、`bin/` | Millennium 二进制，可由官方安装器重新获取 |
| `themes/*/`（图片/字体/CSS 资源） | 体积大（约 14 MB），可由主题仓库重新下载 |
| `crashes/`、`debug.log` | 崩溃转储与运行日志 |

---

## 当前配置概览

### 通用设置（`config/config.json`）
- 强调色：`#00ff00`（纯绿）
- 更新通道：`stable`
- 启用 CSS 注入、JavaScript 注入
- 当前激活主题：**Adwaita-for-Steam**

### 快照保存的插件清单

| 插件 | 名称 | 版本 | 功能 |
|------|------|------|------|
| `extendium` | Extendium | 2.0.4 | 为 Steam 客户端提供 Chrome 扩展支持（SteamDB、Augmented Steam、uBlock Origin 等） |
| `steam-easygrid` | Easy SteamGrid | 4.1.0 | 快捷的 SteamGridDB 封面集成 |
| `hltb-for-millennium` | HLTB for Steam | 2.1.0 | 游戏页面显示 How Long To Beat 通关时长 |
| `size-on-disk` | Size on Disk | 1.1.0 | 即时显示游戏占用磁盘大小 |
| `steam-taskbar-progress` | Taskbar Download progress | 2.3.0 | 在 Windows 任务栏显示下载进度 |

当前启用：`extendium`、`size-on-disk`、`steam-easygrid`。

### 已安装主题

| 主题 | 来源 | 说明 |
|------|------|------|
| **Adwaita-for-Steam** | [`tkashkin/Adwaita-for-Steam`](https://github.com/tkashkin/Adwaita-for-Steam) | GNOME Adwaita 风格主题（当前激活） |
| **Zehn** | [`yurisuika/Zehn`](https://github.com/yurisuika/Zehn) | 高度可定制的现代化主题 |

`config.json` 内保存了两套主题的 `conditions`（开关选项）与 `themeColors`（配色变量）。这些值用于恢复原来的选择；实际外观还取决于重新安装的 Steam、Millennium 和主题版本。未做过目标机器的恢复验收前，不能保证新版本会原样呈现旧配置。

表格是仓库内 `plugin.json` 的版本记录，不是联网推荐的最新版，也不证明对应插件正在 Steam 中加载。当前启用项读取 `config.json` 的 `plugins.enabledPlugins`；各插件的源提交记录在 `metadata.json`。

---

## 如何恢复

1. 通过官方安装器安装 [Millennium](https://github.com/SteamClientHomebrew/Millennium)。
2. 在 Millennium 内重新安装上表中列出的插件与主题。
3. 退出 Steam，保留目标机器当前配置副本，再把本仓库 `config/`、`plugins/`、`themes/` 中的白名单文件合并复制回 `C:\Program Files (x86)\Steam\millennium\` 对应位置。不要删除再替换整个插件或主题目录：仓库没有它们的程序、图片、字体等资源。
4. 若新装插件或主题版本与备份不同，先按实际安装版本核对 `metadata.json` 和 `install-state.json`；旧清单只记录原来装了什么，复制它不能把新程序变回旧程序。不要用旧安装记录冒充当前状态。
5. 启动 Steam，检查主题、颜色、滚动条及启用插件；逐个检查插件自己的设置页面，必要时重新填写未备份的设置。配置格式变更或上游资源不可取得时，需要按对应版本处理，不能把文件复制成功当作恢复验收。

这里提供手工恢复规程，没有自动安装或一键恢复脚本。`tools/snapshot-millennium-config.ps1` 的方向始终是 **Steam 安装目录 → 备份目录**，不要把源与目标反过来作为恢复工具；它会重建目标中的三个快照目录。

## 更新本机快照

在仓库根目录执行：

```powershell
pwsh -NoProfile -File tools/snapshot-millennium-config.ps1
```

脚本先读取当前用户的 Steam 注册表路径；找不到时检查常见安装路径，也可用 `-SourceRoot` 指定 Millennium 目录。`-DestinationRoot` 默认为本仓库，`-RuntimeRoot` 默认为仓库的 `runtime/`。默认在上次成功快照后的 7 天内跳过；`-Force` 只跳过这个时间限制。

脚本拒绝源与目标相同或相互嵌套。备份仓库有未提交改动时，只有快照文件已经与当前源文件逐字节相同，或仅采集脚本自身有改动，才允许继续；存在不同的手工修改或其他脏文件时会报错，保留现场。先检查差异，确认允许覆盖后才考虑 `-AllowDirtyDestination`，它不会绕过路径检查与内容检查。

快照先在 `runtime/staging` 收集白名单文件，并检查禁用文件、扩展名、SteamID64 形式及非空代理用户名/密码，然后依次替换备份目录中的 `config/`、`plugins/`、`themes/`。这是分目录复制，不是原子事务；复制期间中断可能留下部分新快照。旧 Git 提交可供回退，但未提交的新改动不会自动获得额外历史副本。内容检查只覆盖脚本列出的规则，不是任意凭据或私人内容的通用识别器。

成功后 `runtime/snapshot-state.json` 写入采集 UTC 时间、源目录、目标目录和文件数。快照不会自动 commit（提交）或 push（推送）；准备公开提交时仍需检查实际差异。

## 每周自动快照与验证

```powershell
powershell.exe -NoProfile -File tools/register-millennium-config-snapshot-task.ps1
pwsh -NoProfile -File tests/run-snapshot-tests.ps1
```

注册命令会创建或更新当前用户的 `SteamMillenniumConfigSnapshot` 任务：每周日当地时间 19:30，通过 `wscript.exe` 与项目 VBS 启动器以隐藏窗口方式调用 Windows PowerShell。任务需要该用户已登录；错过计划时间后会尽快执行，失败每隔 15 分钟重试，最多 3 次，执行上限 10 分钟，同一任务已有实例时忽略新触发。VBS 会把子进程退出码交还任务计划程序。注册命令不是只读检查，也不会替你验证下一次运行成功。

测试只使用临时虚构配置，检查白名单复制、排除项、源与目标重叠、并发手工改动的保护以及 Windows PowerShell 5.1 兼容性。通过测试不等于目标机器已完成恢复，也不等于全部插件实际加载成功。日常可结合任务最后结果、快照时间与当前文件差异判断是否需要更新。

---

## 文件清单

```
config/
  ├─ config.json          # 核心配置（强调色、更新通道、插件开关、主题选项与配色）
  └─ quick.css            # 全局快速 CSS（将滚动条收窄为 4px 极简细线）
plugins/
  ├─ extendium/           # plugin.json + metadata.json + install-state.json
  ├─ hltb-for-millennium/
  ├─ size-on-disk/
  ├─ steam-easygrid/
  └─ steam-taskbar-progress/
themes/
  ├─ Adwaita-for-Steam/   # metadata.json + skin.json + theme.json
  └─ Zehn/                # metadata.json + skin.json + options.json + waifus.json
```

---


*配置快照由自动化脚本采集，人类指南单独维护。白名单以外的文件不随快照保存；公开内容仍以实际提交为准。*
