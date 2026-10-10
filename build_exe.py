"""Reproducible offline one-file build after installing pinned build tools."""
import json
import argparse
import os
from pathlib import Path
import sys
import PyInstaller.__main__

ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--payload-dir',type=Path,default=ROOT/'payload')
p.add_argument('--output-dir',type=Path,default=ROOT/'dist')
p.add_argument('--work-dir',type=Path,default=ROOT/'.build')
a=p.parse_args()
payload=a.payload_dir.resolve();dist=a.output_dir.resolve();work=a.work_dir.resolve()
os.chdir(ROOT)
# Exclude unrelated application DLL locations from analysis and subprocesses.
base=Path(sys.base_prefix);windows=Path(os.environ.get('SystemRoot',r'C:\Windows'))
os.environ['PATH']=os.pathsep.join(str(p) for p in [Path(sys.executable).parent,base,base/'DLLs',windows/'System32',windows])
assert (payload/'payload.json').is_file(), 'Run build_payload.py first'
PyInstaller.__main__.run(['--noconfirm','--clean','--onefile','--windowed','--noupx',
    '--name','VoidWar_Chinese_Patch','--distpath',str(dist),'--workpath',str(work/'work'),'--specpath',str(work),
    '--icon',str(ROOT/'assets/installer.ico'),
    '--add-data',str(ROOT/'assets')+os.pathsep+'assets',
    '--add-data',str(payload)+os.pathsep+'payload',str(ROOT/'installer_gui.py')])
from payload_format import sha
exe=dist/'VoidWar_Chinese_Patch.exe'
report={'status':'BUILT','exe':'VoidWar_Chinese_Patch.exe','bytes':exe.stat().st_size,'sha256':sha(exe),
        'python_version':sys.version.split()[0],'pyinstaller_version':__import__('PyInstaller').__version__,
        'payload_manifest_sha256':sha(payload/'payload.json'),'code_signed':False,
        'validation':'Run tests and frozen self-check separately; BUILT alone is not acceptance.'}
(work/'build_report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report,indent=2))
