"""
tests/test_undercut_analyzer.py
--------------------------------
Enhedstests for UndercutAnalyzer.

Kræver ikke GPU – bruger CPU-fallback eksplicit.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
import trimesh

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.gpu_accelerator   import GPUAccelerator
from core.undercut_analyzer  import UndercutAnalyzer, UndercutReport


@pytest.fixture
def cpu_gpu():
    """GPUAccelerator med tvungen CPU-tilstand."""
    return GPUAccelerator(force_cpu=True)


@pytest.fixture
def simple_box():
    """En simpel boks-mesh centreret i origo."""
    return trimesh.creation.box(extents=(20.0, 30.0, 40.0))


@pytest.fixture
def sphere_mesh():
    """En sfære – bør have høj underskæring for alle akseparallelle retninger."""
    return trimesh.creation.icosphere(subdivisions=3, radius=10.0)


class TestDirectionSet:

    def test_direction_count(self, cpu_gpu):
        """Antallet af retninger skal matche n_directions + 6 (akseparallelle)."""
        n = 100
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=n)
        assert len(analyzer._directions) == n + 6

    def test_directions_unit_vectors(self, cpu_gpu):
        """Alle retninger skal være enhedsvektorer (|d| ≈ 1)."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=200)
        norms = np.linalg.norm(analyzer._directions, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)

    def test_axis_directions_included(self, cpu_gpu):
        """De 6 akseparallelle retninger skal altid være med."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=50)
        dirs = analyzer._directions
        axis_dirs = [
            [1, 0, 0], [-1, 0, 0],
            [0, 1, 0], [0, -1, 0],
            [0, 0, 1], [0, 0, -1],
        ]
        for axis in axis_dirs:
            dists = np.linalg.norm(dirs - np.array(axis), axis=1)
            assert dists.min() < 1e-4, f"Akseparallel retning {axis} mangler"


class TestAnalyze:

    def test_returns_report(self, cpu_gpu, simple_box):
        """analyze() skal returnere en UndercutReport."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=50)
        report   = analyzer.analyze(simple_box)
        assert isinstance(report, UndercutReport)

    def test_box_best_direction_axis_aligned(self, cpu_gpu, simple_box):
        """
        For en akseparallel boks skal den bedste retning være akseparallel
        og underskæringen nær 0%.
        """
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=100)
        report   = analyzer.analyze(simple_box, threshold_pct=2.0)
        assert report.best.undercut_pct < 5.0, \
            f"Boks bør have lav underskæring, fik {report.best.undercut_pct:.1f}%"
        assert report.best.axis_aligned, \
            "Bedste retning for boks bør være akseparallel"

    def test_scores_in_valid_range(self, cpu_gpu, simple_box):
        """Alle scores skal være i [0, 1]."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=50)
        report   = analyzer.analyze(simple_box)
        for r in report.results:
            assert 0.0 <= r.score <= 1.0, f"Score uden for [0,1]: {r.score}"

    def test_results_sorted(self, cpu_gpu, simple_box):
        """Resultaterne skal være sorteret med lavest score først."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=50)
        report   = analyzer.analyze(simple_box)
        scores   = [r.score for r in report.results]
        assert scores == sorted(scores), "Resultater er ikke sorteret"

    def test_recommended_splits_box(self, cpu_gpu, simple_box):
        """En boks bør kræve 2 formhalvdele."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=100)
        report   = analyzer.analyze(simple_box, threshold_pct=2.0)
        assert report.recommended_splits == 2, \
            f"Boks bør give 2 dele, fik {report.recommended_splits}"

    def test_total_area_positive(self, cpu_gpu, simple_box):
        """Total areal skal være positivt."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=50)
        report   = analyzer.analyze(simple_box)
        assert report.total_area_mm2 > 0

    def test_summary_string(self, cpu_gpu, simple_box):
        """summary() skal returnere en ikke-tom streng."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=50)
        report   = analyzer.analyze(simple_box)
        summary  = report.summary()
        assert isinstance(summary, str)
        assert len(summary) > 10

    def test_top_n(self, cpu_gpu, simple_box):
        """top_n() skal returnere korrekt antal resultater."""
        analyzer = UndercutAnalyzer(gpu=cpu_gpu, n_directions=50)
        report   = analyzer.analyze(simple_box)
        top3 = report.top_n(3)
        assert len(top3) == 3
        # Skal stadig være sorteret
        assert top3[0].score <= top3[1].score <= top3[2].score


class TestCPUFallback:

    def test_cpu_undercut_scores_shape(self):
        """cpu_undercut_scores skal returnere (K,) array."""
        normals    = np.random.randn(100, 3).astype(np.float32)
        normals   /= np.linalg.norm(normals, axis=1, keepdims=True)
        areas      = np.ones(100, dtype=np.float32)
        directions = np.random.randn(20, 3).astype(np.float32)
        directions /= np.linalg.norm(directions, axis=1, keepdims=True)

        scores = GPUAccelerator.cpu_undercut_scores(normals, areas, directions)
        assert scores.shape == (20,)

    def test_cpu_scores_range(self):
        """CPU-scores skal være i [0, 1]."""
        normals    = np.random.randn(50, 3).astype(np.float32)
        normals   /= np.linalg.norm(normals, axis=1, keepdims=True)
        areas      = np.ones(50, dtype=np.float32)
        directions = np.eye(3, dtype=np.float32)

        scores = GPUAccelerator.cpu_undercut_scores(normals, areas, directions)
        assert (scores >= 0).all() and (scores <= 1).all()
