"""
main.py
-------
Indgangspunkt for Mold Generator.

Bruges både som:
  1. CLI: python main.py model.stl [--config config/defaults.yaml]
  2. Import: from main import MoldPipeline

Pipeline-rækkefølge:
  STLLoader → UndercutAnalyzer → PartingOptimizer → MoldBuilder
  → RegistrationSystem → SprueCalculator → [ScrewCapGenerator]
  → STLExporter → SlicerAdvisor
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# Kerne
from core.gpu_accelerator   import GPUAccelerator
from core.stl_loader        import STLLoader, MeshReport
from core.undercut_analyzer  import UndercutAnalyzer, UndercutReport
from core.parting_optimizer  import PartingOptimizer, PartingResult
from core.mold_builder       import MoldBuilder, MoldPart
from core.registration       import RegistrationSystem
from core.sprue_calculator   import SprueCalculator, SprueResult
from core.screw_cap_generator import ScrewCapGenerator

# Output
from output.stl_exporter    import STLExporter, ExportResult
from output.slicer_advisor  import SlicerAdvisor, CastingMethod, FilamentMaterial

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt= "%H:%M:%S",
)
logger = logging.getLogger("mold_generator")


# ─────────────────────────────────────────────────────────────────────────────
#  Konfiguration
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Config:
    """Samlet konfiguration (smeltet fra YAML + CLI-overrides)."""
    # Geometri
    wall_thickness_mm:   float = 3.0
    draft_angle_deg:     float = 1.5
    undercut_threshold:  float = 2.0
    max_parts:           int   = 6

    # Registration
    min_pins:            int   = 3
    pin_tolerance_mm:    float = 0.2
    snap_lock:           bool  = False

    # Sprue
    min_sprue_diam_mm:   float = 5.0
    air_vent_diam_mm:    float = 2.0

    # Toggles
    symmetric_split:     bool  = True
    asymmetric_logic:    bool  = False
    auto_part_count:     bool  = True
    force_2part:         bool  = False
    auto_sprue:          bool  = True
    registration_pins:   bool  = True

    # GPU
    gpu_enabled:         bool  = True
    gpu_device:          int   = 0

    # Output
    output_dir:          str   = "./output"
    prefix:              str   = "mold"

    # Slicer
    casting_method:      str   = "gips"     # "gips" | "moderform"
    material:            str   = "PLA"      # "PLA" | "PETG"

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path) as f:
            raw = yaml.safe_load(f)
        g   = raw.get("geometry", {})
        reg = raw.get("registration", {})
        sp  = raw.get("sprue", {})
        tog = raw.get("toggles", {})
        gpu = raw.get("gpu", {})
        out = raw.get("output", {})
        return cls(
            wall_thickness_mm  = g.get("wall_thickness_mm", 3.0),
            draft_angle_deg    = g.get("draft_angle_deg", 1.5),
            undercut_threshold = g.get("undercut_threshold_pct", 2.0),
            max_parts          = g.get("max_parts", 6),
            min_pins           = reg.get("min_pins", 3),
            pin_tolerance_mm   = reg.get("pin_tolerance_mm", 0.2),
            snap_lock          = reg.get("snap_lock", False),
            min_sprue_diam_mm  = sp.get("min_diameter_mm", 5.0),
            air_vent_diam_mm   = sp.get("air_vent_diameter_mm", 2.0),
            symmetric_split    = tog.get("symmetric_split", True),
            asymmetric_logic   = tog.get("asymmetric_logic", False),
            auto_part_count    = tog.get("auto_part_count", True),
            force_2part        = tog.get("force_2part", False),
            auto_sprue         = tog.get("auto_sprue", True),
            registration_pins  = tog.get("registration_pins", True),
            gpu_enabled        = gpu.get("enabled", True),
            gpu_device         = gpu.get("cuda_device", 0),
            output_dir         = out.get("export_dir", "./output"),
            prefix             = out.get("prefix", "mold"),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Pipeline
# ─────────────────────────────────────────────────────────────────────────────

class MoldPipeline:
    """
    Kører den komplette STL → støbeform-pipeline.

    Eksempel::

        pipeline = MoldPipeline(config)
        result   = pipeline.run("model.stl")
    """

    def __init__(self, config: Config):
        self.cfg = config
        self.gpu = GPUAccelerator(
            device_index = config.gpu_device,
            force_cpu    = not config.gpu_enabled,
        )
        logger.info("GPU: %s", self.gpu.info())

    def run(
        self,
        stl_path:        str,
        casting_method:  Optional[CastingMethod] = None,
        material:        Optional[FilamentMaterial] = None,
    ) -> dict:
        """
        Kør fuld pipeline og returner resultat-dictionary.

        Returns dict med nøgler:
          mesh_report, undercut_report, parting_result,
          parts, sprue_result, export_result, slicer_profile
        """
        cfg = self.cfg

        # ── 1. Indlæs STL ────────────────────────────────────────────────────
        logger.info("─── Fase 1: Indlæser STL …")
        loader = STLLoader(auto_repair=True, center_mesh=True)
        mesh, mesh_report = loader.load(stl_path)
        logger.info("\n%s", mesh_report)

        # ── 2. Underskæringsanalyse ──────────────────────────────────────────
        logger.info("─── Fase 2: Underskæringsanalyse …")
        analyzer = UndercutAnalyzer(gpu=self.gpu, n_directions=500)
        undercut_report = analyzer.analyze(mesh, threshold_pct=cfg.undercut_threshold)
        logger.info("\n%s", undercut_report.summary())

        # ── 3. Delingsoptimering ─────────────────────────────────────────────
        logger.info("─── Fase 3: Delingsoptimering …")
        force2 = cfg.force_2part
        symmetric = cfg.symmetric_split and not cfg.asymmetric_logic
        optimizer = PartingOptimizer(
            gpu          = self.gpu,
            symmetric    = symmetric,
            max_parts    = 2 if force2 else cfg.max_parts,
        )
        parting_result = optimizer.optimize(
            mesh, undercut_report, threshold_pct=cfg.undercut_threshold
        )
        logger.info("\n%s", parting_result.summary())

        # ── 4. Byg formhalvdele ──────────────────────────────────────────────
        logger.info("─── Fase 4: Bygger formhalvdele …")
        builder = MoldBuilder(
            wall_thickness_mm = cfg.wall_thickness_mm,
            draft_angle_deg   = cfg.draft_angle_deg,
        )
        parts = builder.build(mesh, parting_result)

        # ── 5. Samletappe ────────────────────────────────────────────────────
        if cfg.registration_pins:
            logger.info("─── Fase 5: Tilføjer samletappe …")
            reg = RegistrationSystem(
                min_pins     = cfg.min_pins,
                tolerance_mm = cfg.pin_tolerance_mm,
                snap_lock    = cfg.snap_lock,
            )
            import numpy as np
            parts = reg.add_pins(
                parts, parting_result.split_planes[0],
                np.array(mesh.bounding_box.extents)
            )

        # ── 6. Indløb og lufthuller ──────────────────────────────────────────
        sprue_result = None
        screw_caps   = None
        if cfg.auto_sprue:
            logger.info("─── Fase 6: Beregner indløb og lufthuller …")
            sprue_calc  = SprueCalculator(
                min_diameter_mm      = cfg.min_sprue_diam_mm,
                air_vent_diameter_mm = cfg.air_vent_diam_mm,
            )
            split_normal = parting_result.split_planes[0].normal \
                           if parting_result.split_planes else None
            sprue_result = sprue_calc.calculate(
                mesh, parts,
                split_normal    = split_normal,
                wall_thickness  = cfg.wall_thickness_mm,
            )
            parts = sprue_calc.add_to_parts(parts, sprue_result, split_normal=split_normal)

            if sprue_result.needs_screw_cap:
                logger.info("─── Fase 6b: Genererer skruelåg …")
                cap_gen    = ScrewCapGenerator()
                cap_tuples = cap_gen.generate(sprue_result.sprue_specs)
                screw_caps = [cap for cap, _ in cap_tuples]

        # ── 7. Eksporter STL'er ──────────────────────────────────────────────
        logger.info("─── Fase 7: Eksporterer STL-filer …")
        exporter = STLExporter(
            output_dir = cfg.output_dir,
            prefix     = cfg.prefix,
        )
        export_result = exporter.export(parts, screw_caps)
        logger.info("\n%s", export_result.summary())

        # ── 8. Slicer-anbefalinger ───────────────────────────────────────────
        logger.info("─── Fase 8: Slicer-anbefalinger …")
        method_enum = casting_method or _parse_method(cfg.casting_method)
        mat_enum    = material       or _parse_material(cfg.material)
        advisor     = SlicerAdvisor()
        slicer_profile = advisor.get_profile(method_enum, mat_enum)
        print("\n" + slicer_profile.as_text())

        return {
            "mesh_report":     mesh_report,
            "undercut_report": undercut_report,
            "parting_result":  parting_result,
            "parts":           parts,
            "sprue_result":    sprue_result,
            "export_result":   export_result,
            "slicer_profile":  slicer_profile,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_method(s: str) -> CastingMethod:
    s = s.lower().strip()
    if s in ("gips", "plaster"):
        return CastingMethod.GIPS
    if s in ("moderform", "master", "ceramic"):
        return CastingMethod.MODERFORM
    raise ValueError(f"Ukendt støbemetode: {s!r}. Brug 'gips' eller 'moderform'.")

def _parse_material(s: str) -> FilamentMaterial:
    s = s.upper().strip()
    if s == "PLA":
        return FilamentMaterial.PLA
    if s == "PETG":
        return FilamentMaterial.PETG
    raise ValueError(f"Ukendt materiale: {s!r}. Brug 'PLA' eller 'PETG'.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mold Generator – STL til 3D-printbar støbeform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Eksempler:
  python main.py                             ← Start GUI (standard)
  python main.py --gui                       ← Start GUI eksplicit
  python main.py model.stl                   ← CLI: gips + PLA
  python main.py model.stl --method moderform --material PETG
  python main.py model.stl --asymmetric --max-parts 4 --no-gpu
""",
    )
    # Valgfri STL-fil – udeladt = start GUI
    parser.add_argument("stl_file",  nargs="?", default=None,
                        help="Sti til STL-fil (udelad for at starte GUI)")
    parser.add_argument("--gui",     action="store_true",
                        help="Start grafisk brugergrænseflade (standard ved ingen STL-fil)")
    parser.add_argument("--config",  default="config/defaults.yaml",
                        help="YAML-konfigurationsfil")
    parser.add_argument("--method",  default=None,
                        choices=["gips", "moderform"])
    parser.add_argument("--material", default=None,
                        choices=["PLA", "PETG"])
    parser.add_argument("--output",  default=None)
    parser.add_argument("--asymmetric", action="store_true")
    parser.add_argument("--max-parts", type=int, default=None)
    parser.add_argument("--force-2part", action="store_true")
    parser.add_argument("--no-gpu", action="store_true")
    parser.add_argument("--prefix", default=None)

    args = parser.parse_args()

    # ── GUI-tilstand (standard når ingen STL-fil angives) ────────────────────
    if args.gui or args.stl_file is None:
        return _launch_gui(args)

    # ── CLI-tilstand ─────────────────────────────────────────────────────────
    config_path = args.config
    if Path(config_path).is_file():
        cfg = Config.from_yaml(config_path)
    else:
        logger.warning("Config-fil ikke fundet: %s – bruger standardindstillinger.", config_path)
        cfg = Config()

    if args.asymmetric:
        cfg.asymmetric_logic = True
        cfg.symmetric_split  = False
    if args.max_parts is not None:
        cfg.max_parts = args.max_parts
    if args.force_2part:
        cfg.force_2part = True
    if args.no_gpu:
        cfg.gpu_enabled = False
    if args.output is not None:
        cfg.output_dir = args.output
    if args.prefix is not None:
        cfg.prefix = args.prefix

    casting = _parse_method(args.method)    if args.method   else None
    mat     = _parse_material(args.material) if args.material else None

    try:
        pipeline = MoldPipeline(cfg)
        pipeline.run(args.stl_file, casting_method=casting, material=mat)
        return 0
    except FileNotFoundError as exc:
        logger.error("Fil ikke fundet: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Pipeline fejlede: %s", exc)
        return 2


def _launch_gui(args) -> int:
    """Start PyQt6 GUI-applikationen."""
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore    import Qt
        from gui.main_window import MainWindow
    except ImportError as exc:
        print(
            f"Kan ikke starte GUI: {exc}\n"
            "Installer GUI-afhængigheder:\n"
            "  pip install PyQt6 PyOpenGL PyOpenGL-accelerate\n"
            "Eller brug CLI-tilstand: python main.py model.stl",
            file=sys.stderr,
        )
        return 1

    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Mold Generator")
    app.setOrganizationName("MoldGen")

    # Mørkt tema via stylesheet
    app.setStyleSheet(_DARK_STYLESHEET)

    window = MainWindow()
    window.show()

    # Åbn STL direkte hvis givet som argument til --gui
    if args.stl_file:
        window._stl_path = args.stl_file
        window._on_open_stl_path(args.stl_file)

    return app.exec()


# ─────────────────────────────────────────────────────────────────────────────
#  Mørkt tema (QSS)
# ─────────────────────────────────────────────────────────────────────────────

_DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1a1a1e;
    color: #d4d4d8;
}
QMenuBar {
    background-color: #111114;
    color: #d4d4d8;
    border-bottom: 1px solid #2a2a30;
}
QMenuBar::item:selected { background: #2a2a38; }
QMenu {
    background-color: #1f1f26;
    color: #d4d4d8;
    border: 1px solid #2a2a30;
}
QMenu::item:selected { background: #2e2e3e; }
QToolBar {
    background-color: #111114;
    border-bottom: 1px solid #2a2a30;
    spacing: 4px;
    padding: 3px 6px;
}
QPushButton {
    background-color: #25252e;
    color: #d4d4d8;
    border: 1px solid #3a3a46;
    border-radius: 5px;
    padding: 5px 14px;
    font-size: 13px;
}
QPushButton:hover   { background-color: #2e2e3c; border-color: #5a5a78; }
QPushButton:pressed { background-color: #1e1e28; }
QPushButton:disabled { color: #555; border-color: #2a2a30; }
QGroupBox {
    border: 1px solid #2e2e38;
    border-radius: 6px;
    margin-top: 10px;
    font-weight: bold;
    font-size: 12px;
    color: #9090b0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QDoubleSpinBox, QSpinBox {
    background-color: #1f1f26;
    color: #d4d4d8;
    border: 1px solid #3a3a46;
    border-radius: 4px;
    padding: 2px 6px;
}
QCheckBox { color: #c4c4d0; spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1px solid #4a4a5a;
    border-radius: 3px;
    background: #1f1f28;
}
QCheckBox::indicator:checked {
    background: #5080d0;
    border-color: #6090e0;
    image: none;
}
QRadioButton { color: #c4c4d0; spacing: 6px; }
QRadioButton::indicator {
    width: 14px; height: 14px;
    border: 1px solid #4a4a5a;
    border-radius: 7px;
    background: #1f1f28;
}
QRadioButton::indicator:checked { background: #5080d0; border-color: #6090e0; }
QScrollBar:vertical {
    background: #15151a;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical { background: #3a3a50; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #5050708; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTabWidget::pane { border: 1px solid #2a2a30; background: #111114; }
QTabBar::tab {
    background: #1a1a22;
    color: #9090a8;
    border: 1px solid #2a2a30;
    border-bottom: none;
    padding: 5px 14px;
    font-size: 12px;
}
QTabBar::tab:selected { background: #111114; color: #d4d4d8; border-color: #3a3a50; }
QTabBar::tab:hover    { background: #22222e; }
QSplitter::handle { background: #2a2a30; }
QSplitter::handle:horizontal { width: 3px; }
QSplitter::handle:vertical   { height: 3px; }
QProgressBar {
    border: 1px solid #3a3a46;
    border-radius: 4px;
    background: #1f1f26;
    color: #d4d4d8;
    text-align: center;
    font-size: 11px;
}
QProgressBar::chunk { background: #4070c0; border-radius: 3px; }
QStatusBar {
    background: #111114;
    color: #888;
    border-top: 1px solid #2a2a30;
    font-size: 12px;
}
QLabel { color: #c4c4d0; }
"""


if __name__ == "__main__":
    sys.exit(main())

