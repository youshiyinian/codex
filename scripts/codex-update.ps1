<#
.SYNOPSIS
  安装或更新 Codex CLI 汉化版（Windows x64）。

.DESCRIPTION
  1. 读取汉化仓库最新 Release 对应的官方版本号；
  2. 用 npm 安装同版本的官方 @openai/codex（保证配套文件一致）；
  3. 用汉化版 codex.exe 替换官方 codex.exe（原文件备份为 codex.exe.official）。

.EXAMPLE
  codex-update            # 安装/更新到最新汉化版
  codex-update -Restore   # 恢复官方英文版
  codex-update -Force     # 即使版本相同也重新安装
#>
[CmdletBinding()]
param(
    [string]$Repo = "youshiyinian/codex",
    [switch]$Restore,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Find-CodexExe {
    $npmRoot = (& npm root -g).Trim()
    $base = Join-Path $npmRoot "@openai\codex"
    if (-not (Test-Path $base)) { return $null }
    Get-ChildItem -Path $base -Recurse -Filter codex.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'vendor\\x86_64-pc-windows-msvc\\bin\\codex\.exe$' } |
        Select-Object -First 1 -ExpandProperty FullName
}

function Get-RemoteText([string]$Url) {
    $content = (Invoke-WebRequest -Headers @{ "User-Agent" = "codex-zh-updater" } -Uri $Url).Content
    if ($content -is [byte[]]) { $content = [Text.Encoding]::UTF8.GetString($content) }
    return ([string]$content).Trim()
}

function Get-InstalledNpmVersion {
    $json = & npm ls -g @openai/codex --depth=0 --json 2>$null | Out-String
    try { return ($json | ConvertFrom-Json).dependencies.'@openai/codex'.version } catch { return $null }
}

function Assert-CodexNotRunning {
    $procs = Get-Process -Name codex -ErrorAction SilentlyContinue
    if ($procs) {
        throw "检测到 Codex 正在运行，请先退出所有 Codex 窗口后再试。"
    }
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "未找到 npm，请先安装 Node.js（https://nodejs.org）。"
}

Assert-CodexNotRunning

if ($Restore) {
    $exe = Find-CodexExe
    if (-not $exe) { throw "未找到通过 npm 安装的 Codex。" }
    if (Test-Path "$exe.official") {
        Copy-Item "$exe.official" $exe -Force
        Write-Host "已恢复官方英文版。" -ForegroundColor Green
    } else {
        & npm install -g @openai/codex
        Write-Host "已重新安装官方英文版。" -ForegroundColor Green
    }
    return
}

Write-Host "正在获取最新汉化版信息..."
$headers = @{ "User-Agent" = "codex-zh-updater" }
$release = Invoke-RestMethod -Headers $headers "https://api.github.com/repos/$Repo/releases/latest"
$zipAsset = $release.assets | Where-Object { $_.name -eq "codex-zh-x86_64-pc-windows-msvc.zip" }
$verAsset = $release.assets | Where-Object { $_.name -eq "version.txt" }
$shaAsset = $release.assets | Where-Object { $_.name -eq "sha256.txt" }
if (-not $zipAsset -or -not $verAsset) { throw "Release $($release.tag_name) 缺少安装文件。" }

$version = Get-RemoteText $verAsset.browser_download_url
Write-Host "最新汉化版对应官方版本：$version"

$stateDir = Join-Path $env:LOCALAPPDATA "codex-zh"
New-Item -ItemType Directory -Force $stateDir | Out-Null
$stateFile = Join-Path $stateDir "installed.txt"

$installed = Get-InstalledNpmVersion
$exe = Find-CodexExe
$stamp = if (Test-Path $stateFile) { (Get-Content $stateFile -Raw).Trim() } else { "" }
$wanted = "$($release.tag_name)|$($zipAsset.updated_at)"
if (-not $Force -and $installed -eq $version -and $exe -and $stamp -eq "$wanted|$((Get-Item $exe).Length)") {
    Write-Host "已经是最新汉化版（$version），无需更新。" -ForegroundColor Green
    return
}

if ($installed -ne $version -or -not $exe) {
    Write-Host "正在用 npm 安装官方 @openai/codex@$version（下载较大，请稍候）..."
    & npm install -g "@openai/codex@$version"
    if ($LASTEXITCODE -ne 0) { throw "npm 安装失败。" }
    $exe = Find-CodexExe
    if (-not $exe) { throw "安装后仍未找到 codex.exe。" }
    Copy-Item $exe "$exe.official" -Force
} elseif (-not (Test-Path "$exe.official")) {
    Copy-Item $exe "$exe.official" -Force
}

$tmp = Join-Path $env:TEMP "codex-zh-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Force $tmp | Out-Null
try {
    $zip = Join-Path $tmp "codex-zh.zip"
    Write-Host "正在下载汉化版 codex.exe..."
    Invoke-WebRequest -Headers $headers -Uri $zipAsset.browser_download_url -OutFile $zip
    if ($shaAsset) {
        $expected = Get-RemoteText $shaAsset.browser_download_url
        $actual = (Get-FileHash $zip -Algorithm SHA256).Hash
        if ($expected -ne $actual) { throw "下载文件校验失败（SHA256 不一致），已中止。" }
    }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    Assert-CodexNotRunning
    Copy-Item (Join-Path $tmp "codex.exe") $exe -Force
    Set-Content -Path $stateFile -Value "$wanted|$((Get-Item $exe).Length)" -NoNewline
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

# 把本脚本保存到本地，并在 PowerShell 配置中注册 codex-update 命令
$selfCopy = Join-Path $stateDir "codex-update.ps1"
if ($PSCommandPath -and ($PSCommandPath -ne $selfCopy)) {
    Copy-Item $PSCommandPath $selfCopy -Force
} elseif (-not $PSCommandPath) {
    Invoke-WebRequest -Headers $headers -Uri "https://raw.githubusercontent.com/$Repo/zh-cn/scripts/codex-update.ps1" -OutFile $selfCopy
}
$profileLine = "function codex-update { & `"$selfCopy`" @args }"
if (-not (Test-Path $PROFILE)) { New-Item -ItemType File -Force $PROFILE | Out-Null }
if (-not (Select-String -Path $PROFILE -SimpleMatch "codex-update.ps1" -Quiet)) {
    Add-Content -Path $PROFILE -Value "`n# Codex 汉化版更新命令`n$profileLine"
    Write-Host "已在 PowerShell 配置中添加 codex-update 命令（新开窗口后可用）。"
}

Write-Host "完成！Codex 汉化版 $version 已安装，运行 codex 即可使用。" -ForegroundColor Green
