"""
tests/test_stl_loader.py
------------------------
Enhedstests for STLLoader.

Kører med:  python -m pytest tests/ -v
Kræver ikke GPU eller rigtige STL-filer – bruger syntetiske trimesh-meshes.
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.stl_loader import STLLoader, MeshReport


def _make_box_stl(path: str, extents=(20.0, 30.0, 40.0)) -> None:
    """Gem en simpel boks som STL-fil til testbrug."""
    mesh = trimesh.creation.box(extents=extents)
    data = mesh.export(file_type="stl")
    with open(path, "wb") as f:
        f.write(data)


class TestSTLLoaderBasic:

    def test_load_valid_box(self):
        """En simpel boks-STL skal indlæses uden fejl."""
        loader = STLLoader()
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            _make_box_stl(tmp)
            mesh, report = loader.load(tmp)
            assert isinstance(mesh, trimesh.Trimesh)
            assert isinstance(report, MeshReport)
            assert report.is_watertight
            assert report.volume_cm3 > 0
        finally:
            os.unlink(tmp)

    def test_file_not_found(self):
        """FileNotFoundError skal rejses for ikke-eksisterende fil."""
        loader = STLLoader()
        with pytest.raises(FileNotFoundError):
            loader.load("/tmp/denne_fil_eksisterer_ikke_xyz.stl")

    def test_mesh_centered_after_load(self):
        """Med center_mesh=True skal centroid være tæt på origo."""
        loader = STLLoader(center_mesh=True)
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            _make_box_stl(tmp)
            mesh, _ = loader.load(tmp)
            centroid = mesh.bounding_box.centroid
            np.testing.assert_allclose(centroid, [0, 0, 0], atol=1.0)
        finally:
            os.unlink(tmp)

    def test_bbox_reported_correctly(self):
        """Bounding box i rapporten skal matche den faktiske mesh-størrelse."""
        loader = STLLoader()
        extents = (10.0, 20.0, 30.0)
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            _make_box_stl(tmp, extents=extents)
            _, report = loader.load(tmp)
            for expected, actual in zip(sorted(extents), sorted(report.bbox_mm)):
                assert abs(expected - actual) < 0.5, \
                    f"Forventet bbox-dim {expected}, fik {actual}"
        finally:
            os.unlink(tmp)

    def test_scale_detection_meters(self):
        """Et mesh i meter (bbox < 1) skal skaleres × 1000 til mm."""
        loader = STLLoader(scale_to_mm=True)
        # Opret boks 0.02 × 0.03 × 0.04 m (= 20 × 30 × 40 mm)
        mesh_m = trimesh.creation.box(extents=(0.02, 0.03, 0.04))
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            data = mesh_m.export(file_type="stl")
            with open(tmp, "wb") as fh:
                fh.write(data)
            mesh, report = loader.load(tmp)
            # Skal nu være i mm-størrelsesorden
            assert max(report.bbox_mm) > 1.0, \
                f"Skalering fejlede: bbox = {report.bbox_mm}"
            assert any("skaleret" in w.lower() for w in report.warnings)
        finally:
            os.unlink(tmp)

    def test_no_center_option(self):
        """Med center_mesh=False skal centroid IKKE flyttes til origo."""
        loader = STLLoader(center_mesh=False)
        mesh_shifted = trimesh.creation.box(extents=(10, 10, 10))
        mesh_shifted.apply_translation([100, 200, 300])
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            data = mesh_shifted.export(file_type="stl")
            with open(tmp, "wb") as fh:
                fh.write(data)
            mesh, _ = loader.load(tmp)
            centroid = mesh.bounding_box.centroid
            # Centroid skal stadig være tæt på (100, 200, 300)
            assert np.linalg.norm(centroid - [100, 200, 300]) < 2.0
        finally:
            os.unlink(tmp)


class TestSTLLoaderReport:

    def test_report_fields(self):
        """MeshReport skal have alle forventede felter udfyldt."""
        loader = STLLoader()
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            _make_box_stl(tmp)
            _, report = loader.load(tmp)
            assert report.filepath == tmp
            assert report.original_faces > 0
            assert report.repaired_faces > 0
            assert isinstance(report.warnings, list)
            assert len(report.bbox_mm) == 3
        finally:
            os.unlink(tmp)

    def test_str_representation(self):
        """str(report) skal returnere en læsbar streng uden fejl."""
        loader = STLLoader()
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            _make_box_stl(tmp)
            _, report = loader.load(tmp)
            text = str(report)
            assert "Watertight" in text
            assert "cm³" in text
        finally:
            os.unlink(tmp)
