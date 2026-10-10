"""Destructive fault scenarios run only inside synthetic temporary fixtures."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from payload_format import ORIGINAL_FILES, EXTRA_FILES, PAYLOAD_FILES, build_delta, sha
from patcher_core import Installer, PatchError, BACKUP, TXN, game_lock, profile_change

class Fixture:
    def __init__(self, root):
        self.root = Path(root); self.game = self.root / "游戏 空格 [方括号] & '单引号'"; self.game.mkdir()
        self.original = self.root / 'original'; self.original.mkdir()
        self.payload = self.root / 'payload'; self.payload.mkdir()
        self.profile = self.root / '用户 设置' / 'profile.sav'; self.profile.parent.mkdir()
        self.raw = b'{\r\n  "progress": 7, "savedSettings": {"currLanguage" : 2.0}, "name": "kept"\r\n}\0'
        self.profile.write_bytes(self.raw)
        (self.profile.parent / 'autosave.sav').write_bytes(b'autosave untouched')
        (self.profile.parent / 'score.sav').write_bytes(b'score untouched')
        (self.game / 'Void War.exe').write_bytes(b'synthetic executable marker, never executed')
        for n in ORIGINAL_FILES:
            value = bytes(range(256)) * 64 if n == 'data.win' else ('original ' + n).encode()
            for base in [self.game, self.original]:
                p = base / n; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(value)
        self.make_payload(1)

    def make_payload(self, version):
        before = json.loads((self.payload / 'payload.json').read_text('utf8')) if (self.payload / 'payload.json').exists() else None
        target = self.root / 'target.win'; data = bytearray((self.original / 'data.win').read_bytes())
        data[25:30] = bytes([version]) * 5; data[1000:1010] = b'Chinese123'; target.write_bytes(data)
        delta = build_delta(self.original / 'data.win', target, self.payload / 'engine.delta.gz')
        files = []
        for n in PAYLOAD_FILES:
            p = self.payload / n; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(('中文载荷 version ' + str(version) + ' ' + n).encode('utf8'))
            files.append({'path': n, 'bytes': p.stat().st_size, 'sha256': sha(p)})
        compat = {'engine_sha256': [], 'file_sha256': {}}
        if before:
            compat['engine_sha256'].append(before['delta']['target_sha256'])
            compat['file_sha256'] = {x['path']: [x['sha256']] for x in before['files']}
        self.m = {'schema': 1, 'game_version': '1.5.2b', 'release_version': str(version),
                  'original_files': [{'path': n, 'sha256': sha(self.original / n)} for n in ORIGINAL_FILES],
                  'files': files, 'delta': delta, 'delta_sha256': sha(self.payload / 'engine.delta.gz'), 'compatible_previous': compat}
        (self.payload / 'payload.json').write_text(json.dumps(self.m), encoding='utf8')

    def installer(self, **kw): return Installer(self.payload, self.game, self.profile, running=lambda: False, **kw)

    def snapshot(self):
        paths = {n: self.game / n for n in ORIGINAL_FILES + EXTRA_FILES}
        paths.update({'profile': self.profile, 'autosave': self.profile.parent / 'autosave.sav', 'score': self.profile.parent / 'score.sav'})
        return {n: sha(p) if p.is_file() else None for n, p in paths.items()}

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='VWZH-synthetic-')
        self.f = Fixture(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_install_restore_preserves_new_progress(self):
        f=self.f; before=f.snapshot(); f.installer().run('install')
        self.assertEqual(sha(f.game/'data.win'), f.m['delta']['target_sha256'])
        self.assertEqual(f.profile.read_bytes(), profile_change(f.raw,3)[0])
        progressed=f.profile.read_bytes().replace(b'"progress": 7',b'"progress": 999')
        f.profile.write_bytes(progressed); f.installer().run('restore')
        self.assertEqual(f.profile.read_bytes(),profile_change(progressed,2)[0])
        for n in ORIGINAL_FILES: self.assertEqual(sha(f.game/n),before[n])
        self.assertEqual(f.snapshot()['autosave'],before['autosave']); self.assertEqual(f.snapshot()['score'],before['score'])
        self.assertFalse((f.game/EXTRA_FILES[0]).exists()); self.assertFalse((f.game/EXTRA_FILES[1]).exists())

    def test_reinstall_and_upgrade(self):
        f=self.f; f.installer().run('install'); f.installer().run('install')
        f.make_payload(2); f.installer().run('install')
        self.assertEqual(sha(f.game/'data.win'),f.m['delta']['target_sha256'])
        f.installer().run('restore'); self.assertEqual(sha(f.game/'data.win'),sha(f.original/'data.win'))

    def test_existing_font_and_license_restored(self):
        f=self.f
        for n in EXTRA_FILES:
            p=f.game/n; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'preexisting user resource')
        before=f.snapshot(); f.installer().run('install'); f.installer().run('restore')
        self.assertEqual(f.snapshot(),before)

    def test_wrong_version_and_missing_resource_rejected(self):
        f=self.f; (f.game/'data.win').write_bytes(b'wrong version'); before=f.snapshot()
        with self.assertRaisesRegex(PatchError,'版本'): f.installer().run('install')
        self.assertEqual(f.snapshot(),before); self.assertFalse((f.game/BACKUP).exists())
        (f.game/'data.win').write_bytes((f.original/'data.win').read_bytes()); (f.game/ORIGINAL_FILES[1]).unlink(); before=f.snapshot()
        with self.assertRaises(PatchError): f.installer().run('install')
        self.assertEqual(f.snapshot(),before)

    def test_corrupt_payload_and_delta_rejected(self):
        f=self.f; before=f.snapshot(); (f.payload/'engine.delta.gz').write_bytes(b'corrupt')
        with self.assertRaises(PatchError): f.installer().run('install')
        self.assertEqual(f.snapshot(),before); self.assertFalse((f.game/BACKUP).exists())
        f.make_payload(1); (f.payload/ORIGINAL_FILES[2]).write_bytes(b'corrupt')
        with self.assertRaises(PatchError): f.installer().run('install')
        self.assertEqual(f.snapshot(),before)

    def test_duplicate_and_invalid_profile_rejected(self):
        f=self.f
        for raw in [b'{"currLanguage":0,"currLanguage":3}',b'{"currLanguage":true}',b'{"currLanguage":-1}',b'{"currLanguage":2.5}',b'{"currLanguage":3,"x":{"currLanguage":0}}',b'{"savedSettings":{"currLanguage":0}}\0\0']:
            f.profile.write_bytes(raw); before=f.snapshot()
            with self.assertRaises(PatchError): f.installer().run('install')
            self.assertEqual(f.snapshot(),before)

    def test_running_guard(self):
        f=self.f; before=f.snapshot()
        with self.assertRaisesRegex(PatchError,'关闭'):
            Installer(f.payload,f.game,f.profile,running=lambda:True).run('install')
        self.assertEqual(f.snapshot(),before)

    def test_missing_and_damaged_backup_preflight(self):
        f=self.f; f.installer().run('install'); path=f.game/BACKUP/ORIGINAL_FILES[2]; path.unlink(); before=f.snapshot()
        with self.assertRaises(PatchError): f.installer().run('restore')
        self.assertEqual(f.snapshot(),before)
        path.write_bytes(b'damaged')
        with self.assertRaises(PatchError): f.installer().run('install')
        self.assertEqual(f.snapshot(),before)

    def test_failure_at_each_install_replace_rolls_back(self):
        for phase in ['before_replace','after_replace','before_commit']:
            for index in (range(8) if phase!='before_commit' else [8]):
                with self.subTest(phase=phase,index=index),tempfile.TemporaryDirectory(prefix='VWZH-fault-') as t:
                    f=Fixture(t); before=f.snapshot()
                    def fault(p,i):
                        if (p,i)==(phase,index): raise RuntimeError('injected synthetic IO failure')
                    with self.assertRaises(RuntimeError): f.installer(fault=fault).run('install')
                    self.assertEqual(f.snapshot(),before); self.assertFalse((f.game/TXN).exists())

    def test_restore_failure_rolls_back_to_chinese(self):
        f=self.f; f.installer().run('install'); before=f.snapshot()
        def fault(p,i):
            if (p,i)==('after_replace',4): raise RuntimeError('synthetic restore failure')
        with self.assertRaises(RuntimeError): f.installer(fault=fault).run('restore')
        self.assertEqual(f.snapshot(),before)

    def test_hard_process_exit_recovers_on_next_run(self):
        f=self.f; before=f.snapshot()
        code="import os,sys; from patcher_core import Installer; f=lambda p,i:os._exit(73) if p=='after_replace' and i==2 else None; Installer(*sys.argv[1:],running=lambda:False,fault=f).run('install')"
        p=subprocess.run([sys.executable,'-c',code,str(f.payload),str(f.game),str(f.profile)],cwd=SOURCE)
        self.assertEqual(p.returncode,73); self.assertTrue((f.game/TXN/'journal.json').is_file())
        with game_lock(f.game): self.assertTrue(f.installer().recover())
        self.assertEqual(f.snapshot(),before)
        f.installer().run('install'); self.assertFalse((f.game/TXN).exists())

    def test_external_profile_change_is_never_overwritten_on_recovery(self):
        f=self.f
        class Interruption(BaseException): pass
        def fault(p,i):
            if (p,i)==('after_replace',1): raise Interruption()
        with self.assertRaises(Interruption): f.installer(fault=fault).run('install')
        changed=f.raw.replace(b'"progress": 7',b'"progress": 9999'); f.profile.write_bytes(changed)
        with self.assertRaisesRegex(PatchError,'其他程序修改'): f.installer().recover()
        self.assertEqual(f.profile.read_bytes(),changed)

    def test_recovery_cannot_bind_to_another_profile_with_identical_content(self):
        f=self.f
        class Interruption(BaseException): pass
        def fault(p,i):
            if (p,i)==('after_replace',1): raise Interruption()
        with self.assertRaises(Interruption): f.installer(fault=fault).run('install')
        other=f.root/'另一账户 空格'/'profile.sav'; other.parent.mkdir(); other.write_bytes(f.profile.read_bytes())
        before=f.snapshot(); journal=(f.game/TXN/'journal.json').read_bytes()
        with self.assertRaises(PatchError) as caught:
            Installer(f.payload,f.game,other,running=lambda:False).recover()
        self.assertEqual(caught.exception.code,'PROFILE_BINDING')
        self.assertEqual(f.snapshot(),before)
        self.assertEqual((f.game/TXN/'journal.json').read_bytes(),journal)
        self.assertEqual(other.read_bytes(),f.profile.read_bytes())
        with game_lock(f.game): self.assertTrue(f.installer().recover())

    def test_profile_change_between_prepare_and_commit_is_preserved(self):
        f=self.f; before=f.snapshot()
        changed=f.raw.replace(b'"progress": 7',b'"progress": 123456')
        def progress(message):
            if message.startswith('准备已完成'): f.profile.write_bytes(changed)
        with self.assertRaises(PatchError) as caught: f.installer(progress=progress).run('install')
        self.assertEqual(caught.exception.code,'FILE_CHANGED')
        expected=dict(before); expected['profile']=sha(f.profile)
        self.assertEqual(f.profile.read_bytes(),changed)
        self.assertEqual(f.snapshot(),expected)
        with game_lock(f.game): self.assertTrue(f.installer().recover())
        self.assertEqual(f.profile.read_bytes(),changed)

    def test_legacy_powershell_backup(self):
        f=self.f; f.installer().run('install'); p=f.game/BACKUP/'installation.json'
        p.write_text(json.dumps({'original_language':2.0,'font_was_present':False,'game_path':'legacy private path must not be copied to new state'}),encoding='utf8')
        f.installer().run('install'); state=json.loads(p.read_text('utf8')); self.assertNotIn('game_path',state)
        f.installer().run('restore'); self.assertEqual(sha(f.game/'data.win'),sha(f.original/'data.win'))

if __name__=='__main__': unittest.main(verbosity=2)
