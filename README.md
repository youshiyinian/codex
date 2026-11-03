# Codex CLI 简体中文汉化版（Windows）

这个分支（`zh-cn`）只放汉化工具，不包含 Codex 源码：

- `i18n/zh-CN/*.json`：中英对照翻译表，按文件分组。
- `i18n/apply.py`：把翻译表应用到官方源码。只替换界面上显示的字符串，在比较/匹配中用到的字符串会自动跳过，保证程序逻辑不变。
- `.github/workflows/build-zh.yml`：每 6 小时检查一次官方 [openai/codex](https://github.com/openai/codex) 是否发布了新正式版，有就自动“拉取官方源码 → 套用翻译 → 编译 Windows 版 → 发布 Release”。修改翻译表并推送后也会自动重新编译。
- `scripts/codex-update.ps1`：一键安装/更新脚本。

## 安装

前提：已安装 Node.js（带 npm）。在 PowerShell 7 中运行：

```powershell
irm https://raw.githubusercontent.com/youshiyinian/codex/zh-cn/scripts/codex-update.ps1 | iex
```

脚本会：

1. 用 npm 安装与汉化版相同版本的官方 `@openai/codex`（保证配套文件一致）；
2. 下载汉化版 `codex.exe`，校验 SHA256 后替换官方的 `codex.exe`（原文件备份为 `codex.exe.official`）；
3. 在 PowerShell 配置里注册 `codex-update` 命令。

## 日常更新

```powershell
codex-update            # 更新到最新汉化版（官方发布新版后通常 1~2 小时内可用）
codex-update -Force     # 强制重新安装
codex-update -Restore   # 恢复官方英文版
```

如果你直接运行了 `npm install -g @openai/codex`，界面会变回英文，再运行一次 `codex-update` 即可。

## 本地试用翻译

```bash
git clone --depth 1 --branch rust-v0.166.0 https://github.com/openai/codex.git upstream
python i18n/apply.py upstream
```

输出中的“警告: 未找到原文”表示官方改了那句英文，对应位置会显示英文，更新翻译表即可。
