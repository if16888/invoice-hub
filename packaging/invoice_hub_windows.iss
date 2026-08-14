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
#ifndef AppIdGuid
#define AppIdGuid "B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D"
#endif
#ifndef DefaultInstallDir
#define DefaultInstallDir "{localappdata}\Programs\InvoiceHub"
#endif

[Setup]
AppId={{B4A5B8B8-0F83-4E8B-9A8D-3C4321609C5D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Invoice Hub
DefaultDirName={#DefaultInstallDir}
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

[UninstallDelete]
; Legacy runtime export folders are removed only when migration left them empty.
Type: dirifempty; Name: "{app}\exports"
; A damaged previous uninstall registration may leave a renamed installer-owned
; uninstaller behind until this install is later removed.
Type: files; Name: "{app}\unins???.exe.invoicehub-orphan"
; When an older uninstall log was lost, the replacement log did not record the
; original app-directory creation. Remove it only when every owned file is gone.
Type: dirifempty; Name: "{app}"

[Icons]
Name: "{autoprograms}\Invoice Hub"; Filename: "{app}\InvoiceHub.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Invoice Hub"; Filename: "{app}\InvoiceHub.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\InvoiceHub.exe"; Description: "Launch Invoice Hub"; Flags: nowait postinstall skipifsilent

[Code]
const
  InvoiceHubUninstallKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppIdGuid}}_is1';

var
  BrokenRegisteredUninstaller: String;

function PathWithoutTrailingBackslash(const Value: String): String;
begin
  Result := RemoveBackslashUnlessRoot(Value);
end;

function RegisteredExecutable(const CommandLine: String): String;
var
  Value: String;
  ClosingQuote: Integer;
  ExeEnd: Integer;
begin
  Result := '';
  Value := Trim(CommandLine);
  if Value = '' then
    Exit;

  if Value[1] = '"' then
  begin
    Delete(Value, 1, 1);
    ClosingQuote := Pos('"', Value);
    if ClosingQuote > 1 then
      Result := Copy(Value, 1, ClosingQuote - 1);
    Exit;
  end;

  ExeEnd := Pos('.exe', Lowercase(Value));
  if ExeEnd > 0 then
    Result := Copy(Value, 1, ExeEnd + 3);
end;

function IsInnoUninstallerName(const FileName: String): Boolean;
var
  Name: String;
begin
  Name := Lowercase(FileName);
  Result :=
    (Length(Name) = 12) and
    (Copy(Name, 1, 5) = 'unins') and
    (Name[6] >= '0') and (Name[6] <= '9') and
    (Name[7] >= '0') and (Name[7] <= '9') and
    (Name[8] >= '0') and (Name[8] <= '9') and
    (Copy(Name, 9, 4) = '.exe');
end;

function DirectoryHasEntries(const Directory: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(PathWithoutTrailingBackslash(Directory) + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := True;
          Break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure RemoveEmptyDirectoryTree(const Directory: String);
var
  FindRec: TFindRec;
  ChildDirectory: String;
begin
  if not DirExists(Directory) then
    Exit;

  if FindFirst(PathWithoutTrailingBackslash(Directory) + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') and
           (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and
           (FindRec.Attributes and FILE_ATTRIBUTE_REPARSE_POINT = 0) then
        begin
          ChildDirectory := PathWithoutTrailingBackslash(Directory) + '\' +
            FindRec.Name;
          RemoveEmptyDirectoryTree(ChildDirectory);
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;

  { This procedure never deletes files. It only removes directories that are
    empty after native Inno uninstall processing, and it is called only for
    the installer-owned application tree. }
  if not DirectoryHasEntries(Directory) then
    RemoveDir(Directory);
end;

function RemoveBrokenUninstallRegistration: String;
var
  InstallLocation: String;
  UninstallCommand: String;
  UninstallerPath: String;
  AppDirectory: String;
begin
  Result := '';
  if not RegQueryStringValue(
    HKEY_CURRENT_USER, InvoiceHubUninstallKey, 'InstallLocation',
    InstallLocation) then
    Exit;
  if not RegQueryStringValue(
    HKEY_CURRENT_USER, InvoiceHubUninstallKey, 'UninstallString',
    UninstallCommand) then
    Exit;

  InstallLocation := PathWithoutTrailingBackslash(InstallLocation);
  AppDirectory := InstallLocation;
  UninstallerPath := RegisteredExecutable(UninstallCommand);

  { Handle only the exact per-user Invoice Hub registration and only when its
    registered Inno uninstaller is directly inside the recorded app directory. }
  if (CompareText(
       PathWithoutTrailingBackslash(ExtractFileDir(UninstallerPath)),
       AppDirectory) <> 0) or
     (not IsInnoUninstallerName(ExtractFileName(UninstallerPath))) then
    Exit;

  { A matching .dat makes this a valid uninstall registration. Native Inno
    upgrade/append behavior must remain untouched in that case. }
  if FileExists(ChangeFileExt(UninstallerPath, '.dat')) then
    Exit;

  Log('Detected an Invoice Hub uninstall registration without its matching log.');
  { Remove only the exact per-user ARP key. Do not rewrite either uninstall
    command and do not touch any uninsNNN.exe/.dat pair. Native Inno Setup must
    discover the AppId and choose a new or appended uninstall log itself. }
  if not RegDeleteKeyIncludingSubkeys(
    HKEY_CURRENT_USER, InvoiceHubUninstallKey) then
  begin
    Result := '检测到旧版卸载信息已损坏，且无法清理旧注册。请重试安装。';
    Exit;
  end;
  BrokenRegisteredUninstaller := UninstallerPath;
  Log('Removed the damaged Invoice Hub uninstall registration before native setup.');
end;

procedure RemoveBrokenRegisteredUninstaller;
begin
  if (BrokenRegisteredUninstaller = '') or
     (not FileExists(BrokenRegisteredUninstaller)) or
     FileExists(ChangeFileExt(BrokenRegisteredUninstaller, '.dat')) then
    Exit;

  { Native Setup owns the selected/new log. Remove only the previously
    registered installer-owned executable when it is still an unpaired stale
    file; never remove a valid alternate uninsNNN.exe/.dat pair. }
  if not DeleteFile(BrokenRegisteredUninstaller) then
    Log('Warning: could not remove the obsolete Invoice Hub uninstaller.');
end;

function InitializeSetup: Boolean;
var
  RepairError: String;
begin
  RepairError := RemoveBrokenUninstallRegistration;
  Result := RepairError = '';
  if not Result then
    SuppressibleMsgBox(RepairError, mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RemoveBrokenRegisteredUninstaller;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveEmptyDirectoryTree(ExpandConstant('{app}'));
end;
