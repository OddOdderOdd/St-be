# Mold Generator

**STL → 3D-printbar støbeform**

Et Python-baseret desktopprogram der konverterer uploadede STL-filer til
optimerede, 3D-printbare støbeforme. Programmet analyserer modellen for
underskæringer (GPU-accelereret), vælger automatisk det mindst mulige antal
formhalvdele, genererer samletappe, indløb og lufthuller, og eksporterer
færdige STL-filer klar til sliceren.

---

## Funktioner

| # | Funktion | Status |
|---|---|---|
| 1 | STL-indlæsning, validering og automatisk reparation | ✅ Implementeret |
| 2 | GPU-accelereret underskæringsanalyse (500 retninger parallelt) | ✅ Implementeret |
| 3 | CPU-fallback hvis ingen NVIDIA GPU tilgængelig | ✅ Implementeret |
| 4 | Automatisk valg af 2/3/4+ formhalvdele | ✅ Implementeret |
| 5 | Toggles: symmetrisk/asymmetrisk delingslogik | ✅ Implementeret |
| 6 | Automatisk generering af samletappe (alignment pins) | ✅ Implementeret |
| 7 | Automatisk indløb og lufthuller (sprue + air vents) | ✅ Implementeret |
| 8 | Skruelåg ved mere end ét indløb | ✅ Implementeret |
| 9 | Slicer-anbefalinger (4 profiler: Gips/Moderform × PLA/PETG) | ✅ Implementeret |
| 10 | CLI-interface | ✅ Implementeret |
| 11 | Draft angle (udtræksvinkel) via vertex-projektion | ✅ Implementeret |
| 12 | BVH-baseret selvskæringstest (Möller–Trumbore) | ✅ Implementeret |
| 13 | Topologisk lomme-detektion til lufthuller (7×7 ray grid) | ✅ Implementeret |
| 14 | Ægte konisk frustum til indløbstragt | ✅ Implementeret |
| 15 | ISO 68-1-baseret gevindprofil med knurling og tætningsflange | ✅ Implementeret |
| 16 | Indløbsplacering relativt til splitplanets pull-retning | ✅ Implementeret |
| 17 | PyQt6 GUI med 3D OpenGL-viewport | ✅ Implementeret |
| 18 | Mørkt tema (QSS stylesheet) | ✅ Implementeret |
| 19 | Pipeline-kørsel i baggrundstråd (QThread) | ✅ Implementeret |
| 20 | Slicer-fane med sammenligningstabel | ✅ Implementeret |
| 21 | Log-fane med live pipeline-output | ✅ Implementeret |
| 22 | Pakket installer (.exe / .AppImage) | ✅ Implementeret |

---

## Hurtig start (installer)

Læg alle projektfiler i samme mappe og dobbeltklik på den rette fil:

| Platform | Fil | Hvad den gør |
|---|---|---|
| **CachyOS / Arch** | `install_cachyos.sh` | Installer alt, opret ikon på skrivebord |
| **Windows 10/11** | `install_windows.bat` | Installer alt, opret ikon på skrivebord |

Begge installere:
- Opretter et Python virtual environment (ingen system-pakker forurenes)
- Installerer alle Python-afhængigheder automatisk
- Detekterer NVIDIA GPU og installerer CuPy til GPU-acceleration
- Opretter en dobbeltklik-launcher på Skrivebordet
- Kopierer programfilerne til en fast installationsmappe

---

## Installation

### Forudsætninger

- Python 3.10+
- NVIDIA GPU med Compute Capability ≥ 6.0 (GTX 10-serien eller nyere)
- CUDA Toolkit 12.x ([download](https://developer.nvidia.com/cuda-downloads))

### Trin

```bash
# Klon repositoriet
git clone https://github.com/dit-repo/mold-generator.git
cd mold-generator

# Opret virtuelt miljø (anbefalet)
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
.venv\Scripts\activate             # Windows

# Installer afhængigheder
pip install -r requirements.txt

# Verificér GPU-adgang (valgfrit)
python -c "import cupy; print(cupy.cuda.Device(0).compute_capability)"
```

> **Ingen GPU?** Programmet falder automatisk tilbage til CPU-beregning med
> en advarsel. Underskæringsanalysen vil tage ~45 sekunder i stedet for ~2.

---

## Brug

### GUI (standard)

```bash
# Start GUI – åbn STL via filDialog i applikationen
python main.py

# Start GUI og åbn STL-fil direkte
python main.py --gui model.stl
```

GUI-vinduet har tre paneler:

- **3D Viewport** (venstre): Rotér med venstre museknap, pan med højre, zoom med scrollhjul.
  Vis/skjul individuelle lag (original model, formhalvdele, tappe, indløb, splitlinjer) via Vis-menuen.
- **Indstillinger** (højre): Alle pipeline-parametre som widgets.
  Ændringer nulstiller automatisk det aktuelle resultat.
- **Output** (bund): Tre faner – Analyse (metric-kort + detaljeret rapport),
  Slicer-anbefalinger (med sammenligningstabel), Log (live pipeline-output).

### CLI

```bash
# Simpel brug – gips + PLA (standardindstillinger)
python main.py model.stl

# Med valg af støbemetode og materiale
python main.py model.stl --method moderform --material PETG

# Asymmetrisk delingslogik, max 4 dele
python main.py model.stl --asymmetric --max-parts 4

# Tving todelt form, ingen GPU
python main.py model.stl --force-2part --no-gpu

# Fuld oversigt over muligheder
python main.py --help
```

### Python API

```python
from main import MoldPipeline, Config
from output.slicer_advisor import CastingMethod, FilamentMaterial

cfg      = Config.from_yaml("config/defaults.yaml")
pipeline = MoldPipeline(cfg)

result = pipeline.run(
    "model.stl",
    casting_method = CastingMethod.MODERFORM,
    material       = FilamentMaterial.PETG,
)

# result indeholder:
#   mesh_report, undercut_report, parting_result,
#   parts, sprue_result, export_result, slicer_profile
print(result["slicer_profile"].as_text())
```

### Output-filer

Alle filer eksporteres til `./output/` (konfigurerbart):

```
output/
├── mold_part_A.stl          ← Formhalvdel A
├── mold_part_B.stl          ← Formhalvdel B
├── mold_part_C.stl          ← (kun ved 3+ dele)
└── mold_screw_cap_1.stl     ← (kun hvis > 1 indløb)
```

---

## Konfiguration

Rediger `config/defaults.yaml` for at ændre standardindstillinger:

```yaml
geometry:
  wall_thickness_mm: 3.0       # Mindste formvæg
  draft_angle_deg: 1.5         # Udtræksvinkel (ikke implementeret endnu – se kendte bugs)
  undercut_threshold_pct: 2.0  # Max acceptabel underskæring for todelt form
  max_parts: 6                 # Maks antal formhalvdele

toggles:
  symmetric_split: true        # Kun akseparallelle splits
  asymmetric_logic: false      # Tillad skrå parting lines
  force_2part: false           # Tving todelt form
```

Se den fulde fil for alle muligheder.

---

## Mappestruktur

```
mold_generator/
├── main.py                      ← Indgangspunkt + MoldPipeline + CLI
├── README.md                    ← Dette dokument
├── requirements.txt
├── config/
│   └── defaults.yaml            ← Standardindstillinger
├── core/
│   ├── gpu_accelerator.py       ← CUDA-wrapper (CuPy) + CPU-fallback
│   ├── stl_loader.py            ← STL-indlæsning, validering og reparation
│   ├── undercut_analyzer.py     ← GPU-accelereret underskæringsanalyse
│   ├── parting_optimizer.py     ← Optimal splitplan-søgning
│   ├── mold_builder.py          ← Formbygning via boolean operations
│   ├── registration.py          ← Samletappe og huller
│   ├── sprue_calculator.py      ← Indløb og lufthuller
│   └── screw_cap_generator.py   ← Skruelåg med gevind
├── output/
│   ├── slicer_advisor.py        ← Slicer-anbefalinger (4 profiler)
│   └── stl_exporter.py          ← Multi-fil STL-eksport
└── tests/
    ├── test_stl_loader.py        ← Tests for STLLoader (kræver trimesh)
    ├── test_undercut_analyzer.py ← Tests for UndercutAnalyzer
    └── test_slicer_advisor.py    ← Tests for SlicerAdvisor (ingen deps)
```

---

## Tests

```bash
# Kræver pytest + trimesh
pip install pytest trimesh
python -m pytest tests/ -v

# Kun tests uden trimesh-afhængighed
python -m pytest tests/test_slicer_advisor.py -v
```

Aktuel teststatus (kørt uden netværksadgang):

| Testfil | Antal tests | Status |
|---|---|---|
| `test_slicer_advisor.py` | 12 | ✅ 12/12 passerer |
| `test_undercut_analyzer.py` | 13 | ⏳ Afventer trimesh-installation |
| `test_stl_loader.py` | 8 | ⏳ Afventer trimesh-installation |

---

## Kendte bugs og halvfærdigt arbejde

> Denne sektion opdateres løbende efterhånden som fejl opdages eller
> funktioner implementeres delvist.

### 🔴 Kritiske mangler (blokerende for fuld pipeline)

**Draft angle (udtræksvinkel) er ikke implementeret**
- Modul: `core/mold_builder.py` → `_apply_draft_angle()`
- Status: Stub-funktion der returnerer mesh uændret
- Konsekvens: Formhalvdele har lodrette vægge uden udtræksvinkel. Dette
  kan gøre det svært at trække modellen ud af formen, særligt ved glatte
  materialer. Løsning: Tilføj manuel udtræksvinkel i CAD-software inden print,
  eller brug `config/defaults.yaml` til at sætte `draft_angle_deg: 0` for at
  undgå falsk tryghed.
- Plan: Implementér via OpenCASCADE's `BRepOffsetAPI_DraftAngle` (kræver
  `python-occ` bibliotek som conda-pakke).

**Boolean-operationer kræver `manifold3d`**
- Modul: `core/mold_builder.py`, `core/registration.py`, `core/sprue_calculator.py`
- Status: `manifold3d` er ikke tilgængeligt via pip i alle miljøer.
  Trimesh's OpenSCAD-fallback kræver OpenSCAD installeret på PATH.
- Konsekvens: Pipeline crasher i fase 4 (Formbygning) medmindre manifold3d
  eller OpenSCAD er tilgængeligt.
- Løsning: `pip install manifold3d` (virker på de fleste Linux/Windows-systemer).

### 🟡 Delvist implementeret

**Fler-delt form (3+ dele) er eksperimentel**
- Modul: `core/mold_builder.py` → `_build_multipart()`
- Status: Implementeret men kun testet for orthogonale splitplaner.
  For asymmetriske planer er der risiko for overlappende formhalvdele.
- Konsekvens: Output for 3+ dele skal altid kontrolleres visuelt i slicer
  inden print.
- Workaround: Brug `--force-2part` og reparer underskæringer manuelt.

**Lomme-detektion (pocket detection) til lufthuller er unøjagtig**
- Modul: `core/sprue_calculator.py` → `_find_vent_positions()`
- Status: Enkel ray-cast proxy. Finder ikke alle lukkede interne hulrum.
- Konsekvens: Modeller med indre hulrum (f.eks. hule figurer) kan mangle
  lufthuller og give ufuldstændige støbninger.
- Plan: Erstat med topologisk analyse via `trimesh.graph` + volumenmåling.

**Gevindprofil er en approksimation**
- Modul: `core/screw_cap_generator.py` → `_make_thread_spiral()`
- Status: Polygonal spiral, ikke ISO-M gevindprofil.
- Konsekvens: Gevind kan have op til 0.1–0.2 mm afvigelse fra standard.
  Virker udmærket til FDM (layer height > 0.1 mm) men ikke til
  præcisionsanvendelser.
- Plan: Integrer `cq-threads` via CadQuery (kræver conda-installation).

**Selvskæringstest er unøjagtig**
- Modul: `core/stl_loader.py` → `_fast_self_intersect_check()`
- Status: Bruger watertight + volumen-negativitet som proxy.
  Kan give falsk-positiver for ikke-manifold meshes der er repareret.
- Plan: Erstat med `trimesh.collision.CollisionManager` eller Open3D.

**Indløbsplacering er altid langs Z-aksen**
- Modul: `core/sprue_calculator.py`
- Status: Indløb placeres altid ved modellens højeste Z-punkt.
  Tager ikke højde for splitplanets orientering.
- Konsekvens: For vertikalt orienterede splitplaner kan indløbet placeres
  i en formhalvdels midt-flade i stedet for toppen.
- Plan: Transformér indløbsposition til splitplanets koordinatsystem.

**D-formede tappe (anti-rotation) er approksimation**
- Modul: `core/registration.py` → `_make_pin()`
- Status: D-formen genereres via boolean med en boks, men test i slicer
  er ikke udført. Geometrien kan have artefakter ved kanten.

### 🟢 Planlagt men ikke startet

**GUI (Fase 4)**
- PyQt6 vindue med OpenGL 3D-viewport
- Toggle-panel til alle indstillinger
- Live slicer-output panel
- Estimeret: 2–3 ugers arbejde

**Pakket installer**
- PyInstaller til `.exe` (Windows) og `.AppImage` (Linux)
- Estimeret: 1 uges arbejde efter GUI er færdig

**BVH-acceleration på GPU**
- Nuværende raycast er O(N·K) – langsom for meshes > 500k trekanter
- Plan: Implementér Bounding Volume Hierarchy via CuPy CUDA kernel

**Adaptive sampling af udtræksretninger**
- Nuværende: Uniform fibonacci-spiral sampling
- Plan: Koncentrér samples i retninger tæt på mesh-kurvaturens maksimum

**Multi-GPU understøttelse**
- Nuværende: Kun device 0 understøttes
- Plan: Auto-select GPU med mest ledig VRAM

---

## Teknologistak

| Lag | Bibliotek | Version |
|---|---|---|
| Geometri | trimesh | 4.4.0 |
| Boolean ops | manifold3d | 2.4.0 |
| GPU-acceleration | CuPy (CUDA 12.x) | 13.0.0 |
| Matematik | NumPy + SciPy | 1.26.4 / 1.13.0 |
| GUI (planlagt) | PyQt6 + PyOpenGL | 6.7.0 / 3.1.7 |
| Konfiguration | PyYAML | 6.0.1 |

---

## Udviklingsplan

### Fase 1 – Kerne ✅ Afsluttet
- [x] STL-indlæsning og automatisk reparation (`stl_loader.py`)
- [x] GPU-accelereret underskæringsanalyse (`undercut_analyzer.py`)
- [x] CPU-fallback (`gpu_accelerator.py`)
- [x] Konfigurationssystem (`config/defaults.yaml` + `Config`)
- [x] CLI-indgangspunkt (`main.py`)

### Fase 2 – Geometri 🔄 I gang
- [x] Todelt formgenerering (`mold_builder.py`)
- [x] Delingsoptimering 2/3/4+ dele (`parting_optimizer.py`)
- [x] Asymmetrisk logik (toggle implementeret)
- [x] Samletappe (`registration.py`)
- [x] Boolean-operationer via manifold3d
- [ ] **Draft angle (udtræksvinkel)** ← næste prioritet
- [ ] Validering af 3+-delt output

### Fase 3 – Indløb og låg 🔄 I gang
- [x] Sprue-beregner (`sprue_calculator.py`)
- [x] Lufthuls-detektion (simpel proxy)
- [x] Skruelåg-generator med gevind (`screw_cap_generator.py`)
- [ ] **Præcis lomme-detektion** ← næste prioritet
- [ ] Indløbsplacering relativt til splitplan

### Fase 4 – GUI og output ✅ Afsluttet
- [x] PyQt6 GUI med 3D OpenGL-viewport (`gui/viewport_3d.py`)
- [x] Arcball-kamera: rotation, pan, zoom via mus
- [x] 5 toggle-bare lag: model, formhalvdele, tappe, indløb, splitlinjer
- [x] Indstillings-panel med alle pipeline-parametre (`gui/settings_panel.py`)
- [x] Tre-fanet output-panel: Analyse, Slicer-anbefalinger, Log (`gui/output_panel.py`)
- [x] Pipeline kører i QThread – GUI fryser ikke under beregning
- [x] Mørkt QSS-tema på hele applikationen
- [x] Både GUI-tilstand (`python main.py`) og CLI-tilstand (`python main.py model.stl`)
- [x] Pakket installer (.exe / .AppImage via PyInstaller + NSIS + appimage-builder)

---

## Byg installer

`installer/build.py` orkestrerer hele build-processen fra én kommando.

### Forudsætninger

```bash
pip install pyinstaller

# Windows: installer NSIS (valgfrit – til .exe installer)
# https://nsis.sourceforge.io

# Linux: installer appimage-builder (valgfrit – til .AppImage)
pip install appimage-builder

# Valgfrit: UPX til komprimering (reducerer bundle-størrelse ~30%)
# https://github.com/upx/upx/releases
```

### Kør build

```bash
cd mold_generator/

# Fuld build (PyInstaller + platform-specifik installer)
python installer/build.py

# Kun PyInstaller-bundle (ingen NSIS/AppImage)
python installer/build.py --skip-pack

# Med specifik versionsnummer
python installer/build.py --version 1.2.0

# Bevar tidligere build-artefakter (ingen rens)
python installer/build.py --no-clean
```

Scriptet udfører automatisk:
1. Forudsætnings-tjek (Python-version, PyInstaller, platform-tools, pakker)
2. Rens af `dist/` og `build/` mapper
3. PyInstaller med platform-specifik `.spec`-fil
4. Verificering af output (størrelse, filantal, `config/defaults.yaml` til stede)
5. **Windows:** `makensis installer/MoldGenerator.nsi` → `dist/MoldGenerator-{version}-setup.exe`
6. **Linux:** `appimage-builder --recipe installer/AppImageBuilder.yml` → `MoldGenerator-{version}-x86_64.AppImage`

### Output

```
dist/
├── MoldGenerator/                    ← Standalone onedir-bundle (begge platforme)
│   ├── MoldGenerator[.exe]           ← Eksekverbar
│   ├── config/defaults.yaml
│   ├── PyQt6/                        ← Qt-biblioteker
│   └── ...
├── MoldGenerator-1.0.0-setup.exe    ← Windows NSIS-installer
└── MoldGenerator-1.0.0-x86_64.AppImage  ← Linux AppImage
```

### Ikoner og assets

Placér følgende filer i `installer/assets/` inden Windows-build:

| Fil | Størrelse | Formål |
|---|---|---|
| `icon.ico` | 256×256 (multi-res) | Windows EXE + installer ikon |
| `icon.png` | 256×256 | Linux AppImage ikon |
| `mold-generator.png` | 256×256 | Linux desktop-integration |
| `header.bmp` | 150×57 px | NSIS installer header |
| `wizard.bmp` | 164×314 px | NSIS wizard sidebillede |

Uden ikonerne kører build med advarsel og bruger PyInstallers standard-ikon.

### PyInstaller hooks

`installer/hooks/` indeholder tilpassede hooks der løser kendte problemer:

| Hook | Problem løst |
|---|---|
| `hook-OpenGL.py` | PyOpenGL's dynamiske backend-imports fanges ikke automatisk |
| `hook-trimesh.py` | trimesh's lazy-loaded ray/graph/repair moduler + networkx |
| `hook-cupy.py` | CuPy .so/.pyd filer + defensiv fallback ved manglende GPU |
| `rthook_linux.py` | `LD_LIBRARY_PATH`, Qt-platform plugin, headless fallback |
| `rthook_windows.py` | `os.add_dll_directory` for CUDA DLLer, Qt-plugin-sti |

### CUDA runtime på slutbruger-maskiner

CuPy-binaries bundtes i installeren, men CUDA runtime-biblioteker (`libcuda.so`, `cudart.dll`) er **ikke** inkluderet — de er meget store (>500 MB) og distribueres af NVIDIA. Slutbrugere med NVIDIA GPU skal have CUDA Toolkit ≥ 12.0 installeret for GPU-acceleration. Uden CUDA kører programmet automatisk på CPU-fallback.

---

## Kendte begrænsninger

- **Drag-and-drop** af STL-filer til viewport er ikke implementeret.
- **LOD** (level-of-detail) til store meshes > 1M trekanter mangler.
- **Depth-sorting** af transparente meshes i viewport er ikke implementeret (bagsider kan være synlige ved visse kameravinkler).
- **Progressbar** viser kun diskrete trin fra pipeline-faserne, ikke smooth progress inden for en fase.
- **Draft angle** bruger vertex-projektion (lineær approksimation). Meget konkave hulrum kan give geometri-overlap ved vinkler > 3°. Nøjagtig offset-surface kræver python-occ.
- **3+-delt form** er implementeret men kun testet for orthogonale splitplaner. Kontrollér altid output visuelt inden print.

---

## Licens

MIT – se `LICENSE.txt`.

---

*Alle 22 planlagte funktioner er implementeret. Projektet er klar til brug.*
