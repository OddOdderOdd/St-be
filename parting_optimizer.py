"""
parting_optimizer.py
--------------------
Bestemmer det optimale antal formhalvdele og de tilhørende splitplaner.

Algoritme (sekventiel greedy):
  1. Vælg primær udtræksretning D₁ (fra UndercutAnalyzer).
  2. Beregn residuel underskæring for resterende faces under D₁.
  3. Søg D₂ vinkelret på D₁ der minimerer residualen.
  4. Gentag for D₃, D₄, … indtil underskæring < tærskel eller max_parts nået.

Asymmetrisk logik (toggle):
  Når aktiveret søges D₂ … Dₙ uden kravet om ortogonalitet med tidligere
  retninger. Dette kan reducere antallet af formhalvdele men giver
  vanskeligere formgeometri. Implementeret som brute-force søgning over
  samme icosphere-kandidatsæt som UndercutAnalyzer.

Kendte begrænsninger / halvfærdigt arbejde:
  - Selve splitplanet gemmes som (punkt, normal) – clipning af mesh'et
    til formhalvdele udføres i MoldBuilder, ikke her.
  - Asymmetrisk logik er implementeret men ikke optimeret; den kører
    en fuld sekventiel søgning og er ~3× langsommere end symmetrisk.
  - Kurvede parting surfaces (f.eks. cylindriske forme) understøttes ikke.
  - Validering af at de fundne splitplaner ikke skærer hinanden er
    ikke implementeret; ved 4+ dele kan der opstå konflikter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import trimesh

from .undercut_analyzer import UndercutAnalyzer, UndercutReport, DirectionResult
from .gpu_accelerator import GPUAccelerator

logger = logging.getLogger(__name__)


@dataclass
class SplitPlane:
    """Beskriver et enkelt splitplan."""
    normal:    np.ndarray    # (3,) enhedsvektor
    point:     np.ndarray    # (3,) et punkt i planet (typisk mesh-centroid)
    part_index: int          # Hvilken formhalvdel hører dette plan til (0-baseret)

    def __repr__(self) -> str:
        return (
            f"SplitPlane(normal={np.round(self.normal,3)}, "
            f"point={np.round(self.point,3)}, del={self.part_index})"
        )


@dataclass
class PartingResult:
    """Komplet output fra PartingOptimizer.optimize()."""
    n_parts:          int
    split_planes:     list[SplitPlane]
    final_undercut_pct: float
    symmetric:        bool
    warnings:         list[str] = field(default_factory=list)

    def summary(self) -> str:
        sym = "symmetrisk" if self.symmetric else "asymmetrisk"
        lines = [
            f"Antal formhalvdele: {self.n_parts}  ({sym} logik)",
            f"Resterende underskæring: {self.final_undercut_pct:.2f}%",
        ]
        for i, sp in enumerate(self.split_planes):
            lines.append(f"  Splitplan {i+1}: normal={np.round(sp.normal,3)}")
        for w in self.warnings:
            lines.append(f"⚠  {w}")
        return "\n".join(lines)


class PartingOptimizer:
    """
    Finder optimalt antal formhalvdele og tilhørende splitplaner.

    Eksempel::

        optimizer = PartingOptimizer(gpu=gpu, symmetric=True, max_parts=4)
        result = optimizer.optimize(mesh, undercut_report, threshold_pct=2.0)
        print(result.summary())
    """

    def __init__(
        self,
        gpu:          Optional[GPUAccelerator] = None,
        symmetric:    bool = True,
        max_parts:    int  = 6,
        n_directions: int  = 300,     # Færre end analyse-fasen er tilstrækkeligt
        dot_threshold: float = -0.01,
    ):
        self.gpu           = gpu
        self.symmetric     = symmetric
        self.max_parts     = max_parts
        self.n_directions  = n_directions
        self.dot_threshold = dot_threshold
        self._candidates   = UndercutAnalyzer._build_direction_set(n_directions)

    # ──────────────────────────────────────────────────────────────────────────

    def optimize(
        self,
        mesh:             trimesh.Trimesh,
        undercut_report:  UndercutReport,
        threshold_pct:    float = 2.0,
    ) -> PartingResult:
        """
        Find optimale splitplaner.

        Args:
            mesh:            Mesh der skal opdeles.
            undercut_report: Resultat fra UndercutAnalyzer.analyze().
            threshold_pct:   Acceptable resterende underskæring (%).

        Returns:
            PartingResult med splitplaner og diagnostik.
        """
        warnings: list[str] = []
        normals = mesh.face_normals.astype(np.float32)
        areas   = mesh.area_faces.astype(np.float32)
        centroid = np.array(mesh.centroid, dtype=np.float32)

        # Start med den bedste retning fra underskæringsanalysen
        best_dir    = undercut_report.best.direction
        split_planes = [SplitPlane(normal=best_dir, point=centroid, part_index=0)]
        current_score = undercut_report.best.score * 100.0

        logger.info(
            "Start: bedste retning %s → %.2f%% underskæring",
            np.round(best_dir, 3), current_score
        )

        # Iterér: tilføj splitplaner indtil tærskel nået eller max_parts nået
        covered_mask = self._faces_covered_by(normals, best_dir)

        for part_idx in range(1, self.max_parts - 1):
            if current_score <= threshold_pct:
                break

            # Søg næste retning
            candidates = self._filter_candidates(best_dir if self.symmetric else None)
            next_dir, next_score = self._find_best_for_residual(
                normals, areas, covered_mask, candidates
            )

            new_covered = self._faces_covered_by(normals, next_dir)
            combined_mask = covered_mask | new_covered

            # Beregn ny samlet underskæring
            total_area      = areas.sum()
            uncovered_area  = areas[~combined_mask].sum()
            new_score_pct   = (uncovered_area / total_area * 100.0) if total_area > 0 else 0.0

            improvement = current_score - new_score_pct
            logger.info(
                "Del %d: retning %s → %.2f%% residual (forbedring %.2f%%)",
                part_idx + 1, np.round(next_dir, 3), new_score_pct, improvement
            )

            if improvement < 0.1:
                warnings.append(
                    f"Splitplan {part_idx + 1} reducerer underskæringen med < 0.1%; "
                    "yderligere dele anbefales ikke."
                )
                break

            split_planes.append(
                SplitPlane(normal=next_dir, point=centroid, part_index=part_idx)
            )
            covered_mask  = combined_mask
            current_score = new_score_pct

        n_parts = len(split_planes) + 1   # Antal dele = antal planer + 1

        if current_score > threshold_pct:
            warnings.append(
                f"Resterende underskæring ({current_score:.1f}%) overstiger "
                f"tærskel ({threshold_pct:.1f}%) efter {n_parts} dele. "
                "Overvej asymmetrisk logik eller manuel justering."
            )

        return PartingResult(
            n_parts            = n_parts,
            split_planes       = split_planes,
            final_undercut_pct = current_score,
            symmetric          = self.symmetric,
            warnings           = warnings,
        )

    # ──────────────────────────────────────────────────────────────────────────
    #  Hjælpemetoder
    # ──────────────────────────────────────────────────────────────────────────

    def _faces_covered_by(
        self, normals: np.ndarray, direction: np.ndarray
    ) -> np.ndarray:
        """
        Returnerer bool-maske: True for faces der KAN udtræk es i `direction`.
        En face er "covered" (ikke en underskæring) hvis dot >= dot_threshold.
        """
        dots = normals @ direction
        return dots >= self.dot_threshold

    def _filter_candidates(
        self, primary: Optional[np.ndarray]
    ) -> np.ndarray:
        """
        Ved symmetrisk logik: filtrer kandidater der er tilnærmelsesvis
        vinkelrette på `primary` (|dot| < 0.3).
        Ved asymmetrisk logik: returnér alle kandidater.
        """
        if primary is None or not self.symmetric:
            return self._candidates
        dots = np.abs(self._candidates @ primary)
        return self._candidates[dots < 0.3]

    @staticmethod
    def _find_best_for_residual(
        normals:       np.ndarray,        # (M, 3)
        areas:         np.ndarray,        # (M,)
        covered_mask:  np.ndarray,        # (M,) bool
        candidates:    np.ndarray,        # (K, 3)
    ) -> tuple[np.ndarray, float]:
        """
        Find den kandidatretning der dækker flest af de resterende
        (endnu ikke-dækkede) underskæringer.

        Returnerer (bedste_retning, bedste_score_pct).
        """
        residual_normals = normals[~covered_mask]
        residual_areas   = areas[~covered_mask]

        if len(residual_normals) == 0:
            return candidates[0], 0.0

        total_area = areas.sum()

        # dots[k, m] = dot(candidate[k], residual_normal[m])
        dots           = candidates @ residual_normals.T          # (K, M_res)
        newly_covered  = dots >= -0.01                            # (K, M_res) bool
        covered_area   = (newly_covered.astype(np.float32) @ residual_areas)  # (K,)

        # Vi vil maksimere ny dækning = minimere resterende underskæring
        remaining_residual = (residual_areas.sum() - covered_area) / total_area * 100.0
        best_idx = int(np.argmin(remaining_residual))
        return candidates[best_idx], float(remaining_residual[best_idx])
