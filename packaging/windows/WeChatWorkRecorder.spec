# -*- mode: python ; coding: utf-8 -*-
"""在 Windows 上用 PyInstaller 生成含 Python/PySide6 的程序目录。"""
import os
from PyInstaller.utils.hooks import collect_data_files


a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.join(SPECPATH, "..", "..", "src")],
    binaries=[],
    datas=collect_data_files("wechat_work_recorder", includes=["historical_items.csv"]),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WeChatWorkRecorder",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WeChatWorkRecorder",
)
