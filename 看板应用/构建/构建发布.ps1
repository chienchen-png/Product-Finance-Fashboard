param([ValidateSet('本机','独立')][string]$目标 = '本机')
$ErrorActionPreference = 'Stop'
$应用根 = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$项目根 = [IO.Path]::GetFullPath((Split-Path -Parent $应用根))
Set-Location -LiteralPath $项目根
function 核项目内路径([string] $路径) {
    $绝对 = [IO.Path]::GetFullPath($路径)
    $前缀 = $项目根.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if ($绝对 -ne $项目根 -and -not $绝对.StartsWith($前缀, [StringComparison]::OrdinalIgnoreCase)) { throw "拒绝操作项目外路径：$绝对" }
    return $绝对
}
$产物 = $应用根
if ($目标 -eq '独立') {
    if (-not (Test-Path -LiteralPath (Join-Path $项目根 'requirements.txt'))) { throw '独立目标仅能在独立软件目录构建' }
    $产物 = $项目根
}
$标识 = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$暂存 = 核项目内路径 (Join-Path $应用根 ('构建缓存/发布_' + $标识))
$回滚 = 核项目内路径 (Join-Path $暂存 '回滚')
function 确认旧看板未占用 {
    $可执行路径 = [IO.Path]::GetFullPath((Join-Path $产物 '比赛看板.exe'))
    $占用进程 = @(Get-Process -Name '比赛看板' -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and [IO.Path]::GetFullPath($_.Path) -eq $可执行路径
    })
    if ($占用进程.Count -gt 0) { throw '看板正在运行；请关闭旧看板，等待服务退出后重新构建。原包未改变。' }
}
确认旧看板未占用
python -m compileall -q (Join-Path $应用根 '源码')
if ($LASTEXITCODE -ne 0) { throw '源码语法检查失败；原包未改变' }
New-Item -ItemType Directory -Path $暂存 -Force | Out-Null
python -m PyInstaller --noconfirm --clean --distpath (Join-Path $暂存 'dist') --workpath (Join-Path $暂存 'work') (Join-Path $PSScriptRoot '比赛看板.spec')
if ($LASTEXITCODE -ne 0) { throw '打包失败；原包未改变' }
$新包 = 核项目内路径 (Join-Path $暂存 'dist/比赛看板')
foreach ($名称 in @('比赛看板.exe','_internal')) {
    if (-not (Test-Path -LiteralPath (Join-Path $新包 $名称))) { throw "新包缺少$名称；原包未改变" }
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '发布说明.md') -Destination (Join-Path $新包 'README.md') -Force
python (Join-Path $应用根 '测试/验收发布包.py') --发布目录 $新包 --端口 8778 --空闲 5 --页面保持 8
if ($LASTEXITCODE -ne 0) { throw '新EXE验收失败；原包未改变' }
确认旧看板未占用
New-Item -ItemType Directory -Path $产物,$回滚 -Force | Out-Null
$已归档 = @(); $已安装 = @()
try {
    foreach ($名称 in @('比赛看板.exe','_internal')) {
        $旧路径 = 核项目内路径 (Join-Path $产物 $名称)
        if (Test-Path -LiteralPath $旧路径) {
            Move-Item -LiteralPath $旧路径 -Destination (Join-Path $回滚 $名称)
            $已归档 += $名称
        }
    }
    foreach ($名称 in @('比赛看板.exe','_internal')) {
        Move-Item -LiteralPath (核项目内路径 (Join-Path $新包 $名称)) -Destination (Join-Path $产物 $名称)
        $已安装 += $名称
    }
} catch {
    $失败现场 = 核项目内路径 (Join-Path $暂存 '失败安装')
    New-Item -ItemType Directory -Path $失败现场 -Force | Out-Null
    foreach ($名称 in $已安装) {
        Move-Item -LiteralPath (核项目内路径 (Join-Path $产物 $名称)) -Destination $失败现场
    }
    foreach ($名称 in $已归档) {
        Move-Item -LiteralPath (核项目内路径 (Join-Path $回滚 $名称)) -Destination (Join-Path $产物 $名称)
    }
    throw
}
$安全暂存 = 核项目内路径 $暂存
$缓存前缀 = [IO.Path]::GetFullPath((Join-Path $应用根 '构建缓存')).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $安全暂存.StartsWith($缓存前缀, [StringComparison]::OrdinalIgnoreCase)) { throw '暂存路径不安全，停止清理' }
Remove-Item -LiteralPath $安全暂存 -Recurse -Force
Write-Output ("产物：{0}；仅更新程序，账户数据保留" -f $产物)
