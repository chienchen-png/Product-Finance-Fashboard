import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '源码'))
"""以临时项目及假打包器验证发布更新保留真实数据。"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class BuildTests(unittest.TestCase):
    def test_running_package_is_rejected_before_build_or_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tools=root/'看板应用/构建';tools.mkdir(parents=True)
            shutil.copy2(Path(__file__).resolve().parents[1]/'构建/构建发布.ps1',tools/'构建发布.ps1')
            package=root/'看板应用';(package/'_internal').mkdir(parents=True)
            (package/'比赛看板.exe').write_bytes(b'original')
            wrapper=root/'run.ps1'
            wrapper.write_text('''function Get-Process {
 [pscustomobject]@{Id=123;Path=(Join-Path $PSScriptRoot '看板应用/比赛看板.exe')}
}
function python { throw '不应进入打包器' }
& (Join-Path $PSScriptRoot '看板应用/构建/构建发布.ps1')
''',encoding='utf-8-sig')
            result=subprocess.run(['pwsh','-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper)],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('看板正在运行',result.stderr.decode('utf-8',errors='replace'))
            self.assertEqual((package/'比赛看板.exe').read_bytes(),b'original')

    def test_build_does_not_delete_existing_user_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tools=root/'看板应用/构建';tools.mkdir(parents=True)
            shutil.copy2((Path(__file__).resolve().parents[1]/'构建/构建发布.ps1'),tools/'构建发布.ps1')
            shutil.copy2((Path(__file__).resolve().parents[1]/'构建/发布说明.md'),tools/'发布说明.md')
            package=root/'看板应用';(package/'_internal').mkdir(parents=True)
            (package/'_internal/old.dll').write_bytes(b'old runtime')
            (package/'比赛看板.exe').write_bytes(b'old exe')
            account=package/'数据/账户记录/比赛账户.json';account.parent.mkdir(parents=True)
            account.write_bytes(b'{"initial_cash":"1234567"}')
            personal=root/'比赛看板开源/数据/账户记录/比赛账户.json';personal.parent.mkdir(parents=True)
            personal.write_bytes(b'personal-account-unchanged')
            wrapper=root/'run.ps1'
            wrapper.write_text('''[Console]::OutputEncoding=[Text.Encoding]::UTF8
function python {
  $taskArgs=$args
  if ('PyInstaller' -notin $taskArgs) {$global:LASTEXITCODE=0;return}
  $i=[Array]::IndexOf($taskArgs,'--distpath')
  $taskDist=$taskArgs[$i+1]
  $wi=[Array]::IndexOf($taskArgs,'--workpath')
  New-Item -ItemType Directory -Path $taskArgs[$wi+1] -Force | Out-Null
  New-Item -ItemType Directory -Path (Join-Path $taskDist '比赛看板/_internal') -Force | Out-Null
  Set-Content -LiteralPath (Join-Path $taskDist '比赛看板/比赛看板.exe') -Value 'new exe'
  Set-Content -LiteralPath (Join-Path $taskDist '比赛看板/_internal/new.dll') -Value 'new runtime'
  $global:LASTEXITCODE=0
}
& (Join-Path $PSScriptRoot '看板应用/构建/构建发布.ps1')
''',encoding='utf-8-sig')
            r=subprocess.run(['pwsh','-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper)],capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode('utf-8',errors='replace'))
            self.assertTrue(account.exists(),'发布升级不得删除已有账户')
            self.assertEqual(account.read_bytes(),b'{"initial_cash":"1234567"}')
            self.assertIn('new exe',(package/'比赛看板.exe').read_text())
            self.assertFalse((personal.parent.parent.parent/'比赛看板.exe').exists())
            self.assertFalse(list(package.parent.glob('*.zip')))
            self.assertEqual(personal.read_bytes(),b'personal-account-unchanged')
            self.assertIn('new exe',(root/'看板应用/比赛看板.exe').read_text())
            self.assertTrue((root/'看板应用/_internal/new.dll').exists())

    def test_failed_runtime_install_restores_both_old_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);tools=root/'看板应用/构建';tools.mkdir(parents=True)
            shutil.copy2((Path(__file__).resolve().parents[1]/'构建/构建发布.ps1'),tools/'构建发布.ps1')
            shutil.copy2((Path(__file__).resolve().parents[1]/'构建/发布说明.md'),tools/'发布说明.md')
            package=root/'看板应用';(package/'_internal').mkdir(parents=True)
            (package/'_internal/old.dll').write_text('old runtime');(package/'比赛看板.exe').write_text('old exe')
            wrapper=root/'run.ps1'
            wrapper.write_text('''function python {
 $taskArgs=$args;if ('PyInstaller' -notin $taskArgs) {$global:LASTEXITCODE=0;return};$i=[Array]::IndexOf($taskArgs,'--distpath');$taskDist=$taskArgs[$i+1]
 New-Item -ItemType Directory -Path (Join-Path $taskDist '比赛看板/_internal') -Force | Out-Null
 Set-Content -LiteralPath (Join-Path $taskDist '比赛看板/比赛看板.exe') -Value 'new exe'
 Set-Content -LiteralPath (Join-Path $taskDist '比赛看板/_internal/new.dll') -Value 'new runtime'
 $global:LASTEXITCODE=0
}
function Move-Item { param($LiteralPath,$Destination)
 if ($LiteralPath -like '*dist*比赛看板*_internal') { throw 'injected runtime install failure' }
 Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination
}
& (Join-Path $PSScriptRoot '看板应用/构建/构建发布.ps1')
''',encoding='utf-8-sig')
            result=subprocess.run(['pwsh','-NoProfile','-ExecutionPolicy','Bypass','-File',str(wrapper)],capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((package/'比赛看板.exe').read_text(),'old exe')
            self.assertEqual((package/'_internal/old.dll').read_text(),'old runtime')


if __name__=='__main__':unittest.main()
