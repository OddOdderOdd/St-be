"""
installer/hooks/hook-cupy.py
-----------------------------
PyInstaller-hook for CuPy.

CuPy er en valgfri afhængighed – hvis den ikke er installeret kører
programmet på CPU-fallback. Hooken er defensiv: den fejler ikke hvis
CuPy ikke er til stede.

Hvad der IKKE inkluderes (for at holde størrelsen nede):
  - cupy.cuda.compiler (kræver nvcc – ikke nødvendigt at bundle)
  - cupy.testing
  - cupy.prof

CUDA runtime-biblioteker (libcuda.so, cudart.dll) inkluderes IKKE –
disse skal være installeret af brugeren via CUDA Toolkit.
Programmet fungerer uden dem (CPU-fallback aktiveres).
"""

from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs
import sys

try:
    import cupy  # noqa: F401
    HAS_CUPY = True
except ImportError:
    HAS_CUPY = False

if HAS_CUPY:
    # Saml kun de submoduler vi bruger
    hiddenimports = [
        'cupy',
        'cupy.core',
        'cupy.cuda',
        'cupy.cuda.device',
        'cupy.cuda.memory',
        'cupy.linalg',
        'cupy.random',
        'cupy._core',
    ]
    # Platform-specifikke binaries (.pyd / .so)
    binaries = collect_dynamic_libs('cupy')
else:
    hiddenimports = []
    binaries      = []
