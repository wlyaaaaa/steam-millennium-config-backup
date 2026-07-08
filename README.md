# Steam Millennium 配置备份

本仓库是 **Steam + [Millennium](https://github.com/SteamClientHomebrew/Millennium) 库管理器** 的配置快照备份，用于在重装系统、迁移设备或误操作后快速恢复个性化设置。

> 备份来源：`C:\Program Files (x86)\Steam\millennium`
> 备份日期：2026-07-05

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

### 已安装插件

| 插件 | 名称 | 版本 | 功能 |
|------|------|------|------|
| `extendium` | Extendium | 2.0.4 | 为 Steam 客户端提供 Chrome 扩展支持（SteamDB、Augmented Steam、uBlock Origin 等） |
| `steam-easygrid` | Easy SteamGrid | 4.0.1 | 快捷的 SteamGridDB 封面集成 |
| `hltb-for-millennium` | HLTB for Steam | 2.1.0 | 游戏页面显示 How Long To Beat 通关时长 |
| `size-on-disk` | Size on Disk | 1.0.0 | 即时显示游戏占用磁盘大小 |
| `steam-taskbar-progress` | Taskbar Download progress | 2.2.2 | 在 Windows 任务栏显示下载进度 |

当前启用：`extendium`、`size-on-disk`、`steam-easygrid`。

### 已安装主题

| 主题 | 来源 | 说明 |
|------|------|------|
| **Adwaita-for-Steam** | [`tkashkin/Adwaita-for-Steam`](https://github.com/tkashkin/Adwaita-for-Steam) | GNOME Adwaita 风格主题（当前激活） |
| **Zehn** | [`yurisuika/Zehn`](https://github.com/yurisuika/Zehn) | 高度可定制的现代化主题 |

`config.json` 内已保存两套主题的完整 `conditions`（开关选项）与 `themeColors`（配色变量），恢复后即为当前外观。

---

## 如何恢复

1. 通过官方安装器安装 [Millennium](https://github.com/SteamClientHomebrew/Millennium)。
2. 在 Millennium 内重新安装上表中列出的插件与主题。
3. 将本仓库的 `config/`、`plugins/`、`themes/` 覆盖回 `C:\Program Files (x86)\Steam\millennium\` 对应目录。
4. 重启 Steam，并逐个检查插件自己的设置页面；这些插件私有设置不保证由本仓库恢复。

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

*本备份由自动化脚本生成，仅含个性化配置，不含任何账号凭证或可定位个人身份的信息。*
