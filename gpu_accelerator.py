"""
gpu_accelerator.py
------------------
CUDA-wrapper til GPU-accelererede geometriberegninger.

Understøtter:
  - Underskæringsanalyse (raycast, 500 retninger parallelt)
  - Surface-area-akkumulering
  - Voxel-boolean hjælpefunktioner

Falder gracefully tilbage til NumPy/CPU hvis:
  - CuPy ikke er installeret
  - Ingen NVIDIA GPU er tilgængelig
  - CUDA-versionen er inkompatibel

Kendte begrænsninger / halvfærdigt arbejde:
  - BVH-acceleration på GPU er ikke implementeret endnu;
    raycast bruger en naiv O(N·M) kernel som er langsom
    for meshes med > ~500 k trekanter.
  - multi-GPU (> 1 kort) er ikke understøttet.
  - Voxel-boolean hjælpefunktioner er stub-implementering –
    selve boolean ops kører stadig via manifold3d på CPU.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MeshGPU:
    """Mesh-data resident på GPU-hukommelse (CuPy arrays)."""
    vertices: object   # cp.ndarray  (N, 3)  float32
    faces:    object   # cp.ndarray  (M, 3)  int32
    normals:  object   # cp.ndarray  (M, 3)  float32
    areas:    object   # cp.ndarray  (M,)    float32
    _xp:      object = field(repr=False, default=None)  # cupy-modulet

    def to_cpu(self) -> dict[str, np.ndarray]:
        """Kopier data tilbage til CPU-hukommelse som NumPy-arrays."""
        xp = self._xp
        return {
            "vertices": xp.asnumpy(self.vertices),
            "faces":    xp.asnumpy(self.faces),
            "normals":  xp.asnumpy(self.normals),
            "areas":    xp.asnumpy(self.areas),
        }


class GPUAccelerator:
    """
    Håndterer GPU-initialisering og tilbyder accelererede operationer.

    Eksempel::

        gpu = GPUAccelerator()
        if gpu.available:
            mesh_gpu = gpu.transfer_mesh(trimesh_mesh)
            scores   = gpu.batch_undercut_scores(mesh_gpu, directions)
        else:
            # Fald tilbage til cpu_undercut_scores()
            ...
    """

    def __init__(self, device_index: int = 0, force_cpu: bool = False):
        self.device_index = device_index
        self.available    = False
        self._cp          = None          # cupy-modul eller None
        self._compute_cap: Optional[str]  = None

        if not force_cpu:
            self._try_init_cuda()

    # ──────────────────────────────────────────────────────────────────────────
    #  Initialisering
    # ──────────────────────────────────────────────────────────────────────────

    def _try_init_cuda(self) -> None:
        try:
            import cupy as cp                                   # type: ignore
            device = cp.cuda.Device(self.device_index)
            device.use()
            self._compute_cap = ".".join(str(x) for x in device.compute_capability)
            _ = cp.zeros(1)  # Trigger faktisk initialisering
            self._cp = cp
            self.available = True
            logger.info(
                "GPU klar: device=%d  compute capability=%s",
                self.device_index, self._compute_cap
            )
        except ImportError:
            warnings.warn(
                "CuPy er ikke installeret – kører på CPU. "
                "Installer med:  pip install cupy-cuda12x",
                stacklevel=2,
            )
        except Exception as exc:                               # noqa: BLE001
            warnings.warn(
                f"GPU-initialisering fejlede ({exc}) – kører på CPU.",
                stacklevel=2,
            )

    @property
    def compute_capability(self) -> Optional[str]:
        return self._compute_cap

    # ──────────────────────────────────────────────────────────────────────────
    #  Data-overførsel
    # ──────────────────────────────────────────────────────────────────────────

    def transfer_mesh(self, mesh) -> MeshGPU:
        """
        Overfør trimesh.Trimesh til GPU-hukommelse.

        Konverterer til float32 / int32 for lavere VRAM-forbrug og
        bedre GPU-gennemløb.
        """
        if not self.available:
            raise RuntimeError("GPU ikke tilgængelig; kald ikke transfer_mesh().")
        cp = self._cp
        return MeshGPU(
            vertices = cp.asarray(mesh.vertices.astype(np.float32)),
            faces    = cp.asarray(mesh.faces.astype(np.int32)),
            normals  = cp.asarray(mesh.face_normals.astype(np.float32)),
            areas    = cp.asarray(mesh.area_faces.astype(np.float32)),
            _xp      = cp,
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  Underskæringsanalyse
    # ──────────────────────────────────────────────────────────────────────────

    def batch_undercut_scores(
        self,
        mesh_gpu: MeshGPU,
        directions: np.ndarray,          # (K, 3)  udtræksretninger
        threshold: float = -0.01,
    ) -> np.ndarray:
        """
        Beregn underskærings-score for K retninger parallelt på GPU.

        Score = underskæringsareal / total overfladeareal  (0..1).
        Lavere score = bedre udtræksretning.

        Args:
            mesh_gpu:   Mesh-data på GPU.
            directions: (K, 3) enheds-vektorer der skal testes.
            threshold:  Dot-produkt grænse for hvornår en flade
                        betragtes som en underskæring.

        Returns:
            (K,) float32 array med score pr. retning (på CPU).

        TODO:
            Implementér BVH-acceleration. Nuværende O(N·K) kernel er
            acceptabel op til ~100 k trekanter; større meshes bør
            voxeliseres eller stykkes op inden analyse.
        """
        cp = self._cp
        dirs_gpu   = cp.asarray(directions.astype(np.float32))  # (K, 3)
        normals    = mesh_gpu.normals                            # (M, 3)
        areas      = mesh_gpu.areas                              # (M,)
        total_area = float(cp.sum(areas))

        if total_area == 0.0:
            return np.zeros(len(directions), dtype=np.float32)

        # dots[k, m] = dot(direction[k], normal[m])
        dots      = cp.dot(dirs_gpu, normals.T)                 # (K, M)
        undercuts = dots < threshold                             # (K, M) bool

        # Areal-sum for underskæringer pr. retning
        scores_gpu = cp.dot(undercuts.astype(cp.float32), areas) / total_area
        return cp.asnumpy(scores_gpu)                           # (K,) på CPU

    # ──────────────────────────────────────────────────────────────────────────
    #  CPU-fallback
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def cpu_undercut_scores(
        normals:    np.ndarray,          # (M, 3)
        areas:      np.ndarray,          # (M,)
        directions: np.ndarray,          # (K, 3)
        threshold:  float = -0.01,
    ) -> np.ndarray:
        """
        Ren NumPy-implementering af batch_undercut_scores.
        Bruges automatisk når GPU ikke er tilgængelig.
        Kræver ~8 × M × K bytes RAM for float32.
        """
        total_area = areas.sum()
        if total_area == 0.0:
            return np.zeros(len(directions), dtype=np.float32)

        dots      = directions @ normals.T          # (K, M)
        undercuts = (dots < threshold).astype(np.float32)
        return (undercuts @ areas) / total_area     # (K,)

    # ──────────────────────────────────────────────────────────────────────────
    #  Diagnostik
    # ──────────────────────────────────────────────────────────────────────────

    def info(self) -> dict:
        """Returner diagnostikinformation om GPU-tilstand."""
        base = {"available": self.available, "device_index": self.device_index}
        if self.available:
            cp = self._cp
            mem = cp.cuda.Device(self.device_index).mem_info
            base.update({
                "compute_capability": self._compute_cap,
                "free_vram_mb":  mem[0] // 1024 // 1024,
                "total_vram_mb": mem[1] // 1024 // 1024,
            })
        return base
