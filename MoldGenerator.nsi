; =============================================================================
;  NSIS-installerscript – Mold Generator Windows
;
;  Kræver:
;    NSIS ≥ 3.08  (https://nsis.sourceforge.io)
;    MUI2 plugin (bundtet med NSIS)
;
;  Brug (efter pyinstaller har kørt):
;    makensis installer/MoldGenerator.nsi
;
;  Output:
;    dist/MoldGenerator-${VERSION}-setup.exe
;
;  Hvad installeren gør:
;    1. Kopierer dist/MoldGenerator/ til %ProgramFiles%\MoldGenerator\
;    2. Opretter Start Menu genvej
;    3. Opretter Desktop-genvej (valgfrit)
;    4. Tilmelder i Windows Add/Remove Programs
;    5. Tilknytter .stl filtypenavnet til MoldGenerator.exe
;    6. Opretter afinstaller
; =============================================================================

!define APPNAME     "Mold Generator"
!define APPVERSION  "1.0.0"
!define APPEXE      "MoldGenerator.exe"
!define PUBLISHER   "MoldGen"
!define INSTALLDIR  "$PROGRAMFILES64\MoldGenerator"
!define UNINSTALLER "Uninstall.exe"
!define REGKEY      "Software\Microsoft\Windows\CurrentVersion\Uninstall\MoldGenerator"
!define STL_REGKEY  "Software\Classes\.stl"

Name "${APPNAME} ${APPVERSION}"
OutFile "dist\MoldGenerator-${APPVERSION}-setup.exe"
InstallDir "${INSTALLDIR}"
InstallDirRegKey HKLM "${REGKEY}" "InstallLocation"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
Unicode True

; ── MUI2 ────────────────────────────────────────────────────────────────────
!include "MUI2.nsh"

!define MUI_ICON      "installer\assets\icon.ico"
!define MUI_UNICON    "installer\assets\icon.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "installer\assets\header.bmp"  ; 150×57 px
!define MUI_WELCOMEFINISHPAGE_BITMAP "installer\assets\wizard.bmp"  ; 164×314 px

!define MUI_WELCOMEPAGE_TITLE    "Velkommen til Mold Generator ${APPVERSION}"
!define MUI_WELCOMEPAGE_TEXT     "Denne guide installerer Mold Generator på din computer.$\r$\n$\r$\nMold Generator konverterer STL-filer til 3D-printbare støbeforme med GPU-acceleration.$\r$\n$\r$\nKlik Næste for at fortsætte."
!define MUI_FINISHPAGE_RUN       "$INSTDIR\${APPEXE}"
!define MUI_FINISHPAGE_RUN_TEXT  "Start Mold Generator nu"

; Installer-sider
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE    "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; Afinstaller-sider
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; Sprog (dansk som primært, engelsk som fallback)
!insertmacro MUI_LANGUAGE "Danish"
!insertmacro MUI_LANGUAGE "English"

; ── Sektioner ────────────────────────────────────────────────────────────────

Section "Mold Generator (påkrævet)" SecMain
  SectionIn RO   ; Kan ikke fravælges

  SetOutPath "$INSTDIR"

  ; Kopiér hele PyInstaller-bundlen
  File /r "dist\MoldGenerator\*.*"

  ; Konfigurationsfil
  SetOutPath "$INSTDIR\config"
  File "config\defaults.yaml"

  ; ── Genveje ────────────────────────────────────────────────────────────────
  CreateDirectory "$SMPROGRAMS\Mold Generator"
  CreateShortcut  "$SMPROGRAMS\Mold Generator\Mold Generator.lnk" \
                  "$INSTDIR\${APPEXE}" "" "$INSTDIR\${APPEXE}" 0

  CreateShortcut  "$SMPROGRAMS\Mold Generator\Afinstaller.lnk" \
                  "$INSTDIR\${UNINSTALLER}"

  ; Desktop-genvej
  MessageBox MB_YESNO "Opret genvej på skrivebordet?" IDNO no_desktop
    CreateShortcut "$DESKTOP\Mold Generator.lnk" "$INSTDIR\${APPEXE}" \
                   "" "$INSTDIR\${APPEXE}" 0
  no_desktop:

  ; ── .stl filtilknytning ────────────────────────────────────────────────────
  WriteRegStr HKLM "${STL_REGKEY}" "" "MoldGenerator.STLFile"
  WriteRegStr HKLM "Software\Classes\MoldGenerator.STLFile" "" "STL 3D Model"
  WriteRegStr HKLM "Software\Classes\MoldGenerator.STLFile\DefaultIcon" \
              "" "$INSTDIR\${APPEXE},0"
  WriteRegStr HKLM "Software\Classes\MoldGenerator.STLFile\shell\open\command" \
              "" '"$INSTDIR\${APPEXE}" "%1"'

  ; ── Add/Remove Programs ────────────────────────────────────────────────────
  WriteRegStr   HKLM "${REGKEY}" "DisplayName"          "${APPNAME}"
  WriteRegStr   HKLM "${REGKEY}" "DisplayVersion"       "${APPVERSION}"
  WriteRegStr   HKLM "${REGKEY}" "Publisher"            "${PUBLISHER}"
  WriteRegStr   HKLM "${REGKEY}" "InstallLocation"      "$INSTDIR"
  WriteRegStr   HKLM "${REGKEY}" "UninstallString"      "$INSTDIR\${UNINSTALLER}"
  WriteRegStr   HKLM "${REGKEY}" "DisplayIcon"          "$INSTDIR\${APPEXE}"
  WriteRegDWORD HKLM "${REGKEY}" "NoModify"             1
  WriteRegDWORD HKLM "${REGKEY}" "NoRepair"             1

  ; ── Afinstaller ────────────────────────────────────────────────────────────
  WriteUninstaller "$INSTDIR\${UNINSTALLER}"

SectionEnd

; ── Afinstallation ───────────────────────────────────────────────────────────

Section "Uninstall"
  ; Fjern filer
  RMDir /r "$INSTDIR"

  ; Fjern genveje
  RMDir /r "$SMPROGRAMS\Mold Generator"
  Delete   "$DESKTOP\Mold Generator.lnk"

  ; Fjern registreringsdatabasen
  DeleteRegKey HKLM "${REGKEY}"
  DeleteRegKey HKLM "${STL_REGKEY}"
  DeleteRegKey HKLM "Software\Classes\MoldGenerator.STLFile"

SectionEnd
