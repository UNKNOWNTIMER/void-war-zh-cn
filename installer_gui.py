"""Chinese GUI for the offline Void War text patch. No network operations."""
import argparse
import ctypes
from ctypes import wintypes
import json
import logging
import math
import os
from pathlib import Path
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk
from patcher_core import Installer, PatchError, discover_games, read_json
from payload_format import PAYLOAD_FILES, sha

def payload_dir():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'payload'

def asset_dir():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'

def configure_log():
    root = Path(os.environ.get('LOCALAPPDATA', '.')) / 'VoidWarChinesePatcher'
    try:
        root.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=root / 'patcher.log', level=logging.INFO,
                            format='%(asctime)s %(message)s', encoding='utf8')
    except OSError: logging.basicConfig(level=logging.CRITICAL)

def self_check(report):
    p = payload_dir(); m = read_json(p / 'payload.json')
    assert [x['path'] for x in m['files']] == list(PAYLOAD_FILES)
    assert sha(p / 'engine.delta.gz') == m['delta_sha256']
    assert all(sha(p / x['path']) == x['sha256'] for x in m['files'])
    root = tk.Tk(); root.withdraw(); root.update_idletasks(); version = root.tk.call('info', 'patchlevel'); root.destroy()
    result = {'status': 'PASS', 'frozen': bool(getattr(sys, 'frozen', False)), 'tk_version': version,
              'engine_target_sha256': m['delta']['target_sha256'], 'payload_files_verified': len(m['files']) + 1,
              'game_or_save_files_accessed': False}
    Path(report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

class App:
    def __init__(self, root, args):
        self.root = root; self.args = args; self.busy = False; self.messages = queue.Queue()
        self.visual_state = 'ready'; self._animation_job = None; self._font_resource = None
        self._animation_started = time.monotonic()
        root.title('Void War 简体中文汉化补丁'); root.geometry('860x560'); root.minsize(760, 510)
        root.overrideredirect(True)
        root.configure(bg='#08090c')
        self.manifest = read_json(payload_dir() / 'payload.json')
        self._make_fonts()
        self.style = ttk.Style(root); self.style.theme_use('clam')
        self._make_styles()
        self.canvas = tk.Canvas(root, bg='#08090c', highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill='both', expand=True)
        self.logo = tk.PhotoImage(file=str(asset_dir() / 'installer_logo.png'))
        try: root.iconbitmap(str(asset_dir() / 'installer.ico'))
        except tk.TclError: pass
        self.close_button = tk.Button(root, text='×', command=self.close, font=('Segoe UI', 20),
            bg='#08090c', fg='#b6ad95', activebackground='#4c2d2a', activeforeground='#eee1c4',
            relief='flat', borderwidth=0, highlightthickness=0, cursor='hand2', takefocus=True)
        self.close_button.place(relx=1, x=-29, y=25, anchor='ne', width=34, height=34)
        self.canvas.bind('<ButtonPress-1>', self._drag_start)
        self.canvas.bind('<B1-Motion>', self._drag_move)
        root.bind('<Alt-F4>', lambda event: self.close())
        root.after(80, self._taskbar_window)
        # Procedural scenery and an original logo; no extracted game art.
        rng = random.Random(14017)
        self._stars = []
        for _ in range(70):
            size = rng.choice((1, 1, 1, 2))
            item = self.canvas.create_oval(0, 0, size, size, fill='#665e4b', outline='', tags='stars')
            self._stars.append([item, rng.random(), rng.random(), size,
                                rng.uniform(0.4, 1.6), rng.uniform(0, math.tau)])
        self._scan = self.canvas.create_line(0, 0, 0, 0, fill='#766447', width=1, tags='motion')
        self._scan_glow = self.canvas.create_line(0, 0, 0, 0, fill='#342c22', width=3, tags='motion')
        self._orbit_marker = self.canvas.create_oval(0, 0, 0, 0, fill='#b99b66', outline='', tags='motion')
        self.body = tk.Frame(root, bg='#131416', bd=0, highlightthickness=0)
        self.body.place(x=54, y=211, relwidth=1, width=-108, relheight=1, height=-269)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(4, weight=1)
        self.hint = tk.Label(self.body,
            text='安装前请退出游戏。首次自动备份，还原时保留当前游戏进度。',
            bg='#131416', fg='#b4b0a4', font=self.body_font, anchor='w', justify='left')
        self.hint.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        row = tk.Frame(self.body, bg='#080a0c', highlightbackground='#5d594f', highlightthickness=1)
        row.grid(row=1, column=0, sticky='ew')
        row.columnconfigure(0, weight=1)
        found = discover_games(); self.path = tk.StringVar(value=args.game or (str(found[0]) if found else ''))
        self.entry = ttk.Entry(row, textvariable=self.path, style='Void.TEntry', font=self.body_font)
        self.entry.grid(row=0, column=0, sticky='ew', padx=(12, 8), pady=9, ipady=4)
        self.browse = ttk.Button(row, text='选择目录', command=self.choose, style='Browse.Void.TButton')
        self.browse.grid(row=0, column=1, padx=(0, 7), pady=6)
        buttons = tk.Frame(self.body, bg='#131416'); buttons.grid(row=2, column=0, sticky='ew', pady=(20, 0))
        buttons.columnconfigure(0, weight=3); buttons.columnconfigure(1, weight=2)
        self.install = ttk.Button(buttons, text='一键安装 / 更新汉化', style='Install.Void.TButton', command=lambda: self.start('install'))
        self.install.grid(row=0, column=0, sticky='ew', padx=(0, 12), ipady=7)
        self.restore = ttk.Button(buttons, text='还原原版', style='Restore.Void.TButton', command=lambda: self.start('restore'))
        self.restore.grid(row=0, column=1, sticky='ew', ipady=7)
        self.bar = ttk.Progressbar(self.body, mode='indeterminate', style='Void.Horizontal.TProgressbar')
        self.bar.grid(row=3, column=0, sticky='ew', pady=(22, 13))
        initial_status = '已选择游戏目录，可以开始安装。' if args.game else '已自动定位游戏目录，可以开始安装。' if found else '请选择已安装的 Void War 游戏目录（其中应有 Void War.exe）。'
        self.status = tk.StringVar(value=initial_status)
        self.status_label = tk.Label(self.body, textvariable=self.status, bg='#131416', fg='#c8c4b6',
                                     font=self.body_font, justify='left', anchor='nw', wraplength=700)
        self.status_label.grid(row=4, column=0, sticky='nsew', padx=(16, 0))
        self.status_lamp = tk.Canvas(self.body, bg='#131416', width=9, height=9, highlightthickness=0)
        self.status_lamp.place(x=0, y=204)
        self._lamp = self.status_lamp.create_oval(1, 1, 8, 8, fill='#847453', outline='')
        self.status_label.bind('<Configure>', lambda event: self.status_lamp.place(x=0, y=self.status_label.winfo_y() + 5))
        self.profile = Path(args.profile) if args.profile else Path(os.environ.get('APPDATA', '')) / 'Void_War/profile.sav'
        self.canvas.bind('<Configure>', self._layout_canvas)
        self.body.bind('<Configure>', self._layout_body)
        root.bind('<Destroy>', self._on_destroy, add='+')
        root.protocol('WM_DELETE_WINDOW', self.close); root.after(100, self.poll)
        self._animation_job = root.after(40, self._animate)
        if args.action: root.after(300, lambda: self.start(args.action))

    def _make_fonts(self):
        # FR_PRIVATE registers the bundled open font only inside this process.
        font_path = payload_dir() / 'NotoSerifSC-Black.otf'
        if os.name == 'nt' and font_path.is_file():
            try:
                add_font = ctypes.windll.gdi32.AddFontResourceExW
                add_font.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
                add_font.restype = ctypes.c_int
                if add_font(str(font_path), 0x10, None): self._font_resource = str(font_path)
            except (AttributeError, OSError): pass
        available = set(tkfont.families(self.root))
        serif = next((x for x in ('Noto Serif SC Black', 'Noto Serif SC', 'SimSun', 'Songti SC') if x in available), 'serif')
        sans = next((x for x in ('Microsoft YaHei UI', 'Microsoft YaHei', 'Noto Sans CJK SC') if x in available), 'TkDefaultFont')
        latin = 'Georgia' if 'Georgia' in available else serif
        self.title_font = tkfont.Font(root=self.root, family=latin, size=-53, weight='bold')
        self.subtitle_font = tkfont.Font(root=self.root, family=serif, size=-19, weight='bold')
        self.button_font = tkfont.Font(root=self.root, family=serif, size=-19, weight='bold')
        self.body_font = tkfont.Font(root=self.root, family=sans, size=-14)
        self.small_font = tkfont.Font(root=self.root, family=sans, size=-12)

    def _taskbar_window(self):
        if os.name != 'nt': return
        try:
            user32 = ctypes.windll.user32
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
            get_long = user32.GetWindowLongPtrW
            set_long = user32.SetWindowLongPtrW
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]; get_long.restype = ctypes.c_ssize_t
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]; set_long.restype = ctypes.c_ssize_t
            style = get_long(hwnd, -20)
            set_long(hwnd, -20, (style | 0x40000) & ~0x80)
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)
        except (AttributeError, OSError, tk.TclError): pass

    def _drag_start(self, event):
        self._drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y()) if event.y < 190 else None

    def _drag_move(self, event):
        offset = getattr(self, '_drag_offset', None)
        if offset is None: return
        x, y = event.x_root - offset[0], event.y_root - offset[1]
        if os.name == 'nt':
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
            user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x15)
        else: self.root.geometry('%+d%+d' % (x, y))

    def _make_styles(self):
        s = self.style
        s.configure('Void.TEntry', fieldbackground='#080a0c', foreground='#e1ddd0',
                    insertcolor='#ddc795', borderwidth=0, padding=0)
        s.map('Void.TEntry', fieldbackground=[('disabled', '#171819')], foreground=[('disabled', '#6c6d69')])
        for name, bg, fg, border, hover in [
                ('Install', '#c4b18a', '#141311', '#e6d7b4', '#dfcfad'),
                ('Restore', '#292b2c', '#d3cbb8', '#777367', '#383a3b'),
                ('Browse', '#222426', '#c7c2b5', '#555851', '#343737')]:
            style = name + '.Void.TButton'
            s.configure(style, font=self.body_font if name == 'Browse' else self.button_font,
                        background=bg, foreground=fg, bordercolor=border,
                        lightcolor=border, darkcolor='#08090a', focuscolor=fg,
                        borderwidth=1, padding=(16, 9), relief='raised', focusthickness=1)
            s.map(style, background=[('disabled', '#202224'), ('pressed', '#806b49' if name == 'Install' else '#191b1c'), ('active', hover)],
                  foreground=[('disabled', '#696b68')], bordercolor=[('focus', '#e2d0a3'), ('disabled', '#3c3e3b')])
        s.configure('Void.Horizontal.TProgressbar', troughcolor='#06080a', background='#b79c67',
                    bordercolor='#34352f', lightcolor='#d2bd8d', darkcolor='#826b45',
                    thickness=5, borderwidth=0)

    def _layout_body(self, event):
        if event.widget is not self.body: return
        self.hint.configure(wraplength=max(360, event.width))
        self.status_label.configure(wraplength=max(340, event.width - 20))
        self.status_lamp.place(x=0, y=self.status_label.winfo_y() + 5)

    def _layout_canvas(self, event):
        c = self.canvas; w, h = event.width, event.height
        c.delete('frame')
        # Layered steel borders, bevels and rivets echo the game's hardware panels.
        c.create_rectangle(17, 17, w-18, h-18, fill='', outline='#3c3d38', tags='frame')
        c.create_line(18, h-19, 18, 18, w-19, 18, fill='#737162', tags='frame')
        c.create_rectangle(23, 23, w-24, h-24, outline='#1f2426', tags='frame')
        c.create_line(38, 190, w-39, 190, fill='#665d49', tags='frame')
        c.create_line(38, 192, w-39, 192, fill='#242523', tags='frame')
        c.create_rectangle(38, 200, w-39, h-49, fill='#131416', outline='#373a38', tags='frame')
        c.create_line(39, 201, w-40, 201, fill='#53534a', tags='frame')
        for x in (29, w-30):
            for y in (29, 184, h-30):
                c.create_oval(x-2, y-2, x+2, y+2, fill='#727265', outline='#1b1d1d', tags='frame')
                c.create_line(x-1, y, x+1, y, fill='#282b29', tags='frame')
        c.create_rectangle(53, 53, 57, 119, fill='#713e38', outline='', tags='frame')
        c.create_text(75, 51, text='VOID WAR', font=self.title_font, fill='#282924', anchor='nw', tags='frame')
        c.create_text(73, 49, text='VOID WAR', font=self.title_font, fill='#e0dbc9', anchor='nw', tags='frame')
        release = self.manifest.get('release_version', '')
        c.create_text(76, 128, text='简体中文汉化  /  ' + release, font=self.subtitle_font, fill='#bda77d', anchor='nw', tags='frame')
        # An original orbital instrument, intentionally subtle behind the controls.
        cx, cy = w-124, 104
        c.create_oval(cx-68, cy-68, cx+68, cy+68, outline='#302f26', tags='frame')
        c.create_image(cx, cy, image=self.logo, tags='frame')
        version = str(self.manifest.get('game_version', '1.5.2b'))
        build = str(self.manifest.get('steam_build_id', '25669267'))
        c.create_text(39, h-34, text='Steam ' + version + '  ·  build ' + build,
                      font=self.small_font, fill='#87887d', anchor='w', tags='frame')
        c.create_text(w-39, h-34, text='离线安装 · 仅含汉化差分与开放字体',
                      font=self.small_font, fill='#87887d', anchor='e', tags='frame')
        c.tag_lower('stars'); c.tag_raise('motion')

    def _animate(self):
        try:
            if not self.root.winfo_exists(): return
            elapsed = time.monotonic() - self._animation_started
            if self.root.state() != 'iconic':
                w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
                for item, x, y, size, speed, phase in self._stars:
                    # Stars remain in the header/margins; their animation never obscures text.
                    px = 25 + ((x - elapsed * speed * 0.0025) % 1) * max(1, w-50)
                    py = 28 + y * 148
                    value = int(55 + 47 * (0.5 + 0.5 * math.sin(elapsed * speed + phase)))
                    color = '#%02x%02x%02x' % (value, value, int(value * 0.82))
                    self.canvas.coords(item, px, py, px+size, py+size)
                    self.canvas.itemconfigure(item, fill=color)
                scan_x = 40 + ((elapsed * (0.16 if self.busy else 0.075)) % 1) * max(1, w-80)
                self.canvas.coords(self._scan_glow, max(40, scan_x-36), 190, scan_x, 190)
                self.canvas.coords(self._scan, max(40, scan_x-15), 190, scan_x, 190)
                angle = elapsed * (0.65 if self.busy else 0.19)
                ox, oy = w-124+68*math.cos(angle), 104+68*math.sin(angle)
                self.canvas.coords(self._orbit_marker, ox-2, oy-2, ox+2, oy+2)
                lamp = '#bba372' if self.visual_state == 'success' else '#98625a' if self.visual_state == 'error' else '#bca775' if self.busy and math.sin(elapsed*4)>0 else '#746a53'
                self.status_lamp.itemconfigure(self._lamp, fill=lamp)
            self._animation_job = self.root.after(40 if self.root.state() != 'iconic' else 180, self._animate)
        except tk.TclError:
            # UAC handoff or a normal close may have destroyed the interpreter.
            self._animation_job = None

    def _on_destroy(self, event):
        if event.widget is not self.root: return
        if self._animation_job:
            try: self.root.after_cancel(self._animation_job)
            except tk.TclError: pass
            self._animation_job = None
        if self._font_resource and os.name == 'nt':
            try:
                remove_font = ctypes.windll.gdi32.RemoveFontResourceExW
                remove_font.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
                remove_font.restype = wintypes.BOOL
                remove_font(self._font_resource, 0x10, None)
            except (AttributeError, OSError): pass
            self._font_resource = None

    def choose(self):
        p = filedialog.askdirectory(parent=self.root, title='选择 Void War 游戏目录', initialdir=self.path.get() or None)
        if p:
            path = Path(p)
            for candidate in [path, path / 'steamapps/common/Void War', path / 'common/Void War']:
                if (candidate / 'Void War.exe').is_file(): path = candidate; break
            self.path.set(str(path))

    def set_busy(self, value):
        self.busy = value
        for widget in [self.entry, self.browse, self.install, self.restore]: widget.configure(state='disabled' if value else 'normal')
        if value:
            self.visual_state = 'working'; self.status_label.configure(fg='#c8c4b6')
            self.bar.configure(mode='indeterminate', value=0); self.bar.start(15)
        else: self.bar.stop()

    def start(self, action):
        if self.busy: return
        if not self.path.get().strip(): self.status.set('请先选择游戏目录。'); return
        game = Path(self.path.get().strip())
        self.set_busy(True); self.status.set('正在检查…'); logging.info('BEGIN %s', action)
        def worker():
            try:
                result = Installer(payload_dir(), game, self.profile, progress=lambda text: self.messages.put(('progress', text))).run(action)
                self.messages.put(('success', result)); logging.info('PASS %s', action)
            except PermissionError:
                logging.info('ERROR PERMISSION %s', action); self.messages.put(('permission', action))
            except PatchError as error:
                logging.info('ERROR %s %s', error.code, action); self.messages.put(('error', str(error)))
            except Exception:
                # Never put absolute paths, profile content or raw tracebacks in public logs.
                logging.info('ERROR INTERNAL %s', action)
                self.messages.put(('error', '操作未完成。已尽可能自动回滚；请保留原版备份，重新运行补丁器以恢复中断事务。'))
        threading.Thread(target=worker, daemon=False).start()

    def elevate(self, action):
        if os.name != 'nt' or ctypes.windll.shell32.IsUserAnAdmin():
            messagebox.showerror('权限不足', '无法写入游戏或设置目录，请检查文件权限与占用。', parent=self.root); return
        if not messagebox.askyesno('需要写入权限', 'Steam 游戏目录需要管理员权限。是否以管理员身份继续此操作？', parent=self.root):
            self.status.set('操作已停止；没有获得额外权限。'); return
        argv = ['--game', self.path.get(), '--profile', str(self.profile), '--action', action]
        if not getattr(sys, 'frozen', False): argv.insert(0, str(Path(__file__).resolve()))
        execute = ctypes.windll.shell32.ShellExecuteW
        execute.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                            wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int]
        execute.restype = wintypes.HINSTANCE
        result = execute(None, 'runas', sys.executable, subprocess.list2cmdline(argv), None, 1)
        if (result or 0) > 32: self.root.destroy()
        else: self.status.set('管理员授权未完成；请重新运行。')

    def poll(self):
        try:
            while True:
                kind, content = self.messages.get_nowait()
                if kind == 'progress': self.status.set(content)
                elif kind == 'success':
                    self.set_busy(False)
                    self.visual_state = 'success'; self.status_label.configure(fg='#dfcc9c')
                    self.bar.configure(mode='determinate', value=100)
                    self.status.set('汉化已安装并通过散列校验，可从 Steam 正常启动。' if content['action'] == 'install' else '原版已还原，当前游戏进度未回滚。')
                elif kind == 'permission': self.set_busy(False); self.elevate(content)
                else:
                    self.set_busy(False); self.visual_state = 'error'; self.status_label.configure(fg='#d6a49b')
                    self.status.set(content); messagebox.showerror('未完成', content, parent=self.root)
        except queue.Empty: pass
        try:
            if self.root.winfo_exists(): self.root.after(100, self.poll)
        except tk.TclError:
            # A successful UAC handoff has already closed this Tk interpreter.
            return

    def close(self):
        if self.busy: self.status.set('正在完成事务，请等待校验结束后关闭。')
        else: self.root.destroy()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--game'); parser.add_argument('--profile'); parser.add_argument('--action', choices=['install', 'restore'])
    parser.add_argument('--self-check-report', type=Path)
    args = parser.parse_args()
    if args.self_check_report: self_check(args.self_check_report); return
    configure_log()
    root = tk.Tk()
    try: App(root, args)
    except Exception:
        root.withdraw(); messagebox.showerror('无法启动', '补丁载荷缺失或无效，请重新下载完整 EXE。', parent=root); root.destroy(); return
    root.mainloop()

if __name__ == '__main__': main()
