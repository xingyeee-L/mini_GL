param([switch]$Preview)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Database = Join-Path $ProjectRoot "data\mini_gl.sqlite3"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path -LiteralPath $Python -PathType Leaf) {
    & $Python -m mini_gl uninstall-preview --db $Database
}
Write-Host "原始资料目录永远不在卸载范围内。"
if ($Preview) { exit 0 }

$Answer = Read-Host "输入 UNINSTALL MINI_GL 仅删除应用数据库、备份、虚拟环境和开始菜单快捷方式"
if ($Answer -cne "UNINSTALL MINI_GL") {
    Write-Host "已取消，未删除任何内容。"
    exit 1
}

$OwnedTargets = @(
    (Join-Path $ProjectRoot "data\mini_gl.sqlite3"),
    (Join-Path $ProjectRoot "data\mini_gl.sqlite3-wal"),
    (Join-Path $ProjectRoot "data\mini_gl.sqlite3-shm"),
    (Join-Path $ProjectRoot "data\backups"),
    (Join-Path $ProjectRoot ".venv"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\mini_GL")
)
foreach ($Target in $OwnedTargets) {
    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
}
Write-Host "mini_GL 应用自有数据已清理；项目源码和原始资料均已保留。"
