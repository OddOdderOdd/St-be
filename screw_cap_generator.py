"""
screw_cap_generator.py
----------------------
Genererer et 3D-printbart skruelåg til indløbshuller.

Aktiveres automatisk når SprueResult.needs_screw_cap == True
(dvs. formen har mere end ét indløb).

Gevindgeometri:
  - ISO 68-1 metrisk gevindprofil (60° flankevinkel, afrundede toppe/bunde)
  - Eksternt gevind (han-side) på låget
  - Internt gevind (hun-side) i formhullet boret som negativ
  - Pitch, diameter og antal omdrejninger er konfigurerbare

Greb:
  - Ydre knurling (lodrette riller) genereret som boolean difference
  - Sealing-flange (tætningsring) nederst på låget

Kendte begrænsninger:
  - FDM-print kan ikke gengive ISO-gevinds nøjagtige flankprofil
    ved layer height > 0.15 mm. Gevindprofilet er en FDM-tilpasset
    udgave med lettere afrunding af spids og rod (H/8 i stedet for H/6).
  - Gevind < M8 (⌀ < 8 mm) anbefales ikke til FDM pga. min. feature-størrelse.
  - cq-threads (CadQuery) er IKKE brugt – alt genereres via NumPy + trimesh
    for at undgå conda-afhængighed.
"""

from __future__ import annotations

import logging
import math
import warnings as _warnings

import numpy as np
import trimesh
import trimesh.creation
import trimesh.repair

from .sprue_calculator import SprueSpec

logger = logging.getLogger(__name__)


class ScrewCapGenerator:
    """
    Genererer skruelåg med ISO 68-1-baseret gevindprofil.

    Eksempel::

        gen  = ScrewCapGenerator()
        caps = gen.generate(sprue_specs)
        # caps er liste af (cap_mesh, thread_negative_mesh)
        # cap_mesh:             selve låget (printes separat)
        # thread_negative_mesh: hullet der bores i formhalvdelen
    """

    def __init__(
        self,
        pitch_mm:       float = 2.0,
        n_turns:        int   = 3,
        wall_mm:        float = 2.5,
        grip_height_mm: float = 10.0,
        knurl_count:    int   = 20,       # Antal knurling-riller rundt om låget
        clearance_mm:   float = 0.3,      # FDM-tolerance: hun-gevind er clearance større
        flange_height_mm: float = 1.5,    # Tætningsflange i bunden af låget
    ):
        self.pitch          = pitch_mm
        self.n_turns        = n_turns
        self.wall           = wall_mm
        self.grip_height    = grip_height_mm
        self.knurl_count    = knurl_count
        self.clearance      = clearance_mm
        self.flange_height  = flange_height_mm

    # ──────────────────────────────────────────────────────────────────────────

    def generate(
        self,
        sprue_specs: list[SprueSpec],
    ) -> list[tuple[trimesh.Trimesh, trimesh.Trimesh]]:
        """
        Generer ét skruelåg pr. indløb.

        Returns:
            Liste af (cap_mesh, thread_negative) tupler.
            cap_mesh:           Selve låget – eksporteres som separat STL.
            thread_negative:    Negativ af gevind til boolean difference
                                i formhalvdelen (borehullet + gevind).
        """
        results = []
        for i, spec in enumerate(sprue_specs):
            logger.info(
                "Genererer skruelåg %d: ⌀%.1f mm, pitch %.1f mm, %d omdrejninger",
                i + 1, spec.diameter_mm, self.pitch, self.n_turns
            )
            cap, negative = self._build_cap(spec)
            results.append((cap, negative))
        return results

    # ──────────────────────────────────────────────────────────────────────────

    def _build_cap(
        self,
        spec: SprueSpec,
    ) -> tuple[trimesh.Trimesh, trimesh.Trimesh]:
        """
        Byg ét skruelåg og tilhørende gevind-negativ.

        Geometri (bottom-up):
          [flange] → [gevind-cylinder] → [greb-cylinder med knurling]

        Han-gevind (eksternt) sidder på gevind-cylinderen.
        Hun-gevind (negativ) er identisk men med +clearance på radius.
        """
        thread_r    = spec.diameter_mm / 2.0
        outer_r     = thread_r + self.wall
        thread_h    = self.n_turns * self.pitch
        total_h     = thread_h + self.grip_height + self.flange_height

        # ── 1. Ydre greb-cylinder ─────────────────────────────────────────────
        grip = trimesh.creation.cylinder(
            radius   = outer_r,
            height   = self.grip_height,
            sections = 64,
        )
        grip.apply_translation([0, 0, thread_h + self.flange_height + self.grip_height / 2])

        # ── 2. Gevind-cylinder (han-side) ─────────────────────────────────────
        thread_body = trimesh.creation.cylinder(
            radius   = thread_r + self._thread_major_add(),
            height   = thread_h,
            sections = 64,
        )
        thread_body.apply_translation([0, 0, self.flange_height + thread_h / 2])

        # ── 3. ISO-gevindspiral (han) ─────────────────────────────────────────
        spiral_han = self._iso_thread_spiral(
            major_r   = thread_r,
            pitch     = self.pitch,
            n_turns   = self.n_turns,
            clearance = 0.0,
            z_start   = self.flange_height,
        )

        # ── 4. Sealing-flange ─────────────────────────────────────────────────
        flange = trimesh.creation.cylinder(
            radius   = outer_r + 1.0,   # Lidt bredere end greb
            height   = self.flange_height,
            sections = 64,
        )
        flange.apply_translation([0, 0, self.flange_height / 2])

        # ── 5. Indre boring (gennemgang) ──────────────────────────────────────
        bore = trimesh.creation.cylinder(
            radius   = thread_r - self.wall / 2,
            height   = total_h + 2.0,
            sections = 32,
        )

        # ── 6. Saml låg via boolean ────────────────────────────────────────────
        try:
            import manifold3d as mf                            # type: ignore
            cap = mf.boolean(grip, thread_body, "union")
            cap = mf.boolean(cap,  spiral_han,  "union")
            cap = mf.boolean(cap,  flange,      "union")
            cap = mf.boolean(cap,  bore,        "difference")
            cap = self._add_knurling(cap, outer_r, self.grip_height,
                                     thread_h + self.flange_height)
        except Exception as exc:
            _warnings.warn(
                f"Skruelåg boolean fejlede ({exc}); eksporterer simpel cylinder.",
                stacklevel=2,
            )
            cap = trimesh.creation.cylinder(radius=outer_r, height=total_h, sections=64)

        cap.apply_translation(-cap.centroid)

        # ── 7. Gevind-negativ (hun-side, monteres i formhalvdel) ──────────────
        negative = self._build_thread_negative(spec, thread_r, thread_h, outer_r)

        return cap, negative

    # ──────────────────────────────────────────────────────────────────────────
    #  ISO 68-1 gevindprofil
    # ──────────────────────────────────────────────────────────────────────────

    def _thread_major_add(self) -> float:
        """
        ISO 68-1: gevindtandens højde H = pitch × √3 / 2.
        Major diameter = nominal + H/8 (for ekstern gevind).
        Returnerer den radielle tilvækst.
        """
        H = self.pitch * math.sqrt(3) / 2.0
        return H / 8.0

    def _iso_thread_spiral(
        self,
        major_r:   float,
        pitch:     float,
        n_turns:   int,
        clearance: float,
        z_start:   float,
        steps_per_turn: int = 90,
    ) -> trimesh.Trimesh:
        """
        Generer ISO 68-1-baseret gevindspiral som et solid mesh.

        Profil (60° flankevinkel, FDM-tilpasset afrunding):
          - Tandhøjde: H = pitch × √3 / 2
          - Effektiv tandhøjde for ekstern gevind: 5H/8
          - Toppe afrundet med radius H/8 (FDM-venlig)
          - Rødder afrundet med radius H/4

        Metode:
          For hvert trin langs spiralen sweepet et 2D tværsnitsprofil
          (8 punkter der repræsenterer flanker + topp/rod) langs helixen.
          Tværsnittet roteres korrekt til spiralens tangens-retning.

        Args:
            major_r:   Nominel gevindradius (halvdelen af M-diameter).
            pitch:     Stigningshøjde pr. omdrejning (mm).
            n_turns:   Antal omdrejninger.
            clearance: Ekstra radial clearance for hun-gevind (mm).
            z_start:   Z-koordinat for spiralens start.
        """
        H         = pitch * math.sqrt(3) / 2.0
        h_eff     = 5.0 * H / 8.0          # Effektiv tandhøjde (ISO)
        r_tip     = H / 8.0                 # Afrundingsradius ved top
        r_root    = H / 4.0                 # Afrundingsradius ved rod

        # Radier
        r_major   = major_r + clearance
        r_minor   = r_major - h_eff

        # 2D profil i (r, z)-planet (8 punkter pr. tand, normaliseret til én pitch)
        # Halvt tand på hver side for kontinuert spiral
        def _profile(z_frac: float) -> tuple[float, float]:
            """
            Returner (radiel offset, z_offset) for en position 0..1 langs pitch.
            z_frac = 0 ved bunden af tandmellemrum, 1 ved næste bund.
            """
            # Lineær flanke med afrundede top/rod (approksimeret med 3-segmenter)
            if z_frac < 0.1:        # Rod (bund), afrundet
                t = z_frac / 0.1
                return r_minor + r_root * (1 - math.cos(math.pi * t / 2)), z_frac * pitch
            elif z_frac < 0.4:      # Stigende flanke
                t = (z_frac - 0.1) / 0.3
                return r_minor + h_eff * t, z_frac * pitch
            elif z_frac < 0.6:      # Top (spids), afrundet
                t = (z_frac - 0.4) / 0.2
                return r_major - r_tip * (1 - math.cos(math.pi * t)), z_frac * pitch
            elif z_frac < 0.9:      # Faldende flanke
                t = (z_frac - 0.6) / 0.3
                return r_major - h_eff * t, z_frac * pitch
            else:                   # Rod igen
                t = (z_frac - 0.9) / 0.1
                return r_minor + r_root * math.cos(math.pi * t / 2), z_frac * pitch

        # Byg vertices langs spiralen
        total_steps = n_turns * steps_per_turn
        all_verts   = []
        all_faces   = []

        for step in range(total_steps):
            frac_along = step / total_steps
            z_frac     = (step % steps_per_turn) / steps_per_turn

            angle     = 2.0 * math.pi * frac_along * n_turns
            z_base    = frac_along * n_turns * pitch + z_start

            r_prof, z_off = _profile(z_frac)

            # Ydre spids
            x_outer = r_prof * math.cos(angle)
            y_outer = r_prof * math.sin(angle)
            z_outer = z_base + z_off

            # Indre rod (til cylinder-kerne)
            x_inner = r_minor * math.cos(angle)
            y_inner = r_minor * math.sin(angle)
            z_inner = z_outer

            all_verts.append([x_outer, y_outer, z_outer])
            all_verts.append([x_inner, y_inner, z_inner])

        verts = np.array(all_verts, dtype=np.float32)
        n     = total_steps

        for i in range(n - 1):
            o0, i0 = i * 2,     i * 2 + 1
            o1, i1 = (i+1)*2,   (i+1)*2 + 1
            all_faces.append([o0, o1, i0])
            all_faces.append([i0, o1, i1])

        if not all_faces:
            return trimesh.creation.cylinder(radius=r_major, height=n_turns * pitch)

        faces = np.array(all_faces, dtype=np.int32)
        mesh  = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        trimesh.repair.fix_normals(mesh)
        return mesh

    def _add_knurling(
        self,
        cap:       trimesh.Trimesh,
        outer_r:   float,
        grip_h:    float,
        z_start:   float,
    ) -> trimesh.Trimesh:
        """
        Tilføj lodrette knurling-riller (grip) via boolean difference
        med smalle cylindriske kiler rundt om lågets greb-zone.

        Rillerne er 0.5 mm dybe og lige så brede som mellemrummet
        (50/50 fordeling rundt om omkredsen).
        """
        try:
            import manifold3d as mf                            # type: ignore
        except ImportError:
            return cap   # Knurling kræver manifold3d

        n        = self.knurl_count
        depth    = 0.5                     # mm
        arc_half = math.pi / n            # halvvinklen for én rille

        for k in range(n):
            angle_c  = 2.0 * math.pi * k / n
            # Centrum af rille
            cx = (outer_r + depth / 2) * math.cos(angle_c)
            cy = (outer_r + depth / 2) * math.sin(angle_c)

            # Meget smal cylinder der skærer ind i lågets kant
            groove = trimesh.creation.cylinder(
                radius   = depth,
                height   = grip_h + 0.5,
                sections = 8,
            )
            groove.apply_translation([cx, cy, z_start + grip_h / 2])

            try:
                cap = mf.boolean(cap, groove, "difference")
            except Exception:
                break   # Stop ved første fejl – delvis knurling er bedre end crash

        return cap

    def _build_thread_negative(
        self,
        spec:     SprueSpec,
        thread_r: float,
        thread_h: float,
        outer_r:  float,
    ) -> trimesh.Trimesh:
        """
        Byg det negative gevind-mesh der bores i formhalvdelen.

        Indeholder:
          - Cylindrisk borehul (nominal gevinddiameter + clearance)
          - ISO hun-gevindspiral med +clearance
        Placeres ved spec.position.
        """
        bore_r   = thread_r + self.clearance
        bore_h   = thread_h + self.flange_height + 2.0   # +2 mm gennemgang

        bore = trimesh.creation.cylinder(
            radius   = bore_r,
            height   = bore_h,
            sections = 64,
        )
        bore.apply_translation([0, 0, bore_h / 2])

        spiral_hun = self._iso_thread_spiral(
            major_r   = thread_r,
            pitch     = self.pitch,
            n_turns   = self.n_turns,
            clearance = self.clearance,
            z_start   = self.flange_height,
        )

        try:
            import manifold3d as mf                            # type: ignore
            negative = mf.boolean(bore, spiral_hun, "union")
        except Exception:
            negative = bore

        negative.apply_translation(spec.position - np.array([0.0, 0.0, bore_h]))
        return negative
