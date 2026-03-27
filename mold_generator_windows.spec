# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
#  PyInstaller spec-fil – Windows (.exe enkelt-fil + NSIS-installer)
#
#  Brug:
#    cd mold_generator/
#    pyinstaller installer/mold_generator_windows.spec
#
#  Output:
#    dist/MoldGenerator/MoldGenerator.exe   ← standalone-mappe
#    dist/MoldGenerator-setup.exe           ← NSIS-installer (kræver NSIS)
#
#  Forudsætninger:
#    pip install pyinstaller
#    NSIS installeret (https://nsis.sourceforge.io) og på PATH  [valgfrit]
#
#  Særlige hensyn:
#    - CuPy binaries (CUDA DLLer) kopieres eksplicit via collect_dynamic_libs
#    - PyOpenGL DLLer fanges af hookdir/hook-OpenGL.py
#    - trimesh's data-filer (JSON, OBJ-templates) inkluderes via collect_data_files
#    - manifold3d pyd-filer inkluderes via collect_dynamic_libs
#    - config/defaults.yaml og assets bundtes som datas
# =============================================================================

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# ── Datafiler ──────────────────────────────────────────────────────────────────
datas = []

# trimesh inkluderer JSON-metadata og skabeloner
datas += collect_data_files('trimesh',    include_py_files=False)

# Vores egne konfig- og asset-filer
datas += [
    ('config/defaults.yaml', 'config'),
    ('installer/assets/',    'assets'),
]

# ── Binaries (platform-specifikke DLLer) ───────────────────────────────────────
binaries = []
binaries += collect_dynamic_libs('manifold3d')

# CuPy CUDA-DLLer – find dem i site-packages
try:
    import cupy
    cupy_dir = Path(cupy.__file__).parent
    for dll in cupy_dir.rglob('*.dll'):
        binaries.append((str(dll), str(dll.relative_to(cupy_dir.parent))))
except ImportError:
    pass   # CuPy ikke installeret – kørsel sker på CPU-fallback

# ── Skjulte imports (pakker der detekteres dynamisk) ───────────────────────────
hiddenimports = [
    # PyQt6 plugins der kræves men ikke auto-detekteres
    'PyQt6.QtOpenGL',
    'PyQt6.QtOpenGLWidgets',
    'PyQt6.sip',
    # OpenGL backends
    'OpenGL.GL',
    'OpenGL.GLU',
    'OpenGL.GLUT',
    'OpenGL.arrays.vbo',
    'OpenGL.GL.framebufferobjects',
    # numpy sub-moduler der bruges dynamisk
    'numpy.core._multiarray_umath',
    'numpy.random',
    # scipy
    'scipy.spatial',
    'scipy.optimize',
    'scipy._lib.messagestream',
    # trimesh sub-moduler
    'trimesh.ray.ray_triangle',
    'trimesh.repair',
    'trimesh.creation',
    'trimesh.intersections',
    'trimesh.graph',
    # vores egne moduler
    'core.gpu_accelerator',
    'core.stl_loader',
    'core.undercut_analyzer',
    'core.parting_optimizer',
    'core.mold_builder',
    'core.registration',
    'core.sprue_calculator',
    'core.screw_cap_generator',
    'output.slicer_advisor',
    'output.stl_exporter',
    'gui.main_window',
    'gui.viewport_3d',
    'gui.settings_panel',
    'gui.output_panel',
]

# ── Eksklusions-liste (reducer størrelse) ──────────────────────────────────────
excludes = [
    'matplotlib',    # ikke brugt – ~30 MB
    'tkinter',       # ikke brugt
    'notebook',
    'IPython',
    'pandas',
    'PIL',
    'cv2',
    'sklearn',
    'test',
    'tests',
    'unittest',
    'doctest',
]

# ── Analysis ────────────────────────────────────────────────────────────────────
a = Analysis(
    ['../main.py'],
    pathex=[str(Path('../').resolve())],
    binaries  = binaries,
    datas     = datas,
    hiddenimports  = hiddenimports,
    hookspath      = ['installer/hooks'],
    hooksconfig    = {},
    runtime_hooks  = [],
    excludes       = excludes,
    win_no_prefer_redirects = False,
    win_private_assemblies  = False,
    cipher         = block_cipher,
    noarchive      = False,
)

# ── PYZ-arkiv ───────────────────────────────────────────────────────────────────
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher = block_cipher,
)

# ── EXE ─────────────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries = True,
    name             = 'MoldGenerator',
    debug            = False,
    bootloader_ignore_signals = False,
    strip            = False,
    upx              = True,         # UPX komprimering (kræver UPX på PATH)
    console          = False,        # Ingen konsol-vindue
    disable_windowed_traceback = False,
    target_arch      = None,
    codesign_identity= None,
    entitlements_file= None,
    icon             = 'installer/assets/icon.ico',  # Windows ikon
    version          = 'installer/version_info.txt',
)

# ── COLLECT (mappe-distribution) ─────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip    = False,
    upx      = True,
    upx_exclude = ['vcruntime140.dll', 'msvcp140.dll'],  # MS runtime – lad være urørt
    name     = 'MoldGenerator',
)
