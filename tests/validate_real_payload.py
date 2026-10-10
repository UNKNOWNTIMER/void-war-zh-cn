"""Exercise the real public payload against copied resources in a fake game.

Only synthetic save data is used. The source game resources are read/copied,
never modified. The real installed game is never opened or invoked.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
from patcher_core import Installer
from payload_format import ORIGINAL_FILES, PAYLOAD_FILES, sha

def validate(original,payload):
    original=Path(original).resolve();payload=Path(payload).resolve()
    source_hashes={p:sha(original/p) for p in ORIGINAL_FILES}
    manifest=json.loads((payload/'payload.json').read_text('utf8'))
    with tempfile.TemporaryDirectory(prefix='VWZH-real-payload-') as temp:
        root=Path(temp);game=root/"汉化 测试 [路径] & '引号'";game.mkdir()
        (game/'Void War.exe').write_bytes(b'Synthetic marker only; not executable')
        for p in ORIGINAL_FILES:
            target=game/p;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original/p,target)
        profile=root/'synthetic_user'/'profile.sav';profile.parent.mkdir()
        profile.write_bytes(b'{"savedSettings":{"currLanguage":0.0},"synthetic_progress":100}\0')
        (profile.parent/'autosave.sav').write_bytes(b'synthetic save')
        (profile.parent/'score.sav').write_bytes(b'synthetic score')
        save_hashes={n:sha(profile.parent/n) for n in ['autosave.sav','score.sav']}
        installer=Installer(payload,game,profile,running=lambda:False)
        installed=installer.run('install')
        assert sha(game/'data.win')==manifest['delta']['target_sha256']
        assert all(sha(game/x['path'])==x['sha256'] for x in manifest['files'])
        profile.write_bytes(profile.read_bytes().replace(b'100',b'987654'))
        restored=installer.run('restore')
        assert all(sha(game/p)==source_hashes[p] for p in ORIGINAL_FILES)
        assert profile.read_bytes()==b'{"savedSettings":{"currLanguage":0.0},"synthetic_progress":987654}\0'
        assert all(sha(profile.parent/n)==s for n,s in save_hashes.items())
    assert all(sha(original/p)==s for p,s in source_hashes.items())
    return {'status':'PASS','engine_source_sha256':manifest['delta']['source_sha256'],
            'engine_target_sha256':manifest['delta']['target_sha256'],'installed_resource_hashes_verified':1+len(PAYLOAD_FILES),
            'restored_original_hashes_verified':len(ORIGINAL_FILES),'current_progress_preserved':True,
            'synthetic_autosave_and_score_untouched':True,'source_originals_unchanged':True,
            'real_game_executable_or_real_saves_accessed':False,'special_unicode_space_punctuation_path':True,
            'installed_result':installed,'restored_result':restored}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-dir',type=Path,required=True);p.add_argument('--payload',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();report=validate(a.original_dir,a.payload)
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
