"""
installer/hooks/rthook_windows.py
----------------------------------
Runtime-hook til Windows-builds.

Opgaver:
  1. Tilføj bundle-mappen til PATH så CUDA DLLer kan loades.
  2. Sæt Qt-plugin-stien eksplicit (undgår "no platform plugin" crash).
  3. Konfigurér High-DPI scaling kompatibelt med Windows 10/11.
  4. Tilføj Microsoft Visual C++ runtime-DLLer til søgestien hvis
     bundled (PyInstaller inkluderer dem ikke altid automatisk).
"""

import os
import sys

bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

# ── 1. DLL-søgesti ────────────────────────────────────────────────────────────
# os.add_dll_directory er tilgængeligt fra Python 3.8+ på Windows
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(bundle_dir)

    qt_bin = os.path.join(bundle_dir, 'PyQt6', 'Qt6', 'bin')
    if os.path.isdir(qt_bin):
        os.add_dll_directory(qt_bin)

    # CUDA DLLer – typisk kopieret til bundle_dir/cupy/
    cuda_paths = [
        os.path.join(bundle_dir, 'cupy'),
        os.path.join(bundle_dir, 'cuda'),
    ]
    for p in cuda_paths:
        if os.path.isdir(p):
            os.add_dll_directory(p)

# Tilføj også til PATH som fallback for ældre Windows-versioner
existing = os.environ.get('PATH', '')
os.environ['PATH'] = bundle_dir + os.pathsep + existing

# ── 2. Qt-plugin-sti ──────────────────────────────────────────────────────────
qt_plugins = os.path.join(bundle_dir, 'PyQt6', 'Qt6', 'plugins')
if os.path.isdir(qt_plugins):
    os.environ['QT_PLUGIN_PATH'] = qt_plugins

# ── 3. High-DPI ───────────────────────────────────────────────────────────────
os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')

# ── 4. Qt platform ────────────────────────────────────────────────────────────
os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
