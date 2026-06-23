#define AppName "Invoice Hub"
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif
#ifndef SourceDir
#define SourceDir "..\dist\InvoiceHub"
#endif
#ifndef OutputDir
#define OutputDir "..\dist"
#endif

[Setup]
AppId={{B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Invoice Hub
DefaultDirName={localappdata}\Programs\InvoiceHub
DefaultGroupName=Invoice Hub
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=InvoiceHub-{#AppVersion}-win64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\InvoiceHub.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Invoice Hub"; Filename: "{app}\InvoiceHub.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Invoice Hub"; Filename: "{app}\InvoiceHub.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\InvoiceHub.exe"; Description: "Launch Invoice Hub"; Flags: nowait postinstall skipifsilent
