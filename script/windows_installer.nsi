Unicode true
RequestExecutionLevel user
SetCompressor zlib
Name "4G Bridge"
OutFile "..\artifacts\4G-Bridge-0.2.0-preview.1-windows-x64-setup.exe"
InstallDir "$LOCALAPPDATA\Programs\4GBridge"
!include "MUI2.nsh"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  System::Call 'kernel32::OpenMutexW(i 1048576,i 0,w "Local\4GBridgeWindows") p.r0'
  IntCmp $0 0 not_running
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_OK "请先从托盘退出 4G Bridge，再安装。"
    Abort
  not_running:
  IfFileExists "$INSTDIR\*.*" 0 empty
  IfFileExists "$INSTDIR\.4gbridge-install" empty 0
    MessageBox MB_OK "安装目录存在非本程序文件；为保护数据，已取消安装。"
    Abort
  empty:
FunctionEnd

Section "4G Bridge"
  SetOutPath "$INSTDIR"
  File /r "..\dist\windows\4G Bridge\*"
  FileOpen $0 "$INSTDIR\.4gbridge-install" w
  FileWrite $0 "4GBridge-Windows"
  FileClose $0
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\4G Bridge.lnk" "$INSTDIR\4G Bridge.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\4GBridge" "DisplayName" "4G Bridge"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\4GBridge" "DisplayVersion" "0.2.0-preview.1"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\4GBridge" "UninstallString" '$"$INSTDIR\Uninstall.exe$"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\4GBridge" "DisplayIcon" "$INSTDIR\4G Bridge.exe"
SectionEnd

Function un.onInit
  System::Call 'kernel32::OpenMutexW(i 1048576,i 0,w "Local\4GBridgeWindows") p.r0'
  IntCmp $0 0 not_running
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_OK "请先从托盘退出 4G Bridge，再卸载。"
    Abort
  not_running:
  IfFileExists "$INSTDIR\.4gbridge-install" valid 0
    Abort
  valid:
FunctionEnd

Section "Uninstall"
  !include "..\build\windows\uninstall-files.nsh"
  Delete "$INSTDIR\.4gbridge-install"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\4G Bridge.lnk"
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "4G Bridge"
  StrCmp $0 '$"$INSTDIR\4G Bridge.exe$" --background' 0 keep_login
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "4G Bridge"
  keep_login:
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\4GBridge"
  ; Keep settings and locked carrier budgets in LOCALAPPDATA\4G Bridge.
SectionEnd
