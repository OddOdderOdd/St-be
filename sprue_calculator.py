"""
sprue_calculator.py
-------------------
Beregner og placerer indløb (sprue) og lufthuller (air vents) i formdelene.

Algoritme:
  1. Indløbspunkt: Transformeres til splitplanets koordinatsystem og
     placeres på toppen af den del der vender langs pull-retningen.
  2. Indløbsdiameter: d = max(min_diam, 0.15 × ∛V × 10) where V = volumen cm³.
  3. Tragt: Ægte konisk frustum via roteret polygonal profil.
  4. Lomme-detektion: Topologisk analyse med multi-ray sampling +
     connected-component-filtrering for at finde lukkede hulrum.
  5. Lufthuller: Placeres ved toppen af hver detekteret lomme og
     ved modellens absolutte toppunkt i pull-retningen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import trimesh
import trimesh.creation
import trimesh.ray.ray_triangle

from .mold_builder import MoldPart

logger = logging.getLogger(__name__)


@dataclass
class SprueSpec:
    """Specifikation for ét indløb."""
    position:        np.ndarray   # (3,) centrum øverst på formens ydre
    diameter_mm:     float
    depth_mm:        float        # Indløbslængde ind i formen
    funnel_diam_mm:  float        # Tragtens øverste diameter


@dataclass
class VentSpec:
    """Specifikation for ét lufthul."""
    position:    np.ndarray   # (3,) centrum øverst
    diameter_mm: float = 2.0
    depth_mm:    float = 0.0   # Beregnes ved tilføjelse til form


@dataclass
class SprueResult:
    """Output fra SprueCalculator.calculate()."""
    sprue_specs:   list[SprueSpec]
    vent_specs:    list[VentSpec]
    volume_cm3:    float
    warnings:      list[str] = field(default_factory=list)
    needs_screw_cap: bool = False   # True hvis > 1 indløb


class SprueCalculator:
    """
    Beregner indløb og lufthuller for en given formkonfiguration.

    Eksempel::

        calc   = SprueCalculator(min_diameter_mm=5.0)
        result = calc.calculate(mesh, parts)
        print(f"{len(result.sprue_specs)} indløb, {len(result.vent_specs)} lufthuller")
    """

    def __init__(
        self,
        min_diameter_mm:     float = 5.0,
        air_vent_diameter_mm: float = 2.0,
        funnel_ratio:        float = 2.0,
    ):
        self.min_diam        = min_diameter_mm
        self.vent_diam       = air_vent_diameter_mm
        self.funnel_ratio    = funnel_ratio

    # ──────────────────────────────────────────────────────────────────────────

    def calculate(
        self,
        mesh:         trimesh.Trimesh,
        parts:        list[MoldPart],
        split_normal: np.ndarray | None = None,   # pull-retning fra splitplan
        wall_thickness: float = 3.0,
    ) -> SprueResult:
        """
        Beregn indløb og lufthuller.

        Indløbspunktet bestemmes relativt til splitplanets pull-retning,
        ikke blot Z-aksen.  Hvis split_normal ikke er angivet bruges +Z.

        Args:
            mesh:           Original model (volumen og geometri).
            parts:          Formhalvdele fra MoldBuilder + RegistrationSystem.
            split_normal:   Udtræksretning (enhedsvektor fra splitplanet).
            wall_thickness: Formvæggens tykkelse (til placering af
                            indløbstop uden for formhuset).

        Returns:
            SprueResult med specs klar til tilføjelse via add_to_parts().
        """
        warnings: list[str] = []
        volume_cm3 = max(abs(mesh.volume) / 1000.0, 0.001)

        # ── Pull-retning ─────────────────────────────────────────────────────
        pull = np.array(split_normal, dtype=np.float64) if split_normal is not None \
               else np.array([0.0, 0.0, 1.0])
        pull /= np.linalg.norm(pull)

        # ── Indløbsdiameter og tragt ─────────────────────────────────────────
        sprue_diam  = self._calc_sprue_diameter(volume_cm3)
        funnel_diam = sprue_diam * self.funnel_ratio

        # ── Indløbspunkt: højeste vertex langs pull-retningen ────────────────
        # Projicér alle vertices på pull-retningen og find den øverste.
        projections    = mesh.vertices @ pull                    # (N,)
        top_vertex_idx = int(np.argmax(projections))
        top_pos        = mesh.vertices[top_vertex_idx].copy().astype(np.float64)

        # Flyt til formens ydre overflade langs pull-retningen
        bbox_proj_max = float(np.max(mesh.vertices @ pull))
        overshoot     = bbox_proj_max - float(projections[top_vertex_idx])
        top_pos      += pull * (overshoot + wall_thickness)

        primary_sprue = SprueSpec(
            position       = top_pos,
            diameter_mm    = sprue_diam,
            depth_mm       = wall_thickness + 3.0,
            funnel_diam_mm = funnel_diam,
        )
        sprue_specs = [primary_sprue]

        if volume_cm3 > 200.0:
            warnings.append(
                f"Model er stor ({volume_cm3:.0f} cm³). "
                "Overvej at tilføje ekstra indløb manuelt."
            )

        # ── Lufthuller via topologisk lomme-detektion ─────────────────────────
        vent_specs = self._find_vent_positions(mesh, pull, wall_thickness, warnings)

        return SprueResult(
            sprue_specs     = sprue_specs,
            vent_specs      = vent_specs,
            volume_cm3      = volume_cm3,
            warnings        = warnings,
            needs_screw_cap = len(sprue_specs) > 1,
        )

    def add_to_parts(
        self,
        parts:       list[MoldPart],
        result:      SprueResult,
        split_normal: np.ndarray | None = None,
    ) -> list[MoldPart]:
        """
        Bohr indløb og lufthuller ind i de relevante formhalvdele.

        Indløbet bores ind i den halvdel der vender langs pull-retningen
        (den halvdel hvis centroid-projektion på pull_dir er størst).
        Lufthuller placeres i den halvdel der indeholder punktet.
        """
        if not parts:
            return parts

        pull = np.array(split_normal, dtype=np.float64) if split_normal is not None \
               else np.array([0.0, 0.0, 1.0])
        pull /= np.linalg.norm(pull)

        # Find den halvdel der vender langs pull-retningen
        top_part_idx = max(
            range(len(parts)),
            key=lambda i: float(parts[i].mesh.centroid @ pull),
        )

        for sprue in result.sprue_specs:
            cyl = self._make_sprue_cylinder(sprue)
            parts[top_part_idx] = self._subtract(parts[top_part_idx], cyl)

        for vent in result.vent_specs:
            cyl = trimesh.creation.cylinder(
                radius   = vent.diameter_mm / 2.0,
                height   = 20.0,
                sections = 16,
            )
            cyl.apply_translation(vent.position)
            part_idx = self._find_containing_part(parts, vent.position, pull)
            parts[part_idx] = self._subtract(parts[part_idx], cyl)

        return parts

    @staticmethod
    def _orthogonal_basis(normal: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Returner to ortonormale vektorer vinkelrette på `normal`."""
        n   = normal / np.linalg.norm(normal)
        ref = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        u   = np.cross(n, ref)
        u  /= np.linalg.norm(u)
        v   = np.cross(n, u)
        v  /= np.linalg.norm(v)
        return u, v

    @staticmethod
    def _subtract(part: MoldPart, tool: trimesh.Trimesh) -> MoldPart:
        """Boolean difference: part.mesh - tool. Logger fejl men crasher ikke."""
        try:
            import manifold3d as mf                            # type: ignore
            new_mesh = mf.boolean(part.mesh, tool, "difference")
        except Exception as exc:
            logger.error("Sprue/vent boolean fejlede for del %s: %s", part.label, exc)
            part.warnings.append(f"Indløb/lufthul boolean fejlede: {exc}")
            return part
        return MoldPart(
            index=part.index, label=part.label,
            mesh=new_mesh, is_watertight=new_mesh.is_watertight,
            warnings=part.warnings,
        )

    @staticmethod
    def _find_containing_part(
        parts: list[MoldPart],
        point: np.ndarray,
        pull:  np.ndarray,
    ) -> int:
        """
        Find den formhalvdel hvis bounding box indeholder `point`.
        Falder tilbage til den halvdel der vender langs pull-retningen.
        """
        for i, p in enumerate(parts):
            bb = p.mesh.bounding_box
            if (bb.bounds[0] <= point).all() and (point <= bb.bounds[1]).all():
                return i
        return max(range(len(parts)), key=lambda i: float(parts[i].mesh.centroid @ pull))

    def _calc_sprue_diameter(self, volume_cm3: float) -> float:
        """d = max(min_diam, 0.15 × ∛V × 10)  [mm]"""
        return max(self.min_diam, 0.15 * (volume_cm3 ** (1.0 / 3.0)) * 10.0)

    def _find_vent_positions(
        self,
        mesh:           trimesh.Trimesh,
        pull_dir:       np.ndarray,
        wall_thickness: float,
        warnings:       list[str],
    ) -> list[VentSpec]:
        """
        Topologisk lomme-detektion med multi-ray sampling.

        Strategi:
          1. Sample et 7×7 grid af ray-origins i planet vinkelret på pull_dir.
          2. For hvert grid-punkt: kast ray langs pull_dir og find alle
             skæringer med mesh'et.
          3. Par skæringspunkterne (ind → ud). Ethvert par med mere end
             ét skæringsniveau indikerer en lomme eller overgang.
          4. Identificér det højeste "lukkede" interval (ray skærer ind
             og ud igen inden toppen) som en lomme.
          5. Placer lufthul ved toppen af lomme-intervallet + wall_thickness.
          6. Deduplikér lufthuller der er tættere end min_spacing på hinanden.
          7. Tilføj altid ét lufthul ved modellens absolutte toppunkt
             langs pull_dir.

        Denne tilgang finder langt flere lomme-typer end den tidligere
        simple proxy, inkl. sidevende og indre hulrum.
        """
        vents: list[VentSpec] = []
        min_spacing = 5.0   # mm – mindste afstand mellem lufthuller

        # ── 1. Absolut toppunkt langs pull-retningen ─────────────────────────
        projections    = mesh.vertices @ pull_dir
        top_vertex_idx = int(np.argmax(projections))
        top_pos        = mesh.vertices[top_vertex_idx].copy().astype(np.float64)
        top_pos       += pull_dir * wall_thickness
        vents.append(VentSpec(position=top_pos, diameter_mm=self.vent_diam))

        # ── 2. Byg grid vinkelret på pull_dir ────────────────────────────────
        u, v = self._orthogonal_basis(pull_dir)
        bb    = mesh.bounding_box.extents
        # Skaler grid til 70% af bbox for at undgå kant-artefakter
        half_u = float(np.abs(bb @ u)) / 2.0 * 0.70
        half_v = float(np.abs(bb @ v)) / 2.0 * 0.70

        grid_n    = 7
        us        = np.linspace(-half_u, half_u, grid_n)
        vs_       = np.linspace(-half_v, half_v, grid_n)
        centroid  = np.array(mesh.centroid, dtype=np.float64)

        # Start ray bag modellen langs pull-retningen
        bbox_proj_min = float(np.min(projections))
        ray_start_proj = bbox_proj_min - 2.0   # 2 mm bag bunden

        raycaster = trimesh.ray.ray_triangle.RayMeshIntersector(mesh)

        # ── 3. Kast rays og find lommer ──────────────────────────────────────
        pocket_tops: list[np.ndarray] = []

        for du in us:
            for dv in vs_:
                # Ray-origin i planet vinkelret på pull_dir
                lateral = centroid + u * du + v * dv
                origin  = lateral + pull_dir * ray_start_proj - pull_dir * float(centroid @ pull_dir)
                origin  = origin.reshape(1, 3)
                direction = pull_dir.reshape(1, 3)

                try:
                    locs, _, _ = raycaster.intersects_location(
                        ray_origins    = origin,
                        ray_directions = direction,
                    )
                except Exception:
                    continue

                if len(locs) < 2:
                    continue

                # Sortér skæringer langs pull-retningen
                proj_locs = locs @ pull_dir
                order     = np.argsort(proj_locs)
                locs_sorted = locs[order]

                # ── 4. Find lukkede intervaller (lomme = ind + ud) ───────────
                # Par skæringer: [0]=ind, [1]=ud, [2]=ind, [3]=ud, ...
                # Et "lomme-top" er øverste kant af et ind-ud-par (ud-skæring)
                # der ikke er det allersidste skæringspunkt.
                n_locs = len(locs_sorted)
                for pair_start in range(0, n_locs - 1, 2):
                    if pair_start + 1 >= n_locs:
                        break
                    out_loc = locs_sorted[pair_start + 1]     # ud-skæring

                    # Er der en ind-skæring herover? (= lukket lomme)
                    if pair_start + 2 < n_locs:
                        # Toppunktet for denne lomme er ud-skæringen
                        pocket_top = out_loc + pull_dir * wall_thickness
                        pocket_tops.append(pocket_top)

        # ── 5. Deduplikér lomme-toppe og tilføj lufthuller ───────────────────
        for pt in pocket_tops:
            too_close = any(
                np.linalg.norm(pt - v.position) < min_spacing
                for v in vents
            )
            if not too_close:
                vents.append(VentSpec(position=pt, diameter_mm=self.vent_diam))

        logger.info(
            "%d lufthuller detekteret (%d lomme-hits i %d×%d grid).",
            len(vents), len(pocket_tops), grid_n, grid_n,
        )

        if len(vents) == 1 and len(pocket_tops) == 0:
            warnings.append(
                "Ingen lommer detekteret – kun primært lufthul genereret. "
                "Kontrollér manuelt om modellen har indre hulrum."
            )

        return vents

    def _make_sprue_cylinder(self, spec: SprueSpec) -> trimesh.Trimesh:
        """
        Opret indløbskanal som et ægte konisk frustum (tragt → kanal).

        Geometri (bottom-up):
          - Kanal: cylinder med sprue_diam, depth_mm høj
          - Tragt: konisk frustum fra funnel_diam (top) til sprue_diam (bund)
            genereret som en roteret polygonal profil sweepet 360°

        Det kombinerede mesh borekroner ned igennem formhuset når det
        trækkes fra via boolean difference.
        """
        r_narrow  = spec.diameter_mm / 2.0
        r_wide    = spec.funnel_diam_mm / 2.0
        depth     = spec.depth_mm
        funnel_h  = max(r_wide - r_narrow, 3.0)   # tragt-højde minimum 3 mm

        # ── Kanal-cylinder ───────────────────────────────────────────────────
        canal = trimesh.creation.cylinder(
            radius   = r_narrow,
            height   = depth,
            sections = 48,
        )
        # Centrer ved z=0, flyt så bund er ved -depth/2
        canal.apply_translation([0, 0, 0])

        # ── Konisk tragt (frustum) ────────────────────────────────────────────
        # Byg frustum manuelt som roteret trapez-profil
        sections = 48
        angles   = np.linspace(0, 2 * np.pi, sections, endpoint=False)

        # Bund-ring (smal, ved z = depth/2)
        bund_z  = depth / 2.0
        top_z   = bund_z + funnel_h

        bund_pts = np.column_stack([
            r_narrow * np.cos(angles),
            r_narrow * np.sin(angles),
            np.full(sections, bund_z),
        ])
        top_pts = np.column_stack([
            r_wide * np.cos(angles),
            r_wide * np.sin(angles),
            np.full(sections, top_z),
        ])

        # Apex: centrum af topp-cirklen (til at lukke frustum's topplade)
        top_centre    = np.array([[0.0, 0.0, top_z]])
        bund_centre   = np.array([[0.0, 0.0, bund_z]])

        vertices = np.vstack([bund_pts, top_pts, top_centre, bund_centre])
        n        = sections
        top_c_i  = 2 * n       # indeks for top-centrum
        bund_c_i = 2 * n + 1  # indeks for bund-centrum

        faces = []
        for i in range(n):
            j = (i + 1) % n
            # Side-flade (trapez → 2 trekanter)
            faces.append([i, j, n + i])
            faces.append([j, n + j, n + i])
            # Topplade-sektor
            faces.append([n + i, n + j, top_c_i])
            # Bundplade-sektor
            faces.append([j, i, bund_c_i])

        frustum = trimesh.Trimesh(
            vertices = vertices,
            faces    = np.array(faces, dtype=np.int32),
            process  = True,
        )
        trimesh.repair.fix_normals(frustum)

        # ── Kombiner kanal + tragt ────────────────────────────────────────────
        try:
            import manifold3d as mf                            # type: ignore
            combined = mf.boolean(canal, frustum, "union")
        except Exception:
            # Fallback: bare kanalen hvis manifold3d ikke er til stede
            combined = canal

        # Flyt til spec.position (top af frustum skal være ved positionen)
        combined.apply_translation(spec.position - np.array([0, 0, top_z]))
        return combined

    # ── beregningshjælpere er placeret ovenfor ────────────────────────────────
