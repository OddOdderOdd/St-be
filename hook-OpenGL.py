"""
installer/hooks/hook-OpenGL.py
-------------------------------
PyInstaller-hook for PyOpenGL.

PyOpenGL bruger dynamisk import af backend-moduler afhængigt af platform
(WGL på Windows, GLX på Linux). Disse fanges ikke af PyInstallers automatiske
analyse – vi skal eksplicit inkludere dem.

Derudover inkluderes OpenGL.arrays-backends da trimesh og vores viewport
bruger numpy-backed VBO'er.
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Saml alle sub-moduler i OpenGL
hiddenimports = collect_submodules('OpenGL')

# Inkludér OpenGL-data (shader-filer og lignende)
datas = collect_data_files('OpenGL')
