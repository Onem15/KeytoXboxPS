# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

datas = [('assets\\icon-KeytoXboxPS.png', 'assets'), ('assets\\icon-KeytoXboxPS.ico', 'assets')]
binaries = []
hiddenimports = [
    '_tkinter',
]
tmp_ret = collect_all('vgamepad')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ttkbootstrap')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

python_base = Path(sys.base_prefix)
tk_root = python_base / 'tcl'
for dll_name in ('tcl86t.dll', 'tk86t.dll'):
    dll_path = python_base / 'DLLs' / dll_name
    if dll_path.exists():
        binaries.append((str(dll_path), '.'))
for folder_name, target_name in (('tcl8.6', '_tcl_data'), ('tk8.6', '_tk_data')):
    folder_path = tk_root / folder_name
    if folder_path.exists():
        datas.append((str(folder_path), target_name))
module_dir = tk_root / 'tcl8'
if module_dir.exists():
    datas.append((str(module_dir), 'tcl8'))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['pyi_rth_tk_paths.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='KeytoXboxPS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    exclude_binaries=True,
    icon=['assets\\icon-KeytoXboxPS.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='KeytoXboxPS',
)
