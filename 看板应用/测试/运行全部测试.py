"""执行本项目全部单元与本机浏览器测试；不访问金融接口。"""
from pathlib import Path
import subprocess
import sys

folder = Path(__file__).resolve().parent
failed = []
for path in sorted(folder.glob('测试*.py')):
    print(path.name, flush=True)
    if subprocess.run([sys.executable, '-X', 'utf8', str(path)]).returncode:
        failed.append(path.name)
if failed:
    print('失败：' + '、'.join(failed))
    raise SystemExit(1)
print('全部测试文件通过')
