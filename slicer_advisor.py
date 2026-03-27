"""
slicer_advisor.py
-----------------
Genererer slicer-anbefalinger baseret på støbemetode og materiale.

Kombinationerne er:
  - Gips        × PLA
  - Gips        × PETG
  - Moderform   × PLA    (til keramisk støbevæske)
  - Moderform   × PETG

Output indeholder:
  - Layer height, infill type og procent
  - Antal perimeters (vægge)
  - Print- og bed-temperatur
  - Køling
  - Post-processing (slibning, forsegling, frigivelsesmiddel)
  - Advarsler og begrænsninger

Bemærk:
  - Anbefalingerne er baseret på generelle FDM-bedste-praksis.
    Specifikke printere kan kræve justeringer.
  - Tolerancer og temperaturer er vejledende ±10%.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class CastingMethod(Enum):
    GIPS      = auto()    # Direkte gipsstøbning
    MODERFORM = auto()    # Moderform til keramisk støbevæske


class FilamentMaterial(Enum):
    PLA  = auto()
    PETG = auto()


@dataclass
class SlicerProfile:
    """Komplet slicer-profil til ét material/metode-par."""
    method:           CastingMethod
    material:         FilamentMaterial
    layer_height_mm:  float
    infill_type:      str
    infill_pct:       int
    perimeters:       int
    print_temp_c:     int
    bed_temp_c:       int
    cooling_pct:      int             # 0 = ingen, 100 = fuld
    ironing:          bool
    enclosure:        bool
    post_processing:  list[str]
    warnings:         list[str]
    notes:            list[str]

    def as_text(self) -> str:
        """Formattér profil som menneskelig-læsbar tekst."""
        method_str   = "Gips" if self.method == CastingMethod.GIPS else "Moderform (keramik)"
        material_str = self.material.name

        lines = [
            "═" * 58,
            f"  SLICER-ANBEFALINGER: {material_str} / {method_str}",
            "═" * 58,
            f"  Layer height:   {self.layer_height_mm} mm",
            f"  Infill:         {self.infill_pct}% {self.infill_type}",
            f"  Perimeters:     {self.perimeters}",
            f"  Print temp:     {self.print_temp_c}°C",
            f"  Bed temp:       {self.bed_temp_c}°C",
            f"  Køling:         {self.cooling_pct}%",
            f"  Ironing:        {'Ja' if self.ironing else 'Nej'}",
            f"  Enclosure:      {'Anbefalet' if self.enclosure else 'Ikke nødvendigt'}",
        ]

        if self.post_processing:
            lines.append("")
            lines.append("  Post-processing:")
            for step in self.post_processing:
                lines.append(f"    • {step}")

        if self.notes:
            lines.append("")
            lines.append("  Noter:")
            for note in self.notes:
                lines.append(f"    ℹ {note}")

        if self.warnings:
            lines.append("")
            lines.append("  Advarsler:")
            for w in self.warnings:
                lines.append(f"    ⚠ {w}")

        lines.append("═" * 58)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        """Returner profil som dictionary (til JSON-eksport / GUI-binding)."""
        return {
            "method":          self.method.name,
            "material":        self.material.name,
            "layer_height_mm": self.layer_height_mm,
            "infill_type":     self.infill_type,
            "infill_pct":      self.infill_pct,
            "perimeters":      self.perimeters,
            "print_temp_c":    self.print_temp_c,
            "bed_temp_c":      self.bed_temp_c,
            "cooling_pct":     self.cooling_pct,
            "ironing":         self.ironing,
            "enclosure":       self.enclosure,
            "post_processing": self.post_processing,
            "warnings":        self.warnings,
            "notes":           self.notes,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  Profil-database
#  Defineret som konstanter for at gøre det nemt at redigere og udvide.
# ─────────────────────────────────────────────────────────────────────────────

_PROFILES: dict[tuple[CastingMethod, FilamentMaterial], dict] = {

    (CastingMethod.GIPS, FilamentMaterial.PLA): dict(
        layer_height_mm = 0.15,
        infill_type     = "Gyroid",
        infill_pct      = 20,
        perimeters      = 4,
        print_temp_c    = 210,
        bed_temp_c      = 60,
        cooling_pct     = 100,
        ironing         = True,
        enclosure       = False,
        post_processing = [
            "Slib mødeflader med 400-korn sandpapir",
            "Forsegl indersiden med 2 lag shellac eller epoxy-lak",
            "Befugt form i 30 min i vand inden første støbning",
        ],
        warnings = [
            "PLA absorberer vand over tid og bliver skørt – forventet holdbarhed 20–50 støbninger",
            "PLA blødgøres ved > 60°C – undgå varm gips (bland med koldt vand)",
            "Ironing kræver slicer-understøttelse (PrusaSlicer, Bambu Studio, SuperSlicer)",
        ],
        notes = [
            "Frigivelsesmiddel: sæbevand (2 lag) eller vaseline",
            "Egnet til dekorative genstande og prototyper",
        ],
    ),

    (CastingMethod.GIPS, FilamentMaterial.PETG): dict(
        layer_height_mm = 0.15,
        infill_type     = "Gyroid",
        infill_pct      = 25,
        perimeters      = 5,
        print_temp_c    = 240,
        bed_temp_c      = 85,
        cooling_pct     = 40,
        ironing         = False,
        enclosure       = False,
        post_processing = [
            "Slib mødeflader med 400 → 600-korn sandpapir",
            "PETG kan IKKE jævnes med acetone – brug kun mekanisk slibning",
            "Forsegl indersiden med 2 lag epoxy-lak for bedste fugtresistens",
        ],
        warnings = [
            "Kølingsreducering (40%) er vigtig – fuld køling giver svagere lagbinding i PETG",
            "PETG hæfter kraftigt til glatte build plates – brug PEI-ark eller tape",
            "Første lag kan kræve manuel justering af Z-offset",
        ],
        notes = [
            "PETG er mere fugtresistent end PLA – anbefalet til gipsformer der bruges gentagne gange",
            "Frigivelsesmiddel: vaseline eller Ease Release spray",
            "Forventet holdbarhed: 50–150 støbninger",
        ],
    ),

    (CastingMethod.MODERFORM, FilamentMaterial.PLA): dict(
        layer_height_mm = 0.10,
        infill_type     = "Cubic",
        infill_pct      = 30,
        perimeters      = 6,
        print_temp_c    = 210,
        bed_temp_c      = 60,
        cooling_pct     = 100,
        ironing         = True,
        enclosure       = False,
        post_processing = [
            "Slib alle flader med 400 → 800 → 1200-korn (vådslib de to sidste trin)",
            "Forsegl med 3 lag shellac – lad tørre 4 timer mellem lag",
            "Lad forme tørre minimum 48 timer ved 40°C inden første brug",
            "Anvend frigivelsesmiddel (vaseline) i 3 lag på alle indvendige flader",
        ],
        warnings = [
            "PLA tåler ikke varme keramiske slips (> 40°C) – brug kun kolde slip-væsker",
            "Moderformsanvendelse kræver en skarp, høj overfladefinish (< Ra 0.8 µm anbefalet)",
            "Printede lag kan være synlige i keramisk produkt hvis overflade ikke er tilstrækkeligt finpudset",
        ],
        notes = [
            "0.10 mm layer height er minimum for acceptable overfladekvalitet til keramisk moderform",
            "Ironing er stærkt anbefalet på alle eksponerede flader",
            "Egnet til prototyper og small-batch keramik (< 50 afstøbninger)",
        ],
    ),

    (CastingMethod.MODERFORM, FilamentMaterial.PETG): dict(
        layer_height_mm = 0.10,
        infill_type     = "Cubic",
        infill_pct      = 35,
        perimeters      = 6,
        print_temp_c    = 245,
        bed_temp_c      = 90,
        cooling_pct     = 30,
        ironing         = False,
        enclosure       = True,
        post_processing = [
            "Slib alle flader med 400 → 800 → 1200-korn (vådslib fra 600 korn)",
            "Brug roterende slibemaskine med fleksibel skive til kurvede flader",
            "Forsegl med 2-komponent epoxy (f.eks. Smooth-On XTC-3D) for glatteste finish",
            "Hærd epoxy 24 timer inden frigivelsesmiddel påføres",
        ],
        warnings = [
            "Enclosure er nødvendig for at undgå warping – PETG ved 245°C + 90°C bed kræver stabilt temperaturmiljø",
            "Køling må IKKE overstige 30% – lavere køling giver bedre lagbinding og styrke",
            "Første lag: bed-temp 95°C, sænk til 90°C fra lag 2",
        ],
        notes = [
            "PETG + epoxy-coating er den bedste kombination til professionel keramisk moderform",
            "Forventet holdbarhed: 200–500 afstøbninger med korrekt frigivelsesmiddel",
            "Frigivelsesmiddel: Zyvax Watershield eller Ease Release 200",
            "Egnet til professionel keramisk produktion i small-batch (< 500 stk)",
        ],
    ),
}


# ─────────────────────────────────────────────────────────────────────────────

class SlicerAdvisor:
    """
    Returnerer slicer-profil baseret på støbemetode og materiale.

    Eksempel::

        advisor = SlicerAdvisor()
        profile = advisor.get_profile(CastingMethod.GIPS, FilamentMaterial.PETG)
        print(profile.as_text())
    """

    def get_profile(
        self,
        method:   CastingMethod,
        material: FilamentMaterial,
    ) -> SlicerProfile:
        """
        Returner SlicerProfile for det givne metode/materiale-par.

        Raises:
            KeyError: Hvis kombinationen ikke er defineret.
        """
        key = (method, material)
        if key not in _PROFILES:
            raise KeyError(
                f"Ingen profil for {method.name} + {material.name}. "
                f"Tilgængelige: {[f'{m.name}+{f.name}' for m,f in _PROFILES]}"
            )
        params = _PROFILES[key]
        return SlicerProfile(method=method, material=material, **params)

    def all_profiles(self) -> list[SlicerProfile]:
        """Returner alle fire definerede profiler."""
        return [
            self.get_profile(m, f)
            for (m, f) in _PROFILES
        ]
