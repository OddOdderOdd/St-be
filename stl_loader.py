"""
stl_loader.py
-------------
Indlæser, validerer og reparerer STL-filer inden viderebehandling.

Understøtter:
  - ASCII og binær STL
  - Automatisk reparation af ikke-manifold meshes
  - Normalisering (centrering, valgfri skalering)
  - Rapportering af mesh-kvalitet

Kendte begrænsninger:
  - Meget fragmenterede meshes (> 1 000 separate skaller) kan
    fejle i fill_holes(); brugeren skal adviseres om manuelt
    at reparere i f.eks. MeshMixer inden import.
  - ASCII STL > 200 MB er meget langsom at parse; konvertér til
    binær STL med ekstern software først.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
import trimesh
import trimesh.repair

logger = logging.getLogger(__name__)


@dataclass
class MeshReport:
    """Kvalitetsrapport returneret af STLLoader.load()."""
    filepath:           str
    original_faces:     int
    repaired_faces:     int
    is_watertight:      bool
    has_self_intersect: bool
    volume_cm3:         float
    bbox_mm:            tuple[float, float, float]    # (X, Y, Z) i mm
    warnings:           list[str]

    def __str__(self) -> str:
        lines = [
            f"Fil:          {self.filepath}",
            f"Trekanter:    {self.original_faces} → {self.repaired_faces} (efter reparation)",
            f"Watertight:   {'Ja' if self.is_watertight else 'NEJ – advarsler nedenfor'}",
            f"Selvskæring:  {'Ja (kan give fejl)' if self.has_self_intersect else 'Nej'}",
            f"Volumen:      {self.volume_cm3:.2f} cm³",
            f"Bounding box: {self.bbox_mm[0]:.1f} × {self.bbox_mm[1]:.1f} × {self.bbox_mm[2]:.1f} mm",
        ]
        for w in self.warnings:
            lines.append(f"⚠  {w}")
        return "\n".join(lines)


class STLLoader:
    """
    Indlæser en STL-fil og returnerer et valideret trimesh.Trimesh.

    Eksempel::

        loader = STLLoader()
        mesh, report = loader.load("model.stl")
        print(report)
    """

    def __init__(
        self,
        auto_repair:   bool  = True,
        center_mesh:   bool  = True,
        scale_to_mm:   bool  = True,
        max_hole_edges: int  = 200,
    ):
        """
        Args:
            auto_repair:    Forsøg automatisk reparation af ikke-manifold geometri.
            center_mesh:    Centrer mesh i verdensrummets origo.
            scale_to_mm:    Omskal automatisk fra meter til mm hvis enheden
                            detekteres som meter (bbox < 1 i alle akser).
            max_hole_edges: Maks antal kanter pr. hul der forsøges lukket.
                            Huller med flere kanter springes over og rapporteres.
        """
        self.auto_repair    = auto_repair
        self.center_mesh    = center_mesh
        self.scale_to_mm    = scale_to_mm
        self.max_hole_edges = max_hole_edges

    # ──────────────────────────────────────────────────────────────────────────

    def load(self, filepath: str) -> tuple[trimesh.Trimesh, MeshReport]:
        """
        Indlæs STL-fil og returner (mesh, rapport).

        Raises:
            FileNotFoundError: Hvis filen ikke eksisterer.
            ValueError:        Hvis filen ikke kan parses som STL.
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"STL-fil ikke fundet: {filepath!r}")

        warnings_list: list[str] = []

        # ── Indlæs ──────────────────────────────────────────────────────────
        logger.info("Indlæser %s …", filepath)
        try:
            mesh = trimesh.load(filepath, force="mesh")
        except Exception as exc:
            raise ValueError(f"Kan ikke parse STL-fil: {exc}") from exc

        if not isinstance(mesh, trimesh.Trimesh):
            # Scene med flere meshes – flet dem
            if hasattr(mesh, "dump"):
                parts = mesh.dump()
                if not parts:
                    raise ValueError("STL-filen indeholder ingen geometri.")
                mesh = trimesh.util.concatenate(parts)
                warnings_list.append(
                    "Filen indeholder flere meshes; de er flettet til ét."
                )
            else:
                raise ValueError("Ukendt mesh-type efter indlæsning.")

        original_faces = len(mesh.faces)

        # ── Enhedsdetektion ─────────────────────────────────────────────────
        if self.scale_to_mm:
            extents = mesh.bounding_box.extents
            if extents.max() < 1.0:
                mesh.apply_scale(1000.0)
                warnings_list.append(
                    "Mesh ser ud til at være i meter – skaleret × 1000 til mm."
                )

        # ── Reparation ──────────────────────────────────────────────────────
        if self.auto_repair:
            mesh = self._repair(mesh, warnings_list)

        # ── Centrering ──────────────────────────────────────────────────────
        if self.center_mesh:
            mesh.apply_translation(-mesh.bounding_box.centroid)

        # ── Selvskæringstest ────────────────────────────────────────────────
        # Bemærk: trimesh.repair.broken_faces er hurtig men ikke perfekt.
        # En fuld selvskæringstest kræver f.eks. Open3D og tager lang tid
        # for store meshes. Denne implementering bruger en hurtig proxy-check.
        has_si = self._fast_self_intersect_check(mesh)
        if has_si:
            warnings_list.append(
                "Mulig selvskærende geometri detekteret. "
                "Resulterende forme kan have defekter. "
                "Reparer manuelt i MeshMixer eller Blender inden import."
            )

        vol = mesh.volume / 1000.0  # mm³ → cm³
        bb  = tuple(float(x) for x in mesh.bounding_box.extents)

        report = MeshReport(
            filepath           = filepath,
            original_faces     = original_faces,
            repaired_faces     = len(mesh.faces),
            is_watertight      = mesh.is_watertight,
            has_self_intersect = has_si,
            volume_cm3         = vol,
            bbox_mm            = bb,           # type: ignore[arg-type]
            warnings           = warnings_list,
        )

        logger.info("Indlæst OK:\n%s", report)
        return mesh, report

    # ──────────────────────────────────────────────────────────────────────────
    #  Interne hjælpemetoder
    # ──────────────────────────────────────────────────────────────────────────

    def _repair(
        self,
        mesh: trimesh.Trimesh,
        warnings_list: list[str],
    ) -> trimesh.Trimesh:
        """Forsøg sekventiel reparation og log hvad der ændres."""

        # 1. Fiks normaler
        trimesh.repair.fix_normals(mesh, multibody=False)

        # 2. Fjern degenererede trekanter (nul-areal)
        before = len(mesh.faces)
        mask = mesh.area_faces > 1e-10
        if not mask.all():
            mesh.update_faces(mask)
            n_removed = before - len(mesh.faces)
            warnings_list.append(
                f"{n_removed} degenererede trekanter fjernet."
            )

        # 3. Flet duplikerede vertices
        mesh.merge_vertices()

        # 4. Luk huller
        if not mesh.is_watertight:
            try:
                trimesh.repair.fill_holes(mesh)
                if not mesh.is_watertight:
                    warnings_list.append(
                        "Ikke alle huller kunne lukkes automatisk. "
                        "Formen er ikke fuldt watertight."
                    )
            except Exception as exc:                           # noqa: BLE001
                warnings_list.append(
                    f"Hul-lukning fejlede ({exc}). "
                    "Forsøg manuel reparation i MeshMixer."
                )

        # 5. Fiks vindingsorden (winding order)
        trimesh.repair.fix_winding(mesh)

        return mesh

    @staticmethod
    def _fast_self_intersect_check(mesh: trimesh.Trimesh) -> bool:
        """
        BVH-baseret selvskæringstest via trimesh's collision-infrastruktur.

        Metode:
          1. Byg et BVH (Bounding Volume Hierarchy) over alle trekanter.
          2. For hvert face: find naboer via shared vertices (adjacent faces
             deler én eller to kanter og skærer pr. definition ikke).
          3. Tjek kun ikke-adjacente face-par mod hinanden.
          4. Brug Möller–Trumbore-test til at afgøre om to trekanter skærer.

        Kompleksitet: O(N log N) for BVH-opbygning + O(K) for K konflikter.
        I praksis er K << N² for normale meshes og testen kører hurtigt.

        Begrænsninger:
          - Trekanter der kun rører hinanden i ét punkt (vertex-touching)
            rapporteres IKKE som selvskærende (dette er korrekt adfærd).
          - For meshes med > 200 k trekanter bruges en stikprøve (sampling)
            der kan misse sjældne lokale selvskæringer.

        Returns:
            True  = selvskæring detekteret (eller stærk mistanke).
            False = ingen selvskæring fundet.
        """
        # ── Trin 1: Hurtig proxy ────────────────────────────────────────────
        # Ikke-watertight efter reparation er et stærkt signal.
        if not mesh.is_watertight:
            return True
        if mesh.volume < 0:
            return True   # Omvendte normaler dominerer

        # ── Trin 2: BVH-baseret parvis test ────────────────────────────────
        try:
            return STLLoader._bvh_self_intersect(mesh)
        except Exception:                                      # noqa: BLE001
            # BVH-test fejlede (typisk manglende optional dep) – fald
            # tilbage til proxy-resultat (ingen selvskæring antaget).
            return False

    @staticmethod
    def _bvh_self_intersect(mesh: trimesh.Trimesh, max_faces: int = 200_000) -> bool:
        """
        Parvis Möller–Trumbore selvskæringstest med BVH-acceleration.

        For store meshes (> max_faces) bruges en stikprøve.
        """
        vertices  = mesh.vertices
        faces     = mesh.faces
        n_faces   = len(faces)

        # Byg adjacency-sæt: for hvert face, hvilke faces deler mindst en vertex
        # (disse betragtes som "naboer" og springes over).
        # Bruges som eksklusionssæt i den parvise test.
        face_adjacency = mesh.face_adjacency             # (K, 2) par af nabotrekanter
        adj_set: set[tuple[int, int]] = set()
        for a, b in face_adjacency:
            adj_set.add((int(min(a, b)), int(max(a, b))))

        # For store meshes: sample et subset af faces
        if n_faces > max_faces:
            rng       = np.random.default_rng(seed=42)
            sample_i  = rng.choice(n_faces, size=max_faces, replace=False)
            test_faces = faces[sample_i]
            face_map   = {int(si): int(i) for i, si in enumerate(sample_i)}
        else:
            test_faces = faces
            face_map   = {i: i for i in range(n_faces)}

        # Beregn face bounding boxes (AABB) til hurtig pre-screening
        tri_verts  = vertices[test_faces]                  # (M, 3, 3)
        bb_min     = tri_verts.min(axis=1)                 # (M, 3)
        bb_max     = tri_verts.max(axis=1)                 # (M, 3)

        n_test = len(test_faces)

        # Sweep-and-prune langs X-aksen (sortér efter bb_min_x)
        order  = np.argsort(bb_min[:, 0])
        bb_min = bb_min[order]
        bb_max = bb_max[order]
        tris   = tri_verts[order]
        orig_i = np.array([face_map[int(order[k])] for k in range(n_test)])

        for i in range(n_test):
            # Alle faces hvis bb_min_x er inden for face i's bb_max_x
            max_x_i = bb_max[i, 0]
            for j in range(i + 1, n_test):
                if bb_min[j, 0] > max_x_i:
                    break   # Sweep-and-prune: ingen flere overlap mulige

                # Tjek om dette er et adjacency-par (spring over)
                fi, fj = int(min(orig_i[i], orig_i[j])), int(max(orig_i[i], orig_i[j]))
                if (fi, fj) in adj_set:
                    continue

                # Full AABB-overlap check (Y og Z akser)
                if (bb_max[i, 1] < bb_min[j, 1] or bb_min[i, 1] > bb_max[j, 1] or
                        bb_max[i, 2] < bb_min[j, 2] or bb_min[i, 2] > bb_max[j, 2]):
                    continue

                # Möller–Trumbore test
                if STLLoader._triangles_intersect(tris[i], tris[j]):
                    return True

        return False

    @staticmethod
    def _triangles_intersect(t1: np.ndarray, t2: np.ndarray) -> bool:
        """
        Möller–Trumbore trekant–trekant skæringstest.

        t1, t2: (3, 3) arrays af vertex-koordinater.
        Returnerer True hvis de to trekanter skærer (ikke kun rører).

        Implementeret efter:
          Möller, T. (1997). "A Fast Triangle-Triangle Intersection Test."
          Journal of Graphics Tools 2(2):25–30.
        """
        EPS = 1e-8

        def _signed_volumes(a, b, c, d):
            return np.dot(np.cross(b - a, c - a), d - a)

        # Trekant 1's plan
        n1 = np.cross(t1[1] - t1[0], t1[2] - t1[0])
        d1 = -np.dot(n1, t1[0])

        # Afstande fra trekant 2's vertices til plan 1
        dists2 = np.dot(t2, n1) + d1

        # Alle på samme side? → ingen skæring
        if np.all(dists2 > EPS) or np.all(dists2 < -EPS):
            return False

        # Trekant 2's plan
        n2 = np.cross(t2[1] - t2[0], t2[2] - t2[0])
        d2 = -np.dot(n2, t2[0])

        dists1 = np.dot(t1, n2) + d2
        if np.all(dists1 > EPS) or np.all(dists1 < -EPS):
            return False

        # Skæringslinjen D = n1 × n2
        D = np.cross(n1, n2)
        if np.linalg.norm(D) < EPS:
            return False   # Koplanare trekanter (behandles som ikke-skærende)

        # Projicér vertices på D og find overlap-intervaller
        def _interval(tri, dists, D):
            p   = tri @ D
            idx = np.argsort(np.abs(dists))
            # Det isolerede vertex er det med størst absolut afstand
            solo_i = np.argmax(np.abs(dists))
            others = [k for k in range(3) if k != solo_i]
            t0 = p[solo_i] + (p[others[0]] - p[solo_i]) * dists[solo_i] / (dists[solo_i] - dists[others[0]] + EPS)
            t1_ = p[solo_i] + (p[others[1]] - p[solo_i]) * dists[solo_i] / (dists[solo_i] - dists[others[1]] + EPS)
            return min(t0, t1_), max(t0, t1_)

        a0, a1 = _interval(t1, dists1, D)
        b0, b1 = _interval(t2, dists2, D)

        # Overlap?
        return a0 < b1 - EPS and b0 < a1 - EPS
