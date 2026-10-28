"""Run isolated regressions with concise output; no real Telegram messages."""
import os
import shutil
import subprocess
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
node=os.environ.get('NODE_BIN') or shutil.which('node')
checks=sorted((root/'tests').glob('check_*.py'))+sorted((root/'tests').glob('check_*.cjs'))
failed=[]
for path in checks:
    runner=sys.executable if path.suffix=='.py' else node
    if not runner:raise SystemExit('Node.js is required')
    result=subprocess.run([runner,str(path)],cwd=root,capture_output=True,text=True)
    print(('PASS ' if result.returncode==0 else 'FAIL ')+path.name,flush=True)
    if result.returncode:
        failed.append(path.name);print((result.stdout+result.stderr)[-5000:],flush=True)
if failed:raise SystemExit('Failed: '+', '.join(failed))
print(f'All {len(checks)} checks passed')
