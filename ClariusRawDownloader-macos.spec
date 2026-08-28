# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH)

# IMPORTANT:
# Chromium is intentionally NOT added to Analysis/datas on macOS. Modern
# Playwright Chromium contains nested signed .app bundles and Mach-O binaries.
# If those files are handed to PyInstaller, PyInstaller tries to post-process
# and ad-hoc re-sign them, which can fail during COLLECT (especially on Intel
# runners). The GitHub Actions workflow copies the untouched browser tree into
# App.app/Contents/Resources/ms-playwright after PyInstaller finishes.
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
signing_identity = os.environ.get("MACOS_CODESIGN_IDENTITY", "").strip() or None

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
    argv_emulation=False,
    target_arch=None,
    codesign_identity=signing_identity,
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

app = BUNDLE(
    coll,
    name="ClariusRawDownloader.app",
    icon=None,
    bundle_identifier="org.research.clariusrawdownloader",
    version="1.2.0",
    info_plist={
        "CFBundleDisplayName": "Clarius RAW Data Downloader",
        "CFBundleShortVersionString": "1.2.0",
        "CFBundleVersion": "1.2.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    },
)
