#!/usr/bin/env bash
# =============================================================================
#  Mold Generator – Installer til CachyOS / Arch Linux
#
#  Dobbeltklik på filen i filhåndteringen ELLER kør i terminal:
#    chmod +x install_cachyos.sh
#    ./install_cachyos.sh
#
#  Hvad scriptet gør:
#    1. Installerer systemafhængigheder via pacman (python, cuda, pyqt6 osv.)
#    2. Opretter et Python virtual environment i ~/.local/share/mold_generator/
#    3. Installerer Python-pakker i venv via pip
#    4. Opretter en launcher: ~/Desktop/MoldGenerator.desktop
#    5. Opretter kommandoen "moldgenerator" i /usr/local/bin
#
#  Kræver: internet-forbindelse og sudo-adgang
# =============================================================================

set -euo pipefail

# ── Farver ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${CYAN}  ℹ  $*${NC}"; }
ok()    { echo -e "${GREEN}  ✓  $*${NC}"; }
warn()  { echo -e "${YELLOW}  ⚠  $*${NC}"; }
err()   { echo -e "${RED}  ✗  $*${NC}" >&2; }
step()  { echo -e "\n${BOLD}── $* ──${NC}"; }
die()   { err "$*"; exit 1; }

# ── Konstanter ─────────────────────────────────────────────────────────────────
APP_NAME="MoldGenerator"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.local/share/mold_generator/venv"
DATA_DIR="$HOME/.local/share/mold_generator"
BIN_LINK="/usr/local/bin/moldgenerator"
DESKTOP_FILE="$HOME/Desktop/${APP_NAME}.desktop"
DESKTOP_APPS="$HOME/.local/share/applications/${APP_NAME}.desktop"

# ── Banner ─────────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   Mold Generator – Installer             ║"
echo "  ║   CachyOS / Arch Linux                   ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── Tjek at vi er på Arch/CachyOS ──────────────────────────────────────────────
step "Tjekker system"
if ! command -v pacman &>/dev/null; then
    die "pacman ikke fundet. Dette script kræver CachyOS eller Arch Linux."
fi
ok "CachyOS / Arch Linux bekræftet"

# ── Tjek Python 3.10+ ──────────────────────────────────────────────────────────
PY_OK=false
for py in python3.12 python3.11 python3.10 python3; do
    if command -v "$py" &>/dev/null; then
        VER=$("$py" -c "import sys; print(sys.version_info[:2])" 2>/dev/null)
        if "$py" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
            PYTHON="$py"
            PY_OK=true
            ok "Python: $py ($VER)"
            break
        fi
    fi
done
$PY_OK || die "Python 3.10+ kræves. Installer med: sudo pacman -S python"

# ── Trin 1: Systemafhængigheder via pacman ─────────────────────────────────────
step "Installerer systemafhængigheder (pacman)"
info "Opdaterer pakkedatabase..."
sudo pacman -Sy --noconfirm 2>/dev/null || warn "Kan ikke opdatere database – fortsætter med eksisterende"

PACMAN_PKGS=(
    "python"            # Python 3
    "python-pip"        # pip
    "python-virtualenv" # venv support
    "cuda"              # NVIDIA CUDA Toolkit (til CuPy GPU-acceleration)
    "qt6-base"          # Qt6 (PyQt6 bygger på dette)
    "mesa"              # OpenGL (PyOpenGL)
    "libgl"             # OpenGL biblioteker
    "gcc"               # C-compiler (kræves til nogle pip-pakker)
    "git"               # git (kræves af nogle AUR-pakker)
)

for pkg in "${PACMAN_PKGS[@]}"; do
    if pacman -Qi "$pkg" &>/dev/null; then
        ok "$pkg (allerede installeret)"
    else
        info "Installerer $pkg..."
        if sudo pacman -S --noconfirm --needed "$pkg" 2>/dev/null; then
            ok "$pkg installeret"
        else
            warn "$pkg kunne ikke installeres via pacman – fortsætter"
        fi
    fi
done

# ── Trin 2: Opret virtual environment ─────────────────────────────────────────
step "Opretter Python virtual environment"
mkdir -p "$DATA_DIR"

if [[ -d "$VENV_DIR" ]]; then
    warn "Eksisterende venv fundet – sletter og genskaber"
    rm -rf "$VENV_DIR"
fi

info "Opretter venv i $VENV_DIR ..."
"$PYTHON" -m venv "$VENV_DIR"
ok "Virtual environment oprettet"

# Aktiver venv for dette scripts varighed
source "$VENV_DIR/bin/activate"
ok "Virtual environment aktiveret"

# Opdatér pip
info "Opdaterer pip..."
pip install --upgrade pip --quiet
ok "pip opdateret: $(pip --version | cut -d' ' -f2)"

# ── Trin 3: Installer Python-pakker ───────────────────────────────────────────
step "Installerer Python-pakker"

info "Installerer kerne-afhængigheder..."
pip install --quiet \
    "trimesh==4.4.0" \
    "manifold3d==2.4.0" \
    "numpy-stl==3.1.1" \
    "numpy==1.26.4" \
    "scipy==1.13.0" \
    "pyyaml==6.0.1"
ok "Kerne-pakker installeret (trimesh, manifold3d, numpy, scipy)"

info "Installerer GUI-pakker (PyQt6 + PyOpenGL)..."
pip install --quiet \
    "PyQt6==6.7.0" \
    "PyOpenGL==3.1.7" \
    "PyOpenGL-accelerate==3.1.7"
ok "GUI-pakker installeret (PyQt6, PyOpenGL)"

# CuPy – prøv CUDA 12.x, fald tilbage til 11.x, så CPU-only
CUPY_OK=false
if command -v nvcc &>/dev/null || [[ -f /usr/local/cuda/bin/nvcc ]] || [[ -f /opt/cuda/bin/nvcc ]]; then
    CUDA_VER=$(nvcc --version 2>/dev/null | grep -oP 'release \K[0-9]+' | head -1 || echo "0")
    info "CUDA $CUDA_VER detekteret – installerer CuPy..."
    if [[ "$CUDA_VER" -ge 12 ]]; then
        if pip install --quiet "cupy-cuda12x==13.0.0" 2>/dev/null; then
            ok "CuPy (CUDA 12.x) installeret – GPU-acceleration aktiv"
            CUPY_OK=true
        fi
    elif [[ "$CUDA_VER" -ge 11 ]]; then
        if pip install --quiet "cupy-cuda11x" 2>/dev/null; then
            ok "CuPy (CUDA 11.x) installeret – GPU-acceleration aktiv"
            CUPY_OK=true
        fi
    fi
else
    info "CUDA ikke fundet via nvcc – tjekker /opt/cuda og /usr/local/cuda..."
    for cuda_path in /opt/cuda /usr/local/cuda; do
        if [[ -d "$cuda_path" ]]; then
            CUDA_VER=$(cat "$cuda_path/version.txt" 2>/dev/null | grep -oP '[0-9]+' | head -1 || echo "0")
            if [[ "$CUDA_VER" -ge 12 ]]; then
                if pip install --quiet "cupy-cuda12x==13.0.0" 2>/dev/null; then
                    ok "CuPy (CUDA 12.x) installeret"
                    CUPY_OK=true
                    break
                fi
            fi
        fi
    done
fi

if ! $CUPY_OK; then
    warn "CuPy ikke installeret – programmet kører på CPU (underskæringsanalyse ~45 sek i stedet for ~2 sek)"
    warn "For GPU-acceleration: sudo pacman -S cuda && pip install cupy-cuda12x"
fi

# open3d – valgfri, stor pakke
info "Installerer open3d (valgfri, kan tage et øjeblik)..."
if pip install --quiet "open3d==0.18.0" 2>/dev/null; then
    ok "open3d installeret"
else
    warn "open3d kunne ikke installeres – visse avancerede mesh-operationer utilgængelige"
fi

deactivate
ok "Alle pakker installeret"

# ── Trin 4: Kopier programfiler ────────────────────────────────────────────────
step "Kopierer programfiler"
TARGET_DIR="$DATA_DIR/app"
rm -rf "$TARGET_DIR"
cp -r "$APP_DIR" "$TARGET_DIR"
ok "Programfiler kopieret til $TARGET_DIR"

# ── Trin 5: Opret launcher-script ─────────────────────────────────────────────
step "Opretter launcher"

LAUNCHER="$DATA_DIR/launch.sh"
cat > "$LAUNCHER" << LAUNCHEOF
#!/usr/bin/env bash
# Mold Generator launcher – genereret af installer
source "$VENV_DIR/bin/activate"
cd "$TARGET_DIR"
exec python main.py "\$@"
LAUNCHEOF
chmod +x "$LAUNCHER"
ok "Launcher oprettet: $LAUNCHER"

# Symlink i /usr/local/bin så "moldgenerator" virker fra terminal
if sudo ln -sf "$LAUNCHER" "$BIN_LINK" 2>/dev/null; then
    ok "Terminal-kommando oprettet: moldgenerator"
else
    warn "Kunne ikke oprette /usr/local/bin/moldgenerator (ingen sudo?) – brug $LAUNCHER direkte"
fi

# ── Trin 6: .desktop-fil (ikon på skrivebord + app-menu) ──────────────────────
step "Opretter skrivebordsgenvej"

mkdir -p "$HOME/Desktop"
mkdir -p "$HOME/.local/share/applications"

DESKTOP_CONTENT="[Desktop Entry]
Version=1.0
Type=Application
Name=Mold Generator
GenericName=STL til støbeform
Comment=Konvertér STL-filer til 3D-printbare støbeforme
Exec=$LAUNCHER %f
Icon=applications-engineering
Terminal=false
Categories=Graphics;Engineering;Science;
MimeType=model/stl;application/sla;
StartupNotify=true
StartupWMClass=MoldGenerator"

echo "$DESKTOP_CONTENT" > "$DESKTOP_FILE"
echo "$DESKTOP_CONTENT" > "$DESKTOP_APPS"

# Gør .desktop eksekverbar (kræves af KDE/GNOME for "betroet" ikon)
chmod +x "$DESKTOP_FILE" 2>/dev/null || true

# Opdatér desktop-database
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

ok "Skrivebordsgenvej oprettet: $DESKTOP_FILE"
ok "App-menu entry oprettet: $DESKTOP_APPS"

# ── Afslutning ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  Installation fuldført!${NC}"
echo -e "${BOLD}${GREEN}════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Start programmet:${NC}"
echo -e "  • Dobbeltklik på 'MoldGenerator' ikonet på skrivebordet"
echo -e "  • Eller i terminal: ${CYAN}moldgenerator${NC}"
echo -e "  • Eller direkte:    ${CYAN}$LAUNCHER${NC}"
echo ""
if ! $CUPY_OK; then
    echo -e "  ${YELLOW}GPU-acceleration:${NC} Installer CUDA og kør:"
    echo -e "  ${CYAN}  sudo pacman -S cuda${NC}"
    echo -e "  ${CYAN}  $VENV_DIR/bin/pip install cupy-cuda12x${NC}"
    echo ""
fi
