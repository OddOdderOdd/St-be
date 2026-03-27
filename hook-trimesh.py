"""
installer/hooks/hook-trimesh.py
--------------------------------
PyInstaller-hook for trimesh.

trimesh bruger lazy-loading af mange valgfri backends (networkx, rtree,
shapely, pymeshfix osv.). Vi inkluderer kun de backends der faktisk bruges
i Mold Generator og ekskluderer de store valgfri pakker.

Bemærk:
  - trimesh.ray.ray_triangle kræver eksplicit inkludering
  - trimesh.creation og trimesh.repair bruges direkte
  - networkx inkluderes fordi trimesh.graph bruger det til
    connected-components analyse i lomme-detektion
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Alle trimesh-data (JSON-beskrivelser af primitiver, farvetabeller)
datas = collect_data_files('trimesh')

# Kerne-submoduler vi bruger
hiddenimports = [
    'trimesh.ray',
    'trimesh.ray.ray_triangle',
    'trimesh.repair',
    'trimesh.creation',
    'trimesh.intersections',
    'trimesh.graph',
    'trimesh.collision',
    'trimesh.primitives',
    'trimesh.transformations',
    'trimesh.bounds',
    'trimesh.util',
]

# networkx bruges af trimesh.graph til connected-components
hiddenimports += ['networkx', 'networkx.algorithms.components']
