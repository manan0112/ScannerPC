# scanner.spec — PyInstaller build specification
# Run via:  pyinstaller scanner.spec
# Or use:   build.bat  (handles everything automatically)

import sys
from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.build_main import Analysis

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    # Force-include collector sub-modules — PyInstaller misses dynamic imports.
    hiddenimports=[
        'collectors.system_info',
        'collectors.software',
        'collectors.processes',
        'collectors.disk_health',
        'collectors.startup',
        'collectors.security',
        'collectors.network',
        'collectors.onedrive',
        'collectors.junk',
        'collectors.user_folders',
        'collectors.folders',
        'collectors.files',
        'collectors.metadata',
        'winreg',
        'ctypes',
        'ctypes.wintypes',
        'json',
        'subprocess',
        'glob',
        'uuid',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Only exclude modules that are safe to drop (no bootloader dependency).
        'tkinter', 'turtle', 'turtledemo', 'idlelib',
        'antigravity', 'this',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='scanner',           # output: scanner.exe
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                 # compress with UPX if available (smaller exe)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,             # keep console so the user sees progress output
    disable_windowed_traceback=False,
    target_arch=None,         # inherit from build machine (use x64 host)
    codesign_identity=None,
    entitlements_file=None,
    # Embed a version string visible in Windows Explorer > Properties.
    version=None,             # set to 'version_info.txt' if you add one
    icon=None,                # set to 'scanner.ico' if you have one
    # Write the exe directly to dist/ (one-file mode, no subfolder needed).
    onefile=True,
)