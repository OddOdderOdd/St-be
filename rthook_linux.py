"""
installer/hooks/rthook_linux.py
--------------------------------
Runtime-hook der kører FØR applikationskoden ved Linux-start.

Opgaver:
  1. Tilføj bundled .so-biblioteker til LD_LIBRARY_PATH så OpenGL
     og PyQt6 kan finde dem uden system-installation.
  2. Sæt QT_QPA_PLATFORM til 'xcb' som fallback hvis intet display
     er sat (headless-miljøer returnerer fejl ellers).
  3. Deaktiver Qt's automatiske screen-scaling for forudsigeligt layout.
  4. Sæt XDG_DATA_DIRS til at inkludere bundled Qt-plugins.

Denne hook eksekveres af PyInstaller's bootloader som det første
Python-script og har adgang til sys._MEIPASS (bundle-mappen).
"""

import os
import sys

# ── 1. LD_LIBRARY_PATH ────────────────────────────────────────────────────────
bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

existing    = os.environ.get('LD_LIBRARY_PATH', '')
new_paths   = [
    bundle_dir,
    os.path.join(bundle_dir, 'PyQt6', 'Qt6', 'lib'),
    os.path.join(bundle_dir, 'PyQt6', 'Qt6', 'plugins', 'platforms'),
]
os.environ['LD_LIBRARY_PATH'] = ':'.join(new_paths) + ((':' + existing) if existing else '')

# ── 2. Qt platform ────────────────────────────────────────────────────────────
if 'DISPLAY' not in os.environ and 'WAYLAND_DISPLAY' not in os.environ:
    # Headless – brug offscreen platform (ingen 3D viewport)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
else:
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')

# ── 3. Qt scaling ─────────────────────────────────────────────────────────────
os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
os.environ.setdefault('QT_SCALE_FACTOR', '1')

# ── 4. Qt plugin-sti ─────────────────────────────────────────────────────────
qt_plugins = os.path.join(bundle_dir, 'PyQt6', 'Qt6', 'plugins')
if os.path.isdir(qt_plugins):
    os.environ['QT_PLUGIN_PATH'] = qt_plugins
