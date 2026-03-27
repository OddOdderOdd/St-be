"""
tests/test_slicer_advisor.py
-----------------------------
Enhedstests for SlicerAdvisor.
Ingen filsystem eller GPU nødvendigt.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from output.slicer_advisor import (
    SlicerAdvisor, SlicerProfile, CastingMethod, FilamentMaterial
)


@pytest.fixture
def advisor():
    return SlicerAdvisor()


class TestSlicerAdvisor:

    @pytest.mark.parametrize("method,material", [
        (CastingMethod.GIPS,      FilamentMaterial.PLA),
        (CastingMethod.GIPS,      FilamentMaterial.PETG),
        (CastingMethod.MODERFORM, FilamentMaterial.PLA),
        (CastingMethod.MODERFORM, FilamentMaterial.PETG),
    ])
    def test_all_profiles_exist(self, advisor, method, material):
        """Alle fire kombinationer skal returnere en profil uden fejl."""
        profile = advisor.get_profile(method, material)
        assert isinstance(profile, SlicerProfile)

    @pytest.mark.parametrize("method,material", [
        (CastingMethod.GIPS,      FilamentMaterial.PLA),
        (CastingMethod.GIPS,      FilamentMaterial.PETG),
        (CastingMethod.MODERFORM, FilamentMaterial.PLA),
        (CastingMethod.MODERFORM, FilamentMaterial.PETG),
    ])
    def test_layer_height_valid(self, advisor, method, material):
        """Layer height skal være i realistisk FDM-område (0.05–0.35 mm)."""
        p = advisor.get_profile(method, material)
        assert 0.05 <= p.layer_height_mm <= 0.35

    @pytest.mark.parametrize("method,material", [
        (CastingMethod.GIPS,      FilamentMaterial.PLA),
        (CastingMethod.GIPS,      FilamentMaterial.PETG),
        (CastingMethod.MODERFORM, FilamentMaterial.PLA),
        (CastingMethod.MODERFORM, FilamentMaterial.PETG),
    ])
    def test_temperatures_sane(self, advisor, method, material):
        """Print- og bed-temperaturer skal være i realistiske grænser."""
        p = advisor.get_profile(method, material)
        assert 180 <= p.print_temp_c <= 270, f"Print temp {p.print_temp_c} ude af område"
        assert 40  <= p.bed_temp_c  <= 120, f"Bed temp {p.bed_temp_c} ude af område"

    def test_moderform_higher_quality(self, advisor):
        """Moderform-profiler skal have højere kvalitet (lavere layer height) end gips."""
        gips_pla  = advisor.get_profile(CastingMethod.GIPS,      FilamentMaterial.PLA)
        mod_pla   = advisor.get_profile(CastingMethod.MODERFORM, FilamentMaterial.PLA)
        assert mod_pla.layer_height_mm <= gips_pla.layer_height_mm

    def test_moderform_more_perimeters(self, advisor):
        """Moderform-profiler skal have mindst lige så mange perimeters som gips."""
        gips  = advisor.get_profile(CastingMethod.GIPS,      FilamentMaterial.PETG)
        mod   = advisor.get_profile(CastingMethod.MODERFORM, FilamentMaterial.PETG)
        assert mod.perimeters >= gips.perimeters

    def test_as_text_contains_key_info(self, advisor):
        """as_text() skal indeholde temperaturer og layer height."""
        for method in CastingMethod:
            for mat in FilamentMaterial:
                p    = advisor.get_profile(method, mat)
                text = p.as_text()
                assert str(p.layer_height_mm) in text
                assert str(p.print_temp_c) in text
                assert str(p.bed_temp_c) in text

    def test_as_dict_keys(self, advisor):
        """as_dict() skal have alle forventede nøgler."""
        p   = advisor.get_profile(CastingMethod.GIPS, FilamentMaterial.PLA)
        d   = p.as_dict()
        required = {
            "method", "material", "layer_height_mm", "infill_type",
            "infill_pct", "perimeters", "print_temp_c", "bed_temp_c",
            "cooling_pct", "ironing", "enclosure", "post_processing",
            "warnings", "notes"
        }
        assert required.issubset(d.keys())

    def test_all_profiles_returns_four(self, advisor):
        """all_profiles() skal returnere præcis 4 profiler."""
        profiles = advisor.all_profiles()
        assert len(profiles) == 4

    def test_petg_lower_cooling(self, advisor):
        """PETG-profiler skal have lavere køling end PLA-profiler (for samme metode)."""
        pla_gips  = advisor.get_profile(CastingMethod.GIPS, FilamentMaterial.PLA)
        petg_gips = advisor.get_profile(CastingMethod.GIPS, FilamentMaterial.PETG)
        assert petg_gips.cooling_pct < pla_gips.cooling_pct

    def test_moderform_petg_enclosure(self, advisor):
        """Moderform + PETG skal anbefale enclosure."""
        p = advisor.get_profile(CastingMethod.MODERFORM, FilamentMaterial.PETG)
        assert p.enclosure is True

    def test_post_processing_not_empty(self, advisor):
        """Alle profiler skal have mindst ét post-processing trin."""
        for method in CastingMethod:
            for mat in FilamentMaterial:
                p = advisor.get_profile(method, mat)
                assert len(p.post_processing) >= 1, \
                    f"Ingen post-processing for {method.name}+{mat.name}"
