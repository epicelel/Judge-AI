# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the JudgeAI GUI plus its CLI helper."""

from pathlib import Path

root = Path(SPECPATH)
prompt_data = [(str(root / "prompts"), "prompts")]

common = dict(
    pathex=[str(root)],
    datas=prompt_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

gui = Analysis([str(root / "gui_app.py")], **common)
gui_pyz = PYZ(gui.pure)
gui_exe = EXE(
    gui_pyz,
    gui.scripts,
    gui.binaries,
    gui.datas,
    [],
    name="JudgeAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

cli = Analysis([str(root / "judge.py")], **common)
cli_pyz = PYZ(cli.pure)
cli_exe = EXE(
    cli_pyz,
    cli.scripts,
    cli.binaries,
    cli.datas,
    [],
    name="JudgeAI-CLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
