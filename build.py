"""
installer/build.py
------------------
Automatiseret build-script til pakket installer.

Orkestrerer:
  1. Forudsætnings-tjek (Python-version, PyInstaller, platform-tools)
  2. Rens tidligere builds
  3. Kør PyInstaller med platform-specifik spec-fil
  4. Verificér output (eksistens, størrelse, minimum-fil-tælling)
  5. Platform-specifik pakning:
     Windows: kør makensis → .exe installer
     Linux:   kør appimage-builder → .AppImage

Brug:
  python installer/build.py
  python installer/build.py --skip-pack    ← kun PyInstaller, ingen NSIS/AppImage
  python installer/build.py --version 1.2.0

Exit-koder:
  0  = success
  1  = forudsætninger ikke opfyldt (se output for detaljer)
  2  = PyInstaller fejlede
  3  = pakknings-trin fejlede

Kør altid fra projektets rodmappe:
  cd mold_generator/
  python installer/build.py
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── Konstanter ─────────────────────────────────────────────────────────────────
ROOT          = Path(__file__).parent.parent.resolve()
INSTALLER_DIR = Path(__file__).parent.resolve()
DIST_DIR      = ROOT / "dist"
BUILD_DIR     = ROOT / "build"

WINDOWS = sys.platform == "win32"
LINUX   = sys.platform.startswith("linux")

APP_NAME    = "MoldGenerator"
APP_VERSION = "1.0.0"   # Overstyres med --version


# ── ANSI-farver til terminal-output ───────────────────────────────────────────
def _c(color: str, text: str) -> str:
    """Wrap tekst i ANSI-farvekode (deaktiveres på Windows cmd.exe)."""
    if WINDOWS and not os.environ.get("WT_SESSION"):  # Ikke Windows Terminal
        return text
    codes = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "bold": "1"}
    return f"\033[{codes.get(color, '0')}m{text}\033[0m"


def info(msg: str)  -> None: print(_c("cyan",   f"  ℹ  {msg}"))
def ok(msg: str)    -> None: print(_c("green",  f"  ✓  {msg}"))
def warn(msg: str)  -> None: print(_c("yellow", f"  ⚠  {msg}"))
def err(msg: str)   -> None: print(_c("red",    f"  ✗  {msg}"), file=sys.stderr)
def step(msg: str)  -> None: print(_c("bold",   f"\n── {msg} ──"))


# ─────────────────────────────────────────────────────────────────────────────
#  Trin 1: Forudsætnings-tjek
# ─────────────────────────────────────────────────────────────────────────────

def check_prerequisites(skip_pack: bool) -> bool:
    """
    Verificer at alle nødvendige værktøjer er til stede.
    Returnerer True hvis vi kan fortsætte, False ved blokkerende fejl.
    """
    step("Forudsætnings-tjek")
    all_ok = True

    # Python-version
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 10):
        ok(f"Python {major}.{minor}")
    else:
        err(f"Python {major}.{minor} – kræver ≥ 3.10")
        all_ok = False

    # PyInstaller
    try:
        import PyInstaller
        ok(f"PyInstaller {PyInstaller.__version__}")
    except ImportError:
        err("PyInstaller ikke installeret – kør: pip install pyinstaller")
        all_ok = False

    # Kerne-pakker (ikke alle behøver at være installeret for at builden kan starte)
    optional_checks = [
        ("trimesh",    "pip install trimesh"),
        ("PyQt6",      "pip install PyQt6"),
        ("numpy",      "pip install numpy"),
        ("manifold3d", "pip install manifold3d"),
    ]
    for pkg, hint in optional_checks:
        try:
            __import__(pkg)
            ok(f"{pkg}")
        except ImportError:
            err(f"{pkg} mangler – {hint}")
            all_ok = False

    # Valgfri (CuPy)
    try:
        import cupy
        ok(f"CuPy {cupy.__version__} (GPU-acceleration aktiv)")
    except ImportError:
        warn("CuPy ikke installeret – build fortsætter med CPU-fallback")

    # Platform-specifik pakknings-tool
    if not skip_pack:
        if WINDOWS:
            if shutil.which("makensis"):
                ok("NSIS (makensis) fundet")
            else:
                warn("makensis ikke på PATH – .exe installer springes over.\n"
                     "     Installer NSIS fra https://nsis.sourceforge.io")

        if LINUX:
            if shutil.which("appimage-builder"):
                ok("appimage-builder fundet")
            else:
                warn("appimage-builder ikke fundet – AppImage springes over.\n"
                     "     Installer med: pip install appimage-builder")

    # UPX (valgfri – komprimering)
    if shutil.which("upx"):
        ok("UPX fundet (komprimering aktiveret)")
    else:
        warn("UPX ikke fundet – build fortsætter uden komprimering.\n"
             "     Download fra https://github.com/upx/upx/releases")

    return all_ok


# ─────────────────────────────────────────────────────────────────────────────
#  Trin 2: Rens tidligere builds
# ─────────────────────────────────────────────────────────────────────────────

def clean_build_dirs() -> None:
    step("Renser tidligere builds")

    for d in (DIST_DIR / APP_NAME, BUILD_DIR):
        if d.exists():
            shutil.rmtree(d)
            info(f"Slettet: {d.relative_to(ROOT)}")
        else:
            info(f"Ikke til stede (OK): {d.relative_to(ROOT)}")

    ok("Build-mapper renset")


# ─────────────────────────────────────────────────────────────────────────────
#  Trin 3: Kør PyInstaller
# ─────────────────────────────────────────────────────────────────────────────

def run_pyinstaller() -> bool:
    step("Kører PyInstaller")

    if WINDOWS:
        spec = INSTALLER_DIR / "mold_generator_windows.spec"
    elif LINUX:
        spec = INSTALLER_DIR / "mold_generator_linux.spec"
    else:
        err(f"Ikke-understøttet platform: {sys.platform}")
        return False

    if not spec.exists():
        err(f"Spec-fil ikke fundet: {spec}")
        return False

    info(f"Spec: {spec.relative_to(ROOT)}")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec),
        "--noconfirm",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--log-level", "WARN",   # Skjul INFO-spam, vis kun advarsler+fejl
    ]

    info(f"Kommando: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        err(f"PyInstaller fejlede med exit-kode {result.returncode}")
        return False

    ok("PyInstaller afsluttet succesfuldt")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  Trin 4: Verificér output
# ─────────────────────────────────────────────────────────────────────────────

def verify_output() -> bool:
    step("Verificerer output")

    bundle_dir = DIST_DIR / APP_NAME
    if not bundle_dir.exists():
        err(f"Bundle-mappe ikke fundet: {bundle_dir}")
        return False

    if WINDOWS:
        exe = bundle_dir / f"{APP_NAME}.exe"
    else:
        exe = bundle_dir / APP_NAME

    if not exe.exists():
        err(f"Eksekverbar ikke fundet: {exe}")
        return False

    exe_mb = exe.stat().st_size / 1024 / 1024
    ok(f"Eksekverbar: {exe.name}  ({exe_mb:.1f} MB)")

    # Tæl filer i bundle
    all_files = list(bundle_dir.rglob("*"))
    file_count = sum(1 for f in all_files if f.is_file())
    total_mb   = sum(f.stat().st_size for f in all_files if f.is_file()) / 1024 / 1024

    ok(f"Bundle: {file_count} filer, {total_mb:.0f} MB total")

    # Minimumstjek – bundles er typisk > 50 MB
    if total_mb < 20:
        warn(f"Bundle er usædvanlig lille ({total_mb:.0f} MB) – mulig ufuldstændig build")

    # Tjek at konfigurationsfilen er med
    cfg = bundle_dir / "config" / "defaults.yaml"
    if cfg.exists():
        ok("config/defaults.yaml inkluderet")
    else:
        warn("config/defaults.yaml MANGLER i bundle – programmet bruger hardkodede standarder")

    return True


# ─────────────────────────────────────────────────────────────────────────────
#  Trin 5a: Windows NSIS-installer
# ─────────────────────────────────────────────────────────────────────────────

def build_windows_installer(version: str) -> bool:
    step("Bygger Windows NSIS-installer")

    if not shutil.which("makensis"):
        warn("makensis ikke fundet – springer installer over")
        return True   # Ikke en blokkerende fejl

    nsi_script = INSTALLER_DIR / "MoldGenerator.nsi"
    if not nsi_script.exists():
        err(f"NSI-script ikke fundet: {nsi_script}")
        return False

    # Tjek at LICENSE.txt eksisterer (kræves af NSIS-scriptet)
    license_file = ROOT / "LICENSE.txt"
    if not license_file.exists():
        warn("LICENSE.txt mangler – opretter placeholder")
        license_file.write_text(
            "MIT License\n\nCopyright (c) 2024 MoldGen\n\n"
            "Permission is hereby granted, free of charge, to any person "
            "obtaining a copy of this software...\n"
        )

    cmd = [
        "makensis",
        f"/DAPPVERSION={version}",
        str(nsi_script),
    ]

    info(f"Kommando: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        err(f"makensis fejlede med exit-kode {result.returncode}")
        return False

    installer = DIST_DIR / f"{APP_NAME}-{version}-setup.exe"
    if installer.exists():
        size_mb = installer.stat().st_size / 1024 / 1024
        ok(f"Installer oprettet: {installer.name}  ({size_mb:.0f} MB)")
    else:
        warn("Installer-fil ikke fundet på forventet sti – tjek NSI output")

    return True


# ─────────────────────────────────────────────────────────────────────────────
#  Trin 5b: Linux AppImage
# ─────────────────────────────────────────────────────────────────────────────

def build_linux_appimage(version: str) -> bool:
    step("Bygger Linux AppImage")

    if not shutil.which("appimage-builder"):
        warn("appimage-builder ikke fundet – springer AppImage over")
        return True   # Ikke blokkerende

    recipe = INSTALLER_DIR / "AppImageBuilder.yml"
    if not recipe.exists():
        err(f"AppImageBuilder recipe ikke fundet: {recipe}")
        return False

    # Forbered AppDir-struktur
    appdir = ROOT / "AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    appdir.mkdir()

    # Kopiér bundle til AppDir/usr/bin
    usr_bin = appdir / "usr" / "bin"
    usr_bin.mkdir(parents=True)
    bundle_dir = DIST_DIR / APP_NAME
    if bundle_dir.exists():
        shutil.copytree(bundle_dir, usr_bin / APP_NAME, dirs_exist_ok=True)
    else:
        err(f"PyInstaller bundle ikke fundet: {bundle_dir}")
        return False

    # .desktop-fil til AppImage desktop-integration
    desktop_dir = appdir / "usr" / "share" / "applications"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "mold-generator.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Mold Generator\n"
        "Exec=MoldGenerator %f\n"
        "Icon=mold-generator\n"
        "Categories=Graphics;Engineering;\n"
        "MimeType=model/stl;application/sla;\n"
        "Comment=STL til 3D-printbar støbeform\n"
        "Terminal=false\n"
    )

    # Symlink til ikon (kræves af appimage-builder)
    icons_dir = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icons_dir.mkdir(parents=True)
    src_icon = INSTALLER_DIR / "assets" / "mold-generator.png"
    dst_icon = icons_dir / "mold-generator.png"
    if src_icon.exists():
        shutil.copy(src_icon, dst_icon)
    else:
        warn(f"Ikon ikke fundet: {src_icon} – AppImage mangler ikon")

    cmd = [
        "appimage-builder",
        "--recipe", str(recipe),
        "--skip-test",   # Kræver Docker – deaktivér i CI-miljø
    ]

    env = os.environ.copy()
    env["APP_VERSION"] = version

    info(f"Kommando: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), env=env)

    if result.returncode != 0:
        err(f"appimage-builder fejlede med exit-kode {result.returncode}")
        return False

    # Find .AppImage-filen
    appimages = list(ROOT.glob("*.AppImage"))
    if appimages:
        ai = appimages[0]
        size_mb = ai.stat().st_size / 1024 / 1024
        ok(f"AppImage oprettet: {ai.name}  ({size_mb:.0f} MB)")
        # Flyt til dist/
        target = DIST_DIR / ai.name
        shutil.move(str(ai), str(target))
        ok(f"Flyttet til: {target.relative_to(ROOT)}")
    else:
        warn("Ingen .AppImage-fil fundet efter build")

    return True


# ─────────────────────────────────────────────────────────────────────────────
#  Print build-sammendrag
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(version: str, skip_pack: bool) -> None:
    step("Build-sammendrag")

    bundle  = DIST_DIR / APP_NAME
    outputs = []

    if bundle.exists():
        all_files  = [f for f in bundle.rglob("*") if f.is_file()]
        total_mb   = sum(f.stat().st_size for f in all_files) / 1024 / 1024
        outputs.append(f"Bundle:   {bundle.relative_to(ROOT)}  ({total_mb:.0f} MB, {len(all_files)} filer)")

    if WINDOWS and not skip_pack:
        installer = DIST_DIR / f"{APP_NAME}-{version}-setup.exe"
        if installer.exists():
            size_mb = installer.stat().st_size / 1024 / 1024
            outputs.append(f"Installer: {installer.relative_to(ROOT)}  ({size_mb:.0f} MB)")

    if LINUX and not skip_pack:
        appimages = list((DIST_DIR).glob("*.AppImage"))
        for ai in appimages:
            size_mb = ai.stat().st_size / 1024 / 1024
            outputs.append(f"AppImage: {ai.relative_to(ROOT)}  ({size_mb:.0f} MB)")

    if outputs:
        print()
        for line in outputs:
            ok(line)
        print()
        ok(f"Build version {version} afsluttet succesfuldt!")
    else:
        warn("Ingen output-filer fundet – build kan have fejlet")


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Byg pakket installer til Mold Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Eksempler:
  python installer/build.py                    # Fuld build (PyInstaller + installer)
  python installer/build.py --skip-pack        # Kun PyInstaller
  python installer/build.py --version 1.2.0   # Med specifik version
  python installer/build.py --no-clean         # Bevar tidligere build-artefakter
""",
    )
    parser.add_argument("--version",    default=APP_VERSION,
                        help=f"App-version (standard: {APP_VERSION})")
    parser.add_argument("--skip-pack",  action="store_true",
                        help="Spring NSIS/AppImage-trin over – kun PyInstaller")
    parser.add_argument("--no-clean",   action="store_true",
                        help="Rens ikke dist/ og build/ inden build")
    args = parser.parse_args()

    print(_c("bold", f"\n{'='*54}"))
    print(_c("bold",  f"  Mold Generator – Build {args.version}"))
    print(_c("bold", f"  Platform: {platform.system()} {platform.machine()}"))
    print(_c("bold", f"{'='*54}"))

    # ── Forudsætninger ────────────────────────────────────────────────────────
    if not check_prerequisites(args.skip_pack):
        err("Forudsætninger ikke opfyldt – afbryder build.")
        return 1

    # ── Rens ──────────────────────────────────────────────────────────────────
    if not args.no_clean:
        clean_build_dirs()

    # ── PyInstaller ───────────────────────────────────────────────────────────
    if not run_pyinstaller():
        return 2

    # ── Verificér ─────────────────────────────────────────────────────────────
    if not verify_output():
        return 2

    # ── Platform-specifik pakning ─────────────────────────────────────────────
    if not args.skip_pack:
        if WINDOWS:
            if not build_windows_installer(args.version):
                return 3
        elif LINUX:
            if not build_linux_appimage(args.version):
                return 3
        else:
            warn(f"Platform '{sys.platform}' understøtter ikke automatisk pakning.")
            warn("Brug den genererede dist/MoldGenerator/-mappe direkte.")

    # ── Sammendrag ────────────────────────────────────────────────────────────
    print_summary(args.version, args.skip_pack)
    return 0


if __name__ == "__main__":
    sys.exit(main())
