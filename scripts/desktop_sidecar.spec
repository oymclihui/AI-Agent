# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AI-AGENT Desktop Sidecar."""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"

a = Analysis(
    [str(SCRIPTS / "desktop_sidecar_entry.py")],
    pathex=[str(BACKEND), str(SCRIPTS)],
    binaries=[],
    datas=[
        (str(BACKEND / "app"), "backend/app"),
        (str(SCRIPTS / "desktop_sidecar.py"), "scripts"),
        (str(SCRIPTS / "sidecar.env.example"), "."),
    ],
    hiddenimports=[
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "structlog",
        "pydantic_settings",
        "app.config",
        "app.core.desktop.openadapt_runner",
        "desktop_sidecar",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib", "numpy", "pandas", "langchain", "sqlalchemy"],
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
    name="AIAGNET-Desktop-Sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
