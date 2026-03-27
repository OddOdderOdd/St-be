# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
#  PyInstaller spec-fil – Linux (.AppImage via appimage-builder)
#
#  Trin 1 – byg PyInstaller onedir-bundle:
#    cd mold_generator/
#    pyinstaller installer/mold_generator_linux.spec
#
#  Trin 2 – pak som AppImage (kræver appimage-builder):
#    pip install appimage-builder
#    appimage-builder --recipe installer/AppImageBuilder.yml
#
#  Output:
#    dist/MoldGenerator/              ← onedir-bundle
#    MoldGenerator-x86_64.AppImage   ← self-contained AppImage
#
#  Note om CuPy på Linux:
#    CuPy linker dynamisk mod libcuda.so.1 og libcublas.so.  Disse er IKKE
#    bundtet – brugeren skal have CUDA Toolkit ≥ 12.0 installeret.
#    PyInstaller inkluderer cupy .so-filer men IKKE CUDA runtime-biblioteker
#    da disse er meget store (>500 MB) og distribueres af NVIDIA.
#    Kørsel på CPU-fallback virker uden CUDA.
# =============================================================================

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

# ── Datafiler ──────────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files('trimesh', include_py_files=False)
datas += [
    ('config/defaults.yaml', 'config'),
    ('installer/assets/',    'assets'),
]

# ── Binaries ──────────────────────────────────────────────────────────────────
binaries = []
binaries += collect_dynamic_libs('manifold3d')

# CuPy .so filer
try:
    import cupy
    cupy_dir = Path(cupy.__file__).parent
    for so in cupy_dir.rglob('*.so*'):
        if so.is_file() and not so.is_symlink():
            rel = so.relative_to(cupy_dir.parent)
            binaries.append((str(so), str(rel.parent)))
except ImportError:
    pass

# ── Skjulte imports (identisk med Windows) ────────────────────────────────────
hiddenimports = [
    'PyQt6.QtOpenGL',
    'PyQt6.QtOpenGLWidgets',
    'PyQt6.sip',
    'OpenGL.GL',
    'OpenGL.GLU',
    'OpenGL.arrays.vbo',
    'OpenGL.GL.framebufferobjects',
    'numpy.core._multiarray_umath',
    'numpy.random',
    'scipy.spatial',
    'scipy.optimize',
    'scipy._lib.messagestream',
    'trimesh.ray.ray_triangle',
    'trimesh.repair',
    'trimesh.creation',
    'trimesh.intersections',
    'trimesh.graph',
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

excludes = [
    'matplotlib', 'tkinter', 'notebook', 'IPython',
    'pandas', 'PIL', 'cv2', 'sklearn', 'test', 'tests',
    'unittest', 'doctest',
]

a = Analysis(
    ['../main.py'],
    pathex=[str(Path('../').resolve())],
    binaries       = binaries,
    datas          = datas,
    hiddenimports  = hiddenimports,
    hookspath      = ['installer/hooks'],
    hooksconfig    = {},
    runtime_hooks  = ['installer/hooks/rthook_linux.py'],
    excludes       = excludes,
    win_no_prefer_redirects = False,
    win_private_assemblies  = False,
    cipher         = block_cipher,
    noarchive      = False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries = True,
    name             = 'MoldGenerator',
    debug            = False,
    strip            = True,      # Strip debug-symboler på Linux
    upx              = False,     # UPX ikke anbefalet til Linux .so filer
    console          = False,
    icon             = 'installer/assets/icon.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip  = True,
    upx    = False,
    name   = 'MoldGenerator',
)
