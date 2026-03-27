"""
stl_exporter.py
---------------
Eksporterer formhalvdele og skruelåg som individuelle STL-filer.

Filnavngivning:
  <prefix>_part_A.stl, <prefix>_part_B.stl, …
  <prefix>_screw_cap_1.stl, <prefix>_screw_cap_2.stl, …

Alle filer eksporteres i binær STL-format (kompakt, hurtig).
ASCII STL kan vælges med use_ascii=True (større filer, human-readable).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import trimesh

from mold_builder import MoldPart

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    """Resultat af STL-eksport."""
    exported_files: list[str]
    skipped:        list[str]
    warnings:       list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Eksporterede {len(self.exported_files)} fil(er):"]
        for f in self.exported_files:
            lines.append(f"  ✓ {f}")
        for f in self.skipped:
            lines.append(f"  ✗ Sprunget over: {f}")
        for w in self.warnings:
            lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


class STLExporter:
    """
    Eksporterer alle formkomponenter som STL-filer.

    Eksempel::

        exporter = STLExporter(output_dir="./output", prefix="mold")
        result   = exporter.export(parts, screw_caps)
        print(result.summary())
    """

    def __init__(
        self,
        output_dir: str  = "./output",
        prefix:     str  = "mold",
        use_ascii:  bool = False,
    ):
        self.output_dir = Path(output_dir)
        self.prefix     = prefix
        self.use_ascii  = use_ascii

    # ──────────────────────────────────────────────────────────────────────────

    def export(
        self,
        parts:       list[MoldPart],
        screw_caps:  list[trimesh.Trimesh] | None = None,
    ) -> ExportResult:
        """
        Eksportér alle dele.

        Args:
            parts:      Formhalvdele fra RegistrationSystem / SprueCalculator.
            screw_caps: Evt. skruelåg fra ScrewCapGenerator.

        Returns:
            ExportResult med liste af eksporterede filer.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        exported: list[str] = []
        skipped:  list[str] = []
        warnings: list[str] = []

        # ── Formhalvdele ─────────────────────────────────────────────────────
        for part in parts:
            filename = f"{self.prefix}_part_{part.label}.stl"
            filepath = self.output_dir / filename

            if len(part.mesh.faces) == 0:
                skipped.append(str(filepath))
                warnings.append(f"Del {part.label} har 0 trekanter – springes over.")
                continue

            try:
                self._write_stl(part.mesh, filepath)
                exported.append(str(filepath))
                logger.info("Eksporteret: %s  (%d trekanter)", filepath, len(part.mesh.faces))
            except Exception as exc:
                skipped.append(str(filepath))
                warnings.append(f"Eksport af del {part.label} fejlede: {exc}")

            # Videresend part-advarsler
            for w in part.warnings:
                warnings.append(f"Del {part.label}: {w}")

        # ── Skruelåg ─────────────────────────────────────────────────────────
        if screw_caps:
            for i, cap in enumerate(screw_caps, start=1):
                filename = f"{self.prefix}_screw_cap_{i}.stl"
                filepath = self.output_dir / filename
                try:
                    self._write_stl(cap, filepath)
                    exported.append(str(filepath))
                    logger.info("Eksporteret skruelåg: %s", filepath)
                except Exception as exc:
                    skipped.append(str(filepath))
                    warnings.append(f"Eksport af skruelåg {i} fejlede: {exc}")

        return ExportResult(
            exported_files = exported,
            skipped        = skipped,
            warnings       = warnings,
        )

    # ──────────────────────────────────────────────────────────────────────────

    def _write_stl(self, mesh: trimesh.Trimesh, filepath: Path) -> None:
        """Skriv mesh til STL-fil i binær eller ASCII format."""
        data = mesh.export(file_type="stl_ascii" if self.use_ascii else "stl")
        with open(filepath, "wb" if not self.use_ascii else "w") as f:
            f.write(data)
