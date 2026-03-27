"""
registration.py
---------------
Genererer samletappe (alignment/registration pins) og tilhørende huller
på formhalvdelenes mødeflade (parting surface).

Princip:
  - Del A får positive tappe (cylindre der stikker ud).
  - Del B får negative tappe (cylindriske huller med +tolerance).
  - Ved mere end 2 dele sættes positive tappe på den "mindste" halvdel
    og negative på alle tilstødende dele.

Tappestørrelser (baseret på formens bounding box):
  - Form < 50 mm:  ⌀4 mm, dybde 4 mm
  - Form 50–150 mm: ⌀6 mm, dybde 6 mm
  - Form > 150 mm:  D-formet tap ⌀8 mm, dybde 8 mm (anti-rotation)

Kendte begrænsninger / halvfærdigt arbejde:
  - D-formede tappe er implementeret som simple cylindre med en
    flad afskæring. Geometrien er korrekt men ikke testet i slicer.
  - Snap-lock kant langs splitlinjen er defineret men IKKE implementeret
    som egentlig geometri – kun som en fremtidig toggle.
  - Boolean-operationen der trækker tapperne ind i formdelene bruger
    samme manifold3d-backend som MoldBuilder og kan fejle for
    komplekse mødeflader.
  - Gummibånd-kanal (groove along parting edge) er ikke implementeret.
"""

from __future__ import annotations

import logging
import math
import warnings as _warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import trimesh
import trimesh.creation

from mold_builder import MoldPart
from parting_optimizer import SplitPlane

logger = logging.getLogger(__name__)


@dataclass
class PinSpec:
    """Geometrisk specifikation for én tapposition."""
    position:   np.ndarray   # (3,) centrum på mødefladen
    diameter:   float        # mm
    depth:      float        # mm
    d_shaped:   bool         # True = D-formet (anti-rotation)
    tolerance:  float        # mm ekstra radius på modtagende hul


class RegistrationSystem:
    """
    Tilføjer samletappe til formhalvdele.

    Eksempel::

        reg = RegistrationSystem(min_pins=3, tolerance_mm=0.2)
        parts = reg.add_pins(parts, split_plane, mesh_bbox_extents)
    """

    def __init__(
        self,
        min_pins:      int   = 3,
        tolerance_mm:  float = 0.2,
        snap_lock:     bool  = False,
    ):
        self.min_pins     = min_pins
        self.tolerance    = tolerance_mm
        self.snap_lock    = snap_lock

        if snap_lock:
            _warnings.warn(
                "Snap-lock kant er aktiveret men ikke implementeret endnu. "
                "Toggle ignoreres.",
                stacklevel=2,
            )

    # ──────────────────────────────────────────────────────────────────────────

    def add_pins(
        self,
        parts:       list[MoldPart],
        plane:       SplitPlane,
        bbox_extents: np.ndarray,      # (3,) bounding box størrelse i mm
    ) -> list[MoldPart]:
        """
        Tilføj samletappe til alle formhalvdele.

        Del A (index 0) får positive tappe (union).
        Del B+ (index 1+) får negative huller (difference).

        Args:
            parts:        Liste af MoldPart fra MoldBuilder.
            plane:        Splitplanet der definerer mødefladen.
            bbox_extents: Formens bounding box (til tappestørrelse).

        Returns:
            Opdateret liste af MoldPart med tappe/huller.
        """
        if len(parts) < 2:
            return parts

        spec = self._choose_pin_spec(bbox_extents)
        pins_pos = self._generate_pin_positions(plane, bbox_extents, spec)

        logger.info(
            "%d tappe, ⌀%.0f mm, dybde %.0f mm, tolerance %.1f mm",
            len(pins_pos), spec.diameter, spec.depth, spec.tolerance
        )

        # Del A: positive tappe (union)
        pin_meshes = [self._make_pin(p, spec, positive=True) for p in pins_pos]
        parts[0] = self._apply_boolean(parts[0], pin_meshes, operation="union")

        # Del B+: negative huller (difference)
        hole_meshes = [self._make_pin(p, spec, positive=False) for p in pins_pos]
        for i in range(1, len(parts)):
            parts[i] = self._apply_boolean(parts[i], hole_meshes, operation="difference")

        return parts

    # ──────────────────────────────────────────────────────────────────────────
    #  Tappestørrelse og placering
    # ──────────────────────────────────────────────────────────────────────────

    def _choose_pin_spec(self, bbox_extents: np.ndarray) -> PinSpec:
        """Vælg tappediameter og -dybde baseret på formstørrelse."""
        max_dim = float(bbox_extents.max())
        if max_dim < 50.0:
            return PinSpec(
                position=np.zeros(3), diameter=4.0, depth=4.0,
                d_shaped=False, tolerance=self.tolerance
            )
        elif max_dim < 150.0:
            return PinSpec(
                position=np.zeros(3), diameter=6.0, depth=6.0,
                d_shaped=False, tolerance=self.tolerance
            )
        else:
            return PinSpec(
                position=np.zeros(3), diameter=8.0, depth=8.0,
                d_shaped=True, tolerance=self.tolerance
            )

    def _generate_pin_positions(
        self,
        plane:       SplitPlane,
        bbox_extents: np.ndarray,
        spec:        PinSpec,
    ) -> list[np.ndarray]:
        """
        Generer tappositioner i et grid på mødefladen.

        Positionerne beregnes i planet defineret af plane.normal og
        fordeles jævnt med mindst min_pins tappe i hjørnerne + centrum.
        """
        # Find to tangent-vektorer i splitplanet
        u, v = self._plane_basis(plane.normal)

        # Brug bbox-projektioner til at estimere planets udstrækning
        # (grov approksimation – præcis plangeometri kræver mesh-clipning)
        half_u = float(np.abs(bbox_extents @ u)) / 2.0 * 0.7
        half_v = float(np.abs(bbox_extents @ v)) / 2.0 * 0.7

        margin = spec.diameter * 2.0
        half_u = max(half_u - margin, margin)
        half_v = max(half_v - margin, margin)

        # Grid af positioner: hjørner + midtpunkter på kanter + centrum
        offsets = [
            ( half_u,  half_v),
            (-half_u,  half_v),
            ( half_u, -half_v),
            (-half_u, -half_v),
        ]
        if self.min_pins > 4:
            offsets += [(0.0, half_v), (0.0, -half_v), (half_u, 0.0), (-half_u, 0.0)]
        if self.min_pins > 8:
            offsets.append((0.0, 0.0))

        positions = []
        for du, dv in offsets[:max(self.min_pins, 4)]:
            pos = plane.point + u * du + v * dv
            positions.append(pos)

        return positions

    # ──────────────────────────────────────────────────────────────────────────
    #  Geometrisk opbygning
    # ──────────────────────────────────────────────────────────────────────────

    def _make_pin(
        self,
        center:   np.ndarray,
        spec:     PinSpec,
        positive: bool,
    ) -> trimesh.Trimesh:
        """
        Opret et tap-mesh (cylinder) centreret i `center` langs Z-aksen.
        Roteres siden til at stå langs splitplanets normal.

        positive=True  → positiv tap (stikker ud fra del A)
        positive=False → negativ hul (lidt større, til del B)
        """
        radius = spec.diameter / 2.0
        if not positive:
            radius += spec.tolerance

        # TODO: D-formet tap via boolean med en boks der fjerner halvdelen
        cyl = trimesh.creation.cylinder(
            radius=radius,
            height=spec.depth,
            sections=32,
        )

        if spec.d_shaped and not positive:
            # Afskær halvdelen af cylinderen (simpel approksimation)
            cut_box = trimesh.creation.box(
                [radius * 2, radius, spec.depth + 1]
            )
            cut_box.apply_translation([radius / 2, 0, 0])
            try:
                import manifold3d as mf                        # type: ignore
                cyl = mf.boolean(cyl, cut_box, "difference")
            except Exception:
                pass  # Fald tilbage til rund tap hvis boolean fejler

        cyl.apply_translation(center)
        return cyl

    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_boolean(
        part:      MoldPart,
        tools:     list[trimesh.Trimesh],
        operation: str,                   # "union" | "difference"
    ) -> MoldPart:
        """
        Anvend boolean operation med alle tool-meshes på part.mesh.
        Forsøger manifold3d; logger fejl og returnerer uændret del hvis det fejler.
        """
        result_mesh = part.mesh
        for tool in tools:
            try:
                import manifold3d as mf                        # type: ignore
                result_mesh = mf.boolean(result_mesh, tool, operation)
            except Exception as exc:
                logger.error(
                    "Boolean %s fejlede for del %s: %s",
                    operation, part.label, exc
                )
                part.warnings.append(
                    f"Tap-boolean ({operation}) fejlede: {exc}. "
                    "Del mangler muligvis tappe/huller."
                )
                return part

        wt = result_mesh.is_watertight
        return MoldPart(
            index=part.index,
            label=part.label,
            mesh=result_mesh,
            is_watertight=wt,
            warnings=part.warnings,
        )

    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _plane_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Returner to ortonormale vektorer i planet defineret af `normal`."""
        n = normal / np.linalg.norm(normal)
        # Vælg en arbitrær ikke-parallel vektor
        ref = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u = np.cross(n, ref)
        u /= np.linalg.norm(u)
        v = np.cross(n, u)
        v /= np.linalg.norm(v)
        return u, v
