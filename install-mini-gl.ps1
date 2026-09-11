param(
    [switch]$NoShortcut,
    [switch]$SkipDependencies,
    [switch]$IncludeML
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Launcher = Join-Path $ProjectRoot "start-mini-gl.cmd"
$Command = Join-Path $ProjectRoot ".venv\Scripts\mini-gl.cmd"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "mini_GL requires Python 3.11 or newer" }
    py -3 -m venv (Join-Path $ProjectRoot ".venv")
}
if (-not $SkipDependencies) {
    & $Python -m pip install --requirement (Join-Path $ProjectRoot "requirements-runtime.lock")
    if ($IncludeML) {
        & $Python -m pip install --requirement (Join-Path $ProjectRoot "requirements-ml.lock")
    }
}
$CommandContent = "@echo off`r`nchcp 65001 >nul`r`nset `"PYTHONPATH=$ProjectRoot\src`"`r`n`"$Python`" -m mini_gl %*`r`n"
Set-Content -LiteralPath $Command -Value $CommandContent -Encoding utf8
if (-not $NoShortcut) {
    $ShortcutDirectory = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\mini_GL"
    New-Item -ItemType Directory -Path $ShortcutDirectory -Force | Out-Null
    $ShortcutPath = Join-Path $ShortcutDirectory "mini_GL.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $Launcher
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.Description = "mini_GL 本地知识工作台"
    $Shortcut.Save()
}

& $Python -m mini_gl product-status --db (Join-Path $ProjectRoot "data\mini_gl.sqlite3")
Write-Host "mini_GL 安装准备完成。运行 start-mini-gl.cmd 或从开始菜单启动。"
