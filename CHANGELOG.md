# Changelog

Alle nævneværdige ændringer i dette projekt dokumenteres her.
Format følger [Keep a Changelog](https://keepachangelog.com/da/1.0.0/).

---

## [1.0.0] – 2024

### Tilføjet
- STL-indlæsning med automatisk reparation (trimesh.repair)
- BVH-baseret selvskæringstest med Möller–Trumbore algoritme
- GPU-accelereret underskæringsanalyse (500 retninger, CuPy/CUDA)
- CPU-fallback ved manglende GPU (ren NumPy)
- Automatisk valg af 2/3/4+ formhalvdele via greedy splitplan-optimering
- Asymmetrisk delingslogik (toggle)
- Draft angle (udtræksvinkel) via vertex-projektion langs pull-retning
- Samletappe: runde og D-formede, størrelse baseret på formens bbox
- Topologisk lomme-detektion via 7×7 multi-ray grid
- Konisk indløbstragt (frustum) med korrekt dimensionering
- ISO 68-1-baseret gevindprofil (60° flankevinkel, FDM-tilpasset)
- Knurling og tætningsflange på skruelåg
- Han/hun-gevind-par med konfigurerbar FDM-clearance
- 4 slicer-profiler: Gips/Moderform × PLA/PETG
- PyQt6 GUI med mørkt tema
- OpenGL 3D-viewport med 5 toggle-bare lag og arcball-kamera
- Pipeline kørsel i QThread (ikke-blokerende GUI)
- Tre-fanet output-panel (Analyse, Slicer, Log)
- CLI-interface med fuld parameter-kontrol
- PyInstaller spec-filer til Windows og Linux
- NSIS-installerscript til Windows .exe
- AppImageBuilder-recipe til Linux .AppImage
- Automatiseret build.py med forudsætnings-tjek og fejlhåndtering

### Teknisk
- manifold3d til robuste boolean-operationer
- Sweep-and-prune + AABB pre-screening i selvskæringstest
- Fibonacci-spiral sampling af udtræksretninger (jævnere end random)
- Pull-direction-aware indløbsplacering (ikke blot Z-aksen)

---

## Kommende

- Drag-and-drop af STL-filer til viewport
- LOD (level-of-detail) til meshes > 1M trekanter
- Depth-sorted transparens-rendering
- python-occ draft angle (nøjagtig offset-surface)
- Multi-GPU understøttelse
