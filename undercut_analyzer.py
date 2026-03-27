"""
undercut_analyzer.py
--------------------
Analyserer et 3D-mesh for underskæringer (undercuts) langs kandidat-
udtræksretninger og returnerer en rangeret liste af optimale retninger.

Algoritme:
  1. Generer K kandidatretninger jævnt fordelt på en enhedskugle
     (icosphere-sampling, standard K=500).
  2. For hver retning: beregn dot-produkt mellem retning og face-normaler.
     Face-normaler med negativt dot-produkt peger "imod" udtræksretningen
     og udgør underskæringer.
  3. Underskærings-score = underskæringsareal / totalt overfladeareal.
  4. Returner rangeret liste (lavest score = bedst).

GPU-acceleration:
  Hele batch-beregningen (trin 2+3 for alle K retninger) køres parallelt
  på GPU via GPUAccelerator.batch_undercut_scores() med CuPy.
  Falder automatisk tilbage til NumPy hvis GPU ikke er tilgængelig.

Kendte begrænsninger / halvfærdigt arbejde:
  - Icosphere-sampling er uniform men ikke optimal; adaptive sampling
    baseret på kurvatur er ikke implementeret endnu.
  - Analyse langs kurvede delingsflader (parting surfaces) understøttes
    ikke – kun flade splitplaner.
  - Tærskelværdien (-0.01) er ikke auto-kalibreret til mesh-skala.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import trimesh.creation
import trimesh

from .gpu_accelerator import GPUAccelerator

logger = logging.getLogger(__name__)


@dataclass
class DirectionResult:
    """Resultat for én udtræksretning."""
    direction:     np.ndarray    # (3,) enhedsvektor
    score:         float         # underskæringsareal / totalt areal  (0..1)
    undercut_pct:  float         # score × 100  (bekvemt display)
    axis_aligned:  bool          # Er retningen akseparallel (±X/Y/Z)?

    def __repr__(self) -> str:
        ax = "ja" if self.axis_aligned else "nej"
        return (
            f"DirectionResult(dir={np.round(self.direction,3)}, "
            f"underskæring={self.undercut_pct:.2f}%, akseparallel={ax})"
        )


@dataclass
class UndercutReport:
    """Samlet rapport fra UndercutAnalyzer.analyze()."""
    total_faces:        int
    total_area_mm2:     float
    n_directions_tested: int
    results:            list[DirectionResult]   # Rangeret, bedste først
    recommended_splits: int                     # Estimeret nødvendigt antal formhalvdele
    threshold_pct:      float                   # Konfigureret tærskel

    @property
    def best(self) -> DirectionResult:
        return self.results[0]

    @property
    def best_undercut_pct(self) -> float:
        return self.best.undercut_pct

    def top_n(self, n: int = 5) -> list[DirectionResult]:
        return self.results[:n]

    def summary(self) -> str:
        lines = [
            f"Analyseret {self.n_directions_tested} retninger på "
            f"{self.total_faces:,} trekanter ({self.total_area_mm2:.0f} mm²)",
            f"Bedste retning: {np.round(self.best.direction, 3)}  "
            f"→ {self.best_undercut_pct:.2f}% underskæring",
            f"Anbefalet antal formhalvdele: {self.recommended_splits}",
        ]
        return "\n".join(lines)


class UndercutAnalyzer:
    """
    Analyserer underskæringer i et trimesh.Trimesh.

    Eksempel::

        gpu = GPUAccelerator()
        analyzer = UndercutAnalyzer(gpu=gpu, n_directions=500)
        report = analyzer.analyze(mesh, threshold_pct=2.0)
        print(report.summary())
    """

    # 6 akseparallelle retninger tilføjes altid til kandidatlisten
    _AXIS_DIRECTIONS = np.array([
        [ 1,  0,  0], [-1,  0,  0],
        [ 0,  1,  0], [ 0, -1,  0],
        [ 0,  0,  1], [ 0,  0, -1],
    ], dtype=np.float32)

    def __init__(
        self,
        gpu:          Optional[GPUAccelerator] = None,   # type: ignore[name-defined]
        n_directions: int   = 500,
        dot_threshold: float = -0.01,
    ):
        """
        Args:
            gpu:           GPUAccelerator-instans (eller None for CPU).
            n_directions:  Antal jævnt fordelte kandidatretninger.
                           Højere tal = mere præcis analyse, men langsommere.
            dot_threshold: Dot-produkt grænse. Faces med dot < threshold
                           betragtes som underskæringer.
        """
        self.gpu           = gpu
        self.n_directions  = n_directions
        self.dot_threshold = dot_threshold
        self._directions   = self._build_direction_set(n_directions)

    # ──────────────────────────────────────────────────────────────────────────

    def analyze(
        self,
        mesh:          trimesh.Trimesh,
        threshold_pct: float = 2.0,
    ) -> UndercutReport:
        """
        Analysér mesh og returner UndercutReport.

        Args:
            mesh:          Det mesh der skal analyseres.
            threshold_pct: Acceptabel underskæringsprocent for todelt form.
                           Bruges til at estimere nødvendigt antal formhalvdele.
        """
        normals = mesh.face_normals.astype(np.float32)
        areas   = mesh.area_faces.astype(np.float32)
        dirs    = self._directions

        # ── Beregn scores (GPU eller CPU) ────────────────────────────────────
        use_gpu = (self.gpu is not None and self.gpu.available)
        if use_gpu:
            logger.info("Underskæringsanalyse: %d retninger på GPU …", len(dirs))
            try:
                mesh_gpu = self.gpu.transfer_mesh(mesh)
                scores   = self.gpu.batch_undercut_scores(
                    mesh_gpu, dirs, threshold=self.dot_threshold
                )
            except Exception as exc:                           # noqa: BLE001
                logger.warning("GPU-analyse fejlede (%s); falder tilbage til CPU.", exc)
                use_gpu = False

        if not use_gpu:
            logger.info("Underskæringsanalyse: %d retninger på CPU …", len(dirs))
            scores = GPUAccelerator.cpu_undercut_scores(
                normals, areas, dirs, threshold=self.dot_threshold
            )

        # ── Byg resultatliste ────────────────────────────────────────────────
        axis_set = {tuple(np.round(d, 6)) for d in self._AXIS_DIRECTIONS}
        results  = []
        for i, (direction, score) in enumerate(zip(dirs, scores)):
            results.append(DirectionResult(
                direction    = direction,
                score        = float(score),
                undercut_pct = float(score) * 100.0,
                axis_aligned = tuple(np.round(direction, 6)) in axis_set,
            ))

        results.sort(key=lambda r: r.score)

        # ── Estimér antal formhalvdele ────────────────────────────────────────
        # Naiv heuristik: hvis bedste todelte score > tærskel, prøv
        # at estimere om en sekundær retning (vinkelret på den bedste)
        # reducerer den resterende underskæring tilstrækkeligt.
        # TODO: erstat med den fulde sekventielle optimizer fra PartingOptimizer.
        recommended = self._estimate_part_count(results, threshold_pct, normals, areas)

        return UndercutReport(
            total_faces          = len(mesh.faces),
            total_area_mm2       = float(areas.sum()),
            n_directions_tested  = len(dirs),
            results              = results,
            recommended_splits   = recommended,
            threshold_pct        = threshold_pct,
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  Hjælpemetoder
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def _build_direction_set(cls, n: int) -> np.ndarray:
        """
        Generer N jævnt fordelte retninger på enhedskugle via icosphere-sampling
        kombineret med de 6 akseparallelle retninger.

        Returnerer (N+6, 3) float32-array af enhedsvektorer.
        """
        # Fibonacci-spiral sampling (hurtigere og jævnere end random)
        golden = (1.0 + np.sqrt(5.0)) / 2.0
        indices = np.arange(n, dtype=np.float64)
        theta   = np.arccos(1.0 - 2.0 * (indices + 0.5) / n)
        phi     = 2.0 * np.pi * indices / golden

        x = np.sin(theta) * np.cos(phi)
        y = np.sin(theta) * np.sin(phi)
        z = np.cos(theta)
        sphere_dirs = np.column_stack([x, y, z]).astype(np.float32)

        # Kombiner med akseparallelle retninger (deduplikér)
        all_dirs = np.vstack([sphere_dirs, cls._AXIS_DIRECTIONS])
        # Normalisér (fibonacci-sampling er allerede normaliseret)
        norms = np.linalg.norm(all_dirs, axis=1, keepdims=True)
        return (all_dirs / np.where(norms == 0, 1, norms)).astype(np.float32)

    @staticmethod
    def _estimate_part_count(
        results:       list[DirectionResult],
        threshold_pct: float,
        normals:       np.ndarray,
        areas:         np.ndarray,
    ) -> int:
        """
        Simpel heuristik til at estimere nødvendigt antal formhalvdele.

        TODO: Erstat med fuld sekventiel analyse fra PartingOptimizer
              som faktisk beregner restunderskæring korrekt.
        """
        best_score = results[0].score * 100.0
        if best_score <= threshold_pct:
            return 2
        # Meget grov heuristik baseret på bedste opnåelige score
        if best_score <= threshold_pct * 3:
            return 3
        if best_score <= threshold_pct * 6:
            return 4
        return 6   # Worst case – bruger bør inspicere manuelt


# Gør Optional tilgængelig uden import i type hints oven i filen
from typing import Optional   # noqa: E402
