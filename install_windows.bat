@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

:: ================================================================
::  Mold Generator - Windows Installer
::  Krav: Windows 10/11, internet-forbindelse
::  Koer som administrator (scriptet beder om det automatisk)
:: ================================================================

title Mold Generator - Installer

:: ---- Admin check -----------------------------------------------
net session > nul 2>&1
if %errorLevel% neq 0 (
    echo Starter med administrator-rettigheder...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: ---- Paths -----------------------------------------------------
set "APP_DIR=%~dp0"
if "%APP_DIR:~-1%"=="\" set "APP_DIR=%APP_DIR:~0,-1%"

set "INSTALL_DIR=%APPDATA%\MoldGenerator"
set "VENV_DIR=%INSTALL_DIR%\venv"
set "APP_COPY=%INSTALL_DIR%\app"
set "LAUNCHER=%INSTALL_DIR%\launch.bat"
set "PYTHON_VENV=%VENV_DIR%\Scripts\python.exe"
set "PIP=%VENV_DIR%\Scripts\pip.exe"

echo.
echo ================================================================
echo   Mold Generator - Installer
echo ================================================================
echo.

:: ---- Find Python 3.10+ -----------------------------------------
echo [1/8] Finder Python...
echo.

set "PYTHON_EXE="

for %%P in (python3.12.exe python3.11.exe python3.10.exe python.exe python3.exe) do (
    if not defined PYTHON_EXE (
        where %%P > nul 2>&1
        if !errorLevel! equ 0 (
            %%P --version > nul 2>&1
            if !errorLevel! equ 0 (
                set "PYTHON_EXE=%%P"
            )
        )
    )
)

if not defined PYTHON_EXE (
    py -3 --version > nul 2>&1
    if !errorLevel! equ 0 (
        set "PYTHON_EXE=py -3"
    )
)

if not defined PYTHON_EXE (
    echo FEJL: Python 3.10+ ikke fundet.
    echo.
    echo Download Python fra: https://www.python.org/downloads/
    echo Saet kryds i "Add Python to PATH" under installationen.
    echo.
    echo Aabner download-siden...
    start https://www.python.org/downloads/
    echo Koer denne installer igen naar Python er installeret.
    pause
    exit /b 1
)

echo  OK: Python fundet (%PYTHON_EXE%)

%PYTHON_EXE% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2> nul
if %errorLevel% neq 0 (
    echo FEJL: Python version er for gammel. Kraever 3.10 eller nyere.
    echo Download fra: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PYTHON_EXE% --version 2^>^&1') do echo  Version: %%V

:: ---- Opret mapper ----------------------------------------------
echo.
echo [2/8] Opretter mapper...
echo.

if exist "%VENV_DIR%" (
    echo  Fjerner gammel installation...
    rmdir /s /q "%INSTALL_DIR%"
)

mkdir "%INSTALL_DIR%" 2> nul
mkdir "%APP_COPY%" 2> nul
echo  OK: %INSTALL_DIR%

:: ---- Virtual environment ---------------------------------------
echo.
echo [3/8] Opretter Python virtual environment...
echo.

%PYTHON_EXE% -m venv "%VENV_DIR%"
if %errorLevel% neq 0 (
    echo FEJL: Kunne ikke oprette virtual environment.
    pause
    exit /b 1
)
echo  OK: venv oprettet

"%PYTHON_VENV%" -m pip install --upgrade pip --quiet 2> nul
echo  OK: pip opdateret

:: ---- Kerne-pakker ----------------------------------------------
echo.
echo [4/8] Installerer kerne-pakker (kan tage 2-4 min)...
echo.
echo  Installerer: trimesh, manifold3d, numpy, scipy, pyyaml...

"%PIP%" install --quiet ^
    "trimesh==4.4.0" ^
    "manifold3d==2.4.5" ^
    "numpy-stl==3.1.1" ^
    "numpy==1.26.4" ^
    "scipy==1.13.0" ^
    "pyyaml==6.0.1"

if %errorLevel% neq 0 (
    echo FEJL: Kerne-pakker fejlede. Tjek internet-forbindelsen.
    pause
    exit /b 1
)
echo  OK: Kerne-pakker installeret

:: ---- GUI-pakker ------------------------------------------------
echo.
echo [5/8] Installerer GUI-pakker (PyQt6, PyOpenGL)...
echo.

"%PIP%" install --quiet ^
    "PyQt6==6.7.0" ^
    "PyOpenGL==3.1.7"

if %errorLevel% neq 0 (
    echo FEJL: GUI-pakker fejlede.
    pause
    exit /b 1
)
echo  OK: PyQt6 og PyOpenGL installeret

:: ---- open3d (valgfri) ------------------------------------------
echo.
echo [6/8] Installerer open3d (valgfri, stor pakke)...
echo.

"%PIP%" install --quiet "open3d==0.18.0" 2> nul
if %errorLevel% equ 0 (
    echo  OK: open3d installeret
) else (
    echo  ADVARSEL: open3d ikke installeret - ikke kritisk
)

:: ---- CuPy GPU-acceleration -------------------------------------
echo.
echo [7/8] Undersoeger GPU (NVIDIA CUDA)...
echo.

set "CUPY_OK=0"

where nvidia-smi > nul 2>&1
if %errorLevel% equ 0 (
    echo  NVIDIA GPU fundet - proever CuPy CUDA 12.x...
    "%PIP%" install --quiet "cupy-cuda12x==13.0.0" 2> nul
    if !errorLevel! equ 0 (
        echo  OK: CuPy CUDA 12.x installeret - GPU-acceleration aktiv
        set "CUPY_OK=1"
    ) else (
        echo  Proever CuPy CUDA 11.x...
        "%PIP%" install --quiet "cupy-cuda11x" 2> nul
        if !errorLevel! equ 0 (
            echo  OK: CuPy CUDA 11.x installeret - GPU-acceleration aktiv
            set "CUPY_OK=1"
        ) else (
            echo  ADVARSEL: CuPy fejlede - programmet koerer pa CPU
        )
    )
) else (
    echo  Ingen NVIDIA GPU fundet - koerer pa CPU
    echo  Underskaeringsanalyse tager ca. 45 sek i stedet for 2 sek
)

:: ---- Kopier programfiler ---------------------------------------
echo.
echo [8/8] Kopierer programfiler...
echo.

xcopy "%APP_DIR%\*" "%APP_COPY%\" /E /I /Q /Y > nul 2>&1
if %errorLevel% neq 0 (
    echo FEJL: Kunne ikke kopiere programfiler.
    pause
    exit /b 1
)
echo  OK: Programfiler kopieret

:: ---- Launcher --------------------------------------------------
echo  Opretter launcher...

(
    echo @echo off
    echo cd /d "%APP_COPY%"
    echo start "" "%PYTHON_VENV%" main.py %%*
) > "%LAUNCHER%"

echo  OK: Launcher oprettet

:: ---- Skrivebordsgenvej -----------------------------------------
echo  Opretter skrivebordsgenvej...

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\Mold Generator.lnk'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_COPY%'; $s.Description = 'STL til 3D-printbar stoebeform'; $s.Save()" 2> nul

if %errorLevel% equ 0 (
    echo  OK: Skrivebordsgenvej oprettet
) else (
    echo  ADVARSEL: Skrivebordsgenvej fejlede
)

:: ---- Startmenu -------------------------------------------------
echo  Opretter Startmenu-genvej...

set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Mold Generator"
mkdir "%STARTMENU%" 2> nul

powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%STARTMENU%\Mold Generator.lnk'); $s.TargetPath = '%LAUNCHER%'; $s.WorkingDirectory = '%APP_COPY%'; $s.Description = 'STL til 3D-printbar stoebeform'; $s.Save()" 2> nul

echo  OK: Startmenu-genvej oprettet

:: ---- STL filtilknytning ----------------------------------------
echo  Tilknytter .stl filer...

reg add "HKCU\Software\Classes\.stl" /ve /d "MoldGenerator.STLFile" /f > nul 2>&1
reg add "HKCU\Software\Classes\MoldGenerator.STLFile" /ve /d "STL 3D Model" /f > nul 2>&1
reg add "HKCU\Software\Classes\MoldGenerator.STLFile\shell\open\command" /ve /d "\"%LAUNCHER%\" \"%%1\"" /f > nul 2>&1

echo  OK: .stl filer tilknyttet Mold Generator

:: ---- Faerdig ---------------------------------------------------
echo.
echo ================================================================
echo   Installation fuldfoert!
echo ================================================================
echo.
echo   Saadan starter du programmet:
echo   - Dobbeltklik paa "Mold Generator" paa skrivebordet
echo   - Eller via Startmenuen
echo   - Eller koer direkte: %LAUNCHER%
echo.

if "%CUPY_OK%"=="0" (
    echo   GPU-acceleration ikke aktiv.
    echo   Installer CUDA Toolkit: https://developer.nvidia.com/cuda-downloads
    echo   Koer derefter: %PIP% install cupy-cuda12x
    echo.
)

echo   Tryk en tast for at starte programmet...
pause > nul

start "" "%LAUNCHER%"
exit /b 0
