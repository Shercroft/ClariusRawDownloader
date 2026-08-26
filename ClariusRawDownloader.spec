# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH)
browser_root_text = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
if not browser_root_text:
    raise SystemExit(
        "PLAYWRIGHT_BROWSERS_PATH must point to the Chromium folder created by "
        "'python -m playwright install chromium'. Use build_windows.bat."
    )

browser_root = Path(browser_root_text)
if not browser_root.is_dir():
    raise SystemExit(f"Bundled browser folder does not exist: {browser_root}")

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
playwright_datas.append((str(browser_root), "ms-playwright"))

a = Analysis(
    [str(project_root / "app.py")],
    pathex=[str(project_root)],
    binaries=playwright_binaries,
    datas=playwright_datas,
    hiddenimports=playwright_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "unittest.mock"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ClariusRawDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ClariusRawDownloader",
)
