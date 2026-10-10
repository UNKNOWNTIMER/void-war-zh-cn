"""Offline installer core. All mutations are explicit and transaction guarded."""
from __future__ import annotations
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import uuid
from payload_format import ORIGINAL_FILES, PAYLOAD_FILES, EXTRA_FILES, apply_delta, sha, byte_sha

BACKUP = '_VoidWar_Chinese_Original'
TXN = '.VoidWarChinese.transaction'
BACKUP_PREP = '.VoidWarChinese.backup-preparing'
BUILD = '.VoidWarChinese.build'
ALLOWED_TARGETS = set(ORIGINAL_FILES + EXTRA_FILES) | {'@profile', '@state'}
LANG = re.compile(rb'("currLanguage"\s*:\s*)(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)(?=\s*[,}])')

class PatchError(Exception):
    def __init__(self, code, message):
        super().__init__(message); self.code = code

def require(test, code, message):
    if not test: raise PatchError(code, message)

def read_json(path):
    try: return json.loads(path.read_text('utf-8-sig'))
    except (ValueError, OSError): raise PatchError('INVALID_METADATA', '补丁或备份记录不完整，请保留现有文件后重新检查。') from None

def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.' + path.name + '.vwzh-' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()

def atomic_json(path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode('utf8'))

def atomic_copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name('.' + target.name + '.vwzh-' + uuid.uuid4().hex + '.tmp')
    try:
        with source.open('rb') as src, temp.open('xb') as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024); dst.flush(); os.fsync(dst.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists(): temp.unlink()

def file_hash(path):
    return sha(path) if path.is_file() else None

def is_link(path):
    try:
        s = path.lstat()
        return path.is_symlink() or bool(getattr(s, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))
    except FileNotFoundError: return False

def safe_child(root, relative):
    require(relative in set(ORIGINAL_FILES + EXTRA_FILES) | {BACKUP, TXN, BACKUP_PREP, BUILD, '.VoidWarChinese.lock'},
            'UNSAFE_PATH', '发现不安全的文件位置，已停止。')
    p = root / relative
    for part in [p, *list(p.parents)[:len(p.parts) - len(root.parts) - 1]]:
        require(not is_link(part), 'LINK_PATH', '游戏子目录含链接或重定向；请选取实际游戏目录。')
    return p

def remove_owned_tree(root, name):
    path = safe_child(root, name)
    require(name in {TXN, BACKUP_PREP, BUILD}, 'UNSAFE_CLEANUP', '已阻止非事务目录清理。')
    require(path.resolve().parent == root.resolve(), 'UNSAFE_CLEANUP', '事务目录位置无效。')
    if path.exists():
        require(not is_link(path) and all(not is_link(p) for p in path.rglob('*')), 'LINK_PATH', '事务目录包含链接，已停止清理。')
        shutil.rmtree(path)

@contextmanager
def build_workspace(root):
    staging = safe_child(root, BUILD)
    if staging.exists():
        require(read_json(staging / 'owner.json') == {'format': 'VWZH_BUILD_1'}, 'UNKNOWN_BUILD', '发现未知构建临时目录，已保留并停止。')
        remove_owned_tree(root, BUILD)
    staging.mkdir(); atomic_json(staging / 'owner.json', {'format': 'VWZH_BUILD_1'})
    try: yield staging
    finally: remove_owned_tree(root, BUILD)

def profile_change(raw, language):
    require(isinstance(language, (int, float)) and not isinstance(language, bool)
            and math.isfinite(language) and language >= 0 and language == int(language),
            'PROFILE_LANGUAGE', '语言设置无效。')
    seen = []
    def pairs(items):
        seen.extend(value for key, value in items if key == 'currLanguage')
        return dict(items)
    try:
        # GameMaker writes one terminal NUL after its JSON document. Strip it
        # for validation only; the byte replacement below preserves it exactly.
        document = raw.rstrip(b'\r\n\t ')
        if document.endswith(b'\0'): document = document[:-1]
        parsed = json.loads(document.decode('utf-8-sig'), object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        current = seen[0] if len(seen) == 1 else None
        valid = (isinstance(parsed, dict) and len(seen) == 1 and isinstance(current, (int, float))
                 and not isinstance(current, bool) and math.isfinite(current) and current >= 0 and current == int(current))
    except (ValueError, KeyError, TypeError, UnicodeError): valid = False
    matches = list(LANG.finditer(raw))
    require(valid and len(matches) == 1, 'PROFILE_FORMAT', '设置存档缺少唯一有效的语言字段。请先启动并退出游戏一次。')
    m = matches[0]; replacement = (str(int(language)) + '.0').encode('ascii')
    return raw[:m.start(2)] + replacement + raw[m.end(2):], int(current)

def game_running():
    """Toolhelp process enumeration, no process paths or user names recorded."""
    if os.name != 'nt': return False
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    api.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = api.CreateToolhelp32Snapshot(2, 0)
    require(handle not in {None, ctypes.c_void_p(-1).value}, 'PROCESS_CHECK', '无法确认游戏是否已关闭，请稍后重试。')
    try:
        entry = ProcessEntry(); entry.dwSize = ctypes.sizeof(entry)
        more = api.Process32FirstW(handle, ctypes.byref(entry))
        require(bool(more), 'PROCESS_CHECK', '无法读取进程列表。')
        while more:
            if entry.szExeFile.casefold() == 'void war.exe': return True
            more = api.Process32NextW(handle, ctypes.byref(entry))
        return False
    finally: api.CloseHandle(handle)

@contextmanager
def game_lock(root):
    path = safe_child(root, '.VoidWarChinese.lock')
    with path.open('a+b') as f:
        if f.tell() == 0: f.write(b'0'); f.flush()
        f.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: raise PatchError('BUSY', '另一份补丁器正在操作此游戏，请等待完成。') from None
        try: yield
        finally:
            f.seek(0)
            if os.name == 'nt': msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(f.fileno(), fcntl.LOCK_UN)

class Installer:
    def __init__(self, payload, game, profile, *, progress=None, running=game_running, fault=None):
        self.payload = Path(payload).resolve(); self.game = Path(game).resolve(); self.profile = Path(profile).absolute()
        self.progress = progress or (lambda text: None); self.running = running; self.fault = fault or (lambda phase, index: None)
        self.backup = self.game / BACKUP; self.txn = self.game / TXN
        self.manifest = None

    def guard(self):
        require(not self.running(), 'GAME_RUNNING', '请先关闭 Void War，再安装或还原。')

    def target(self, name):
        require(name in ALLOWED_TARGETS, 'UNSAFE_TARGET', '事务包含未授权文件，已停止。')
        if name == '@profile':
            require(not is_link(self.profile) and not is_link(self.profile.parent), 'LINK_PROFILE', '设置存档不能是链接文件。')
            return self.profile
        if name == '@state':
            safe_child(self.game, BACKUP)
            require(not is_link(self.backup / 'installation.json'), 'LINK_PATH', '备份记录不能是链接。')
            return self.backup / 'installation.json'
        return safe_child(self.game, name)

    def load_payload(self):
        m = read_json(self.payload / 'payload.json')
        require(m.get('schema') == 1, 'PAYLOAD_VERSION', '补丁载荷版本不受支持。')
        require([x.get('path') for x in m.get('original_files', [])] == list(ORIGINAL_FILES)
                and [x.get('path') for x in m.get('files', [])] == list(PAYLOAD_FILES), 'PAYLOAD_LIST', '补丁文件清单无效。')
        for x in m['files']:
            require(file_hash(self.payload / x['path']) == x['sha256'], 'PAYLOAD_HASH', '补丁载荷校验失败，请重新下载。')
        require(file_hash(self.payload / 'engine.delta.gz') == m['delta_sha256'], 'DELTA_HASH', '引擎差分校验失败，请重新下载。')
        require(m['original_files'][0]['sha256'] == m['delta']['source_sha256'], 'PAYLOAD_HASH', '原版校验信息不一致。')
        self.manifest = m
        return m

    def recover(self):
        if not self.txn.exists(): return False
        safe_child(self.game, TXN)
        require(all(not is_link(p) for p in self.txn.rglob('*')), 'LINK_PATH', '事务中含链接，已保留现场。')
        marker = self.txn / 'journal.json'
        if not marker.exists():
            require((self.txn / 'owner.json').is_file() and read_json(self.txn / 'owner.json') == {'format': 'VWZH_TXN_1'}, 'UNKNOWN_TRANSACTION', '发现未知临时目录，已保留并停止。')
            remove_owned_tree(self.game, TXN); return True
        journal = read_json(marker)
        require(journal.get('format') == 'VWZH_TXN_1' and journal.get('phase') in {'prepared', 'committing', 'committed'}, 'INVALID_TRANSACTION', '事务恢复记录无效。')
        require(journal.get('profile_binding') == byte_sha(str(self.profile.resolve()).casefold().encode('utf8')),
                'PROFILE_BINDING', '该中断事务属于另一设置存档位置，请使用原来的账户和设置存档。')
        entries = journal.get('entries', [])
        require(len(entries) <= len(ALLOWED_TARGETS) and len({x['target'] for x in entries}) == len(entries), 'INVALID_TRANSACTION', '事务文件表无效。')
        if journal['phase'] == 'committed':
            remove_owned_tree(self.game, TXN); return True
        self.guard(); self.progress('正在恢复上次中断的操作…')
        # Validate every rollback source and target before changing any file.
        for i, x in enumerate(entries):
            target = self.target(x['target']); current = file_hash(target)
            require(current in {x['before'], x['after']}, 'RECOVERY_CONFLICT', '中断后有文件被其他程序修改，已保留现场；请关闭游戏后联系维护者。')
            if x['before'] is not None:
                require(file_hash(self.txn / 'old' / str(i)) == x['before'], 'ROLLBACK_DAMAGED', '事务回滚副本损坏，已保留现场。')
        for i in reversed(range(len(entries))):
            x = entries[i]; target = self.target(x['target'])
            if file_hash(target) == x['before']: continue
            if x['before'] is None:
                if target.exists(): target.unlink()
            else: atomic_copy(self.txn / 'old' / str(i), target)
            require(file_hash(target) == x['before'], 'ROLLBACK_FAILED', '自动回滚校验失败，已保留备份。')
        remove_owned_tree(self.game, TXN)
        return True

    def check_original_backup(self):
        m = self.manifest
        require(all(not is_link(p) for p in self.backup.rglob('*')), 'LINK_PATH', '原版备份含链接，已停止。')
        state = read_json(self.backup / 'installation.json')
        language = state.get('original_language')
        require(isinstance(language, (int, float)) and not isinstance(language, bool) and math.isfinite(language)
                and language >= 0 and int(language) == language and isinstance(state.get('font_was_present'), bool), 'BACKUP_STATE', '原版备份记录缺少有效信息。')
        for item in m['original_files']:
            p = self.backup / item['path']
            require(not is_link(p) and not is_link(p.parent) and file_hash(p) == item['sha256'], 'BACKUP_HASH', '原版备份缺失或损坏；已停止，未覆盖游戏。')
        extras = state.get('extra_originals')
        if extras is None:
            # Adopt the already-verified legacy PowerShell backup without copying
            # its historical profile over the current game progress.
            extras = {}
            if state['font_was_present']:
                p = self.backup / EXTRA_FILES[0]
                require(file_hash(p) == state.get('original_font_sha256'), 'BACKUP_FONT', '原字体备份校验失败。')
                extras[EXTRA_FILES[0]] = state['original_font_sha256']
            else:
                # Legacy restore intentionally retained an added OFL font.
                extras[EXTRA_FILES[0]] = file_hash(self.target(EXTRA_FILES[0]))
                if extras[EXTRA_FILES[0]]: atomic_copy(self.target(EXTRA_FILES[0]), self.backup / EXTRA_FILES[0])
            extras[EXTRA_FILES[1]] = file_hash(self.target(EXTRA_FILES[1]))
            if extras[EXTRA_FILES[1]]: atomic_copy(self.target(EXTRA_FILES[1]), self.backup / EXTRA_FILES[1])
        require(set(extras) == set(EXTRA_FILES), 'BACKUP_STATE', '原附加文件清单不完整。')
        for name, expected in extras.items():
            if expected: require(file_hash(self.backup / name) == expected, 'BACKUP_EXTRA', '原附加文件备份损坏。')
        return {'schema': 2, 'original_language': language, 'font_was_present': state['font_was_present'],
                'original_font_sha256': state.get('original_font_sha256'), 'extra_originals': extras,
                'installed_files': state.get('installed_files', {}), 'last_action': state.get('last_action', 'legacy')}

    def create_backup(self, raw_profile, language):
        staging = safe_child(self.game, BACKUP_PREP)
        if staging.exists():
            require(read_json(staging / 'owner.json') == {'format': 'VWZH_BACKUP_1'}, 'INCOMPLETE_BACKUP', '未知备份临时目录已保留。')
            remove_owned_tree(self.game, BACKUP_PREP)
        staging.mkdir(); atomic_json(staging / 'owner.json', {'format': 'VWZH_BACKUP_1'})
        extra = {}
        for item in self.manifest['original_files']:
            source = self.target(item['path'])
            require(file_hash(source) == item['sha256'], 'ORIGINAL_HASH', '原版资源与支持版本不一致。')
            atomic_copy(source, staging / item['path'])
            require(file_hash(staging / item['path']) == item['sha256'], 'BACKUP_HASH', '原版备份写入校验失败。')
        for name in EXTRA_FILES:
            source = self.target(name); extra[name] = file_hash(source)
            if extra[name]: atomic_copy(source, staging / name)
        atomic_bytes(staging / 'profile.before-install.sav', raw_profile)
        state = {'schema': 2, 'original_language': language, 'font_was_present': extra[EXTRA_FILES[0]] is not None,
                 'original_font_sha256': extra[EXTRA_FILES[0]], 'extra_originals': extra, 'installed_files': {}, 'last_action': 'backup'}
        atomic_json(staging / 'installation.json', state)
        if self.backup.exists():
            require(not any(self.backup.iterdir()), 'INCOMPLETE_BACKUP', '原版备份目录不完整；已保留目录并停止。')
            self.backup.rmdir()
        os.replace(staging, self.backup)
        return self.check_original_backup()

    def preflight(self, action):
        self.guard()
        require((self.game / 'Void War.exe').is_file(), 'GAME_NOT_FOUND', '所选目录没有 Void War.exe。请选择 Steam 中的 Void War 游戏目录。')
        for name in [*ORIGINAL_FILES, *EXTRA_FILES, BACKUP, TXN]: self.target(name) if name in ALLOWED_TARGETS else safe_child(self.game, name)
        require(self.profile.is_file(), 'PROFILE_MISSING', '未找到游戏设置存档。请先启动并退出游戏一次。')
        raw = self.profile.read_bytes(); _, language = profile_change(raw, 3)
        m = self.load_payload(); current = file_hash(self.target('data.win'))
        observed = {'data.win': current, '@profile': byte_sha(raw)}
        valid_engines = {m['delta']['source_sha256'], m['delta']['target_sha256'], *m.get('compatible_previous', {}).get('engine_sha256', [])}
        require(current in valid_engines, 'WRONG_VERSION', '游戏版本或 data.win 不匹配。仅支持 Void War 1.5.2b；请勿覆盖更新版或其他修改版。')
        if (self.backup / 'installation.json').exists(): state = self.check_original_backup()
        else:
            require(action == 'install' and current == m['delta']['source_sha256'], 'BACKUP_MISSING', '缺少完整原版备份。请先用 Steam 验证并还原原版游戏。')
            require(not self.backup.exists() or not any(self.backup.iterdir()), 'INCOMPLETE_BACKUP', '发现不完整原版备份，已保留并停止。')
            for item in m['original_files']:
                require(file_hash(self.target(item['path'])) == item['sha256'], 'ORIGINAL_HASH', '原版语言资源缺失或散列不匹配。')
            state = None
        original_hashes = {x['path']: x['sha256'] for x in m['original_files']}
        new_hashes = {x['path']: x['sha256'] for x in m['files']}
        for name in ORIGINAL_FILES[1:]:
            valid = {original_hashes[name], new_hashes[name], *m.get('compatible_previous', {}).get('file_sha256', {}).get(name, [])}
            if state: valid.add(state.get('installed_files', {}).get(name))
            observed[name] = file_hash(self.target(name))
            require(observed[name] in valid - {None}, 'CURRENT_FILE_CHANGED', '当前语言资源缺失或被其他修改覆盖，已停止。')
        for name in EXTRA_FILES:
            observed[name] = file_hash(self.target(name))
            if state and state.get('last_action') != 'legacy':
                accepted = {new_hashes[name], state['extra_originals'][name], state.get('installed_files', {}).get(name)}
                require(observed[name] in accepted, 'CURRENT_EXTRA_CHANGED', '字体或许可文件被其他程序修改，已保留并停止。')
        needed = 3 * self.target('data.win').stat().st_size + sum(x['bytes'] for x in m['files']) + 16 * 1024 * 1024
        require(shutil.disk_usage(self.game).free >= needed, 'DISK_SPACE', '游戏磁盘剩余空间不足；请至少预留约 1.1 GB。')
        return raw, language, state, observed

    def transact(self, desired, observed):
        self.txn.mkdir(); atomic_json(self.txn / 'owner.json', {'format': 'VWZH_TXN_1'})
        (self.txn / 'old').mkdir(); (self.txn / 'new').mkdir()
        entries = []
        for i, (name, source) in enumerate(desired.items()):
            target = self.target(name); before = file_hash(target)
            require(before == observed[name], 'FILE_CHANGED', '文件在准备过程中发生变化，已停止。')
            if before is not None: atomic_copy(target, self.txn / 'old' / str(i))
            require(before is None or file_hash(self.txn / 'old' / str(i)) == before, 'FILE_CHANGED', '事务副本校验失败，未写入游戏。')
            after = None
            if source is not None:
                if isinstance(source, bytes): atomic_bytes(self.txn / 'new' / str(i), source)
                else: atomic_copy(source, self.txn / 'new' / str(i))
                after = file_hash(self.txn / 'new' / str(i))
            entries.append({'target': name, 'before': before, 'after': after})
        journal = {'format': 'VWZH_TXN_1', 'phase': 'prepared', 'entries': entries,
                   'profile_binding': byte_sha(str(self.profile.resolve()).casefold().encode('utf8'))}
        atomic_json(self.txn / 'journal.json', journal)
        self.fault('prepared', -1)
        try:
            self.guard()
            for x in entries:
                require(file_hash(self.target(x['target'])) == x['before'], 'FILE_CHANGED', '文件在准备过程中发生变化，已停止并自动回滚。')
            journal['phase'] = 'committing'; atomic_json(self.txn / 'journal.json', journal)
            for i, x in enumerate(entries):
                self.guard(); self.fault('before_replace', i)
                target = self.target(x['target'])
                require(file_hash(target) == x['before'], 'FILE_CHANGED', '文件被其他程序修改，已停止并保留现场。')
                if x['after'] is None:
                    if target.exists(): target.unlink()
                else: atomic_copy(self.txn / 'new' / str(i), target)
                self.fault('after_replace', i)
                require(file_hash(target) == x['after'], 'WRITE_VERIFY', '写入后校验失败，正在自动回滚。')
            self.fault('before_commit', len(entries))
            journal['phase'] = 'committed'; atomic_json(self.txn / 'journal.json', journal)
        except Exception:
            self.recover(); raise
        remove_owned_tree(self.game, TXN)

    def run(self, action):
        require(action in {'install', 'restore'}, 'INVALID_ACTION', '操作无效。')
        self.guard()
        require(self.game.is_dir(), 'GAME_NOT_FOUND', '游戏目录不存在。')
        with game_lock(self.game):
            self.recover()
            self.progress('正在验证游戏、补丁和设置存档…')
            raw, language, state, observed = self.preflight(action)
            require(self.profile.read_bytes() == raw, 'PROFILE_CHANGED', '设置存档发生变化，请关闭游戏后重试。')
            if state is None:
                self.progress('正在创建完整原版备份…'); state = self.create_backup(raw, language)
            observed['@state'] = file_hash(self.target('@state'))
            desired = {}
            # A marked local workspace is safely reclaimed after interruption.
            with build_workspace(self.game) as staging:
                if action == 'install':
                    self.progress('正在依据原版备份生成并校验中文引擎…')
                    try: apply_delta(self.backup / 'data.win', self.payload / 'engine.delta.gz', staging / 'data.win', self.manifest['delta'])
                    except (ValueError, OSError): raise PatchError('DELTA_APPLY', '差分生成或目标散列校验失败，未修改游戏。') from None
                    desired['data.win'] = staging / 'data.win'
                    for name in PAYLOAD_FILES: desired[name] = self.payload / name
                    updated, _ = profile_change(raw, 3)
                    state['installed_files'] = {name: sha(path) for name, path in desired.items()}
                    state['last_action'] = 'install'; state['release_version'] = self.manifest['release_version']
                else:
                    for name in ORIGINAL_FILES: desired[name] = self.backup / name
                    for name, previous in state['extra_originals'].items(): desired[name] = self.backup / name if previous else None
                    updated, _ = profile_change(raw, state['original_language'])
                    state['installed_files'] = {}; state['last_action'] = 'restore'
                desired['@profile'] = updated
                desired['@state'] = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2).encode('utf8')
                require(self.profile.read_bytes() == raw, 'PROFILE_CHANGED', '设置存档在准备时发生变化，已停止。')
                self.guard(); self.progress('准备已完成，正在事务写入并逐项校验…')
                self.transact(desired, observed)
            self.progress('安装完成，原版备份已保留。' if action == 'install' else '还原完成，当前游戏进度保持不变。')
            return {'status': 'PASS', 'action': action, 'engine_sha256': file_hash(self.target('data.win')),
                    'language': 3 if action == 'install' else state['original_language']}

def discover_games():
    roots = []
    if os.name == 'nt':
        import winreg
        for hive, key, value in [(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                  (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath')]:
            try:
                with winreg.OpenKey(hive, key) as k: roots.append(Path(winreg.QueryValueEx(k, value)[0]))
            except OSError: pass
    for base in [os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles')]:
        if base: roots.append(Path(base) / 'Steam')
    libraries = list(roots)
    for root in roots:
        try:
            text = (root / 'steamapps/libraryfolders.vdf').read_text('utf8')
            libraries.extend(Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', text))
        except OSError: pass
    found = []
    for root in libraries:
        game = root / 'steamapps/common/Void War'
        if (game / 'Void War.exe').is_file() and game.resolve() not in found: found.append(game.resolve())
    return found
