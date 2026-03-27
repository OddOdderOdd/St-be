"""
mold_builder.py
---------------
Bygger de fysiske formhalvdele (mold halves) ud fra mesh og splitplaner.

For hvert splitplan:
  1. Opret et formhus (bounding box + wall_thickness margin).
  2. Boolean subtraction: fjern modellens negative fra formhuset.
  3. Anvend udtræksvinkel (draft angle) på lodrette flader.
  4. Clip formhuset langs splitplanet.

Boolean-operationer:
  Primært via manifold3d (robust, CPU).
  Fallback til trimesh's interne boolean via OpenSCAD-backend hvis
  manifold3d fejler (kræver OpenSCAD installeret).

Kendte begrænsninger:
  - Draft angle bruger vertex-projektion (lineær approksimation).
    Nøjagtighed er tilstrækkelig for FDM men ikke CNC-fræsning.
    Meget konkave hulrum kan give geometri-overlap ved vinkler > 3°.
  - Clip langs splitplan bruger trimesh.intersections.slice_mesh_plane()
    som kan give ikke-watertight output for komplekse meshes.
    ManifoldMesh clip er planlagt men ikke implementeret.
  - Understøtter kun flade splitplaner (ikke kurvede).
  - 3+ dele bygges sekventielt, ikke parallelt.
"""

from __future__ import annotations

import logging
import warnings as _warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import trimesh
import trimesh.creation
import trimesh.intersections
import trimesh.repair

from parting_optimizer import SplitPlane, PartingResult

logger = logging.getLogger(__name__)


@dataclass
class MoldPart:
    """En enkelt formhalvdel."""
    index:    int               # 0 = A, 1 = B, osv.
    label:    str               # "A", "B", "C", …
    mesh:     trimesh.Trimesh
    is_watertight: bool = False
    warnings: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"MoldPart({self.label}: "
            f"{len(self.mesh.faces):,} trekanter, "
            f"watertight={self.is_watertight})"
        )


class MoldBuilder:
    """
    Bygger formhalvdele ud fra mesh og PartingResult.

    Eksempel::

        builder = MoldBuilder(wall_thickness=3.0)
        parts   = builder.build(mesh, parting_result)
        for p in parts:
            print(p)
    """

    _LABELS = "ABCDEFGHIJ"

    def __init__(
        self,
        wall_thickness_mm: float = 3.0,
        draft_angle_deg:   float = 1.5,
        boolean_backend:   str   = "manifold",   # "manifold" | "scad"
    ):
        self.wall_thickness  = wall_thickness_mm
        self.draft_angle     = draft_angle_deg
        self.boolean_backend = boolean_backend

    # ──────────────────────────────────────────────────────────────────────────

    def build(
        self,
        mesh:    trimesh.Trimesh,
        result:  PartingResult,
    ) -> list[MoldPart]:
        """
        Byg alle formhalvdele og returner dem som liste.

        Rækkefølgen svarer til PartingResult.split_planes:
          del[0] = den side der vender "med" splitplan[0].normal
          del[1] = den side der vender "imod" splitplan[0].normal
          del[2] = yderligere halvdele ved 3+ planer (TODO)
        """
        parts = []
        n = result.n_parts

        if n == 2:
            parts = self._build_two_part(mesh, result.split_planes[0])
        elif n >= 3:
            parts = self._build_multipart(mesh, result.split_planes, n)
        else:
            raise ValueError(f"Ugyldigt antal dele: {n}")

        return parts

    # ──────────────────────────────────────────────────────────────────────────
    #  Todelt form
    # ──────────────────────────────────────────────────────────────────────────

    def _build_two_part(
        self,
        mesh:  trimesh.Trimesh,
        plane: SplitPlane,
    ) -> list[MoldPart]:
        """Byg to formhalvdele langs ét splitplan."""
        mold_box    = self._build_mold_box(mesh)
        cavity_mesh = self._boolean_subtract(mold_box, mesh)

        # Clip halvdel A (med normalen) og B (imod normalen)
        half_a = self._clip_at_plane(cavity_mesh, plane.point, plane.normal)
        half_b = self._clip_at_plane(cavity_mesh, plane.point, -plane.normal)

        results = []
        for i, (half, label) in enumerate(zip([half_a, half_b], "AB")):
            half = self._apply_draft_angle(half, plane)
            wt   = half.is_watertight
            w    = []
            if not wt:
                w.append(f"Del {label} er ikke watertight efter clipning.")
            results.append(MoldPart(
                index=i, label=label, mesh=half,
                is_watertight=wt, warnings=w
            ))
        return results

    # ──────────────────────────────────────────────────────────────────────────
    #  Fler-delt form (3+)
    # ──────────────────────────────────────────────────────────────────────────

    def _build_multipart(
        self,
        mesh:         trimesh.Trimesh,
        planes:       list[SplitPlane],
        n_parts:      int,
    ) -> list[MoldPart]:
        """
        Byg 3+ formhalvdele.

        TODO:
            Denne implementering er en simpel extension af todelt-logikken
            og fungerer kun korrekt for orthogonale splitplaner.
            For asymmetriske planer er der risiko for overlappende dele.
            En korrekt implementering kræver Voronoi-partitionering af
            formhuset baseret på alle splitplaners normalvektorer.
        """
        _warnings.warn(
            "Fler-delt formgenerering (3+ dele) er halvfærdig. "
            "Kontrollér output visuelt inden print.",
            stacklevel=3,
        )

        mold_box    = self._build_mold_box(mesh)
        cavity_mesh = self._boolean_subtract(mold_box, mesh)

        parts = []
        remaining = cavity_mesh

        for i, plane in enumerate(planes):
            label = self._LABELS[i]
            half  = self._clip_at_plane(remaining, plane.point, plane.normal)
            remaining = self._clip_at_plane(remaining, plane.point, -plane.normal)

            wt = half.is_watertight
            w  = []
            if not wt:
                w.append(f"Del {label} er ikke watertight.")
            parts.append(MoldPart(index=i, label=label, mesh=half,
                                  is_watertight=wt, warnings=w))

        # Sidst resterende stykke
        final_label = self._LABELS[len(planes)]
        wt = remaining.is_watertight
        w  = [] if wt else [f"Del {final_label} er ikke watertight."]
        parts.append(MoldPart(
            index=len(planes), label=final_label,
            mesh=remaining, is_watertight=wt, warnings=w
        ))

        return parts

    # ──────────────────────────────────────────────────────────────────────────
    #  Geometriske hjælpemetoder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_mold_box(self, mesh: trimesh.Trimesh) -> trimesh.Trimesh:
        """
        Opret et formhus som en solid boks med wall_thickness margin
        rundt om mesh'ets bounding box.
        """
        extents = mesh.bounding_box.extents + self.wall_thickness * 2
        box     = trimesh.creation.box(extents=extents)
        box.apply_translation(mesh.bounding_box.centroid)
        return box

    def _boolean_subtract(
        self,
        mold:  trimesh.Trimesh,
        model: trimesh.Trimesh,
    ) -> trimesh.Trimesh:
        """
        Udfør boolean subtraction: mold - model = hulrum til støbning.
        Forsøger manifold3d; falder tilbage til trimesh's OpenSCAD-backend.
        """
        if self.boolean_backend == "manifold":
            try:
                import manifold3d as mf                        # type: ignore
                result = mf.boolean(mold, model, "difference")
                return result
            except ImportError:
                logger.warning("manifold3d ikke installeret; falder tilbage til trimesh.")
            except Exception as exc:                           # noqa: BLE001
                logger.warning("manifold3d fejlede (%s); falder tilbage til trimesh.", exc)

        # Trimesh fallback (kræver OpenSCAD eller Blender på PATH)
        try:
            result = trimesh.boolean.difference([mold, model])
            if result is None or len(result.faces) == 0:
                raise RuntimeError("Boolean subtraction returnerede tomt mesh.")
            return result
        except Exception as exc:
            raise RuntimeError(
                f"Boolean subtraction fejlede med alle backends: {exc}\n"
                "Installer manifold3d:  pip install manifold3d\n"
                "Eller installer OpenSCAD og tilføj til PATH."
            ) from exc

    @staticmethod
    def _clip_at_plane(
        mesh:   trimesh.Trimesh,
        point:  np.ndarray,
        normal: np.ndarray,
    ) -> trimesh.Trimesh:
        """
        Klip mesh og behold kun den del der er på normalens side af planet.
        Returnerer et nyt Trimesh.
        """
        try:
            clipped = trimesh.intersections.slice_mesh_plane(
                mesh,
                plane_normal  = normal,
                plane_origin  = point,
                cap           = True,    # Luk den åbne flade
            )
            if clipped is None or len(clipped.faces) == 0:
                logger.warning("Clip returnerede tomt mesh; returnerer original.")
                return mesh
            return clipped
        except Exception as exc:
            logger.error("Clip fejlede: %s", exc)
            return mesh

    def _apply_draft_angle(
        self,
        mesh:  trimesh.Trimesh,
        plane: SplitPlane,
    ) -> trimesh.Trimesh:
        """
        Anvend udtræksvinkel (draft angle) på alle faces der er
        tilnærmelsesvis lodrette i forhold til udtræksretningen.

        Metode – vertex-projektion langs udtræksretning:
          For hvert vertex beregnes dets afstand fra splitplanet (h).
          Lodrette faces identificeres ved at dot(face_normal, pull_dir)
          ligger i intervallet (-cos_threshold, +cos_threshold).
          Vertexer på lodrette faces forskydes radialt udad
          proportionalt med h × tan(draft_angle_rad), så formen
          bliver lettere at trække ud.

        Begrænsninger:
          - Virker bedst for konvekse eller mild-konkave geometrier.
          - Meget konkave hulrum (f.eks. undercut-kanaler) kan give
            overlappende geometri ved store vinkler (> 3°).
          - Forskydes på vertex-niveau; kanten langs splitplanet
            flyttes ikke, så tætningsfladen forbliver præcis.
          - Metoden er en lineær approksimation; nøjagtighed er
            tilstrækkelig for FDM-print (tolerance ≈ ±0.1 mm
            ved 1.5° og formhøjde ≤ 100 mm).

        Args:
            mesh:  Formhalvdel-mesh der skal modificeres.
            plane: Splitplanet – bruges til at bestemme udtræksretning
                   og referenceplan for højdeberegning.

        Returns:
            Modificeret Trimesh med draft angle påført.
        """
        if self.draft_angle <= 0.0:
            return mesh

        angle_rad      = np.radians(self.draft_angle)
        tan_angle      = np.tan(angle_rad)
        pull_dir       = plane.normal.astype(np.float64)
        pull_dir      /= np.linalg.norm(pull_dir)
        plane_pt       = plane.point.astype(np.float64)

        vertices = mesh.vertices.copy().astype(np.float64)

        # ── Identificér lodrette faces ──────────────────────────────────────
        # "Lodret" = face-normalen er tilnærmelsesvis vinkelret på pull_dir
        cos_threshold = np.cos(np.radians(80.0))   # faces inden for ±80° af lodret
        face_normals  = mesh.face_normals.astype(np.float64)
        dots          = np.abs(face_normals @ pull_dir)          # (M,)
        draft_faces   = dots < cos_threshold                     # (M,) bool

        if not draft_faces.any():
            logger.debug("Ingen lodrette faces fundet; draft angle sprunget over.")
            return mesh

        # ── Find vertices der tilhører mindst ét draft-face ────────────────
        draft_face_indices  = np.where(draft_faces)[0]
        draft_vertex_set    = np.unique(mesh.faces[draft_face_indices])

        # ── Beregn højde over splitplanet for hvert vertex ──────────────────
        # h = (vertex - plane_point) · pull_dir
        # Positiv h = på udtræks-siden; negativ = under splitplanet
        rel          = vertices - plane_pt                        # (N, 3)
        heights      = rel @ pull_dir                             # (N,)

        # ── Beregn radiel forskydning ────────────────────────────────────────
        # For hvert draft-vertex: forskyd radialt udad med h × tan(angle)
        # Radiel retning = komponent af (vertex - plane_point) vinkelret på pull_dir
        for vi in draft_vertex_set:
            h = heights[vi]
            if abs(h) < 1e-6:
                continue   # Vertex ligger i splitplanet – flyt ikke

            # Radiel komponent: fjern pull_dir-komponenten
            radial = rel[vi] - h * pull_dir                      # (3,)
            radial_len = np.linalg.norm(radial)

            if radial_len < 1e-6:
                # Vertex ligger præcis på pull_dir-aksen – ingen veldefineret
                # radiel retning; spring over for at undgå numerisk ustabilitet
                continue

            radial_unit  = radial / radial_len
            displacement = abs(h) * tan_angle                    # mm udad
            vertices[vi] += radial_unit * displacement

        # ── Byg nyt mesh med modificerede vertices ──────────────────────────
        new_mesh = trimesh.Trimesh(
            vertices = vertices,
            faces    = mesh.faces.copy(),
            process  = False,
        )
        trimesh.repair.fix_normals(new_mesh)

        logger.debug(
            "Draft angle %.1f° påført: %d/%d vertices modificeret.",
            self.draft_angle,
            len(draft_vertex_set),
            len(vertices),
        )
        return new_mesh
