# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.pyw'],
    pathex=[],
    binaries=[],
    datas=[('Frech_Birld.png', '.'), ('Silly_Bild.png', '.'), ('Verwirrt_Bild.png', '.'), ('Wutend_Bild.png', '.'), ('Frech_Birld.ico', '.')],
    # Optional features in main.pyw import these dynamically; include them in the bundle.
    hiddenimports=[
        'pypresence',
        'winotify',
        'win10toast',
        # win10toast depends on pywin32 modules
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        'pywintypes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CubePet_Final',
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
    icon='Frech_Birld.ico',
    version='version_info.txt',
)
