; The Windows installer: the tree build-tree.sh makes, installed for the user
; who runs it, without administrator rights - into
; %LOCALAPPDATA%\Programs\Danu - with a Start menu entry and an uninstaller.
;
;   iscc /DVersion=0.2.0 /DTree=C:\path\to\OUT\Danu /DOut=C:\path\to\out danu.iss

#ifndef Version
  #error pass /DVersion=x.y.z
#endif
#ifndef Tree
  #error pass /DTree=the tree build-tree.sh made
#endif
#ifndef Out
  #define Out "."
#endif

[Setup]
AppId={{6B0E6C52-5D8E-4F7B-9B3A-2C1D0A9E7F31}
AppName=Danu
AppVersion={#Version}
AppVerName=Danu {#Version}
AppPublisher=OpenGeofiction
AppPublisherURL=https://github.com/opengeofiction-net/danu
AppSupportURL=https://github.com/opengeofiction-net/danu/issues
DefaultDirName={autopf}\Danu
DefaultGroupName=Danu
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
SetupIconFile=danu.ico
UninstallDisplayIcon={app}\Danu.exe
OutputDir={#Out}
OutputBaseFilename=danu-{#Version}-windows-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "{#Tree}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

; what an earlier version installed and this one does not ship
[InstallDelete]
Type: filesandordirs; Name: "{app}\lib"
Type: filesandordirs; Name: "{app}\share"
Type: filesandordirs; Name: "{app}\bin"

[Icons]
Name: "{group}\Danu"; Filename: "{app}\Danu.exe"
Name: "{autodesktop}\Danu"; Filename: "{app}\Danu.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Put Danu on the desktop"; Flags: unchecked

[Run]
Filename: "{app}\Danu.exe"; Description: "Start Danu"; Flags: nowait postinstall skipifsilent
