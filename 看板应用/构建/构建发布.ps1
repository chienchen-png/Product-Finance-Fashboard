$ErrorActionPreference = 'Stop'
$应用根 = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$项目根 = [IO.Path]::GetFullPath((Split-Path -Parent $应用根))
Set-Location -LiteralPath $项目根
function 核项目内路径([string] $路径) {
    $绝对 = [IO.Path]::GetFullPath($路径)
    $前缀 = $项目根.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $绝对.StartsWith($前缀, [StringComparison]::OrdinalIgnoreCase)) { throw "拒绝操作项目外路径：$绝对" }
    return $绝对
}
$标识 = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N').Substring(0,8)
$暂存 = 核项目内路径 (Join-Path $应用根 ('构建缓存/发布_' + $标识))
$产物 = 核项目内路径 (Join-Path $应用根 '发布/比赛看板')
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
if ($LASTEXITCODE -ne 0) { throw "打包失败；原包未改变，诊断保留在 $暂存" }
$新包 = 核项目内路径 (Join-Path $暂存 'dist/比赛看板')
foreach ($名称 in @('比赛看板.exe','_internal')) {
    if (-not (Test-Path -LiteralPath (Join-Path $新包 $名称))) { throw "新包缺少$名称；原包未改变" }
}
# 分发说明与仓库存档规则随包发布，避免队友拿到裸 exe。
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '发布说明.md') -Destination (Join-Path $新包 'README.md') -Force
Set-Content -LiteralPath (Join-Path $新包 '.gitignore') -Encoding utf8 -Value @('# 运行期本机数据，不进版本库', '数据/', '*.log', '*.log.1')
python -X utf8 (Join-Path $PSScriptRoot '准备仓库.py') $新包
if ($LASTEXITCODE -ne 0) { throw '独立仓库准备失败；原包未改变' }
python (Join-Path $应用根 '测试/验收发布包.py') --发布目录 $新包 --端口 8778 --空闲 5 --页面保持 8
if ($LASTEXITCODE -ne 0) { throw "新EXE验收失败；原包未改变，诊断保留在 $暂存" }
确认旧看板未占用
New-Item -ItemType Directory -Path $产物 -Force | Out-Null
New-Item -ItemType Directory -Path $回滚 -Force | Out-Null
$已归档 = @()
$已安装 = @()
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
    foreach ($名称 in @('README.md','.gitignore','AGENTS.md','LICENSE','智能体工具.py','requirements.txt','requirements-dev.txt','看板应用')) {
        $附属文件 = 核项目内路径 (Join-Path $新包 $名称)
        if (Test-Path -LiteralPath $附属文件) {
            Copy-Item -LiteralPath $附属文件 -Destination $产物 -Recurse -Force
        }
    }
} catch {
    $失败现场 = 核项目内路径 (Join-Path $暂存 '失败安装')
    New-Item -ItemType Directory -Path $失败现场 -Force | Out-Null
    foreach ($名称 in $已安装) {
        if (Test-Path -LiteralPath (Join-Path $产物 $名称)) {
            Move-Item -LiteralPath (核项目内路径 (Join-Path $产物 $名称)) -Destination (Join-Path $失败现场 $名称)
        }
    }
    foreach ($名称 in $已归档) {
        if (-not (Test-Path -LiteralPath (Join-Path $产物 $名称))) {
            Move-Item -LiteralPath (核项目内路径 (Join-Path $回滚 $名称)) -Destination (Join-Path $产物 $名称)
        }
    }
    throw
}
Remove-Item -LiteralPath (核项目内路径 $暂存) -Recurse -Force
$大小 = (Get-ChildItem -LiteralPath $产物 -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Output ("产物：{0}（{1:N1} MB）；账户数据保留；未保留历史构建" -f $产物, $大小)
